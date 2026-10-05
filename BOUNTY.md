# BRAM-ring bounty: beat the FPGA

BRAM-ring is a proof-of-work function designed so that a cheap FPGA mines it
more cost-effectively than any GPU, CPU, or other commodity hardware. I think
that claim is true. **I will pay 0.1 BTC to the first person who shows it is
false**, and 0.01 BTC for each meaningful improvement to the GPU or CPU
reference code along the way.

**Deadline: claims must be posted, and their code made public, by 4 November
2026, 23:59 Pacific Time (America/Los_Angeles).** A claim whose verification
is still running at the deadline is not cut off: it is decided when that
verification finishes. I may extend this offer by announcement, never shorten
it.

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

**0.01 BTC: a real shortcut.** A bit-exact implementation that does at most
half the work per hash of the specification — counted, not timed. The
specification performs `STEPS × B` = 1,572,864 bank read-modify-writes and
`STEPS × B × W` = 31,457,280 cell evaluations per hash; you show, with an
instrumented build I can run, that yours needs half of either. This award is
separate from the speed awards: it needs no speed-up, it does not make your
implementation the champion, and it does not move the bar. Partial outputs do
not count: the function's output is the full SHA-256 digest.

Speed awards ratchet, in order of claim time: a verified claim earns 0.01 BTC
if it measures at least 10% above the champion at that point — initially the
shipped kernel, afterwards the most recent verified winner — and then becomes
the new champion. The bar only rises. Worked example: the shipped GPU kernel
measures 1,493 in a session; A claims first and measures 1,650 (+10.5%), so A
wins and is champion; B claims later and measures 1,700, which is +3% over A,
so B wins nothing; C measures 1,850, +12% over A, so C wins. Limited to 10
awards in total, speed and shortcut awards together.

**The bar can move while you work.** A claim may stay sealed (hash posted, code
private) until the deadline, so the champion you are measured against may be a
claim you cannot see yet. Treat the published figures as a floor, not the bar:
a kernel 10% faster than 1,493 H/s is not guaranteed a prize if an earlier
sealed claim already beat it by more. Posting your own commit hash early is
what protects your place in that order. Verification does not wait for the
deadline: it starts as soon as a claim's code is public, and I post every
verified rate (the number, not the code) as a reply in the announcement
thread within 14 days of the code going public. So the bar set by every
unsealed claim is public; only sealed claims are invisible, and only until
their authors unseal them. Only verified claims move the bar; a claim that
fails verification never does. Sitting on a sealed claim is a bet that nobody
unseals a bigger one first.

## How I measure

Every rate in this document is produced the same way: on the reference
machine (i7-12700KF, RTX 3070, Ubuntu 24.04, nothing else running), five
runs, arithmetic mean. A run hashes at least 920 nonces on the GPU or 800 on
the CPU, timed wall-clock from the first nonce to the last, excluding one-time
setup (table generation, kernel compilation) and including everything done per
nonce (fill, run, SHA-256 digest).

- **GPU:** `python3 gpu/mine.py` — the `blocks= 460` line of its benchmark.
- **CPU:** `OMP_NUM_THREADS=8 taskset -c 0,2,4,6,8,10,12,14 cpu/verify_avx2`
  — the "CPU 8 cores" line: the eight P-cores pinned, which beats every other
  configuration on this part and is the least noisy (the README's thread
  table has the alternatives; on another machine the P-core list differs).

The published figures (1,493 and 822) are indicative. In each verification
session I measure the current champion and your implementation **back to
back**, under the same conditions, and your bar is 10% above the champion's
mean from that session, so drift in the machine (thermals, drivers, the day)
cancels. Your implementation needs a benchmark entry point that meets the run
definition above; ship it with your code, and I read it before I trust it.
The award is decided on that measured mean and nothing else; the number you
claimed is only what you are asked to reproduce. If your mean lands within 2%
of the bar, I replace both means with twenty-run means and decide on those.
The software state of the reference machine (kernel, driver, CUDA and
compiler versions) is recorded in every published decision.

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
kernel for another seed (do it in a scratch clone: it rewrites the generated
files, and your claim commit must keep the published ones). The seed is any
string; it reaches `spec.py` through the `BRAM_EPOCH` environment variable
and `hashlib.shake_256(seed.encode())`. Once your code is public I post a
fresh random seed as a reply in the announcement thread; the 48 hours start
at that reply, and "the same bit-exact result" means `host/check_vectors.py`
passes against the vectors I generate for that seed. Speed is judged on
`epoch0` only.

**2. Hardware cost.** The price is the retail price, **new**, of the hardware
doing the hashing:

- a GPU or accelerator card: the card (its own memory is part of it);
- a CPU claim: the CPU plus the RAM your method uses, priced as the cheapest
  qualifying listing for that capacity of standard memory;
- an integrated device (a Mac, an APU board, an NPU development board, a
  laptop): the whole unit as sold;
- a separate host that only feeds a card (motherboard, power supply, host
  CPU), and energy: excluded. If the host does any of the hashing, it is a
  device and is priced.

