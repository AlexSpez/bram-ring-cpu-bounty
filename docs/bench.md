# bram-ring bench usage

## make targets need a pinned Python

`make` and `make race` need an explicit interpreter override on hosts
where a vendor FPGA toolchain's bundled `python3` shadows the system one:

```
make PY=/usr/bin/python3
make race PY=/usr/bin/python3
```

If such a toolchain's `setup.sh` has been sourced, `PYTHONHOME`/`PYTHONPATH`
point even `/usr/bin/python3` at the wrong standard library (the symptom is
`No module named 'encodings'`). Run repo python with those cleared — the
Makefile already does this as `RUNPY`:

```
env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE /usr/bin/python3 host/verify_solution.py 0x4e708 16
```

## Standalone solution verifier

Outside the Makefile:

```
python3 host/verify_solution.py <nonce-hex> <difficulty-bits>
```

e.g. `python3 host/verify_solution.py 0x4e708 16`. The pure-Python
re-derivation takes minutes per hash at these parameters; for a fast
check, `cpu/verify_avx2 fold <nonce-hex>` computes the same 32-bit fold
in ~12 ms (and is itself proven bit-exact against the spec by
`make prove`).
