---
title: Device Init & Service Management
kind: subsystem
covers:
  - pcie_scsc/dev.c
  - pcie_scsc/dev.h
  - pcie_scsc/cm_if.c
  - pcie_scsc/scsc_wifi_cm_if.h
  - pcie_scsc/mgt.c
  - pcie_scsc/mgt.h
  - pcie_scsc/hanged_record.h
last_synced_sha: null
last_synced: null
sources: []
---

# Device Init & Service Management

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. dev.c is the module entry that builds slsi_dev; cm_if.c is the WLBT core-manager glue that opens/closes the wlan service with the chip subsystem; mgt.c centralizes slsi_dev_attach/detach, start/stop, recovery, and hanged-record handling. Together they own the chip-level lifecycle that everything else depends on.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/dev.c`
- `pcie_scsc/dev.h`
- `pcie_scsc/cm_if.c`
- `pcie_scsc/scsc_wifi_cm_if.h`
- `pcie_scsc/mgt.c`
- `pcie_scsc/mgt.h`
- `pcie_scsc/hanged_record.h`
