# BRAM-ring
#
#   make               build everything and report your environment
#   make race          run the live mining race   (default target: 20 leading-zero bits)
#   make race DIFF=16  ... at a difficulty you choose; 16 = a ~2 min demo without an FPGA
#   make prove         check Python == C == Verilog == CUDA, bit-for-bit
#   BRAM_EPOCH=<seed> make prove   ... on another epoch seed (regenerates everything;
#                      the bounty's fresh-seed check -- use a scratch clone)
#   make clean
#
# Needs: python3 + a C compiler (always). iverilog for the RTL sim, cupy + an
# NVIDIA card for the GPU competitor, the Efinity toolchain + an FPGA board
# for real silicon -- all optional; `make` tells you what you have.
#
# Vendor toolchains (Efinity) hijack python via PYTHONHOME/PYTHONPATH; RUNPY
# clears them. If plain python3 is the wrong one: make PY=/usr/bin/python3

CC     ?= cc
CFLAGS ?= -O3 -march=native
OMP    ?= -fopenmp        # CPU competitors use every core; -fopenmp=off falls back to 1
PY     ?= python3
RUNPY   = env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(PY)
# a CuPy-capable python for the GPU competitor (e.g. a venv); empty = use PY.
#   make race GPU_PY=/path/to/venv/bin/python
GPU_PY ?=
GPY     = $(if $(GPU_PY),$(GPU_PY),$(PY))
# default race target (leading zero bits); override with: make race DIFF=16
# 20 bits ~= 1M hashes: ~15 min with only CPU+GPU racing (~2 kH/s), seconds with an FPGA.
DIFF   ?= 20

.PHONY: all gen bench check warmup race prove sim clean FORCE

all: bench warmup check

# ---- pre-compile the CUDA kernels so 'make race' starts fast (skipped if no GPU) ----
warmup: bench
	@env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) gpu/mine.py warmup >/dev/null 2>&1 \
	  && echo "warmed up GPU kernels (make race will start fast)" || true

# ---- generate every derived file from spec.py (only when spec/generator/seed change) ----
# The generated files (vectors.txt, cpu/tables.h, fpga/ring.v, ...) are shared by
# every seed, so a marker records which seed they currently hold; its mtime moves
# only when BRAM_EPOCH changes, and that is what triggers regeneration.
BRAM_EPOCH ?= epoch0
export BRAM_EPOCH
GEN_STAMP = .gen.stamp
GEN_EPOCH = .gen.epoch
$(GEN_EPOCH): FORCE
	@[ "$$(cat $@ 2>/dev/null)" = "$(BRAM_EPOCH)" ] || echo "$(BRAM_EPOCH)" > $@
$(GEN_STAMP): spec.py generate.py $(GEN_EPOCH)
	@$(RUNPY) generate.py
	@touch $@
gen: $(GEN_STAMP)
FORCE:

# ---- build the CPU competitors (only when their sources or the tables change) ----
bench: cpu/simple cpu/verify_avx2

cpu/simple: cpu/simple.c cpu/sha256.c cpu/sha256.h $(GEN_STAMP)
	@$(CC) $(CFLAGS) $(OMP) -o $@ cpu/simple.c cpu/sha256.c && echo "built cpu/simple"

# the champion CPU attack: AVX2 lane-parallel, scalar RMW (see the file header)
cpu/verify_avx2: cpu/verify_avx2.c cpu/sha256.c cpu/sha256.h $(GEN_STAMP)
	@$(CC) $(CFLAGS) $(OMP) -o $@ cpu/verify_avx2.c cpu/sha256.c && echo "built cpu/verify_avx2"

