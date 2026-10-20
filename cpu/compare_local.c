#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <omp.h>
#include "tables.h"
#include "sha256.h"

void baseline_hash_state(uint64_t nonce, uint32_t out[B]);
void scalar_hash_state(uint64_t nonce, uint32_t out[B]);

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + 1e-9 * t.tv_nsec;
}

static void measure(const char *name, void (*fn)(uint64_t, uint32_t[B]), int n) {
    double t0 = now();
    unsigned char observed[800];
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < n; ++i) {
        uint32_t state[B];
        fn((uint64_t)i, state);
        unsigned char bytes[B * 3], digest[32];
        for (int b = 0; b < B; ++b) {
            bytes[3*b] = (unsigned char)state[b];
            bytes[3*b+1] = (unsigned char)(state[b] >> 8);
            bytes[3*b+2] = (unsigned char)(state[b] >> 16);
        }
        sha256(digest, bytes, sizeof bytes);
        observed[i] = digest[0];
    }
    double dt = now() - t0;
    unsigned checksum = 0;
    for (int i = 0; i < n; ++i) checksum += observed[i];
    printf("%s %.2f H/s (%.3f s, digest checksum %u)\n", name, n / dt, dt, checksum);
    fflush(stdout);
}

int main(void) {
    uint32_t state[B];
    baseline_hash_state(0, state);
    scalar_hash_state(0, state);
    for (int i = 0; i < 5; ++i) {
        if (i % 2 == 0) {
            measure("baseline", baseline_hash_state, 800);
            measure("scalar", scalar_hash_state, 800);
        } else {
            measure("scalar", scalar_hash_state, 800);
            measure("baseline", baseline_hash_state, 800);
        }
    }
}
