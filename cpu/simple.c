/* simple.c — BRAM-ring, one nonce at a time, written to match spec.py
 * line for line. Verifies against vectors.txt, reports hashes/second, and
 * (mode `avalanche`) measures output avalanche under nonce bit-flips.
 *
 *   cc -O3 -march=native -fopenmp -o simple simple.c sha256.c && ./simple
 *
 * Note the working set: bank[B][DEPTH] as uint32 is B*512*4 (1.5 MB at B=768)
 * per thread (20/32 of that is true entropy) -- past per-core L2 on most
 * CPUs. That is the memory-hardness doing its job; this prints the honest naive-CPU rate.
 */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include "tables.h"
#include "sha256.h"
#ifdef _OPENMP
#include <omp.h>
#endif

#define M18 ((1u << 18) - 1)

static double now(void)
{ struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + 1e-9*t.tv_nsec; }

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

/* == spec.init_heads */
static void init_heads(uint64_t nonce, uint32_t head[B])
{
    uint64_t s = nonce ^ EPOCH_CONST;
    uint32_t mask = (1u << W) - 1;
    for (int b = 0; b < B; b++) {
        s ^= s << 13; s ^= s >> 7; s ^= s << 17;
        head[b] = (uint32_t)((s ^ PREVCHUNK[b]) & mask);
    }
}

static void hash_state(uint64_t nonce, uint32_t out[B])
{
    static _Thread_local uint32_t bank[B][DEPTH];
    uint32_t head[B], prev[B], rd[B], nh[B], nrd[B];
    uint64_t prod[NDSP], preg0[NDSP], preg1[NDSP];
    uint32_t mask = (1u << W) - 1;

    init_heads(nonce, head);
    memset(rd, 0, sizeof rd);
    memset(preg0, 0, sizeof preg0); /* v3: 2-deep product pipe — zero at steps 0,1 */
    memset(preg1, 0, sizeof preg1);

    /* spec change #4: steps 0..DEPTH-1 are the FILL phase (same dynamics,
       RAM read forced to zero, write goes to row `step`) */
    for (int step = 0; step < DEPTH + STEPS; step++) {
        int fill = step < DEPTH;
        memcpy(prev, head, sizeof head);
        for (int j = 0; j < NDSP; j++) {        /* DSP layer, 2-step lag: taps read the
                                                   products of the state 2 steps back */
            uint64_t nu = (uint64_t)(prev[MULA[j]] & M18)
                    * (((uint64_t)(prev[MULB[j]] & M18) << 1) | 1) + MULC[j];
            prod[j] = preg0[j]; preg0[j] = preg1[j]; preg1[j] = nu;
        }
        for (int b = 0; b < B; b++) {
            uint32_t g = (head[b] ^ rd[b]) & mask;
            const unsigned short *ru = &RULE[b*W];
            const unsigned char  *tk = &TAPK[b*W];
            const unsigned short *tx = &TAPX[b*W];
            const unsigned char  *ty = &TAPY[b*W];
            uint32_t ng = 0;
            for (int c = 0; c < W; c++) {
                int cl = (c==0)?W-1:c-1, cr = (c==W-1)?0:c+1;
                unsigned L=(g>>cl)&1, C=(g>>c)&1, R=(g>>cr)&1;
                unsigned T = tk[c] ? (unsigned)((prod[tx[c]] >> ty[c]) & 1)
                                   : (unsigned)((prev[tx[c]] >> ty[c]) & 1);
                ng |= (uint32_t)((ru[c] >> ((T<<3)|(R<<2)|(C<<1)|L)) & 1) << c;
            }
            uint32_t v = ng & mask;
            if (fill) {
                bank[b][step] = v;
                nrd[b] = 0;
            } else {
                const unsigned char *ab = &ADDRBIT[b*ADDRB];
                unsigned a = 0;
                for (int k = 0; k < ADDRB; k++) a |= (unsigned)((v>>ab[k])&1) << k;
                nrd[b] = bank[b][a];
                bank[b][a] = v;
            }
            nh[(b+1)%B] = v;
        }
        memcpy(head, nh, sizeof head); memcpy(rd, nrd, sizeof rd);
    }
    memcpy(out, head, sizeof(uint32_t)*B);
}

/* SHA-256 of the packed state -> hex (== spec.digest) */
static void state_digest(const uint32_t head[B], char hex[65])
{
    int nb = (W + 7) / 8;
    static _Thread_local uint8_t raw[B * ((W + 7) / 8)];
    for (int b = 0; b < B; b++)
        for (int k = 0; k < nb; k++) raw[b*nb + k] = (head[b] >> (8*k)) & 0xff;
    uint8_t d[32]; sha256(d, raw, (size_t)B * nb);
    for (int i = 0; i < 32; i++) sprintf(hex + 2*i, "%02x", d[i]);
}

static int avalanche(void)
{
    const uint64_t bases[] = { 0x1111, 0xcafebabe, 0x123456789abcdefULL };
    double tot = 0; int n = 0; double lo = 1, hi = 0;
    for (unsigned i = 0; i < sizeof bases/sizeof *bases; i++) {
        uint32_t ref[B], out[B];
        hash_state(bases[i], ref);
        for (int bit = 0; bit < 32; bit++) {
            hash_state(bases[i] ^ (1ULL << bit), out);
            int d = 0;
            for (int b = 0; b < B; b++) d += __builtin_popcount(ref[b] ^ out[b]);
            double f = (double)d / (B * W);
            tot += f; n++;
            if (f < lo) lo = f; if (f > hi) hi = f;
        }
    }
    printf("avalanche over %d nonce bit-flips: mean %.4f  min %.4f  max %.4f  (ideal 0.5)\n",
           n, tot/n, lo, hi);
    return 0;
}

/* 32-bit XOR fold of the bit-packed state (== spec.difficulty_value) */
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

/* self-tuning share difficulty (== cpu/simple.c): hold ~SHARE_TARGET shares/s */
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
    fprintf(stderr, "simple.c mining on %d cores\n", NT);
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
            n += NT;                                  /* stripe across threads */
            if (tid == 0) vardiff(&gD, &gcnt, &gtsec, SHARE_TARGET);
        }
    }
    return 0;
}

int main(int argc, char **argv)

{
    if (argc > 1 && !strcmp(argv[1], "mine"))
        return mine(argc > 2 ? strtoull(argv[2], 0, 16) : 0);
    if (argc > 1 && !strcmp(argv[1], "avalanche")) return avalanche();
    if (argc > 2 && !strcmp(argv[1], "fold")) {     /* fold <nonce-hex> [count] */
        uint64_t n0 = strtoull(argv[2], 0, 16);
        int cnt = (argc > 3) ? atoi(argv[3]) : 1;
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
        char nh[32], dig[80]; if (sscanf(line, "%31s %79s", nh, dig) != 2) continue;
        uint64_t nonce = strtoull(nh, 0, 16);
        uint32_t out[B]; char got[65];
        hash_state(nonce, out); state_digest(out, got);
        if (strcmp(got, dig)) { printf("MISMATCH nonce %s\n  got %s\n  exp %s\n", nh, got, dig); return 1; }
        nv++;
    }
    fclose(f);
    printf("simple.c == spec.py: %d/%d golden vectors bit-exact\n", nv, nv);

    int NT = ncores();
    int iters = 100 * NT; double t0 = now();
    #pragma omp parallel for num_threads(NT)
    for (int i = 0; i < iters; i++) { uint32_t out[B]; hash_state(i, out); }
    double dt = now() - t0;
    printf("CPU %d cores (simple): %.0f hashes/s\n", NT, iters/dt);
    return 0;
}
