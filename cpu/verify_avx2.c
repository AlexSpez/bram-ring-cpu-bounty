/* verify_avx2.c — BRAM-ring verifier/miner, AVX2 lane-parallel. The champion
 * CPU attack: this is the number to beat if you want to close the moat from
 * the CPU side.
 *
 * The key structural fact: within one step, the B lanes are INDEPENDENT --
 * they all read the same frozen ring state (`head`/`pool`) and only the step
 * loop is serial. So a single-nonce hash has B-way data parallelism that a
 * naive kernel throws away. Here we process 8 lanes at a time:
 *
 *   - taps:  one AVX2 gather + variable-shift per cell for 8 lanes at once
 *            (the pool is packed to uint32 -- products are pre-shifted down by
 *             PBITLO so their tapped bits [PBITLO..PBITHI] land in 32 bits).
 *            The per-cell tap index and shift are packed into ONE uint16
 *            (`PKT` = (shift << 10) | pool_index), so the inner loop streams
 *            half the table bytes it otherwise would -- at B=768, W=20 the tap
 *            tables are read every step and were costing more bandwidth than
 *            the banks themselves.
 *   - CA:    the 15-mux tree runs on 8 lanes per instruction (rule-bit masks
 *            are stored bit-major, lane-contiguous: RB_CM[i*B + b])
 *   - ring:  head/rd are DOUBLE-BUFFERED (pointer swap, no copying) and the
 *            shift to the next lane is one unaligned vector store per 8 lanes
 *            at nh[b0+1] -- the ring shift is a pure address offset. The
 *            straightforward version memcpy'd ~15 MB per hash to achieve the
 *            same thing.
 *   - RMW:   stays SCALAR, on purpose. That is the memory-hard part -- the
 *            thing that starves the GPU and defines the moat. We delete the
 *            CPU's *compute* tax, never its memory traffic.
 *
 * Threading note: this box's "20 threads" are not equal. On a hybrid CPU
 * (P-cores + hyperthread siblings + E-cores), pin to the physical P-cores or
 * use ~16 threads; running 20 unpinned threads measurably LOSES to 8 pinned
 * ones. See README's "What you'll see" for the measured curve.
 *
 * Bit-exact against vectors.txt. No spec change -- ever: this file is an
 * implementation of spec.py, and spec.py is the definition.
 *
 * The tap-packing and double-buffering wins came from an external red-team
 * pass (2026-08-05) that was asked to beat this kernel and did, by 47%.
 *
 *   cc -O3 -march=native -fopenmp -o verify_avx2 verify_avx2.c sha256.c
 *   ./verify_avx2            # verify against the golden vectors + benchmark
 *   ./verify_avx2 mine 0     # mine, emitting SHARE lines for race.py
 *   ./verify_avx2 fold <nonce-hex> [count]   # fast fold of specific nonces
 */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <immintrin.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#include "tables.h"
#include "sha256.h"

#define M18    ((1u << 18) - 1)
#define MASK   ((1u << W) - 1)
#define NPOOL  (B + NDSP)
#define PBITLO 8                     /* must match spec.PBITLO */

static double now(void)
{ struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + 1e-9*t.tv_nsec; }

static uint32_t RB_CM[16*B];
static uint32_t AMASK[B];
static uint16_t PKT[W*B];            /* (sh << 10) | idx : one 128-bit load per cell */
static int      ready = 0;

static void build_tables(void)
{
    for (int b = 0; b < B; b++) {
        uint32_t m = 0;
        for (int q = 0; q < ADDRB; q++) m |= 1u << ADDRBIT[b*ADDRB + q];
        AMASK[b] = m;
        for (int i = 0; i < 16; i++) {
            uint32_t m = 0;
            for (int c = 0; c < W; c++)
                if ((RULE[b*W + c] >> i) & 1) m |= 1u << c;
            RB_CM[i*B + b] = m;
        }
        for (int c = 0; c < W; c++) {
            int k = b*W + c;
            int idx, sh;
            if (TAPK[k]) { idx = B + TAPX[k]; sh = TAPY[k] - PBITLO; }
            else         { idx = TAPX[k];     sh = TAPY[k]; }
            PKT[c*B + b] = (uint16_t)((sh << 10) | idx);
        }
    }
    ready = 1;
}

static void init_heads(uint64_t nonce, uint32_t head[B])
{
    uint64_t s = nonce ^ EPOCH_CONST;
    for (int b = 0; b < B; b++) {
        s ^= s << 13; s ^= s >> 7; s ^= s << 17;
        head[b] = (uint32_t)((s ^ PREVCHUNK[b]) & MASK);
    }
}

#define MUX(s, a, b) _mm256_or_si256(_mm256_and_si256(s, a), _mm256_andnot_si256(s, b))

