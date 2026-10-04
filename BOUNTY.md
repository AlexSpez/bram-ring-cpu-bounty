# BRAM-ring bounty: beat the FPGA

BRAM-ring is a proof-of-work function designed so that a cheap FPGA mines it
more cost-effectively than any GPU, CPU, or other commodity hardware. I think
that claim is true. **I will pay 0.1 BTC to the first person who shows it is
false**, and 0.01 BTC for each meaningful improvement to the GPU or CPU
reference code along the way.

**Deadline: claims must be posted, and their code made public, by 31 October
2026, 23:59 Pacific Time.**

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
target.

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
rate per dollar it achieves on real hardware.

## Prizes

**0.1 BTC: the idea is broken.** Awarded to the first claim showing non-FPGA
hardware at or above the target, under the rules below.

**0.01 BTC: a better GPU kernel.** A bit-exact GPU implementation whose mean
hash rate is at least **10% above** the current champion (1,493 H/s) on the
reference **RTX 3070**, measured by me on my machine.

**0.01 BTC: a better CPU implementation.** A bit-exact CPU implementation whose
mean hash rate is at least **10% above** the current champion (805 H/s) on the
reference **Intel i7-12700KF**, measured by me on my machine.

Improvement awards are decided after the deadline, in order of claim time: a
verified claim earns 0.01 BTC if it is at least 10% faster than the champion at
that point (the reference above, or the most recent winning claim), and then
becomes the new champion. Limited to 10 improvement awards in total.

**The bar can move while you work.** A claim may stay sealed (hash posted, code
private) until the deadline, so the champion you are measured against may be a
claim you cannot see yet. Treat the published figures as a floor, not the bar:
a kernel 10% faster than 1,493 H/s is not guaranteed a prize if an earlier
sealed claim already beat it by more. Posting your own commit hash early is
what protects your place in that order.

## Rules

**1. Correctness.** Your implementation must reproduce every column of
`vectors.txt` exactly, under `make prove`. The function is defined by
`spec.py`, `generate.py`, and `vectors.txt` and must not be modified. Claims
must also be bit-exact on a fresh epoch seed that I publish when the claim is
made, so nothing can be specialised to `epoch0`.

**2. Hardware cost.** Hardware is priced **new**: the lowest in-stock,
fixed-price listing (not an auction) for that exact model from a major
authorized retailer, at any time in the 30 days before the claim. Used,
refurbished, surplus, and grey-market prices do not count. A multi-device rig
counts total hash rate over total device price. Host systems (motherboard,
CPU, power supply) and energy are excluded. The FPGA side is fixed at $100 per
Tz170-equivalent, as above.

**3. Verification.** I re-run your published code on the claimed hardware
model, which I will buy or rent, or you may give me access. My measured mean
hash rate must come within 10% of your claim. Improvement awards are verified
only on my own reference RTX 3070 and i7-12700KF.

**4. Claims and priority.** To make a claim, reply to the announcement tweet
(link to be added here when it is posted) with the **full 40-character git commit hash** of your submission and the
prize you are claiming. The reply's timestamp is your priority time. Edited
replies do not count; post a new one.

You may publish your code immediately, or keep it private and publish it any
time before the deadline. Because the commit hash fixes your code exactly, you
can establish priority without revealing your method. The commit must contain
everything needed to reproduce the result: code, build instructions, and, for
the 0.1 BTC prize, evidence of the hardware's price. A claim whose commit is
not public by the deadline lapses. If two valid claims qualify for the same
prize, the earlier reply wins.

**5. What does not count.**
- Custom ASICs that are not commercially available.
- Changes to the function, the vectors, or the epoch-seed procedure.
- Hardware that cannot be bought new.
- Rented clusters presented as single devices: the rate must come from the
  hardware whose price you claim.

**6. Judging and payout.** Claims are adjudicated by me, Peter Rizun. Every
decision is published within 14 days of the claim's commit going public (28
days if I must purchase new hardware to verify it), together with the
reproduction commands, logs, and price evidence used. Claimants may observe
the reproduction run and may supply their own benchmark script. Where a result
is within measurement error of a threshold, I take a longer average until it
is not; where a rule is genuinely ambiguous, I rule in the claimant's favour.

Because a claim made earlier may be revealed later, the winners are settled
only after the deadline, once every claim has been verified. Prizes are paid
in BTC to an address the winner provides, within 14 days after the deadline,
or within 28 days if verifying a claim requires me to purchase new hardware.
Winning code must be published under an open-source licence.

**Negative results are welcome.** "I tried X; here is the profile showing why
it loses" earns no BTC, but it will be credited in the README and saves the
next person the trouble.
