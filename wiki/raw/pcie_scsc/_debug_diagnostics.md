---
title: Debug / Trace / Crash Diagnostics
kind: subsystem
covers:
  - pcie_scsc/debug.c
  - pcie_scsc/debug.h
  - pcie_scsc/debug_frame.c
  - pcie_scsc/log_clients.c
  - pcie_scsc/log_clients.h
  - pcie_scsc/log2us.c
  - pcie_scsc/log2us.h
  - pcie_scsc/fw_test.c
  - pcie_scsc/fw_test.h
  - pcie_scsc/slsi_tracepoint_debug.c
  - pcie_scsc/slsi_tracepoint_debug.h
last_synced_sha: null
last_synced: null
sources: []
---

# Debug / Trace / Crash Diagnostics

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. debug.c/debug_frame.c provide the logging macros and on-the-fly frame decoders; log_clients is the pub-sub registry that lets udi/sap_dbg subscribe to in/out signals; log2us emits Android event log lines from connection events; fw_test injects synthetic signals for firmware-less testing; slsi_tracepoint_debug wires ftrace tracepoints. Together they form the observability stack.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/debug.c`
- `pcie_scsc/debug.h`
- `pcie_scsc/debug_frame.c`
- `pcie_scsc/log_clients.c`
- `pcie_scsc/log_clients.h`
- `pcie_scsc/log2us.c`
- `pcie_scsc/log2us.h`
- `pcie_scsc/fw_test.c`
- `pcie_scsc/fw_test.h`
- `pcie_scsc/slsi_tracepoint_debug.c`
- `pcie_scsc/slsi_tracepoint_debug.h`
