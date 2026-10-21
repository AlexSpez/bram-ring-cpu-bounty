#!/usr/bin/env python3
"""Experimental CUDA implementation of the unchanged BRAM-ring function.

The reference launch, shared state, DSP pipeline, and bank RMW come directly
from mine.BODY. Only the cellular-automaton evaluator and its read-only tables
are replaced: 20 cells become 16 lane-wide rule masks and 15 Boolean muxes.
Tap bits still come from the reference shared ring/product pools.

Environment knobs (set before importing):
  PACKED_VARIANT=packed|scalar      # scalar keeps per-cell truth-table lookup
  PACKED_TAP_LAYOUT=column|lane     # column makes warp table reads contiguous
  PACKED_MIN_BLOCKS=2|1             # second launch_bounds argument
  PACKED_UNROLL_TAPS=1|0            # unroll the 20 shared-memory tap gathers
  MINE_K=1                         # inherited reference nonces per block

python packed.py vectors | python ../host/check_vectors.py
python packed.py warmup

No speed claim is made by this file; compare against the reference on the
same device and verify full final states before interpreting measurements.
"""
import hashlib
import os
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import mine as reference

cp, np, spec = reference.cp, reference.np, reference.spec
B, W, DEPTH = reference.B, reference.W, reference.DEPTH
MINE_K = reference.MINE_K

VARIANT = os.environ.get("PACKED_VARIANT", "packed")
TAP_LAYOUT = os.environ.get("PACKED_TAP_LAYOUT", "column")
MIN_BLOCKS = int(os.environ.get("PACKED_MIN_BLOCKS", "2"))
UNROLL_TAPS = int(os.environ.get("PACKED_UNROLL_TAPS", "1"))
if VARIANT not in ("packed", "scalar"):
    raise ValueError("PACKED_VARIANT must be packed or scalar")
if TAP_LAYOUT not in ("column", "lane"):
    raise ValueError("PACKED_TAP_LAYOUT must be column or lane")
if MIN_BLOCKS not in (1, 2) or UNROLL_TAPS not in (0, 1):
    raise ValueError("PACKED_MIN_BLOCKS must be 1 or 2; PACKED_UNROLL_TAPS must be 0 or 1")

# One uint16 holds a pool index and its bit shift. The current parameters
# need 10 + 5 bits. Assert before packing to avoid silently truncating a new
# parameter set. Layout changes do not change the represented tap.
if B + reference.NDSP > (1 << 11) or np.any(reference.TSH >= 32):
    raise ValueError("the tap pool or bit shifts do not fit this uint16 encoding")
_taps = ((reference.TIDX.astype(np.uint32) << 5)
         | reference.TSH.astype(np.uint32)).astype(np.uint16).reshape(B, W)
TAPS = np.ascontiguousarray(_taps.T if TAP_LAYOUT == "column" else _taps)

# Bit c of rule mask q is bit q of cell (b,c)'s truth table. Thus the
# Boolean evaluator can act on all W cells of a lane in one uint32 word.
RULE_MASKS = np.zeros((16, B), dtype=np.uint32)
for q in range(16):
    for c in range(W):
        RULE_MASKS[q] |= (((reference.RULEf.reshape(B, W)[:, c] >> q) & 1)
                          .astype(np.uint32) << c)


def _macro(lines):
    return "#define CA_STEP(cur, k, rdk, v) " + "\\\n" + " \\\n".join(lines) + "\n"


def _ca_macro():
    tap_index = "c*B + b" if TAP_LAYOUT == "column" else "b*W + c"
    unroll = '_Pragma("unroll")' if UNROLL_TAPS else '_Pragma("unroll 1")'
    lines = ["{", "u32 Cw = (sh[cur][k][b] ^ (rdk)) & wmask;",
             "u32 Tw = 0;", unroll, "for (int c = 0; c < W; ++c) {",
             f"u32 pk = TIDX[{tap_index}];",
             "int ti = pk >> 5; int ts = pk & 31;",
             "u32 pool_word = ti < B ? sh[cur][k][ti] : prodsh[cur][k][ti-B];",
             "Tw |= ((pool_word >> ts) & 1u) << c;", "}"]
    if VARIANT == "packed":
        lines += ["u32 Lw = ((Cw << 1) | (Cw >> (W-1))) & wmask;",
                  "u32 Rw = ((Cw >> 1) | (Cw << (W-1))) & wmask;"]
        for j in range(8):
            lines.append(f"u32 e{j} = PMUX(Lw, r{2*j}, r{2*j+1});")
        for j in range(4):
            lines.append(f"u32 f{j} = PMUX(Cw, e{2*j}, e{2*j+1});")
        for j in range(2):
            lines.append(f"u32 h{j} = PMUX(Rw, f{2*j}, f{2*j+1});")
        lines += ["(v) = PMUX(Tw, h0, h1) & wmask;"]
    else:
        lines += ["u32 ng = 0;", '_Pragma("unroll")',
                  "for (int c = 0; c < W; ++c) {",
                  "int cl = c == 0 ? W-1 : c-1, cr = c == W-1 ? 0 : c+1;",
                  "u32 L = (Cw >> cl) & 1u, C = (Cw >> c) & 1u;",
                  "u32 R = (Cw >> cr) & 1u, T = (Tw >> c) & 1u;",
                  "ng |= ((u32)(ru[c] >> ((T<<3)|(R<<2)|(C<<1)|L)) & 1u) << c;",
                  "}", "(v) = ng & wmask;"]
    return _macro(lines + ["}"])


def _make_body():
    body = reference.BODY
    begin = body.index("#define CA_STEP(")
    end = body.index('extern "C" __global__', begin)
    body = (body[:begin] + "#define PMUX(s, a, z) ((a) ^ (((a) ^ (z)) & (s)))\n"
            + _ca_macro() + "\n" + body[end:])
    body = body.replace("__launch_bounds__(B, 2)", f"__launch_bounds__(B, {MIN_BLOCKS})")
    body = body.replace("    const unsigned short* ti_ = &TIDX[b*W];\n", "")
    body = body.replace("    const unsigned char*  ts_ = &TSH[b*W];\n", "")
    if VARIANT == "packed":
        body = body.replace("const unsigned short* __restrict__ RULE,",
                            "const u32* __restrict__ RULE,")
        declarations = "\n".join(f"    const u32 r{q} = RULE[{q}*B+b];" for q in range(16))
        body = body.replace("    const unsigned short* ru  = &RULE[b*W];", declarations)
    return body


BODY = _make_body()
_mod = cp.RawModule(code=reference.DEFS + BODY, options=("-std=c++14",))
_mine = _mod.get_function("ring_mine")
d_RULE = cp.asarray(RULE_MASKS if VARIANT == "packed" else reference.RULEf)
d_TAPS = cp.asarray(TAPS)


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
           reference.d_AB, reference.d_MULA, reference.d_MULB,
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
        print("Use compare_gpu.py for correctness checks and matched benchmarks.")
