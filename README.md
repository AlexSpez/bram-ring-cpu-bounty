# NEXA BRAM-ring

A proof-of-work function **tailored to run fast on a cheap FPGA and slow on
CPUs and GPUs** — with a race you can run to watch it happen, and a standing
invitation: **beat the FPGA if you can.**

Every chip does logic; that's a commodity. The scarce resource is *memory*.
This function gives every nonce its own pile of small RAMs and reads and writes
them at data-dependent addresses every step. An FPGA has hundreds of
independent single-cycle RAM blocks wired next to its logic, so it does this for
free; a CPU or GPU has to fake those RAMs out of one shared memory system and
chokes once it runs enough nonces in parallel to keep its ALUs busy.

The whole function is one readable file of Python — **[`spec.py`](spec.py)** —
and every other implementation (C, CUDA, Verilog) is checked against it
bit-for-bit.

## What it computes

`B=768` lanes arranged in a ring. Each lane owns one RAM bank (`DEPTH=512`×`W=20`
bits — exactly one native FPGA block RAM) and a row of epoch-fixed 4-input
lookup tables. One nonce owns the whole ring. The first `DEPTH` steps *are* the
fill: the same dynamics run with the RAM read masked and the write address
forced to the row counter, so software can't skip the fill or treat unwritten
entries as a known constant. Then on each of `STEPS=2048` steps, every lane in
parallel:

```
u = head XOR last_read                 # mix in this lane's previous RAM read
v = lut_row(u, neighbours, remote)     # one row of per-cell cellular automaton
a = selected bits of v                 # data-dependent bank address
last_read = bank[a];  bank[a] = v      # read-modify-write (read old, write new)
head_of_next_lane = v                  # shift around the ring
```

A layer of `NDSP=128` 18×19-bit multipliers (the FPGA's otherwise-idle DSP
blocks) mixes epoch-chosen lane pairs each step, and a few cells per lane tap
the product bits — global, multiply-grade diffusion that costs the FPGA
nothing. The products are consumed with a two-step lag, mirroring the DSP's
pipeline registers. SHA-256 of the final ring state is the output. Tables and
wiring derive from an epoch seed — in hardware that's the bitstream, which a
fixed-function ASIC can't cheaply reproduce. One hash is 2563 cycles.

## Requirements

The core — `make`, `make race` (CPU), `make prove` — needs only **Python 3** and
a **C compiler with OpenMP**. `make prove` also uses **iverilog** for the RTL
sim. The optional competitors need a little more (all in `requirements.txt`):

- **GPU** (NVIDIA): `pip install numpy cupy-cuda12x` (match your CUDA version),
  then run with `make race GPU_PY=/path/to/python`.
