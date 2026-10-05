#!/usr/bin/env python3
"""
rmw_wall.py — the microbenchmark behind the "scattered-RMW wall" number.

Contributed by the 2026-08-05 adversarial review pass (which also produced
the current atomicExch kernel); ships so the ceiling in the README is
reproducible on your own card rather than taken on faith.

README.md ("Why the GPU can't catch up") says the RTX 3070's *measured*
random-RMW throughput is ~137 GB/s (34% of streaming), flat from the real
geometry (512 rows per lane) up to multi-GB working sets -- smaller working
sets run faster -- implying a
1,359 H/s wall (each hash does STEPS*B = 2048*768 = 1,572,864 dependent RMWs;
each RMW costs a 32B sector read + 32B sector write = 64B).

This microbenchmark contains NO bram-ring code. It mimics the access pattern:
per-lane private region, data-dependent dependent-chain RMW, one warp per 32
lanes, exactly the lane-strided layout mine.py uses (entry-major within a
nonce's banks: address a*B + b).

Variants:
  plain   : old = buf[i]; buf[i] = v            (two transactions)
  ldlu    : __ldlu load + plain store           (what mine.py does)
  ldcs    : __ldcs load + __stcs store          (streaming, evict-first)
  atomic  : old = atomicExch(&buf[i], v)        (single L2 RMW transaction)
"""
import sys, time
import cupy as cp

BODY = r"""
typedef unsigned int u32; typedef unsigned long long u64;
#define B 768

// xorshift-ish mix so the compiler can't fold the chain away
__device__ __forceinline__ u32 mix(u32 x) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17; return x;
}

extern "C" __global__ void rmw_plain(u32* __restrict__ buf, u32* __restrict__ sink,
                                     int steps, u32 mask, long long span) {
    const int b = threadIdx.x;
    u32* base = buf + (long long)blockIdx.x * span;
    u32 rd = mix(blockIdx.x * B + b);
    for (int s = 0; s < steps; s++) {
        u32 v = mix(rd ^ (u32)s);
        u32 a = v & mask;
        u32 old = base[(long long)a * B + b];
        base[(long long)a * B + b] = v;
        rd = old;
    }
    if (rd == 0xdeadbeefu) sink[0] = rd;
}

extern "C" __global__ void rmw_ldlu(u32* __restrict__ buf, u32* __restrict__ sink,
                                    int steps, u32 mask, long long span) {
    const int b = threadIdx.x;
    u32* base = buf + (long long)blockIdx.x * span;
    u32 rd = mix(blockIdx.x * B + b);
    for (int s = 0; s < steps; s++) {
        u32 v = mix(rd ^ (u32)s);
        u32 a = v & mask;
        u32 old = __ldlu((const u32*)&base[(long long)a * B + b]);
        base[(long long)a * B + b] = v;
        rd = old;
    }
    if (rd == 0xdeadbeefu) sink[0] = rd;
}

extern "C" __global__ void rmw_ldcs(u32* __restrict__ buf, u32* __restrict__ sink,
                                    int steps, u32 mask, long long span) {
    const int b = threadIdx.x;
    u32* base = buf + (long long)blockIdx.x * span;
    u32 rd = mix(blockIdx.x * B + b);
    for (int s = 0; s < steps; s++) {
        u32 v = mix(rd ^ (u32)s);
        u32 a = v & mask;
        u32 old = __ldcs((const u32*)&base[(long long)a * B + b]);
        __stcs(&base[(long long)a * B + b], v);
        rd = old;
    }
    if (rd == 0xdeadbeefu) sink[0] = rd;
}

extern "C" __global__ void rmw_atomic(u32* __restrict__ buf, u32* __restrict__ sink,
                                      int steps, u32 mask, long long span) {
    const int b = threadIdx.x;
    u32* base = buf + (long long)blockIdx.x * span;
    u32 rd = mix(blockIdx.x * B + b);
    for (int s = 0; s < steps; s++) {
        u32 v = mix(rd ^ (u32)s);
        u32 a = v & mask;
        u32 old = atomicExch(&base[(long long)a * B + b], v);
        rd = old;
    }
    if (rd == 0xdeadbeefu) sink[0] = rd;
}

// same pattern with 8-byte words: if scattered throughput is sector-quantized,
// doubling the word size should NOT halve the RMW rate (kills bit-packing hopes)
extern "C" __global__ void rmw_wide(u64* __restrict__ buf, u32* __restrict__ sink,
                                    int steps, u32 mask, long long span) {
    const int b = threadIdx.x;
    u64* base = buf + (long long)blockIdx.x * span;
    u32 rd = mix(blockIdx.x * B + b);
    for (int s = 0; s < steps; s++) {
        u32 v = mix(rd ^ (u32)s);
        u32 a = v & mask;
        u64 old = base[(long long)a * B + b];
        base[(long long)a * B + b] = ((u64)v << 32) | v;
        rd = (u32)old;
    }
    if (rd == 0xdeadbeefu) sink[0] = rd;
}

// streaming copy for the 405 GB/s reference
extern "C" __global__ void stream_copy(const u32* __restrict__ src, u32* __restrict__ dst,
                                       long long n) {
    long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    long long stride = (long long)gridDim.x * blockDim.x;
    for (; i < n; i += stride) dst[i] = src[i];
}
"""