A qualifying listing is the exact SKU, in stock, at a fixed price before tax
and shipping, sold and shipped by Amazon, Newegg, B&H, Best Buy or Micro
Center themselves (not a marketplace seller) or by the manufacturer's own
store, at any time in the 30 days before the claim and in stock at that price
for at least 24 hours, evidenced by a dated screenshot or an archive.org
capture in your commit. Used, refurbished, surplus and grey-market prices do
not count; hardware with no qualifying listing cannot be claimed. A
multi-device rig counts total hash rate over total device price, every device
in your possession at the claimed price. "FPGA" means a device whose logic is
configured by a bitstream, including eFPGA fabric inside an SoC; CGRA, AI
engine and NPU arrays are not FPGAs. The FPGA side of the comparison is fixed
at $100 per Tz170-equivalent, as above.

**3. Verification.** I re-run your published code on the claimed hardware
model under the protocol in "How I measure". I buy or rent hardware up to
$3,000 per claim; above that, or if I cannot obtain it within 28 days, you
give me access to yours (remote is fine) and I run the protocol there. If
neither has happened 56 days after your code went public, the claim is
decided on the evidence in your commit, the five-run log and the mined nonce,
and the decision says so. The decision rests on my measured mean. Speed
awards are verified only on my own reference RTX 3070 and i7-12700KF.

**4. Claims and priority.** To make a claim, reply to the announcement tweet
from [@PeterRizun](https://x.com/PeterRizun) (link to be added here when it
is posted) with the **full 40-character git commit hash** of your submission
and the prize you are claiming. The reply's timestamp is your priority time;
replies in the same minute rank by tweet ID, lower first. Edited replies do
not count; post a new one. A reply you later delete or hide no longer counts.
Should X become unusable, the replacement channel is announced in this
repository's README and existing claims keep their times.

You may publish your code immediately, or keep it private and publish it any
time before the deadline, on any public git host. Because the commit hash
fixes your code exactly, you can establish priority without revealing your
method. The commit must contain everything needed to reproduce the result:
code, build instructions, your benchmark entry point, your licence, and, for
the 0.1 BTC prize, the hardware's price evidence, your five-run log and one
mined nonce that `host/verify_solution.py` accepts. A packaging slip (a
missing dependency, a wrong path) gets one 72-hour cure; the code, the
numbers and the hash do not. A claim whose commit is not public by the
deadline lapses. For the 0.1 BTC prize, if two valid claims qualify, the
earlier claim wins; speed awards ratchet as described above.

**5. What does not count.**
- Custom ASICs that are not commercially available.
- Changes to the function or the vectors (rule 1).
- Hardware that cannot be bought new.
- Rented or borrowed hardware presented as yours: the rate must come from
  devices in your possession at the claimed price (rule 2).
- Projections: every claimed rate is one you measured on hardware you have.

**6. Judging and payout.** Claims are adjudicated by me, Peter Rizun, under
the text of this document on this repository's `main` branch at the moment of
your reply. I may clarify this document afterwards, but a clarification never
binds a claim made before it. Every decision is posted as a reply in the
announcement thread within 14 days of the claim's code going public (28 days
if I must buy hardware to verify it), with the reproduction commands, logs,
the reference machine's software versions and the price evidence used.
Claimants may observe the reproduction run. Where a rule is genuinely
ambiguous, I rule in the claimant's favour. Each decision is open to public
objection for 7 days: reply to it in the thread, and I answer every objection
in the thread before the decision is final.

The prize pool is 0.2 BTC (0.1 + 10 × 0.01), held at the address in "Proof
of funds" below, with a message signed by that address. Because a claim made earlier may be
revealed later, winners are settled after the deadline, once every claim has
been verified, and no later than 60 days after the deadline; prizes are paid
in BTC to an address the winner provides within 14 days of the final decision.
Winning code must be published under the MIT licence or any other
OSI-approved licence, named in the frozen commit. Anyone may claim except
people I have paid to work on this repository. Taxes are the winner's affair,
and I cannot pay anyone sanctions law forbids me to pay.

**Negative results are welcome.** "I tried X; here is the profile showing why
it loses" earns no BTC, but it will be credited in the README and saves the
next person the trouble.

## Proof of funds

The prize pool sits at this address (0.20093990 BTC, confirmed in block
970089):

    bc1qtk8q5nsupm47kg5vz9turqacx8lg2whvxukpuj

Message, signed by that address:

    Peter Rizun holds the 0.2 BTC prize pool for the NEXA BRAM-ring bounty at this address. Rules: https://git.nodelabs.ca/nexapow/bram-ring/-/blob/main/BOUNTY.md 2026-10-05

Signature:

    HxALKo2u0bmkpOxC6Xdvb26yeMs/eT/flSNVaIFzLC9FL0GY4/oUkw+OJXS5sXVIRP9gER4LKmYl3ymHT21LrsY=

Verify with Electrum or Sparrow ("verify message"): the signature is in the
classic Bitcoin Signed Message format those wallets use for SegWit addresses.

## The frozen function

SHA-256 of the three files that define it, as this document ships them:

    5596327c5fc89b4d87eaf64df0b25e8430a9b25247ebae4c3e1037c19cd2f292  spec.py
    20f78b63ff10f7b4fee681355190e91eaaeb527a733d2701d928eb0ac6534dab  generate.py
    d406e2319f21e641dc77fcf79693c88062cc312cd1d75f0c286fa4ba85cf88f1  vectors.txt
