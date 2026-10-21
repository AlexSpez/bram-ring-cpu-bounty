/* Compare four externally wrapped BRAM-ring CPU implementations.
 *
 * Link with sha256.c and wrappers exporting the four *_hash_state functions.
 * Build with GCC and -fopenmp (for example -O3 -march=native -std=c11).
 *
 *   compare_combined verify [count=32]
 *   compare_combined bench count runs [original scalar competitor combined]
 *
 * Every measured nonce includes hash_state, canonical little-endian lane
 * serialization, and full SHA-256. Allocation, serial table initialization,
 * result comparisons, and the aggregate checksum are outside the timer.
 * The aggregate SHA-256 consumes all 32 bytes of every ordered nonce digest.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#include "tables.h"
#include "sha256.h"

_Static_assert(B > 0, "B must be positive");
_Static_assert(W > 0 && W <= 32, "uint32_t states require 1 <= W <= 32");
enum { LANE_BYTES = (W + 7) / 8, DIGEST_BYTES = 32, NVARIANTS = 4 };

void original_hash_state(uint64_t nonce, uint32_t out[B]);
void scalar_hash_state(uint64_t nonce, uint32_t out[B]);
void competitor_hash_state(uint64_t nonce, uint32_t out[B]);
void combined_hash_state(uint64_t nonce, uint32_t out[B]);

typedef void (*hash_fn)(uint64_t, uint32_t[B]);
struct implementation { const char *name; hash_fn hash; };
static const struct implementation implementations[NVARIANTS] = {
    { "original", original_hash_state },
    { "scalar", scalar_hash_state },
    { "competitor", competitor_hash_state },
    { "combined", combined_hash_state }
};

static double now_seconds(void)
{
#ifdef _OPENMP
    return omp_get_wtime();
#else
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)value.tv_sec + 1e-9 * (double)value.tv_nsec;
#endif
}

static void state_digest(const uint32_t state[B], uint8_t digest[DIGEST_BYTES])
{
    uint8_t bytes[(size_t)B * LANE_BYTES];
    for (size_t lane = 0; lane < B; ++lane)
        for (unsigned byte = 0; byte < LANE_BYTES; ++byte)
            bytes[lane * LANE_BYTES + byte] = (uint8_t)(state[lane] >> (8 * byte));
    sha256(digest, bytes, sizeof bytes);
}

static uint32_t state_fold(const uint32_t state[B])
{
    uint32_t value = 0;
    for (size_t lane = 0; lane < B; ++lane) {
        unsigned shift = (unsigned)((lane * W) & 31);
        uint32_t word = state[lane];
        value ^= shift ? (word << shift) | (word >> (32 - shift)) : word;
    }
    return value;
}

static void digest_hex(const uint8_t digest[DIGEST_BYTES], char hex[65])
{
    static const char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < DIGEST_BYTES; ++i) {
        hex[2 * i] = digits[digest[i] >> 4];
        hex[2 * i + 1] = digits[digest[i] & 15];
    }
    hex[64] = '\0';
}

static void serial_initialize_all(void)
{
    uint32_t state[B];
    uint8_t digest[DIGEST_BYTES];
    /* Main calls this before the worker warm-up, so all lazy table builders
     * finish serially. Each worker then reuses it to commit its own TLS and
     * consume all warm-up digest bytes outside the timed measurements. */
    volatile unsigned sink = 0;
    for (unsigned i = 0; i < NVARIANTS; ++i) {
        implementations[i].hash(UINT64_C(0x0123456789abcdef), state);
        state_digest(state, digest);
        for (unsigned j = 0; j < DIGEST_BYTES; ++j) sink ^= digest[j];
    }
    (void)sink;
}

static void warm_worker_state(void)
{
    #pragma omp parallel
    {
        serial_initialize_all();
    }
}

static uint64_t verification_nonce(size_t index)
{
    static const uint64_t special[] = {
        UINT64_C(0), UINT64_C(1), UINT64_C(0xdeadbeef), UINT64_MAX,
        UINT64_C(0x8000000000000000), UINT64_C(0x0123456789abcdef),
        UINT64_C(0x5555555555555555), UINT64_C(0x00000000ffffffff)
    };
    if (index < sizeof special / sizeof special[0]) return special[index];
    /* SplitMix64 gives reproducible, well-spread 64-bit inputs after the
     * boundary cases and all eight published vector nonces above. */
    uint64_t z = UINT64_C(0xd1b54a32d192ed03)
               + (uint64_t)index * UINT64_C(0x9e3779b97f4a7c15);
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}

