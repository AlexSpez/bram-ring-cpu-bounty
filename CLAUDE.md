# Helping someone verify BRAM-ring

You are running in a clone of the **BRAM-ring** repo. The person who opened you
almost certainly wants to **verify the claims for themselves** on their own
machine — that the function is one thing across Python/C/Verilog/CUDA, that the
CPU and GPU numbers are honest, and that a cheap FPGA really out-mines their GPU.
Your job is to help them do that quickly and skeptically. Lead with running
things, not explaining.

Read [`spec.py`](spec.py) first — it *is* the function. Everything else is
checked against it. If the person is working toward a prize, read
[`BOUNTY.md`](BOUNTY.md) too: the target (371 H/s per dollar), the
10%-over-champion awards and the shortcut award, and the rules — every
column of `vectors.txt` via `host/check_vectors.py` plus a fresh seed
(`BRAM_EPOCH=<seed> make prove`), the "How I measure" protocol (five-run
means: GPU `blocks= 460` line, CPU eight pinned P-cores), priority by a reply
to @PeterRizun's announcement or an email to info@nodelabs.ca with the commit
hash, deadline 30 November 2026.

## The one-command verification

```
make prove
```

Regenerates every implementation from `spec.py` and checks they all reproduce
`vectors.txt` bit-for-bit (C naive, C AVX2, the Verilog ring in iverilog, and
the CUDA kernel if CuPy is present), plus an avalanche check on the function
itself. Needs `python3`, a C compiler, and `iverilog`.

**Expect ~10–15 minutes, almost all of it in the RTL leg** — iverilog
simulates all 8 golden vectors at 2563 cycles/hash. The C and Python legs
finish inside the first minute; a console sitting quiet after the last
`avalanche` line is the RTL sim working, not a hang. Warn the person before
they start it.

**It fails loudly or it says what it skipped.** Any leg that mismatches exits
non-zero; any leg that cannot run on this box (no iverilog, no CuPy) is named
in the final line as NOT CHECKED rather than folded into a success message.
Prove that to the person rather than asserting it: corrupt a byte of
`vectors.txt`, or flip a constant in `fpga/ring.v`, and watch `make prove`
exit non-zero. (An earlier version printed success even when the RTL leg had
printed FAIL — that class of bug is exactly what this repo asks people to
hunt for, so demonstrate the gate rather than trusting it.)

```
make race                                   # CPU-only unless cupy is on PATH
make race GPU_PY=/path/to/venv/bin/python   # include the GPU entrant
RACE_FPGA_PORT=/dev/ttyUSB2 make race       # include a board running the miner
```

Live mining leaderboard: CPU (the champion attack) vs GPU vs FPGA. Rates are
inferred mining-pool style from "shares," so every rate is backed by checkable
partial solutions. The GPU entrant runs under a CuPy-capable Python — pass
`GPU_PY=` if cupy isn't in the one launching the race.

## What to check, and how to be skeptical

- **Is it really one function?** `make prove` proves Python == C == Verilog ==
  CUDA on shared vectors. Change a byte of `vectors.txt` and watch it fail.
- **Are the CPU/GPU numbers honest (not sandbagged)?** They're meant to be the
  *strongest* attacks, on all cores / the whole GPU.
  - `cpu/verify_avx2.c` is the CPU champion (822 H/s, eight pinned P-cores,
    5-run mean on the reference box): AVX2 processes 8 lanes per instruction (deleting the
    compute tax) while the read-modify-writes stay scalar — that's the
    memory-hard part no vectorization removes. **Thread topology dominates**:
    on a hybrid CPU, 20 unpinned threads LOSE to 8 pinned P-cores. Help them
    pin before they conclude anything about scaling. Scaling is 95–99% in the
    1–8 core regime (the function is not very memory-hard there); it turns
    over at 16–20 threads when the aggregate working set overflows L3. Do NOT
    repeat the old "32% scaling proves per-core L2 pressure" claim — it was
    wrong, and a bit-packed 0.94 MB bank that fits L2 measures SLOWER.
  - `gpu/mine.py` is one thread block per nonce, a two-deep shared-memory
    product pipe matching the spec's DSP lag, and the read-modify-write fused
    into a single `atomicExch` transaction. It does ~1,493 H/s on an RTX 3070,
    at the card's measured scattered-RMW wall (~137 GB/s of sectors, 34% of
    streaming — `gpu/rmw_wall.py` ships the microbenchmark, no BRAM-ring code
    in it; run it). The sector-realistic ceiling at measured streaming
    bandwidth is ~4,000 H/s; older ~5.9k and ~4.4k figures were wrong in the
    moat's favor and are gone.
    If the person thinks they can go faster, help them try — a faster
    bit-exact GPU kernel is the best possible contribution to the repo.