mod = cp.RawModule(code=BODY, options=("-std=c++14",))
B = 768

def bench_rmw(name, nblocks, depth, steps=2048):
    """nblocks blocks x B lanes, each lane owns `depth` words (entry-major)."""
    span = depth * B
    wsize = 8 if name == "rmw_wide" else 4
    dtype = cp.uint64 if name == "rmw_wide" else cp.uint32
    buf = cp.empty(nblocks * span, dtype=dtype)
    buf[:] = 1
    sink = cp.zeros(1, dtype=cp.uint32)
    fn = mod.get_function(name)
    args = (buf, sink, cp.int32(steps), cp.uint32(depth - 1), cp.int64(span))
    fn((nblocks,), (B,), args)  # warm
    cp.cuda.Stream.null.synchronize()
    t0 = time.time()
    fn((nblocks,), (B,), args)
    cp.cuda.Stream.null.synchronize()
    dt = time.time() - t0
    rmws = nblocks * B * steps
    gbs = rmws * 64 / dt / 1e9          # 32B read + 32B write per RMW
    hs = rmws / dt / 1_572_864          # equivalent H/s at STEPS*B RMW per hash
    ws_mb = nblocks * span * wsize / 1e6
    print(f"  {name:8s} blocks={nblocks:4d} depth={depth:4d} ws={ws_mb:7.0f} MB "
          f"{rmws/dt/1e9:6.2f} G-RMW/s  {gbs:7.1f} GB/s(sector)  ~{hs:6.0f} H/s-equiv", flush=True)
    del buf
    return gbs, hs

def bench_stream(gb=2.0):
    n = int(gb * 1e9 / 8)
    src = cp.empty(n, dtype=cp.uint32); dst = cp.empty(n, dtype=cp.uint32)
    fn = mod.get_function("stream_copy")
    args = (src, dst, cp.int64(n))
    fn((1184,), (256,), args); cp.cuda.Stream.null.synchronize()
    t0 = time.time(); fn((1184,), (256,), args); cp.cuda.Stream.null.synchronize()
    dt = time.time() - t0
    print(f"  streaming copy: {n*8/dt/1e9:.0f} GB/s (read+write, {gb:.0f} GB moved)", flush=True)

if __name__ == "__main__":
    print("== streaming reference ==")
    bench_stream()
    print("== scattered RMW, depth=512 (1.5 MB/block: the real geometry) ==")
    for name in ("rmw_plain", "rmw_ldlu", "rmw_ldcs", "rmw_atomic"):
        for nb in (46, 92, 128, 256, 460):
            bench_rmw(name, nb, 512)
    print("== word-size probe (8B words, same geometry: depth=256 words = same bytes) ==")
    for nb in (128, 460):
        bench_rmw("rmw_wide", nb, 256)
    print("== flatness check: working-set sweep at 460 blocks-equivalent footprint ==")
    for nb, depth in ((460, 128), (460, 512), (460, 2048), (128, 512)):
        bench_rmw("rmw_ldlu", nb, depth)
