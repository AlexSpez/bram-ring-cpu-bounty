#!/usr/bin/env python3
"""
race_fpga.py — bridge the FPGA miner's UART status stream into the race's
share protocol, so the FPGA competes live next to the CPU and GPU.

The board emits, ~2x/second (fpga/top.v, module miner_top):
    <hash_count:16hex> <sol_nonce:16hex> <sol_fold:8hex> <found>\n
hash_count is the cumulative hashes summed across all rings -- a real hardware
counter, not an Fmax guess. We turn its per-frame delta into the race's
pool-style "SHARE <nonce> <zeros> <D>" lines: each share represents 2^D hashes,
so the race's sum-of-2^D estimator recovers the true on-chip rate. D is chosen
from the measured rate to hold ~SHARE_TARGET shares/s. When the board latches a
real solution (found=1) we emit it as a high-difficulty share; the board keeps
improving its latched best (fpga/miner.v re-arms on a lower fold), so every
NEW best is emitted as it lands and a race at any difficulty stays winnable.

  race_fpga.py <port> [baud]        e.g. race_fpga.py /dev/ttyUSB3 115200

Validated against a live Ti375 devkit 2026-08-05 (3-way race, rate within 5%
of the hardware counter). Gated in race.py behind the RACE_FPGA_PORT env var,
so it never runs unless you point it at a real port.
"""
import sys, time, math

SHARE_TARGET = 12.0     # synthetic shares/sec (matches the CPU/GPU competitors)

def clz32(x):
    x &= 0xffffffff
    return 32 if x == 0 else 32 - x.bit_length()

def open_port(port, baud):
    """pyserial if available; else a raw device file (set baud first with
    `stty -F <port> <baud> raw -echo`)."""
    try:
        import serial
        return serial.Serial(port, baud, timeout=1)
    except ImportError:
        return open(port, "rb", buffering=0)

def readlines(p):
    buf = b""
    while True:
        chunk = p.read(256)
        if not chunk:
            time.sleep(0.02); continue
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("ascii", "replace").strip()

def main():
    if len(sys.argv) < 2:
        print("usage: race_fpga.py <port> [baud]", file=sys.stderr); return 1
    port = sys.argv[1]; baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    p = open_port(port, baud)
    prev_hc = None; prev_t = None; carry = 0; last_sol = None
    for line in readlines(p):
        f = line.split()
        if len(f) != 4:
            continue                                   # partial / malformed frame
        try:
            hc, sol_nonce, sol_fold, found = int(f[0],16), int(f[1],16), int(f[2],16), int(f[3])
        except ValueError:
            continue
        t = time.perf_counter()
        if prev_hc is not None:
            dt = max(1e-3, t - prev_t)
            delta = (hc - prev_hc) & ((1 << 64) - 1)   # cumulative counter, tolerate wrap/restart
            if delta > (1 << 63): delta = 0            # counter reset (reprogram) -> skip this frame
            rate = delta / dt
            D = max(1, min(30, int(round(math.log2(max(1.0, rate / SHARE_TARGET))))))
            carry += delta
            n = carry >> D; carry -= n << D            # emit `n` shares of 2^D hashes each
            for i in range(int(n)):
                print(f"SHARE {i:x} {D} {D}", flush=True)
        prev_hc, prev_t = hc, t
        if found and sol_nonce != last_sol:            # each NEW best solution -> a real share
            print(f"SHARE {sol_nonce:x} {clz32(sol_fold)} 0", flush=True)
            last_sol = sol_nonce
    return 0

if __name__ == "__main__":
    sys.exit(main())
