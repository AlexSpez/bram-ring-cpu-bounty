# BRAM-ring bounty: beat the FPGA

BRAM-ring is a proof-of-work function designed so that a cheap FPGA mines it
more cost-effectively than any GPU, CPU, or other commodity hardware. I think
that claim is true. **I will pay 0.1 BTC to the first person who shows it is
false**, and 0.01 BTC for each meaningful improvement to the GPU or CPU
reference code along the way.

**Deadline: claims must be posted, and their code made public, by 30 November
2026, 23:59 Pacific Time.** A claim still under verification at the deadline
keeps its place; its own deadline is its decision. I may extend this offer by
announcement, never shorten it.

## The target

Everything is judged by one number: **mean hash rate per US dollar of
hardware.**

The reference miner is one ring on the Efinix **Tz170**, the cheap part this
design targets. I define its cost as **$100 per Tz170-equivalent**, covering
chip, board, and retail margin. (Chips cost about $40 at small volume, so I
believe $100 overstates the at-scale cost.)

| | |
|---|---|
| Reference rate | **37,100 H/s** per Tz170-equivalent: one ring at 95 MHz, the clock the 2-ring Ti375 build ran bit-exact on silicon (74,233 H/s measured) |
| Reference cost | **$100** (defined) |
| **Target** | **371 H/s per USD**, fixed for the duration of this offer |

This is conservative: the Tz170 closes timing at 201.8 MHz on the production
speed grade (about 78,700 H/s), roughly double the rate used here.

For scale: the best GPU result so far is an RTX 3070 at 1,493 H/s, which at its
$499 launch price is about 3 H/s per USD, more than 100 times short of the
target. (Launch price, for scale only; real claims are priced under rule 2.)

## Three ways to break it

Any of these counts. They are all judged by the same number.

**(a) Better hardware.** Find a GPU, CPU, NPU, or other commercially available
non-FPGA hardware that reaches the target, for example a card with more memory
bandwidth per dollar, or enough on-die cache to hold a nonce's state.

**(b) Better code.** Make the CPU or GPU implementation (or your own) fast
enough to reach the target. Start from `gpu/mine.py` and `cpu/verify_avx2.c`,
and assume the easy wins are gone: see the README for the adversarial passes
these already survived.

**(c) A shortcut in the function.** Find a weakness that lets you compute
correct outputs with substantially less work or memory than the specification
implies, such as degenerate address patterns, short cycles in the ring
dynamics, weak lookup tables, a time-memory trade-off, or a way around the
fill. A shortcut is rewarded through its effect on the target: show the hash
rate per dollar it achieves on real hardware. A shortcut that falls short of
the target still pays — see the shortcut award below, and note that a
bit-exact shortcut implementation competes for the kernel awards like any
other kernel.

## Prizes

**0.1 BTC: the idea is broken.** Awarded to the first claim showing non-FPGA
hardware at or above the target, under the rules below.

**0.01 BTC: a better GPU kernel.** A bit-exact GPU implementation that
measures at least **10% above** the current champion (1,493 H/s) on the
reference **RTX 3070**, under the protocol in "How I measure" below.

**0.01 BTC: a better CPU implementation.** A bit-exact CPU implementation that
measures at least **10% above** the current champion (822 H/s) on the
reference **Intel i7-12700KF**, under the same protocol.

**0.01 BTC: a real shortcut.** A bit-exact implementation that demonstrably
halves the work per hash — half the memory operations or half the arithmetic,
shown on the reference machine against the champion of its class — earns
0.01 BTC even if it reaches neither the target nor a 10% speed-up. Partial
outputs do not count: the function's output is the full SHA-256 digest.

Improvement awards are decided after the deadline, in order of claim time: a
verified claim earns 0.01 BTC if it measures at least 10% above the champion
at that point (the figures above, or the **measured** rate of the most recent
verified winner), and then becomes the new champion. Limited to 10
improvement awards in total, GPU, CPU and shortcut awards together.

**The bar can move while you work.** A claim may stay sealed (hash posted, code
private) until the deadline, so the champion you are measured against may be a
claim you cannot see yet. Treat the published figures as a floor, not the bar:
a kernel 10% faster than 1,493 H/s is not guaranteed a prize if an earlier
sealed claim already beat it by more. Posting your own commit hash early is
what protects your place in that order. Only verified claims move the bar; a
claim that fails verification never does. I publish every verified rate (the
number, not the code) within 14 days of verifying it, so the current bar is
always public even while the code behind it is not.

## How I measure

Every rate in this document, the champions included, is produced the same
way: on the reference machine (i7-12700KF, RTX 3070, Ubuntu, nothing else
running), five runs, arithmetic mean.