- **FPGA**: `pip install pyserial`, then `RACE_FPGA_PORT=/dev/ttyUSB2 make race`
  with any board running the miner bitstream — see [Mine on an FPGA](#mine-on-an-fpga)
  for the devkit build.

## Run it

```
make          # build everything; report what you have (GPU, iverilog, Efinity, board)
make race     # live mining race   (default 20 bits; make race DIFF=16 for a ~2 min demo)
make prove    # check Python == C == Verilog == CUDA bit-for-bit + avalanche
```

`make prove` takes **~10–15 minutes**, almost all of it in the iverilog RTL
leg (8 vectors at 2563 cycles/hash); a quiet console after the avalanche line
is the RTL sim working, not a hang.

`make race` runs each competitor mining until one clears a target difficulty,
then prints the winning nonce — check it with `host/verify_solution.py`. The
default 20-bit target is about a million hashes: **~15 minutes when only the
CPU and GPU are racing** (~2 kH/s between them; 818 s measured on the reference
box), seconds once an FPGA joins; `make race DIFF=16` is a ~2-minute demo. Rates
are inferred mining-pool style from "shares" (partial solutions), so every
number is backed by checkable proofs of work. With no GPU it races the two CPU
attacks; add the GPU with `make race GPU_PY=/path/to/venv/bin/python`, and the
FPGA joins when you set `RACE_FPGA_PORT` to its UART.

## What you'll see

Standalone hash rates, each attack on its own silicon (i7-12700KF / 20 threads,
RTX 3070, Efinix Ti375 devkit):

| competitor | hash rate | notes |
|---|---|---|
| CPU, naive, 20 threads | 131 H/s | one nonce per core, readable baseline |
| CPU, AVX2 lane-parallel, best config | 805 H/s | the champion CPU attack (16 threads, pinned) |
| GPU, RTX 3070, best CUDA | 1,493 H/s | at the card's measured scattered-RMW wall (below) |
| **FPGA, Ti375, 2 rings @ 95 MHz** | **74,233 H/s** | measured on silicon at full speed |

That's **~50× the GPU and ~92× the CPU**, measured kernel against measured
silicon. Both software numbers are the best we know of *after* two independent
adversarial passes were hired to beat them — both wins are merged; see
[Beat us](#beat-us).

**The economics, honestly framed.** The FPGA doing this is a single mid-range
part — a **~$50 chip** of the Tz170's class; built into a finished device it
is plausibly a **~$100 product**, against a ~$500 GPU it out-mines ~50-fold.
(The measured numbers above come from our Ti375 development board — dev kits
of any brand carry lab-tool pricing that says nothing about the part.) Power:
the 3070 drew ~170 W measured mid-race; a card-level FPGA power measurement is
pending and will be published when the production-part board exists.

**CPU thread topology matters more than you'd think.** On this hybrid CPU the
"20 threads" are 8 P-cores + 8 hyperthread siblings + 4 much slower E-cores,
and running all 20 unpinned *loses* to 8 pinned P-cores. The measured curve
(same binary, same box, one locked run):

| threads | config | H/s | scaling vs 1 core |
|---|---|---|---|
| 1 | — | 108 | 1.00× |
| 4 | pinned P-cores | 414 | 0.96× |
| 8 | pinned P-cores | 722 | 0.84× |
| 16 | bound close | 805 | 0.47× |
| 20 | unpinned | 715 | 0.33× |

Reproduce the champion row with `OMP_NUM_THREADS=16 OMP_PROC_BIND=close
cpu/verify_avx2`; the pinned rows use `taskset -c <P-core list>`.

Read that honestly: **the function is NOT very memory-hard on a CPU in the
1–8 core regime** — scaling there is 84–96%. Memory-hardness bites at the top
end, where 16–20 concurrent nonces × ~1.5 MB overflows the shared 25 MB L3 and
the curve turns over. Anyone quoting the 20-thread number as evidence of
per-core cache pressure (we did, in an earlier version of this README) is
wrong. What actually keeps the CPU slow is simpler: it does the same
dependent, scattered read-modify-writes the GPU does, without an FPGA's
hundreds of private single-cycle RAMs.

**The FPGA number is silicon, not projection.** The 2-ring build ran bit-exact
at its full 95 MHz clock — 100.1% of the cycle model — and found nonce
`0x4e708`, which re-derives VALID against `spec.py`. On the cheap reference
part (Tz170, one ring — the smallest miner floorplan that sets `B` for the
network), timing closes at **201.8 MHz** on the slower production speed grade
(STA-certified, best of the two shipped seeds — the other closes 199.8;
that's ~78.7k H/s from a ~$50 chip — silicon run pending).

### Why the GPU can't catch up

Each nonce forces `STEPS×B` *dependent, uncoalesced* random read-modify-writes
into a ~1.5 MB scratchpad. Three bounds, from most generous to actual, all on
the same RTX 3070 and all on its **measured** 405 GB/s streaming bandwidth
(spec sheet says 448; we don't get to mine on the spec sheet):

| bound | assumption | H/s |
|---|---|---|
| perfect-granularity | every 4-byte word costs only its own bytes | ~32,000 |
| sector-realistic | each scattered 4-byte access moves a 32-byte sector | **~4,000** |
| **measured** | the card's *actual* scattered-RMW throughput: ~137 GB/s of sectors (34% of streaming) | **~1,360–1,400** |

The third row is not a model — it's `gpu/rmw_wall.py`, a microbenchmark of
the access pattern with no BRAM-ring code in it, flat across working sets;
run it on your own card. **Our CUDA kernel does 1,493 H/s — at that wall,
and a hair over it, because `atomicExch` fuses each read-modify-write into
one memory transaction.** So the honest statement is not "we're 13× faster
than a bandwidth-perfect GPU"; it's:

> Even a *perfect* kernel that somehow moved nothing but 32-byte sectors at
> the card's full measured streaming bandwidth — no kernel does — caps near
> **~4,000 H/s** on a 3070, still **~18× below one mid-range FPGA**. Against
> what the hardware actually achieves, the gap is ~50×.

(An earlier version claimed a ~5,900 H/s ceiling with no derivation, and a
later one quoted ~4,400 by mixing spec-sheet and measured bandwidth. Both
were wrong in the moat's favor; the measured-basis arithmetic above, and the
shipped microbenchmark, replace them.)

## Beat us

This repo exists to be beaten. If you make a **bit-exact** implementation
faster than ours, you have found the moat's real width — and we want the
number.

**What counts as a win.** Your implementation must reproduce `vectors.txt`
exactly — every vector, fold *and* full-state digest — and mine the unmodified
function (`spec.py`, `vectors.txt` and `generate.py` are the definition; if you
changed them, you optimized a different problem). Beyond that, anything goes:
any language, any hardware, any trick.

**How to prove it, so nobody has to trust you:**

1. `make prove` passes with your implementation in place (it exits non-zero if
   any leg fails — try breaking one on purpose and watch it).
2. Report your rate with the exact command, the hardware, and how you avoided
   measuring a contended machine.
3. Mine a real solution and publish the nonce:
   `python3 host/verify_solution.py <nonce> <target>` re-derives it from the
   spec alone. A winning nonce is a proof of work that anyone can check without
   trusting your kernel, your timings, or you.

**Where to send it:** open a merge request, or publish it anywhere and send us
the link — we will re-run it and update the table above with attribution. A
faster CPU or GPU kernel is the single most valuable contribution this repo
can receive, and negative results ("I tried X, here's the profile showing why
it loses") are nearly as valuable — we'll take those too.

**Prior art on beating us:** the current numbers have survived two dedicated
adversarial passes (2026-08-05), each given this machine and asked to break
them. The first beat our CPU kernel by 47% and our CUDA kernel by 3%. The
second — five independent skeptical reviewers, including a CUDA specialist —
beat the CUDA kernel by another 5.7% (the `atomicExch` fusion now in
`gpu/mine.py`) and independently reproduced every number in this README,
including rebuilding the bandwidth microbenchmark before we shipped it. All
wins are merged above; that is the standing offer. The structural attacks —
bit-packed banks, multi-nonce interleaving, cache-blocking, alternate memory
layouts — all *lost*, with profiles explaining why. So the numbers you see
are post-attack, not first-draft, and they stand on what you can re-run from
this clone, not on anyone's word. Start from `gpu/mine.py` and
`cpu/verify_avx2.c` and assume the easy wins are gone.

## Mine on an FPGA

The measured 74k number is reproducible on the Efinix **Ti375 Development Kit**
with the free Efinity toolchain:

```
source <efinity>/bin/setup.sh
cd fpga/devkit
NRINGS=2 CLKDIV=1 PLL_MHZ=95 ./build_devkit.sh build
./build_devkit.sh program        # volatile JTAG load — gone at power-off,
                                 # never touches the board's flash
python3 ../read_miner.py --port /dev/ttyUSB2   # H/s from the hardware counter,
                                 # solutions re-derived against spec.py
```

Then from the repo root, `RACE_FPGA_PORT=/dev/ttyUSB2 make race` puts the
board on the leaderboard. `fpga/top.v` is board-agnostic (clock in, UART out):
porting to another Efinix part is a pinout + interface script, not RTL work —
`fpga/tz170/` runs the same flow against the Tz170 reference part, where it
closes timing at 201.8 MHz on the production speed grade (STA-certified;
that board's silicon run is pending).

## Layout

```
spec.py         the function, written to be read   (start here)
generate.py     emits the C tables, the Verilog ring, and the golden vectors
vectors.txt     golden (nonce -> digest, fold) tuples every implementation must hit
cpu/            simple.c (naive baseline), verify_avx2.c (the champion attack)
gpu/            mine.py — the CUDA competitor (CuPy)
fpga/           ring.v + miner.v + top.v, iverilog testbenches, devkit/ + tz170/ builds
host/           verify_solution.py  (re-derive a nonce with the spec)
race.py         the live leaderboard
docs/           bench notes
CLAUDE.md       boots a Claude session to help you verify all of this
```

## Caveats

- Parameters (`B=768`, `W=20`, `DEPTH=512`, `STEPS=2048`, `NDSP=128`) are sized
  so one ring is about half a Tz170, the cheap reference part; bigger parts
  replicate rings (the Ti375 devkit above runs two).
- The Tz170 rate is STA-certified timing on the production speed grade, not yet
  a silicon run; the Ti375 rate is a full-speed silicon measurement and the
  cycle model they share is confirmed on-chip to 0.1%.
- The GPU competitor needs an NVIDIA card + CuPy; other GPUs are skipped. A
  4090 (~2.25× bandwidth) halves the bandwidth-ceiling moat *by calculation* —
  worth measuring, not yet measured.
- The nonce enters via the un-skippable fill and the previous-block hash is
  XOR-spread into the initial state, so the FPGA computes no SHA in its hot
  loop (SHA only touches the once-per-block header, on the host).
- **The race's difficulty is demonstrator difficulty.** Race targets count
  leading zeros of the 32-bit *fold* — a cheap on-chip filter — which caps at
  2³² hashes. A real chain would target the full 256-bit SHA-256 digest
  (already the function's output); the fold would remain what it is here:
  telemetry and a share filter, not consensus difficulty.
- **The epoch seed is a trust decision this repo does not make.** Tables and
  wiring derive from a seed; who chooses it, on what schedule, and why a
  chooser can't grind seeds for a weak epoch are production-design questions,
  deliberately out of scope here alongside the reconfiguration schedule. What
  this repo demonstrates is the *mechanism*: for a fixed public seed,
  everything is derivable and checkable by anyone from `spec.py`.
- A demonstrator, not a deployed coin: the epoch-reconfiguration schedule and
  the surrounding production design live outside this repo.