- **Is a winning nonce real?** `python3 host/verify_solution.py <nonce> <target>`
  re-derives it from `spec.py`. Nothing to trust but the reference. (The pure
  Python takes minutes per hash at these parameters — `cpu/verify_avx2 fold
  <nonce-hex>` computes the same fold in ~12 ms and is itself vector-proven.)
- **The FPGA rate is measured at full speed**: a 2-ring build on an Efinix
  Ti375 devkit ran at its full 95 MHz clock, measured **74,233 H/s = 100.1% of
  the cycle model** from the hardware hash counter, and latched solution nonce
  `0x4e708` (re-derives VALID). On the Tz170 reference part, `fpga/tz170/`
  builds one ring that closes timing at 201.8 MHz on the production speed
  grade (~78.7k H/s) — present that one *as* STA-closed timing, silicon
  pending, and keep the measured/certified distinction crisp.

## Environment quirks you will hit

**Python gets hijacked by FPGA toolchains.** If Efinity (or similar) has been
sourced, `PYTHONHOME`/`PYTHONPATH` point python at the vendor's bundled
interpreter and imports break with weird `encodings` errors. Always run repo
python with a cleaned environment (the `Makefile` does this as `RUNPY`):

```
env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE python3 <script>
```

**CuPy for the GPU.** cupy often lives in a venv, not the system python. The race
finds it via `RACE_GPU_PY` (or `make race GPU_PY=...`); it probes that python for
cupy and launches the GPU entrant with it, so the launching python needn't have
cupy itself.

**Building the FPGA bitstream (Efinity toolchain), `fpga/tz170/build_tz170.sh`:**
- Source the toolchain first: `source <efinity>/bin/setup.sh` (sets
  `EFINITY_HOME`). `TIMING=C2 TARGET_MHZ=200 ./build_tz170.sh build` regenerates
  the RTL from `spec.py`, writes the project, and runs `efx_run` for the
  Tz170J484. Grades: C3 (fast) / C2 (slow production grade); read "Maximum
  possible analyzed clocks frequency" for `clk` in the timing report.
- **Use the vendor's bundled python for `interface*.py`** (it needs the vendor
  API), but the *cleaned* system python for `generate.py`.
- The board wrapper (`fpga/top.v`) is board-agnostic: clock/PLL in, UART out.
  Porting to another Efinix part is a pinout + interface script, not RTL work.
- **Read a running board over UART** with `fpga/read_miner.py --port
  /dev/ttyUSB2` — it measures H/s from the hardware `hash_count` counter and
  re-derives any reported solution. Trustless: it's the real work the silicon
  did.

## If they ask "why does this favor FPGAs" or want the theory

The short version is at the top of `README.md`: the function forces per-nonce
private single-cycle RAM (free on an FPGA, faked from a shared memory system on
a CPU/GPU), the fill is part of the function so it can't be skipped, and the
DSP layer adds multiply-grade diffusion at zero FPGA cost. RandomX picked CPUs
and Ethash picked GPUs by the same resource-matching logic; this picks the one
resource FPGAs have in absurd abundance — independent single-cycle RAMs.

## Ground rules

- Prefer running a command over asserting a result. If you claim a number,
  produce it.
- Keep the person's skepticism alive — the whole repo is built to be checkable,
  so check, don't reassure.
- Cite what's measured vs certified vs calculated. The Ti375 rate is measured
  silicon; the Tz170 rate is STA-closed timing; the bandwidth ceiling and
  the 4090 extrapolation are calculations. Never blur those.