# ---- report what's available (never fails the build) ----
check:
	@echo ""
	@echo "environment check (all optional pieces -- the race runs with whatever you have):"
	@command -v iverilog >/dev/null 2>&1 \
	  && echo "  [ok]  iverilog        RTL simulation available (make prove / make sim)" \
	  || echo "  [--]  iverilog        missing: 'make sim' skipped  (apt install iverilog)"
	@env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) -c "import cupy" >/dev/null 2>&1 \
	  && echo "  [ok]  GPU (cupy)      $$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1) will race" \
	  || echo "  [--]  GPU (cupy)      not in GPU_PY: race runs without GPU  (set GPU_PY=/venv/bin/python)"
	@{ [ -n "$$EFINITY_HOME" ] || ls -d $$HOME/efinity* >/dev/null 2>&1; } \
	  && echo "  [ok]  Efinity         toolchain found: you can build the FPGA bitstream" \
	  || echo "  [--]  Efinity         not found: FPGA build unavailable (not needed for the race)"
	@{ lsusb 2>/dev/null | grep -qiE "0403:601[01]|0403:6043|efinix|future technology"; } \
	  && echo "  [ok]  FPGA board      a compatible USB device is plugged in" \
	  || echo "  [--]  FPGA board      not detected: only needed to mine on real silicon"
	@echo ""
	@echo "ready.  race:  make race        (target=$(DIFF) leading-zero bits; override with DIFF=)"

# ---- run the live race ----
race: bench
	@RACE_GPU_PY="$(GPU_PY)" $(RUNPY) race.py --target $(DIFF)

# ---- prove every implementation is bit-exact against the golden vectors ----
#
# Every leg either PASSES or FAILS THE MAKE. A leg that cannot run on this
# box is reported by name in the final summary as NOT CHECKED -- never
# silently folded into a success line. Scratch files (the compiled sim,
# the NOT-CHECKED markers) live inside this clone, not in /tmp, so two
# clones proving on one machine cannot clobber each other. (An earlier version printed
# "ALL ... BIT-EXACT" even when the RTL leg had printed FAIL and when the
# CUDA leg had not run at all. Red-proof any change here: break an
# implementation on purpose and confirm `make prove` exits non-zero.)
prove: bench
	@rm -f .prove_skip_rtl .prove_skip_gpu      # never inherit a stale marker
	@cd cpu && ./simple
	@cd cpu && ./verify_avx2
	@cd cpu && ./verify_avx2 vectors | $(RUNPY) ../host/check_vectors.py
	@cd cpu && ./simple avalanche
	@if command -v iverilog >/dev/null 2>&1; then \
	  cd fpga && iverilog -o tb_vectors.vvp tb_vectors.v ring.v efx_ram10_model.v && vvp tb_vectors.vvp \
	    || { echo "RTL LEG FAILED"; exit 1; }; \
	else echo RTL > .prove_skip_rtl; echo "!! iverilog missing -- RTL leg NOT CHECKED"; fi
	@if env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) -c "import cupy" >/dev/null 2>&1; then \
	  env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) gpu/mine.py \
	    && env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) gpu/mine.py vectors \
	       | env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE $(GPY) host/check_vectors.py \
	    || { echo "CUDA LEG FAILED"; exit 1; }; \
	else echo CUDA > .prove_skip_gpu; echo "!! cupy/NVIDIA GPU missing -- CUDA leg NOT CHECKED (cupy in a venv? re-run: make prove GPU_PY=/path/to/venv/bin/python)"; fi
	@echo ""
	@skipped=""; \
	 [ -f .prove_skip_rtl ] && skipped="$$skipped RTL"; \
	 [ -f .prove_skip_gpu ] && skipped="$$skipped CUDA"; \
	 rm -f .prove_skip_rtl .prove_skip_gpu; \
	 if [ -n "$$skipped" ]; then \
	   echo "PYTHON + C LEGS BIT-EXACT ON THE GOLDEN VECTORS"; \
	   echo "NOT CHECKED ON THIS BOX:$$skipped  (install iverilog / cupy to check them too)"; \
	 else \
	   echo "ALL FOUR IMPLEMENTATIONS (Python, C, Verilog, CUDA) BIT-EXACT ON THE GOLDEN VECTORS"; \
	 fi

sim: gen
	cd fpga && iverilog -o tb_vectors.vvp tb_vectors.v ring.v efx_ram10_model.v && vvp tb_vectors.vvp

clean:
	rm -f cpu/simple cpu/verify_avx2 cpu/*.o .gen.stamp .gen.epoch fpga/tb_vectors.vvp .prove_skip_rtl .prove_skip_gpu
