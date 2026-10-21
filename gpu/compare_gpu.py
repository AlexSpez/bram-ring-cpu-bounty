#!/usr/bin/env python3
"""Compare two GPU miners, including SHA-256 in every measured hash.

Examples (from the repository root):
  python gpu/compare_gpu.py --smoke
  python gpu/compare_gpu.py --hashes 920 --blocks 460 --json-output gpu-results.json
  python gpu/compare_gpu.py --vectors-only --vector-output candidate-vectors.txt
  python gpu/compare_gpu.py --baseline packed --candidate packed_pool --smoke
  python host/check_vectors.py candidate-vectors.txt

Both miners use run_states(), so both allocate their nonce banks and return the
same full states and folds to the host. Wall time includes these allocations,
all GPU work, host transfer, serialization and one SHA-256 per nonce. Imports,
epoch tables, compilation, warm-up and correctness comparisons are not timed.
The smoke mode is explicitly a small correctness check, not a bounty benchmark.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def arguments():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", default="mine", help="baseline module in gpu/")
    parser.add_argument("--candidate", default="packed", help="candidate module in gpu/")
    parser.add_argument("--vectors", type=Path, default=HERE.parent / "vectors.txt")
    parser.add_argument("--vectors-only", action="store_true")
    parser.add_argument("--vector-output", type=Path,
                        help="write the candidate's four-column vector proof")
    parser.add_argument("--hashes", type=int, default=920)
    parser.add_argument("--blocks", type=int, default=128,
                        help="same grid size for both implementations")
    parser.add_argument("--chunk-hashes", type=int, default=0,
                        help="split each timed run into this many hashes per GPU launch; "
                             "0 uses the full batch (same setting for both miners)")
    parser.add_argument("--runs", type=int, default=5,
                        help="paired runs, at least five for the full benchmark")
    parser.add_argument("--smoke", action="store_true",
                        help="small repeated same-nonce comparison; no speed claim")
    parser.add_argument("--smoke-hashes", type=int, default=4)
    parser.add_argument("--smoke-repeats", type=int, default=3)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if args.blocks < 1:
        parser.error("--blocks must be positive")
    if args.chunk_hashes < 0:
        parser.error("--chunk-hashes must be zero or positive")
    if args.smoke_hashes < 1 or args.smoke_repeats < 2:
        parser.error("smoke mode requires positive hashes and at least two repeats")
    if not args.smoke and not args.vectors_only:
        if args.hashes < 920 or args.runs < 5:
            parser.error("a full benchmark requires --hashes >= 920 and --runs >= 5")
    return args


def load_vectors(path, spec, np):
    rows = []
    seen = set()
    width = (spec.W + 3) // 4
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("every vector must contain nonce, digest, fold and full state")
        nonce, digest, fold, raw = fields
        nonce = int(nonce, 16)
        if nonce in seen or not 0 <= nonce < 2**64:
            raise ValueError("duplicate or invalid vector nonce")
        seen.add(nonce)
        # The vector format is lane B-1..0, fixed hex width per lane.
        raw = f"{int(raw, 16):0{spec.B * width}x}"
        if len(raw) != spec.B * width:
            raise ValueError("vector state has the wrong number of lanes")
        lanes = np.array([int(raw[i:i + width], 16)
                          for i in range(0, len(raw), width)][::-1], dtype=np.uint32)
        if np.any(lanes > (1 << spec.W) - 1):
            raise ValueError("vector lane exceeds the specified width")
        rows.append((nonce, digest.lower().zfill(64), int(fold, 16), lanes, raw))
    if len(rows) != 8:
        raise ValueError(f"expected all eight vectors, found {len(rows)}")
    return rows


def state_digests(states, spec, np):
    """Exactly spec.pack(): W=20 uses THREE bytes per lane, not 20-bit packing."""
    nbytes = (spec.W + 7) // 8
    # Force little endian even on a big-endian host. Slice off each lane's
    # unused fourth byte, then make contiguous rows before feeding hashlib.
    words = np.ascontiguousarray(states, dtype="<u4")
    byte_rows = words.view(np.uint8).reshape(len(words), spec.B, 4)
    packed = np.ascontiguousarray(byte_rows[:, :, :nbytes]).reshape(len(words), -1)
    return tuple(hashlib.sha256(row).digest() for row in packed)


def validate_shape(folds, states, count, spec, np):
    if not isinstance(folds, np.ndarray) or folds.shape != (count,):
        raise ValueError(f"expected {count} host folds")
    if not isinstance(states, np.ndarray) or states.shape != (count, spec.B):
        raise ValueError(f"expected host states of shape {(count, spec.B)}")
    if folds.dtype != np.uint32 or states.dtype != np.uint32:
        raise ValueError("both implementations must return uint32 folds and states")
    if np.any(states > (1 << spec.W) - 1):
        raise ValueError("computed state exceeds the lane width")


def check_vectors(modules, vectors, args, spec, np, emit):
    proof = []
    for name, module in modules:
        for nonce, expected_digest, expected_fold, expected_lanes, raw in vectors:
            folds, states = module.run_states(nonce, 1, nblocks=args.blocks)
            validate_shape(folds, states, 1, spec, np)
            digest = state_digests(states, spec, np)[0].hex()
            if int(folds[0]) != expected_fold:
                raise ValueError(f"{name}: fold mismatch at nonce {nonce:016x}")
            if not np.array_equal(states[0], expected_lanes):
                raise ValueError(f"{name}: full-state mismatch at nonce {nonce:016x}")
            if digest != expected_digest:
                raise ValueError(f"{name}: SHA-256 mismatch at nonce {nonce:016x}")
            if name == "candidate":
                computed_raw = "".join(f"{int(v):0{(spec.W + 3) // 4}x}"
                                       for v in states[0, ::-1])
                if int(computed_raw, 16) != int(raw, 16):
                    raise ValueError(f"{name}: raw-state column mismatch")
                proof.append(f"{nonce:016x} {digest} {int(folds[0]):08x} {computed_raw}")
            emit(f"VECTOR {name:9s} nonce={nonce:016x} digest={digest} "
                 f"fold={int(folds[0]):08x} full_state=PASS")
        emit(f"PASS {name}: 8/8 vectors, every column bit-exact")
    if args.vector_output:
        args.vector_output.parent.mkdir(parents=True, exist_ok=True)
        args.vector_output.write_text("\n".join(proof) + "\n", encoding="utf-8")
        emit(f"Wrote candidate vector proof: {args.vector_output}")


def rounded_count(module, count):
    k = int(getattr(module, "MINE_K", 1))
    return ((count + k - 1) // k) * k


def bank_words_per_nonce(module, spec):
    """BANK_STRIDE is uint32 words per row; an explicit total overrides it."""
    words = int(getattr(module, "BANK_WORDS_PER_NONCE",
                        spec.DEPTH * int(getattr(module, "BANK_STRIDE", spec.B))))
    if words < spec.B * spec.DEPTH:
        raise ValueError("bank allocation estimate is smaller than the specified banks")
    return words


def check_memory(modules, count, spec, cp, emit):
    # Free inactive allocations left by vector checks before measuring free VRAM.
    # Only one miner runs at a time, so two whole banks are never needed at once.
    cp.cuda.Stream.null.synchronize()
    cp.get_default_memory_pool().free_all_blocks()
    free_bytes, total_bytes = cp.cuda.runtime.memGetInfo()
    required = max(rounded_count(module, count)
                   * (bank_words_per_nonce(module, spec) * 4 + spec.B * 4 + 4)
                   for _, module in modules)
    reserve = max(128 * 1024**2, total_bytes // 20)
    emit(f"MEMORY free={free_bytes / 1024**2:.1f}MiB "
         f"estimated_peak={required / 1024**2:.1f}MiB "
         f"reserve={reserve / 1024**2:.1f}MiB")
    if required + reserve > free_bytes:
        raise ValueError("insufficient free GPU memory for this batch; close GPU apps "
                         "or use --smoke (full benchmark requires at least 920 hashes)")


def timed_run(module, base, count, blocks, spec, np, cp, chunk_hashes=0):
    cp.cuda.Stream.null.synchronize()
    started = time.perf_counter()
    if not chunk_hashes or chunk_hashes >= count:
        folds, states = module.run_states(base, count, nblocks=blocks)
        digests = state_digests(states, spec, np)
    else:
        fold_parts, state_parts, digest_parts = [], [], []
        for offset in range(0, count, chunk_hashes):
            size = min(chunk_hashes, count - offset)
            chunk_folds, chunk_states = module.run_states(base + offset, size, nblocks=blocks)
            fold_parts.append(chunk_folds)
            state_parts.append(chunk_states)
            digest_parts.extend(state_digests(chunk_states, spec, np))
        # Chunk host bookkeeping and concatenation are part of the measured work.
        folds = np.concatenate(fold_parts)
        states = np.concatenate(state_parts)
        digests = tuple(digest_parts)
    elapsed = time.perf_counter() - started
    # Validation is intentionally after the timer, identically for both miners.
    validate_shape(folds, states, count, spec, np)
    return elapsed, folds, states, digests


def metadata(modules, spec, np, cp):
    dev = cp.cuda.Device()
    props = cp.cuda.runtime.getDeviceProperties(dev.id)
    name = props.get("name", "unknown")
    if isinstance(name, bytes):
        name = name.decode(errors="replace")
    kernel_attributes = {}
    module_configuration = {}
    module_sha256 = {}
    for label, module in modules:
        module_path = Path(module.__file__).resolve()
        module_sha256[label] = hashlib.sha256(module_path.read_bytes()).hexdigest()
        configuration = {}
        for attribute, value in vars(module).items():
            if (attribute in ("VARIANT", "TAP_LAYOUT", "MIN_BLOCKS", "UNROLL_TAPS",
                              "PACKED_STRIDE_BASE",
                              "BANK", "PAD", "POOL")
                    or attribute.startswith(("BANK_", "POOL_"))):
                # Record scalar configuration knobs without expanding device
                # arrays or other objects that may use the same prefixes.
                if isinstance(value, (str, int, float, bool)) or value is None:
                    configuration[attribute] = value
                elif isinstance(value, np.generic):
                    configuration[attribute] = value.item()
        module_configuration[label] = configuration
        kernel = getattr(module, "_mine", None)
        if kernel is not None:
            try:
                # RawKernel.attributes is CuPy's documented resource API.
                kernel_attributes[label] = dict(kernel.attributes)
            except Exception as exc:
                kernel_attributes[label] = {"unavailable": str(exc)}
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform.platform(), "python": platform.python_version(),
        "numpy": np.__version__, "cupy": cp.__version__,
        "cuda_runtime": cp.cuda.runtime.runtimeGetVersion(),
        "cuda_driver": cp.cuda.runtime.driverGetVersion(),
        "device_id": dev.id, "device_name": name,
        "sm_count": props.get("multiProcessorCount"),
        "total_vram_bytes": props.get("totalGlobalMem"),
        "compute_capability": dev.compute_capability,
        "epoch": spec.EPOCH, "B": spec.B, "W": spec.W,
        "DEPTH": spec.DEPTH, "STEPS": spec.STEPS, "NDSP": spec.NDSP,
        "kernel_attributes": kernel_attributes,
        "module_configuration": module_configuration,
        "module_sha256": module_sha256,
        "modules": {label: str(Path(module.__file__).resolve())
                    for label, module in modules},
        "MINE_K": {label: int(getattr(module, "MINE_K", 1))
                   for label, module in modules},
    }


def main():
    args = arguments()
    result = {"status": "running", "arguments": vars(args).copy(), "runs": [], "log": []}
    result["arguments"] = {key: str(value) if isinstance(value, Path) else value
                           for key, value in result["arguments"].items()}

    def emit(message):
        print(message, flush=True)
        result["log"].append(message)

    try:
        import numpy as np
        import cupy as cp
        import spec

        baseline = importlib.import_module(args.baseline)
        candidate = importlib.import_module(args.candidate)
        modules = [("baseline", baseline), ("candidate", candidate)]
        if spec.W > 32:
            raise ValueError("this uint32 comparison harness requires W <= 32")
        vectors = load_vectors(args.vectors, spec, np)
        emit(f"COMPARE baseline={args.baseline} candidate={args.candidate} "
             f"epoch={spec.EPOCH!r} blocks={args.blocks}")
        check_vectors(modules, vectors, args, spec, np, emit)
        result["vectors"] = {"baseline": 8, "candidate": 8, "columns": "all four"}
        result["metadata"] = metadata(modules, spec, np, cp)
        result["metadata"]["chunk_hashes"] = args.chunk_hashes
        emit("METADATA " + json.dumps(result["metadata"], sort_keys=True))
        if args.vectors_only:
            result["status"] = "passed"
            return 0

        count = args.smoke_hashes if args.smoke else args.hashes
        repeats = args.smoke_repeats if args.smoke else args.runs
        resident_count = min(count, args.chunk_hashes) if args.chunk_hashes else count
        check_memory(modules, resident_count, spec, cp, emit)
        emit(f"BATCH hashes_per_run={count} chunk_hashes={args.chunk_hashes} "
             f"maximum_resident_hashes={resident_count}")
        emit("TIMING wall-clock: GPU bank/output allocation + fill + run + "
             "full-state/fold host transfer + spec.pack serialization + SHA-256 per nonce; "
             "excludes tables, compilation, warm-up and comparisons")
        if args.smoke:
            emit("SMOKE correctness/repeatability only; these small-batch rates are not a bounty result")
        # Complete kernel warm-up before measured runs. Golden checks have already
        # compiled both kernels, but warm-up also follows the benchmark's base.
        for _, module in modules:
            module.run_states(0x100000, 1, nblocks=args.blocks)
        anchor = None
        for pair in range(repeats):
            base = 0x100000 if args.smoke else 0x100000 + pair * count
            order = modules if pair % 2 == 0 else modules[::-1]
            outputs = {}
            for label, module in order:
                elapsed, folds, states, digests = timed_run(
                    module, base, count, args.blocks, spec, np, cp, args.chunk_hashes)
                record = {"pair": pair + 1, "implementation": label,
                          "base_nonce": f"{base:016x}", "hashes": count,
                          "blocks": args.blocks, "chunk_hashes": args.chunk_hashes,
                          "seconds": elapsed,
                          "hashes_per_second": count / elapsed,
                          "digest_sha256": hashlib.sha256(b"".join(digests)).hexdigest()}
                result["runs"].append(record)
                emit(f"RUN pair={pair + 1} {label:9s} base={base:016x} "
                     f"hashes={count} blocks={args.blocks} seconds={elapsed:.6f} "
                     f"H/s={count / elapsed:.6f} digest_sha256={record['digest_sha256']}")
                outputs[label] = (folds, states, digests)
            first, second = outputs["baseline"], outputs["candidate"]
            if (not np.array_equal(first[0], second[0])
                    or not np.array_equal(first[1], second[1]) or first[2] != second[2]):
                raise ValueError(f"baseline/candidate disagreement in pair {pair + 1}")
            if args.smoke:
                if anchor is None:
                    anchor = first
                elif (not np.array_equal(anchor[0], first[0])
                      or not np.array_equal(anchor[1], first[1]) or anchor[2] != first[2]):
                    raise ValueError(f"nondeterministic output in smoke repeat {pair + 1}")
            emit(f"PASS pair={pair + 1}: all {count} full states, folds and SHA-256 digests agree")
        means = {}
        for label, _ in modules:
            rates = [row["hashes_per_second"] for row in result["runs"]
                     if row["implementation"] == label]
            means[label] = sum(rates) / len(rates)
        ratio = means["candidate"] / means["baseline"]
        result["summary"] = {"arithmetic_mean_hps": means,
                             "candidate_to_baseline_ratio": ratio,
                             "improvement_percent": (ratio - 1) * 100,
                             "bounty_sized_runs": not args.smoke}
        emit(f"ARITHMETIC_MEAN baseline={means['baseline']:.6f}H/s "
             f"candidate={means['candidate']:.6f}H/s ratio={ratio:.6f} "
             f"improvement={(ratio - 1) * 100:+.3f}%")
        emit("Local comparison complete. An award still requires the reference RTX 3070 session.")
        result["status"] = "passed"
        return 0
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        emit("FAIL " + result["error"])
        return 1
    finally:
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
