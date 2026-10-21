#!/usr/bin/env python3
"""Packed CA with physical RAM tiled into lane groups.

GPU_BANK_TILE=32|64|128 chooses the number of lanes per tile (default 32).
Within each nonce, logical word (row, lane) is stored at
``(lane // TILE) * DEPTH * TILE + row * TILE + lane % TILE``.
The map is bijective over the unchanged B*DEPTH words. Every warp's fill
stores remain contiguous because TILE is a multiple of the warp width.
Only physical addresses change; all fill writes and RAM exchanges remain.

PACKED_TILED_BASE=packed|packed_pool3 chooses the underlying CUDA evaluator.
All its other settings apply. No performance claim is made by this module.
"""
import hashlib
import importlib
import os
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
TILED_BASE = os.environ.get("PACKED_TILED_BASE", "packed")
if TILED_BASE not in ("packed", "packed_pool3"):
    raise ValueError("PACKED_TILED_BASE must be packed or packed_pool3")
parent = importlib.import_module(TILED_BASE)

cp, np, spec, reference = parent.cp, parent.np, parent.spec, parent.reference
B, W, DEPTH, MINE_K = parent.B, parent.W, parent.DEPTH, parent.MINE_K
VARIANT = parent.VARIANT + "_tiled"
TAP_LAYOUT, MIN_BLOCKS, UNROLL_TAPS = parent.TAP_LAYOUT, parent.MIN_BLOCKS, parent.UNROLL_TAPS
BANK_TILE = int(os.environ.get("GPU_BANK_TILE", "32"))
if BANK_TILE not in (32, 64, 128) or B % BANK_TILE:
    raise ValueError("GPU_BANK_TILE must be 32, 64 or 128 and divide B")
BANK_WORDS_PER_NONCE = B * DEPTH
d_RULE, d_TAPS = parent.d_RULE, parent.d_TAPS


def _make_body():
    body = parent.BODY
    replacements = (
        ("bk[(long long)st*B + b]",
         "bk[(long long)(b/BANK_TILE)*DEPTH*BANK_TILE + (long long)st*BANK_TILE + b%BANK_TILE]"),
        ("&bk[(long long)aa[k]*B + b]",
         "&bk[(long long)(b/BANK_TILE)*DEPTH*BANK_TILE + (long long)aa[k]*BANK_TILE + b%BANK_TILE]"),
    )
    for before, after in replacements:
        if body.count(before) != 1:
            raise RuntimeError(f"bank-layout source anchor changed: {before!r}")
        body = body.replace(before, after)
    # The original nonce base offsets stay in place. Two anchors correspond
    # to fill and RMW; each nonce still owns precisely B*DEPTH words.
    if body.count("&banks[((long long)(g0+k))*B*DEPTH]") != 2:
        raise RuntimeError("nonce bank base offsets changed")
    return body


BODY = _make_body()
_mod = cp.RawModule(code=reference.DEFS + f"#define BANK_TILE {BANK_TILE}\n" + BODY,
                    options=("-std=c++14",))
_mine = _mod.get_function("ring_mine")


def _launch(base, nhashes, nblocks=None, want_state=False):
    if nhashes < 1:
        raise ValueError("nhashes must be positive")
    nh = ((nhashes + MINE_K - 1) // MINE_K) * MINE_K
    if nblocks is None:
        nblocks = max(1, min(nh // MINE_K, 64))
    banks = cp.empty(nh * BANK_WORDS_PER_NONCE, dtype=cp.uint32)
    folds = cp.zeros(nh, dtype=cp.uint32)
    states = cp.zeros(nh * B, dtype=cp.uint32) if want_state else cp.zeros(0, dtype=cp.uint32)
    _mine((nblocks,), (B,),
          (np.uint64(base), folds, states, d_RULE, d_TAPS, reference.d_TSH,
           reference.d_AB, reference.d_MULA, reference.d_MULB,
           reference.d_MULC, reference.d_PREV, banks, np.int32(nh)))
    cp.cuda.Stream.null.synchronize()
    return cp.asnumpy(folds)[:nhashes], (cp.asnumpy(states).reshape(-1, B)[:nhashes]
                                        if want_state else None)


def run(base, nhashes, nblocks=None):
    """Return folds for consecutive nonces beginning at base."""
    return _launch(base, nhashes, nblocks)[0]


def run_states(base, nhashes, nblocks=None):
    """Return folds and full final ring states."""
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
        print(f"base={TILED_BASE} variant={VARIANT} bank_tile={BANK_TILE} "
              f"taps={TAP_LAYOUT} min_blocks={MIN_BLOCKS} "
              f"unroll_taps={UNROLL_TAPS} K={MINE_K}")
        print("Use compare_gpu.py --candidate packed_tiled for matched checks.")
