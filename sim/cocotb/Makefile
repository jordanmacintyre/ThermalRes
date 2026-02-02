# Makefile for cocotb + Verilator simulation

# Simulator
SIM ?= verilator

# Top module
TOPLEVEL = top

# RTL source files
VERILOG_SOURCES = $(shell pwd)/../../rtl/link_monitor.sv $(shell pwd)/../../rtl/top.sv

# Python test file
MODULE = test_link_monitor

# Verilator flags
EXTRA_ARGS += --trace --trace-structs

# cocotb configuration
COCOTB_REDUCED_LOG_FMT = 1

include $(shell cocotb-config --makefiles)/Makefile.sim
