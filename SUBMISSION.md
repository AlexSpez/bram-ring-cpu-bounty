# BRAM-ring CPU kernel candidate

This candidate replaces the AVX2 gather path for remote tap bits with scalar
loads from a lane-major packed tap table. The rest of the ring algorithm is
unchanged. It uses the repository's MIT licence.

## Build and verify

From the repository root on a Linux machine with GCC, OpenMP and Python 3:

```sh
gcc -O3 -march=native -funroll-loops -fopenmp \
  -o cpu/verify_scalar_taps cpu/verify_scalar_taps.c cpu/sha256.c
cd cpu
./verify_scalar_taps vectors | python3 ../host/check_vectors.py
OMP_NUM_THREADS=8 taskset -c 0,2,4,6,8,10,12,14 ./verify_scalar_taps bench
```

The `bench` entry point prints five runs of 800 nonces each at eight threads,
plus their arithmetic mean. Timing includes the ring fill, run, and full
SHA-256 digest for every nonce. One-time table setup is excluded. Pinning is
specific to the bounty reference i7-12700KF and should be checked on that
machine.

To test a new epoch, work in a scratch clone. `BRAM_EPOCH=<seed> python3
generate.py` regenerates the tables and vectors; rebuild and run the same
vector check. Keep the published `spec.py`, `generate.py` and `vectors.txt`
unchanged in the claim commit.

## Local evidence

On a Windows laptop with an Intel i7-11850H, GCC 16.2, eight OpenMP threads,
and both variants compiled with `-O3 -march=native -funroll-loops`, an
alternating five-pair benchmark of 800 nonces per run, including SHA-256 for
every nonce, gave the following H/s:

| Pair | Original | Scalar taps |
| --- | ---: | ---: |
| 1 | 92.31 | 113.73 |
| 2 | 95.27 | 116.58 |
| 3 | 89.90 | 113.94 |
| 4 | 95.19 | 114.57 |
| 5 | 95.48 | 115.58 |
| Mean | 93.63 | 114.88 |

That is a 22.7% improvement on this laptop. The original and candidate
produced the same digest checksum in each comparison. This is local evidence,
not a measurement on the bounty's Ubuntu i7-12700KF, where the actual prize
decision must be made. The comparison harness is `cpu/compare_local.py` and
`cpu/compare_local.c`. It builds both kernels into one binary and alternates
the run order.

The standalone `bench` entry point, which also computes the full digest for
each nonce, measured 114.23 H/s for the candidate versus 94.68 H/s for the
original under the same five-run protocol on the laptop (+20.7%).

The candidate also passed all eight published epoch0 vectors, including
digest, 32-bit fold and full state. A new seed was checked separately in a
scratch clone.
