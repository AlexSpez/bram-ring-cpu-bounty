#!/usr/bin/env python3
"""
race.py — a live mining race for the BRAM-ring proof-of-work.

You pick a target difficulty (leading zero bits). Every competitor mines on your
machine until one of them finds a nonce whose hash clears the target -- that
competitor wins and the race stops, printing the winning nonce so you can check
it against the reference spec yourself.

Rate is inferred mining-pool style: competitors report "shares" (nonces clearing
a low, self-tuning partial target) and we estimate hashes/sec from the share
stream (sum of each share's 2^D of work). This works the same over a fast pipe
or a slow UART, and every share is a checkable proof of real work.

  python3 race.py --target 20
  python3 race.py                 # prompts for the target

Competitors are ranked by hash rate, leader on top -- so when the FPGA joins,
it takes the #1 spot.
"""
import os, sys, time, subprocess, threading, argparse, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CPU = os.path.join(HERE, "cpu")
GPU = os.path.join(HERE, "gpu", "mine.py")      # strong kernel: block-per-nonce + K-way MLP
# The GPU competitor runs under a CuPy-capable Python. If cupy isn't in the
# Python running this race, point RACE_GPU_PY at one that has it (e.g. a venv):
#   RACE_GPU_PY=/path/to/venv/bin/python python3 race.py
GPU_PY = os.environ.get("RACE_GPU_PY") or sys.executable
PYCLEAN_VARS = ["env", "-u", "PYTHONHOME", "-u", "PYTHONPATH", "-u", "PYTHONNOUSERSITE"]
PYCLEAN = PYCLEAN_VARS + [GPU_PY]
WINDOW = 5.0    # seconds of shares to average the rate over
ZMAX = 32       # the fold is 32 bits, so at most 32 leading zeros
BOLD, DIM, GRN, RST = "\x1b[1m", "\x1b[2m", "\x1b[32m", "\x1b[0m"
HR = "  " + "─" * 60

def gpu_ready():
    """An NVIDIA GPU with CuPy in the GPU Python (GPU_PY). Any NVIDIA card works
    (the kernel is generic CUDA, batch adapts to VRAM); non-NVIDIA cards are left
    out. If GPU_PY is this process, check in-process (fast); otherwise probe it."""
    if shutil.which("nvidia-smi") is None:
        return False
    if GPU_PY == sys.executable:
        import importlib.util
        return importlib.util.find_spec("cupy") is not None
    try:
        return subprocess.run(PYCLEAN_VARS + [GPU_PY, "-c", "import cupy"],
                              capture_output=True, timeout=60).returncode == 0
    except Exception:
        return False

def competitors():
    out = []
    # ONE CPU entrant = the champion attack, on its own silicon. On this hash
    # the AVX2 lane-parallel kernel (verify_avx2) is the champion: it deletes
    # the CPU's compute tax while keeping every byte of the memory traffic --
    # which is why scaling turns over at high thread counts (the aggregate
    # working set, ~1.5 MB/nonce, overflows the shared L3; see the README's
    # measured curve). Two all-core CPU miners at once would just
    # oversubscribe the same chip, so we race the winner; `cpu/simple` remains
    # the readable baseline (and the no-GPU fallback entrant below).
    # Thread topology matters (hybrid CPUs): the entrant inherits OMP_* from
    # your environment, so race the champion config with e.g.
    #   OMP_NUM_THREADS=16 OMP_PROC_BIND=close make race
    nc = os.environ.get("OMP_NUM_THREADS") or str(os.cpu_count() or 1)
    if os.path.exists(os.path.join(CPU, "verify_avx2")):
        out.append((f"CPU  avx2/{nc}t",   [os.path.join(CPU, "verify_avx2"), "mine", "0"]))
    if gpu_ready():
        out.append(("GPU  (CUDA)",       PYCLEAN + [GPU, "mine", "20000000000"]))
    # FPGA: set RACE_FPGA_PORT (+ optional RACE_FPGA_BAUD) to the board's UART and
    # fpga/race_fpga.py bridges its hash_count frames into the share stream.
    port = os.environ.get("RACE_FPGA_PORT")
    if port:
        rf = os.path.join(HERE, "fpga", "race_fpga.py")
        baud = os.environ.get("RACE_FPGA_BAUD", "115200")
        out.append(("FPGA",           PYCLEAN_VARS + [sys.executable, rf, port, baud]))
    # Always give the race >=2 entrants: with no GPU/FPGA, add the naive miner
    # so it's a real race (and shows the AVX2 kernel's edge directly). The two
    # CPU miners then share the machine, so both read lower than run alone.
    if len(out) < 2 and os.path.exists(os.path.join(CPU, "simple")):
        out.append((f"CPU  simple/{nc}c", [os.path.join(CPU, "simple"), "mine", "10000000000"]))
    return out

