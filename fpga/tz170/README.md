# fpga/tz170/results_* — what each directory is

All are STA/fit characterization builds of ONE ring on the Tz170J484 — no
board, `build_tz170.sh build`, numbers read from `*.timing.rpt`. Only the
`2steplag` directories (and the dated rebuild) are the **shipped RTL** — the
v3 two-step DSP lag that `generate.py` writes into `fpga/ring.v`. The rest are
earlier spins of the design, kept for the record.

| directory | RTL | grade @ target | Fmax | ships |
|---|---|---|---|---|
| `results_c2_t250_2steplag_s1` | shipped | C2 (production) @ 250 | 199.8 MHz | timing |
| `results_c2_t250_2steplag_s2` | shipped | C2 @ 250 | **201.8 MHz** (the README figure) | timing |
| `results_c2_t250_2steplag_rebuild-2026-10-04` | shipped, rebuilt from this clone (seed 2) | C2 @ 250 | 206.4 MHz | timing, place, res — utilisation **104,190 / 172,800 XLR (60.3%), 768 / 1280 RAM (60%), 128 / 640 DSP** |
| `results_c3_t250_2steplag_s1`, `_s2` | shipped | C3 (fast) @ 250 | 227.0 / 222.8 MHz | timing |
| `results_c2_t250_v3respec1_s1`, `results_c3_t250_v3respec_s1`, `_s2` | earlier spin: one-step DSP lag | C2 / C3 | 191.3 / 212.0 / 213.9 MHz | timing (+ place/hier for the C3 s1) |
| `results_c3_t200_s1`, `results_c3_t250_s1` | earlier spin: combinational DSP, no lag | C3 | 159.6 / 161.4 MHz | timing, place, res |
| `results_c3_t250_ptaps0_probe` | probe: `PTAPS=0`, no DSP taps at all | C3 | 222.2 MHz | timing, place |

Place-and-route is not bit-reproducible: the same RTL, seed and tool
(db 20252999) closed at 201.8 MHz in August and 206.4 MHz on 2026-10-04. Read
the figures as "clears 200 MHz on the production grade", not as exact values.
`STA-closed` throughout the README means exactly this: Efinity's static timing
analysis with the vendor timing model (`build_tz170.sh` notes how those tables
are derived), not a silicon measurement.