- **GPU:** `python3 gpu/mine.py` — the `blocks= 460` line of its benchmark.
- **CPU:** `OMP_NUM_THREADS=8 taskset -c 0,2,4,6,8,10,12,14 cpu/verify_avx2`
  — the "CPU 8 cores" line. That is the eight P-cores pinned, which beats
  every other configuration on this part and is the least noisy (the
  README's thread table has the alternatives).

Your implementation is measured with the equivalent command for your code.
You may ship a benchmark script; if it disagrees with this protocol, the
protocol decides. The award is decided on that measured mean and nothing
else; the number you claimed is only what you are asked to reproduce. If the
mean lands within 2% of the bar, twenty more runs decide it.

## Rules

**1. Correctness.** Your implementation must reproduce every column of
`vectors.txt` — nonce, digest, 32-bit fold and full ring state — for all
eight vectors. The repo checks that for you: have your program print one
line per vector in `vectors.txt`'s format and pipe it through
`host/check_vectors.py` (`make prove` holds the shipped implementations to
the same bar). The function is defined by `spec.py`, `generate.py` and
`vectors.txt`; before anything of yours runs, I check that those three files
in your commit are byte-identical to the published ones (SHA-256 at the end
of this document).

Your code must also take the epoch seed as an input. Tables, constants and
generated code may be precomputed from the seed, and that precompute is not
timed, but nothing may depend on the seed being `epoch0`. The repo supports
this: `BRAM_EPOCH=<seed> make prove` regenerates every table, vector and
kernel for another seed. Once your code is public I publish a fresh seed, and
you have 48 hours to show the same bit-exact result on it.

**2. Hardware cost.** The price is the retail price, **new**, of the hardware
doing the hashing: for a GPU or accelerator card, the card; for a CPU claim,
the CPU; for an integrated device (a Mac, an APU board, an NPU development
board), the whole unit; and memory counts whenever your method needs more
than the device ships with. A separate host that only feeds a card
(motherboard, power supply, host CPU) and energy are excluded. The price is
the lowest in-stock, fixed-price, first-party listing at Amazon, Newegg, B&H,
Best Buy or Micro Center, or the manufacturer's own store, at any time in the
30 days before the claim, evidenced by a dated URL or screenshot in your
commit. Used, refurbished, surplus, marketplace-seller and grey-market prices
do not count, and hardware with no such listing cannot be claimed. A
multi-device rig counts total hash rate over total device price, provided
every device is in your possession at that price. The FPGA side is fixed at
$100 per Tz170-equivalent, as above.

**3. Verification.** I re-run your published code on the claimed hardware
model, which I will buy or rent, or you may give me access, under the
protocol in "How I measure". The decision rests on my measured mean. If I
cannot obtain the hardware within 28 days I say so publicly and the claim
waits rather than lapses. Improvement awards are verified only on my own
reference RTX 3070 and i7-12700KF.

**4. Claims and priority.** To make a claim, do either or both of these; the
earlier one is your priority time:

- reply to the announcement tweet from [@PeterRizun](https://x.com/PeterRizun)
  (link to be added here when it is posted) with the **full 40-character git
  commit hash** of your submission and the prize you are claiming; or
- email the same two things to <info@nodelabs.ca> with the subject
  `BRAM-ring claim`. I acknowledge every claim email publicly (hash and
  time, nothing else) within 48 hours.

Edited replies do not count; post a new one. Claims in the same minute rank
by position in the tweet thread, then by email arrival.

You may publish your code immediately, or keep it private and publish it any
time before the deadline. Because the commit hash fixes your code exactly, you
can establish priority without revealing your method. The commit must contain
everything needed to reproduce the result: code, build instructions, and, for
the 0.1 BTC prize, evidence of the hardware's price. A claim whose commit is
not public by the deadline lapses. For the 0.1 BTC prize, if two valid claims
qualify, the earlier claim wins; improvement awards ratchet as described
above.

**5. What does not count.**
- Custom ASICs that are not commercially available.
- Changes to the function or the vectors (rule 1).
- Hardware that cannot be bought new.
- Rented clusters presented as single devices: the rate must come from the
  hardware whose price you claim.

**6. Judging and payout.** Claims are adjudicated by me, Peter Rizun, under
the version of this document at the commit of this repository that your
claim names — the rules cannot change under you. Every decision is published
within 14 days of the claim's commit going public (28 days if I must buy
hardware to verify it), together with the reproduction commands, logs and
price evidence used. Claimants may observe the reproduction run. Where a rule
is genuinely ambiguous, I rule in the claimant's favour. Each decision is
open to public objection for 7 days before it is final.

Because a claim made earlier may be revealed later, the winners are settled
after the deadline, once every claim has been verified, and paid in BTC to an
address the winner provides within 14 days of the final decision. The
announcement carries a message signed by the funding address holding the
full prize pool. Winning code must be published under the MIT licence or any
other OSI-approved licence. Anyone may claim except people who were paid for
the earlier adversarial passes named in the README.

**Negative results are welcome.** "I tried X; here is the profile showing why
it loses" earns no BTC, but it will be credited in the README and saves the
next person the trouble.

## The frozen function

SHA-256 of the three files that define it, as this document ships them:

    1c5b0e9d2557a0a31b6c88a54b23ec8bdffd0370f2d8a10248af3c8f76fc5dee  spec.py
    20f78b63ff10f7b4fee681355190e91eaaeb527a733d2701d928eb0ac6534dab  generate.py
    d406e2319f21e641dc77fcf79693c88062cc312cd1d75f0c286fa4ba85cf88f1  vectors.txt
