#!/usr/bin/env python3
"""Packed CA with one contiguous shared ring/product tap pool.

This local experiment derives from packed.BODY. The first B words of each
ping-pong slot are the ring; its next NDSP words are that slot's two-step
product pipeline. A packed tap index therefore addresses the pool directly,
removing the per-tap ring-versus-product conditional.

The product producer still overwrites slot cur only after all consumers have
finished reading it. Ring output still goes to slot cur^1. All barriers,
initialization, fill steps, bank exchanges, and output logic are retained.

The PACKED_* environment knobs from packed.py also apply. POOL_MIN_BLOCKS
can override only this kernel's launch bound, without changing packed.py.
No performance claim is made here.
"""
import hashlib
import os
from pathlib import Path
import re
import sys

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import packed

cp, np, spec = packed.cp, packed.np, packed.spec
reference = packed.reference
B, W, DEPTH, MINE_K = packed.B, packed.W, packed.DEPTH, packed.MINE_K
VARIANT = packed.VARIANT + "_pool"
TAP_LAYOUT, UNROLL_TAPS = packed.TAP_LAYOUT, packed.UNROLL_TAPS
MIN_BLOCKS = int(os.environ.get("POOL_MIN_BLOCKS", str(packed.MIN_BLOCKS)))
if MIN_BLOCKS not in (1, 2):
    raise ValueError("POOL_MIN_BLOCKS must be 1 or 2")


def _replace_once(body, before, after):
    if body.count(before) != 1:
        raise RuntimeError(f"upstream CUDA source changed around {before!r}")
    return body.replace(before, after, 1)


def _make_body():
    body = packed.BODY
    body = _replace_once(
        body, "__shared__ u32 sh[2][K][B];        // ping-pong ring register",
        "__shared__ u32 sh[2][K][B+NDSP]; // ring followed by lagged products")
    body = _replace_once(
        body,
        "    __shared__ u32 prodsh[2][K][NDSP]; // 2-deep product pipe (pre-shifted), slot = step parity\n",
        "")
    body = _replace_once(
        body,
        "u32 pool_word = ti < B ? sh[cur][k][ti] : prodsh[cur][k][ti-B];",
        "u32 pool_word = sh[cur][k][ti];")

    # Exactly three product accesses remain: its DSP write and the two
    # initial zero stores. Ring accesses preserve their existing indices.
    body, changed = re.subn(r"prodsh\[(cur|0|1)\]\[k\]\[j\]",
                            r"sh[\1][k][B+j]", body)
    if changed != 3:
        raise RuntimeError(f"expected three product accesses, found {changed}")
    # Remaining mentions occur only in explanatory comments.
    body = body.replace("prodsh[cur]", "the product segment of slot cur")
    if "prodsh" in body or "ti < B" in body:
        raise RuntimeError("a split-pool access survived the transformation")
    body = body.replace(f"__launch_bounds__(B, {packed.MIN_BLOCKS})",
                        f"__launch_bounds__(B, {MIN_BLOCKS})")
    return body


BODY = _make_body()
_mod = cp.RawModule(code=reference.DEFS + BODY, options=("-std=c++14",))
_mine = _mod.get_function("ring_mine")
d_RULE, d_TAPS = packed.d_RULE, packed.d_TAPS


def _launch(base, nhashes, nblocks=None, want_state=False):
    """Launch this module's kernel, never packed._mine or reference._mine."""
    if nhashes < 1:
        raise ValueError("nhashes must be positive")
    nh = ((nhashes + MINE_K - 1) // MINE_K) * MINE_K
    if nblocks is None:
        nblocks = max(1, min(nh // MINE_K, 64))
    banks = cp.empty(nh * B * DEPTH, dtype=cp.uint32)
    folds = cp.zeros(nh, dtype=cp.uint32)
    states = cp.zeros(nh * B, dtype=cp.uint32) if want_state else cp.zeros(0, dtype=cp.uint32)
    _mine((nblocks,), (B,),
          (np.uint64(base), folds, states, d_RULE, d_TAPS,
           reference.d_TSH, reference.d_AB, reference.d_MULA, reference.d_MULB,
           reference.d_MULC, reference.d_PREV, banks, np.int32(nh)))
    cp.cuda.Stream.null.synchronize()
    return cp.asnumpy(folds)[:nhashes], (cp.asnumpy(states).reshape(-1, B)[:nhashes]
                                         if want_state else None)


def run(base, nhashes, nblocks=None):
    """Return the folds for consecutive nonces beginning at base."""
    return _launch(base, nhashes, nblocks)[0]


def run_states(base, nhashes, nblocks=None):
    """Return (folds, full final ring states) for verification."""
    return _launch(base, nhashes, nblocks, want_state=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "vectors":
        with (_HERE.parent / "vectors.txt").open() as source:
            nonces = [int(line.split()[0], 16) for line in source
                      if line.strip() and not line.startswith("#")]
        for nonce in nonces:
            folds, states = run_states(nonce, 1)
            print(f"{nonce:016x} {hashlib.sha256(spec.pack(states[0])).hexdigest()} "
                  f"{int(folds[0]):08x} "
                  + "".join(f"{int(v):0{(W+3)//4}x}" for v in states[0][::-1]))
    elif len(sys.argv) > 1 and sys.argv[1] == "warmup":
        run(0, MINE_K)
        print("kernels compiled")
    else:
        print(f"variant={VARIANT} taps={TAP_LAYOUT} min_blocks={MIN_BLOCKS} "
              f"unroll_taps={UNROLL_TAPS} K={MINE_K}")
        print("Use compare_gpu.py --candidate packed_pool for matched checks.")
