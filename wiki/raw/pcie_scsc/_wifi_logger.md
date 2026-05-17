---
title: WiFi Logger Ring Subsystem
kind: subsystem
covers:
  - pcie_scsc/scsc_wifilogger.h
  - pcie_scsc/scsc_wifilogger_api.c
  - pcie_scsc/scsc_wifilogger_core.c
  - pcie_scsc/scsc_wifilogger_core.h
  - pcie_scsc/scsc_wifilogger_internal.c
  - pcie_scsc/scsc_wifilogger_internal.h
  - pcie_scsc/scsc_wifilogger_module.c
  - pcie_scsc/scsc_wifilogger_module.h
  - pcie_scsc/scsc_wifilogger_debugfs.c
  - pcie_scsc/scsc_wifilogger_debugfs.h
  - pcie_scsc/scsc_wifilogger_rings.h
  - pcie_scsc/scsc_wifilogger_types.h
  - pcie_scsc/scsc_wifilogger_ring_connectivity.c
  - pcie_scsc/scsc_wifilogger_ring_connectivity.h
  - pcie_scsc/scsc_wifilogger_ring_connectivity_api.h
  - pcie_scsc/scsc_wifilogger_ring_pktfate.c
  - pcie_scsc/scsc_wifilogger_ring_pktfate.h
  - pcie_scsc/scsc_wifilogger_ring_pktfate_api.h
  - pcie_scsc/scsc_wifilogger_ring_wakelock.c
  - pcie_scsc/scsc_wifilogger_ring_wakelock.h
  - pcie_scsc/scsc_wifilogger_ring_wakelock_api.h
  - pcie_scsc/scsc_wifilogger_ring_test.c
  - pcie_scsc/scsc_wifilogger_ring_test.h
last_synced_sha: null
last_synced: null
sources: []
---

# WiFi Logger Ring Subsystem

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. Builds as its own kernel module (scsc_wifilogger.ko in the Makefile). Core/api/internal/module own the ring-buffer infrastructure and the Android wifi-hal-compatible API; ring_connectivity/pktfate/wakelock/test are concrete ring instances. All files share the scsc_wlc_* internal API and ring registry.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/scsc_wifilogger.h`
- `pcie_scsc/scsc_wifilogger_api.c`
- `pcie_scsc/scsc_wifilogger_core.c`
- `pcie_scsc/scsc_wifilogger_core.h`
- `pcie_scsc/scsc_wifilogger_internal.c`
- `pcie_scsc/scsc_wifilogger_internal.h`
- `pcie_scsc/scsc_wifilogger_module.c`
- `pcie_scsc/scsc_wifilogger_module.h`
- `pcie_scsc/scsc_wifilogger_debugfs.c`
- `pcie_scsc/scsc_wifilogger_debugfs.h`
- `pcie_scsc/scsc_wifilogger_rings.h`
- `pcie_scsc/scsc_wifilogger_types.h`
- `pcie_scsc/scsc_wifilogger_ring_connectivity.c`
- `pcie_scsc/scsc_wifilogger_ring_connectivity.h`
- `pcie_scsc/scsc_wifilogger_ring_connectivity_api.h`
- `pcie_scsc/scsc_wifilogger_ring_pktfate.c`
- `pcie_scsc/scsc_wifilogger_ring_pktfate.h`
- `pcie_scsc/scsc_wifilogger_ring_pktfate_api.h`
- `pcie_scsc/scsc_wifilogger_ring_wakelock.c`
- `pcie_scsc/scsc_wifilogger_ring_wakelock.h`
- `pcie_scsc/scsc_wifilogger_ring_wakelock_api.h`
- `pcie_scsc/scsc_wifilogger_ring_test.c`
- `pcie_scsc/scsc_wifilogger_ring_test.h`
