# =============================================================================
# hw/rtl/Makefile — B3 RTL Tuning build targets (M5+ only)
#
# All targets are no-ops or placeholders in M1-M4. They become live when B3
# is triggered (see docs/decisions/0004_b3_m5_trigger.md).
# =============================================================================

SV_SRCS := $(wildcard src/*.sv)
TB_PY   := $(wildcard tb/tb_*.py)

VERILATOR ?= verilator
PYTHON    ?= python

.PHONY: help rtl_lint rtl_sim rtl_synth_dry clean

help:
	@echo "B3 RTL Tuning Makefile (M5+ targets)"
	@echo "  make rtl_lint       -- verilator --lint-only on every src/*.sv"
	@echo "  make rtl_sim        -- cocotb run for every tb/tb_*.py (M5 W2+)"
	@echo "  make rtl_synth_dry  -- vivado RTL-only synth smoke (M5 W3+)"
	@echo "  make clean          -- rm sim_build_*/"

# Static lint — checks SV syntax + unused signals + width mismatch.
# Works without simulation; safe to wire into CI from M1 W5 onward.
rtl_lint:
	@for sv in $(SV_SRCS); do \
	    echo "[lint] $$sv"; \
	    $(VERILATOR) --lint-only -Wall $$sv || exit 1; \
	done

# cocotb + Verilator simulation. Placeholder until M5 W2 when tb_*.py land.
rtl_sim:
	@if [ -z "$(TB_PY)" ]; then \
	    echo "[rtl_sim] no testbenches yet (M5 W2 target)"; \
	    exit 0; \
	fi
	@for tb in $(TB_PY); do \
	    echo "[sim] $$tb"; \
	    $(PYTHON) $$tb || exit 1; \
	done

# Vivado RTL-only smoke synth. Confirms each .sv is synthesisable on Z-7020
# without doing place-and-route. Placeholder until M5 W3.
rtl_synth_dry:
	@echo "[rtl_synth_dry] M5 W3 placeholder — will invoke vivado -mode batch"

clean:
	rm -rf sim_build_* obj_dir