struct verification_record {
    uint64_t nonce;
    uint8_t digest[NVARIANTS][DIGEST_BYTES];
    uint32_t fold[NVARIANTS];
    int different_lane[NVARIANTS];
    uint32_t expected_word[NVARIANTS], actual_word[NVARIANTS];
};

static int verify_all(size_t count)
{
    if (count > SIZE_MAX / sizeof(struct verification_record)) {
        fprintf(stderr, "verification count exceeds addressable storage\n");
        return 2;
    }
    struct verification_record *records = calloc(count, sizeof *records);
    if (!records) { perror("allocate verification records"); return 2; }

    #pragma omp parallel for schedule(static)
    for (long long index = 0; index < (long long)count; ++index) {
        struct verification_record *record = &records[index];
        uint32_t original[B], actual[B];
        record->nonce = verification_nonce((size_t)index);
        implementations[0].hash(record->nonce, original);
        state_digest(original, record->digest[0]);
        record->fold[0] = state_fold(original);
        record->different_lane[0] = -1;
        for (unsigned variant = 1; variant < NVARIANTS; ++variant) {
            implementations[variant].hash(record->nonce, actual);
            state_digest(actual, record->digest[variant]);
            record->fold[variant] = state_fold(actual);
            int first = -1;
            for (int lane = 0; lane < B; ++lane)
                if (actual[lane] != original[lane] && first < 0) first = lane;
            record->different_lane[variant] = first;
            if (first >= 0) {
                record->expected_word[variant] = original[first];
                record->actual_word[variant] = actual[first];
            }
        }
    }

    size_t errors[NVARIANTS] = {0};
    for (size_t index = 0; index < count; ++index) {
        const struct verification_record *record = &records[index];
        for (unsigned variant = 1; variant < NVARIANTS; ++variant) {
            int bad_state = record->different_lane[variant] >= 0;
            int bad_digest = memcmp(record->digest[0], record->digest[variant], DIGEST_BYTES) != 0;
            int bad_fold = record->fold[0] != record->fold[variant];
            if (bad_state || bad_digest || bad_fold) {
                char expected[65], actual[65];
                digest_hex(record->digest[0], expected);
                digest_hex(record->digest[variant], actual);
                printf("MISMATCH name=%s nonce=%016" PRIx64
                       " state=%s digest=%s fold=%s lane=%d"
                       " expected_word=%08" PRIx32 " actual_word=%08" PRIx32
                       " expected_fold=%08" PRIx32 " actual_fold=%08" PRIx32
                       " expected_digest=%s actual_digest=%s\n",
                       implementations[variant].name, record->nonce,
                       bad_state ? "FAIL" : "PASS", bad_digest ? "FAIL" : "PASS",
                       bad_fold ? "FAIL" : "PASS", record->different_lane[variant],
                       record->expected_word[variant], record->actual_word[variant],
                       record->fold[0], record->fold[variant], expected, actual);
                ++errors[variant];
            }
        }
    }
    int failed = 0;
    for (unsigned variant = 0; variant < NVARIANTS; ++variant) {
        printf("VERIFY name=%s count=%zu state_words=%d digest=SHA256 fold=32bit"
               " mismatches=%zu result=%s\n",
               implementations[variant].name, count, B, errors[variant],
               errors[variant] ? "FAIL" : "PASS");
        if (errors[variant]) failed = 1;
    }
    free(records);
    return failed;
}

static double measure(const struct implementation *implementation, uint64_t base,
                      size_t count, uint8_t *observed, uint8_t checksum[DIGEST_BYTES])
{
    double started = now_seconds();
    #pragma omp parallel for schedule(static)
    for (long long index = 0; index < (long long)count; ++index) {
        uint32_t state[B];
        implementation->hash(base + (uint64_t)index, state);
        state_digest(state, &observed[(size_t)index * DIGEST_BYTES]);
    }
    double elapsed = now_seconds() - started;
    /* All nonce digests are consumed, in nonce order. This reporting checksum
     * and cross-implementation comparisons are not per-nonce mining work. */
    sha256(checksum, observed, count * DIGEST_BYTES);
    return elapsed;
}