static void hash_state(uint64_t nonce, uint32_t out[B])
{
    static _Thread_local uint32_t bank[B][DEPTH];
    static _Thread_local uint32_t pool[NPOOL];
    static _Thread_local uint32_t headA[B+1], headB[B+1], rdA[B], rdB[B];
    uint32_t *head = headA, *nh = headB, *rd = rdA, *nrd = rdB;
    uint32_t vbuf[8];

    if (!ready) build_tables();
    init_heads(nonce, head);
    memset(rd, 0, sizeof rdA);

    const __m256i one  = _mm256_set1_epi32(1);
    const __m256i mask = _mm256_set1_epi32(MASK);

    static _Thread_local uint32_t preg0[NDSP], preg1[NDSP];
    memset(preg0, 0, sizeof preg0);
    memset(preg1, 0, sizeof preg1);

    for (int step = 0; step < DEPTH + STEPS; step++) {
        int fill = step < DEPTH;
        for (int b = 0; b < B; b++) pool[b] = head[b];
        for (int j = 0; j < NDSP; j++) {
            uint64_t p = (uint64_t)(head[MULA[j]] & M18)
                       * (((uint64_t)(head[MULB[j]] & M18) << 1) | 1) + MULC[j];
            pool[B + j] = preg0[j]; preg0[j] = preg1[j];
            preg1[j] = (uint32_t)(p >> PBITLO);
        }

        for (int b0 = 0; b0 < B; b0 += 8) {
            __m256i h8 = _mm256_loadu_si256((const __m256i*)&head[b0]);
            __m256i r8 = _mm256_loadu_si256((const __m256i*)&rd[b0]);
            __m256i Cw = _mm256_and_si256(_mm256_xor_si256(h8, r8), mask);
            __m256i Lw = _mm256_and_si256(_mm256_or_si256(_mm256_slli_epi32(Cw, 1),
                                          _mm256_srli_epi32(Cw, W-1)), mask);
            __m256i Rw = _mm256_and_si256(_mm256_or_si256(_mm256_srli_epi32(Cw, 1),
                                          _mm256_slli_epi32(Cw, W-1)), mask);

            __m256i Tw = _mm256_setzero_si256();
            const __m256i im = _mm256_set1_epi32(0x3FF);
            for (int c = 0; c < W; c++) {
                __m256i pk   = _mm256_cvtepu16_epi32(_mm_loadu_si128((const __m128i*)&PKT[c*B + b0]));
                __m256i idx  = _mm256_and_si256(pk, im);
                __m256i sh   = _mm256_srli_epi32(pk, 10);
                __m256i vals = _mm256_i32gather_epi32((const int*)pool, idx, 4);
                __m256i bit  = _mm256_and_si256(_mm256_srlv_epi32(vals, sh), one);
                Tw = _mm256_or_si256(Tw, _mm256_slli_epi32(bit, c));
            }

            __m256i e[8], f[4], g2[2];
            for (int j = 0; j < 8; j++)
                e[j] = MUX(Lw, _mm256_loadu_si256((const __m256i*)&RB_CM[(2*j+1)*B + b0]),
                               _mm256_loadu_si256((const __m256i*)&RB_CM[(2*j)*B + b0]));
            for (int j = 0; j < 4; j++) f[j]  = MUX(Cw, e[2*j+1], e[2*j]);
            for (int j = 0; j < 2; j++) g2[j] = MUX(Rw, f[2*j+1], f[2*j]);
            __m256i v8 = _mm256_and_si256(MUX(Tw, g2[1], g2[0]), mask);

            _mm256_storeu_si256((__m256i*)vbuf, v8);       /* for the scalar RMW */
            _mm256_storeu_si256((__m256i*)&nh[b0+1], v8);  /* the ring shift, vector-wide */

            for (int k = 0; k < 8; k++) {
                int b = b0 + k;
                uint32_t v = vbuf[k];
                if (fill) {
                    bank[b][step] = v;
                    nrd[b] = 0;
                } else {
                    unsigned a = _pext_u32(v, AMASK[b]);
                    nrd[b] = bank[b][a];
                    bank[b][a] = v;
                }
            }
        }
        nh[0] = nh[B];                                   /* wrap: lane B-1 -> lane 0 */
        uint32_t *t;
        t = head; head = nh; nh = t;
        t = rd;   rd = nrd;  nrd = t;
    }
    memcpy(out, head, sizeof(uint32_t)*B);
}

static void state_digest(const uint32_t head[B], char hex[65])
{
    int nb = (W + 7) / 8;
    static _Thread_local uint8_t raw[B * ((W + 7) / 8)];
    for (int b = 0; b < B; b++)
        for (int k = 0; k < nb; k++) raw[b*nb + k] = (head[b] >> (8*k)) & 0xff;
    uint8_t d[32]; sha256(d, raw, (size_t)B * nb);
    for (int i = 0; i < 32; i++) sprintf(hex + 2*i, "%02x", d[i]);
}

static int ncores(void)
{
#ifdef _OPENMP
    int n = 1;
    #pragma omp parallel
    { _Pragma("omp single") n = omp_get_num_threads(); }
    return n;
#else
    return 1;
#endif
}