class Runner:
    def __init__(self, label, argv, target):
        self.label = label; self.argv = argv; self.target = target
        self.best = 0; self.shares = collections.deque()   # (t, D)
        self.win = None; self.alive = True; self.err = ""
    def start(self):
        self.t_start = time.time()
        try:
            self.p = subprocess.Popen(self.argv, cwd=HERE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, bufsize=1)
        except Exception as e:
            self.alive = False; self.err = str(e); return
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: setattr(self, "err", (self.p.stderr.read() or "")[:300]),
                         daemon=True).start()
    def _read(self):
        for line in self.p.stdout:
            if not line.startswith("SHARE"): continue
            _, nonce, zeros, D = line.split()
            z = int(zeros)
            if z > self.best: self.best = z
            if z >= self.target and self.win is None: self.win = nonce
            self.shares.append((time.time(), int(D)))
        self.alive = False
    def rate(self):
        now = time.time()
        while self.shares and self.shares[0][0] < now - WINDOW: self.shares.popleft()
        if not self.shares: return 0.0
        work = sum(2.0**D for _, D in self.shares)      # expected hashes represented
        span = min(WINDOW, now - self.t_start)          # fixed window (ramps during warmup)
        return work / max(1e-3, span)

def human(x):
    for u in ("", "K", "M", "G"):
        if x < 1000: return f"{x:6.1f} {u}H/s"
        x /= 1000
    return f"{x:6.1f} TH/s"

def bar(best, target):
    """bar filled to the most leading zeros found so far, with the target '|'."""
    W = 22
    b = max(0, min(W, round(best / ZMAX * W)))
    t = max(0, min(W-1, round(target / ZMAX * W)))
    cells = ["#" if i < b else "." for i in range(W)]
    cells[t] = "|" if cells[t] == "." else "%"     # % = reached-and-past the marker
    return "".join(cells)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=None, help="winning difficulty (leading zero bits, 1..32)")
    ap.add_argument("--seconds", type=float, default=0, help="optional time cap")
    a = ap.parse_args()
    target = a.target
    if target is None:
        try: target = int(input("target difficulty (leading zero bits, e.g. 20): ") or "20")
        except (EOFError, ValueError): target = 20
    target = max(1, min(ZMAX, target))

    runners = [Runner(l, v, target) for l, v in competitors()]
    if not runners:
        print("nothing to race -- build the benchmarks first: make bench"); return
    cpu_shared = sum(r.label.strip().startswith("CPU") for r in runners) >= 2
    for r in runners: r.start()
    t0 = time.time(); winner = None
    sys.stdout.write("\x1b[2J")
    try:
        while winner is None:
            time.sleep(0.2)
            el = time.time() - t0
            rows = sorted(((r, r.rate()) for r in runners), key=lambda x: -x[1])  # leader first
            L = [HR,
                 f"  {BOLD}NEXA BRAM-ring mining race{RST}",
                 f"  target: {BOLD}{target}{RST} leading-zero bits       t = {el:5.1f}s",
                 HR, ""]
            for i, (r, rate) in enumerate(rows):
                lbl = f"{r.label:17}"
                rt = (f"{human(rate):>10}" if rate > 0 and r.alive
                      else f"{'warming…':>10}" if r.alive else f"{'stopped':>10}")
                line = f"  {i+1} {lbl} [{bar(r.best, target)}] {r.best:2d}  {rt}"
                if i == 0 and rate > 0: line = f"{BOLD}{GRN}{line}{RST}"   # leader
                L.append(line)
            L += ["", HR,
                  f"  {DIM}bar = best so far · '|' = target · rate from shares{RST}",
                  f"  {DIM}first to the target wins · mining is memoryless{RST}"]
            if cpu_shared:
                L.append(f"  {DIM}(both CPU entrants share this machine — each is faster run alone;"
                         f" add a GPU with GPU_PY=){RST}")
            L.append(HR)
            sys.stdout.write("\x1b[H" + "\n".join(s + "\x1b[K" for s in L) + "\x1b[J")
            sys.stdout.flush()
            for r in runners:
                if r.win is not None: winner = r; break
            if a.seconds and el >= a.seconds: break
    except KeyboardInterrupt:
        pass
    finally:
        for r in runners:
            try: r.p.terminate()
            except Exception: pass
    print()
    if winner:
        print(HR)
        print(f"  {BOLD}{GRN}WINNER: {winner.label.strip()}{RST}  in {BOLD}{time.time()-t0:.1f}s{RST}")
        print(f"  nonce {BOLD}0x{winner.win}{RST} clears {BOLD}{target}{RST} leading-zero bits")
        print(HR)
        print(f"  {DIM}verify:{RST} python3 host/verify_solution.py 0x{winner.win} {target}")
    else:
        print("  no winner (time cap reached)")

if __name__ == "__main__":
    main()