static int benchmark(size_t count, size_t runs, const unsigned selected[], unsigned nselected)
{
    if (count > SIZE_MAX / DIGEST_BYTES) {
        fprintf(stderr, "benchmark count exceeds addressable digest storage\n");
        return 2;
    }
    uint8_t *observed = malloc(count * DIGEST_BYTES);
    if (!observed) { perror("allocate observed digests"); return 2; }
    double rate_sums[NVARIANTS] = {0};
    for (size_t run = 0; run < runs; ++run) {
        uint8_t expected[DIGEST_BYTES] = {0};
        uint64_t base = UINT64_C(0x100000) + (uint64_t)run * (uint64_t)count;
        for (unsigned position = 0; position < nselected; ++position) {
            unsigned variant = selected[(run + position) % nselected];
            const struct implementation *implementation = &implementations[variant];
            uint8_t checksum[DIGEST_BYTES];
            double seconds = measure(implementation, base, count, observed, checksum);
            if (seconds <= 0) {
                fprintf(stderr, "timer returned a nonpositive interval\n");
                free(observed);
                return 2;
            }
            double rate = (double)count / seconds;
            rate_sums[variant] += rate;
            char hex[65];
            digest_hex(checksum, hex);
            printf("RUN name=%s run=%zu count=%zu base=%016" PRIx64
                   " seconds=%.9f Hps=%.9f digest_checksum=%s\n",
                   implementation->name, run + 1, count, base, seconds, rate, hex);
            fflush(stdout);
            if (position == 0) memcpy(expected, checksum, DIGEST_BYTES);
            else if (memcmp(expected, checksum, DIGEST_BYTES) != 0) {
                fprintf(stderr, "FAIL: full digest checksum differs for %s in run %zu\n",
                        implementation->name, run + 1);
                free(observed);
                return 1;
            }
        }
        printf("PASS run=%zu count=%zu all_full_digest_checksums_agree=yes\n", run + 1, count);
    }
    for (unsigned position = 0; position < nselected; ++position) {
        unsigned variant = selected[position];
        printf("MEAN name=%s runs=%zu count=%zu arithmetic_Hps=%.9f\n",
               implementations[variant].name, runs, count, rate_sums[variant] / (double)runs);
    }
    free(observed);
    return 0;
}

static int parse_positive(const char *text, size_t *value)
{
    if (!text[0] || text[0] < '0' || text[0] > '9') return 0;
    char *end;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, 10);
    if (errno || *end || parsed == 0 || parsed > SIZE_MAX || parsed > LLONG_MAX) return 0;
    *value = (size_t)parsed;
    return 1;
}

static void usage(const char *program)
{
    fprintf(stderr, "Usage: %s verify [count=32]\n"
                    "       %s bench count runs [original scalar competitor combined]\n",
            program, program);
}

int main(int argc, char **argv)
{
    if (argc < 2) { usage(argv[0]); return 2; }
    int verify = strcmp(argv[1], "verify") == 0;
    int bench = strcmp(argv[1], "bench") == 0;
    size_t count = 32, runs = 0;
    unsigned selected[NVARIANTS] = {0, 1, 2, 3};
    unsigned nselected = NVARIANTS;
    if (verify) {
        if (argc > 3 || (argc == 3 && !parse_positive(argv[2], &count))) {
            usage(argv[0]); return 2;
        }
    } else if (bench) {
        if (argc < 4 || !parse_positive(argv[2], &count) || !parse_positive(argv[3], &runs)) {
            usage(argv[0]); return 2;
        }
        if (argc > 4) {
            nselected = 0;
            unsigned seen = 0;
            for (int argument = 4; argument < argc; ++argument) {
                unsigned variant;
                for (variant = 0; variant < NVARIANTS; ++variant)
                    if (!strcmp(argv[argument], implementations[variant].name)) break;
                if (variant == NVARIANTS || (seen & (1u << variant))) {
                    fprintf(stderr, "unknown or duplicate implementation: %s\n", argv[argument]);
                    return 2;
                }
                seen |= 1u << variant;
                selected[nselected++] = variant;
            }
        }
    } else { usage(argv[0]); return 2; }

    int threads = 1;
#ifdef _OPENMP
    threads = omp_get_max_threads();
#endif
    printf("CONFIG B=%d W=%d lane_bytes=%d max_threads=%d mode=%s\n",
           B, W, LANE_BYTES, threads, argv[1]);
    serial_initialize_all();
    warm_worker_state();
    printf("SETUP all_four_table_initializers_warmed_serially=yes"
           " all_four_functions_and_full_digests_warmed_per_thread=yes"
           " timing_includes=hash_state+lane_serialization+full_SHA256\n");
    fflush(stdout);
    return verify ? verify_all(count) : benchmark(count, runs, selected, nselected);
}