static uint32_t difficulty_value(const uint32_t head[B])
{
    uint32_t words[(B*W + 31) / 32];
    memset(words, 0, sizeof words);
    for (int b = 0; b < B; b++)
        for (int c = 0; c < W; c++)
            if ((head[b] >> c) & 1) { int bp = b*W + c; words[bp >> 5] |= 1u << (bp & 31); }
    uint32_t v = 0;
    for (int i = 0; i < (int)((B*W + 31) / 32); i++) v ^= words[i];
    return v;
}

#define SHARE_TARGET 12.0
static void vardiff(int *D, long *cnt, double *tsec, double target)
{
    double t = now(), dt = t - *tsec;
    if (dt < 1.0) return;
    double rate = *cnt / dt;
    while (rate > target*1.5 && *D < 31) { (*D)++; rate /= 2; }
    while (rate < target/1.5 && *D > 1)  { (*D)--; rate *= 2; }
    *cnt = 0; *tsec = t;
}

static int mine(uint64_t start)
{
    int NT = ncores();
    fprintf(stderr, "verify_avx2.c mining on %d cores\n", NT);
    { uint32_t out[B]; hash_state(0, out); }
    int gD = 10; long gcnt = 0; double gtsec = now();
    #pragma omp parallel num_threads(NT) shared(gD, gcnt, gtsec)
    {
    #ifdef _OPENMP
        int tid = omp_get_thread_num();
    #else
        int tid = 0;
    #endif
        uint64_t n = start + (uint64_t)tid;
        uint32_t out[B];
        for (;;) {
            hash_state(n, out);
            uint32_t fv = difficulty_value(out);
            int z = fv ? __builtin_clz(fv) : 32;
            if (z >= gD) {
                #pragma omp critical
                { printf("SHARE %llx %d %d\n", (unsigned long long)n, z, gD); fflush(stdout); }
                #pragma omp atomic
                gcnt++;
            }
            n += NT;
            if (tid == 0) vardiff(&gD, &gcnt, &gtsec, SHARE_TARGET);
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && !strcmp(argv[1], "mine"))
        return mine(argc > 2 ? strtoull(argv[2], 0, 16) : 0);
    if (argc > 2 && !strcmp(argv[1], "fold")) {
        uint64_t n0 = strtoull(argv[2], 0, 16);
        int cnt = (argc > 3) ? atoi(argv[3]) : 1;
        { uint32_t out[B]; hash_state(0, out); }
        #pragma omp parallel for ordered schedule(static,1)
        for (int i = 0; i < cnt; i++) {
            uint32_t out[B]; hash_state(n0 + i, out);
            uint32_t fv = difficulty_value(out);
            #pragma omp ordered
            printf("%016llx %08x\n", (unsigned long long)(n0 + i), fv);
        }
        return 0;
    }

    FILE *f = fopen("../vectors.txt","r"); if(!f) f = fopen("vectors.txt","r");
    if (!f) { fprintf(stderr, "vectors.txt missing -- run: python3 generate.py\n"); return 1; }
    char line[8192]; int nv = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0]=='#') continue;
        /* every column: nonce, digest, 32-bit fold, raw state (lane B-1..0, (W+3)/4 hex each) */
        static char nh[32], dig[80], fo[16], st[B * ((W + 3) / 4) + 64];
        if (sscanf(line, "%31s %79s %15s %4000s", nh, dig, fo, st) != 4) continue;
        uint64_t nonce = strtoull(nh, 0, 16);
        uint32_t out[B]; char got[65];
        hash_state(nonce, out); state_digest(out, got);
        if (strcmp(got, dig)) { printf("MISMATCH digest nonce %s\n  got %s\n  exp %s\n", nh, got, dig); return 1; }
        uint32_t fv = difficulty_value(out), ef = (uint32_t)strtoul(fo, 0, 16);
        if (fv != ef) { printf("MISMATCH fold nonce %s\n  got %08x\n  exp %08x\n", nh, fv, ef); return 1; }
        static char raw[B * ((W + 3) / 4) + 1]; char *p = raw;
        for (int b = B - 1; b >= 0; b--) p += sprintf(p, "%0*x", (W + 3) / 4, out[b]);
        if (strcmp(raw, st)) { printf("MISMATCH state nonce %s\n", nh); return 1; }
        nv++;
    }
    fclose(f);
    printf("verify_avx2.c == spec.py: %d/%d golden vectors bit-exact (digest, fold, full state)\n", nv, nv);

    int iters = 200; double t0 = now();
    for (int i = 0; i < iters; i++) { uint32_t out[B]; hash_state(i, out); }
    double dt = now() - t0;
    printf("CPU 1 core (verify_avx2): %.1f hashes/s  (%.2f ms/header)\n",
           iters/dt, 1000.0*dt/iters);

    int NT = ncores();
    int miters = 100 * NT; t0 = now();
    #pragma omp parallel for num_threads(NT)
    for (int i = 0; i < miters; i++) { uint32_t out[B]; hash_state(i, out); }
    dt = now() - t0;
    printf("CPU %d cores (verify_avx2): %.0f hashes/s\n", NT, miters/dt);
    return 0;
}
