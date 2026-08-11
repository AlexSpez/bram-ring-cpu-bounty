#!/usr/bin/env python3
"""
read_miner.py — read the BRAM-ring miner's UART status off the board.

The FPGA streams an ASCII line ~2x/sec:
    <hash_count:16hex> <sol_nonce:16hex> <sol_fold:8hex> <found>

We measure hashes/second from the counter (trustless: it's the real work the
silicon did), and when the miner reports a solution we re-derive that nonce with
spec.py to confirm it's genuine.

  python3 read_miner.py --port /dev/ttyUSB2        # UART channel of the programmed board
  python3 read_miner.py                            # auto-try likely ports
"""
import sys, os, time, argparse, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import spec as spec

TARGET = 0x0000FFFF          # must match TARGET in fpga/top.v (module miner_top)

def parse(line):
    p = line.split()
    if len(p) != 4: return None
    try:
        return int(p[0], 16), int(p[1], 16), int(p[2], 16), int(p[3])
    except ValueError:
        return None

def run(port, baud, seconds):
    import serial
    ser = serial.Serial(port, baud, timeout=2)
    print(f"reading {port} @ {baud}  (target = {TARGET:#010x}, {32-TARGET.bit_length()} leading-zero bits)")
    t0 = time.time(); hc0 = None; verified = {}; win = []
    while True:
        raw = ser.readline().decode("ascii", "ignore").strip()
        f = parse(raw)
        if not f: continue
        hc, nonce, fold, found = f
        now = time.time()
        win.append((now, hc))
        while len(win) > 2 and now - win[0][0] > 10: win.pop(0)   # rolling ~10 s window
        (tw, hw) = win[0]
        rate = (hc - hw) / max(1e-3, now - tw) if now - tw > 1.0 else 0.0
        msg = f"[{now-t0:6.1f}s] hashes={hc:,}  rate={rate:,.0f} H/s"
        if found:
            if nonce not in verified:   # slow pure-python re-derivation, once per nonce
                fv = spec.difficulty_value(spec.run(spec.EPOCH, nonce))
                verified[nonce] = "VALID" if fv <= TARGET else f"BAD(fold={fv:#x})"
            msg += f"  SOLUTION nonce={nonce:#x} fold={fold:#010x} [{verified[nonce]} vs spec]"
        print(msg)
        if seconds and now - t0 > seconds: break

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=0)
    a = ap.parse_args()
    ports = [a.port] if a.port else sorted(glob.glob("/dev/ttyUSB*"))
    for p in ports:
        try:
            run(p, a.baud, a.seconds); return
        except Exception as e:
            print(f"{p}: {e}")
    print("no readable miner found — pass --port explicitly")

if __name__ == "__main__":
    main()
