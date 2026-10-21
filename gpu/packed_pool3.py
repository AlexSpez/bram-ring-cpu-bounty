#!/usr/bin/env python3
"""Three shared ring/product slots, one end barrier per CA step.

At global step s, slot s%3 contains the current ring and P(s-2).
The new ring is written to (s+1)%3, product P(s) to (s+2)%3.
All three slots have disjoint reads/writes within each step; the end
barrier orders each step before the next. The DSP delay remains two.
"""
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packed_pool as parent

cp, np, spec, reference = parent.cp, parent.np, parent.spec, parent.reference
B, W, DEPTH, MINE_K = parent.B, parent.W, parent.DEPTH, parent.MINE_K
VARIANT = "packed_pool3"
TAP_LAYOUT, UNROLL_TAPS, MIN_BLOCKS = parent.TAP_LAYOUT, parent.UNROLL_TAPS, parent.MIN_BLOCKS
POOL_SLOTS = 3
d_RULE, d_TAPS = parent.d_RULE, parent.d_TAPS


def _make_body():
    body = parent.BODY
    replacements = [
        ("__shared__ u32 sh[2][K][B+NDSP]", "__shared__ u32 sh[3][K][B+NDSP]", 1),
        ("sh[cur][k][B+j] = (u32)(p >> PBITLO)",
         "sh[cur == 0 ? 2 : cur-1][k][B+j] = (u32)(p >> PBITLO)", 1),
        ("sh[0][k][B+j] = sh[1][k][B+j] = 0;",
         "sh[0][k][B+j] = sh[1][k][B+j] = sh[2][k][B+j] = 0;", 1),
        ("sh[cur^1][k][(b+1)==B?0:(b+1)]", "sh[cur == 2 ? 0 : cur+1][k][(b+1)==B?0:(b+1)]", 2),
        ("            __syncthreads();                                // the product segment of slot cur fully read\n", "", 2),
        ("            cur ^= 1;", "            cur = cur == 2 ? 0 : cur+1;", 2),
    ]
    for before, after, count in replacements:
        if body.count(before) != count:
            raise RuntimeError(f"source anchor changed: {before!r}")
        body = body.replace(before, after)
    if body.count("__syncthreads()") != parent.BODY.count("__syncthreads()") - 2:
        raise RuntimeError("unexpected barrier change")
    if "cur^1" in body or "cur ^= 1" in body:
        raise RuntimeError("a two-slot phase update survived")
    return body


BODY = _make_body()
_mod = cp.RawModule(code=reference.DEFS + BODY, options=("-std=c++14",))
_mine = _mod.get_function("ring_mine")


def _launch(base, nhashes, nblocks=None, want_state=False):
    if nhashes < 1:
        raise ValueError("nhashes must be positive")
    nh = ((nhashes + MINE_K - 1) // MINE_K) * MINE_K
    if nblocks is None:
        nblocks = max(1, min(nh // MINE_K, 64))
    banks = cp.empty(nh * B * DEPTH, dtype=cp.uint32)
    folds = cp.zeros(nh, dtype=cp.uint32)
    states = cp.zeros(nh * B, dtype=cp.uint32) if want_state else cp.zeros(0, dtype=cp.uint32)
    _mine((nblocks,), (B,),
          (np.uint64(base), folds, states, d_RULE, d_TAPS, reference.d_TSH,
           reference.d_AB, reference.d_MULA, reference.d_MULB, reference.d_MULC,
           reference.d_PREV, banks, np.int32(nh)))
    cp.cuda.Stream.null.synchronize()
    return cp.asnumpy(folds)[:nhashes], (cp.asnumpy(states).reshape(-1, B)[:nhashes]
                                        if want_state else None)


def run(base, nhashes, nblocks=None):
    return _launch(base, nhashes, nblocks)[0]


def run_states(base, nhashes, nblocks=None):
    return _launch(base, nhashes, nblocks, want_state=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "vectors":
        with (Path(__file__).resolve().parent.parent / "vectors.txt").open() as source:
            nonces = [int(line.split()[0], 16) for line in source
                      if line.strip() and not line.startswith("#")]
        for nonce in nonces:
            folds, states = run_states(nonce, 1)
            print(f"{nonce:016x} {hashlib.sha256(spec.pack(states[0])).hexdigest()} "
                  f"{int(folds[0]):08x} "
                  + "".join(f"{int(v):0{(W+3)//4}x}" for v in states[0][::-1]))
    else:
        print("Use compare_gpu.py --candidate packed_pool3 for matched checks.")
