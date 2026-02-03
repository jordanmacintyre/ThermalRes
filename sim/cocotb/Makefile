# Makefile for ThermalRes cocotb co-simulation
#
# This Makefile uses cocotb to drive the RTL link_monitor simulation
# with Python plant models providing the analog domain.
#
# Usage:
#   make                    # Run default test (test_closed_loop_simulation)
#   make test-all           # Run all tests
#   make TESTCASE=test_reset  # Run specific test
#   DUMP_WAVES=1 make       # Generate VCD waveform
#   make waves              # Open waveforms in GTKWave
#   make clean              # Clean build artifacts

# Simulator selection (default: Verilator, can also use Icarus)
SIM ?= verilator
TOPLEVEL_LANG = verilog

# Top-level module name
TOPLEVEL = cosim_top

# RTL source files
RTL_DIR = $(shell pwd)/../../rtl
VERILOG_SOURCES = \
    $(RTL_DIR)/link_monitor.sv \
    $(RTL_DIR)/cosim_top.sv

# cocotb test module
MODULE = test_cosim

# Default test case (if not specified)
TESTCASE ?= test_closed_loop_simulation

# Verilator-specific options
ifeq ($(SIM),verilator)
    # Enable tracing for waveform generation
    EXTRA_ARGS += --trace --trace-structs

    # Verilator warnings to suppress (optional)
    # EXTRA_ARGS += -Wno-fatal

    # Pass parameters to RTL
    # EXTRA_ARGS += -GFAILS_TO_DOWN=4 -GPASSES_TO_UP=8
endif

# Icarus Verilog-specific options
ifeq ($(SIM),icarus)
    COMPILE_ARGS += -g2012
endif

# Enable waveform dumping if DUMP_WAVES is set
ifdef DUMP_WAVES
    ifeq ($(SIM),verilator)
        EXTRA_ARGS += --trace
    else
        PLUSARGS += +dump_waves=1
    endif
endif

# Reduce cocotb log verbosity
COCOTB_REDUCED_LOG_FMT = 1

# Include cocotb's makefile
include $(shell cocotb-config --makefiles)/Makefile.sim

# Custom targets

.PHONY: test-all test-reset test-open-loop test-closed-loop test-transitions clean-all waves

# Run all tests
test-all:
	$(MAKE) TESTCASE=test_reset
	$(MAKE) TESTCASE=test_open_loop_simulation
	$(MAKE) TESTCASE=test_closed_loop_simulation
	$(MAKE) TESTCASE=test_link_state_transitions
	$(MAKE) TESTCASE=test_artifact_generation

# Individual test shortcuts
test-reset:
	$(MAKE) TESTCASE=test_reset

test-open-loop:
	$(MAKE) TESTCASE=test_open_loop_simulation

test-closed-loop:
	$(MAKE) TESTCASE=test_closed_loop_simulation

test-transitions:
	$(MAKE) TESTCASE=test_link_state_transitions

# Open waveforms (requires GTKWave)
waves:
	@if [ -f dump.vcd ]; then \
		gtkwave dump.vcd &; \
	elif [ -f sim_build/dump.vcd ]; then \
		gtkwave sim_build/dump.vcd &; \
	else \
		echo "No VCD file found. Run with DUMP_WAVES=1 first."; \
		exit 1; \
	fi

# Extended clean
clean-all: clean
	rm -rf sim_build __pycache__ results.xml *.vcd
