#!/usr/bin/env python3
"""
verify_solution.py — independently confirm a mined nonce with the reference spec.

Recompute the hash for a nonce with the reference spec (spec.py — the frozen
race function) and report how many leading zero bits its 32-bit fold has. This
is what makes a competitor (or the FPGA) trustworthy: you don't trust its
arithmetic, you re-derive the winning nonce.

  python3 host/verify_solution.py <nonce> [target_zeros]
  python3 host/verify_solution.py 0x1a2b3c 24
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import spec

def leading_zeros(v, width=32):
    return width if v == 0 else width - v.bit_length()

def main(nonce, target=None, epoch=spec.EPOCH):
    heads = spec.run(epoch, nonce)
    fold = spec.difficulty_value(heads)
    z = leading_zeros(fold)
    print(f"nonce      0x{nonce:x}")
    print(f"fold       0x{fold:08x}   ({fold:032b})")
    print(f"leading 0s {z}")
    print(f"digest     {spec.digest(epoch, nonce)}")
    if target is not None:
        ok = z >= target
        print(f"target     {target}  ->  {'VALID WIN' if ok else 'not enough'} "
              f"({z} {'>=' if ok else '<'} {target})")
        return ok
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    nonce = int(sys.argv[1], 0)
    target = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.exit(0 if main(nonce, target) else 1)
