---
title: SAP Dispatch (Service Access Points)
kind: subsystem
covers:
  - pcie_scsc/sap.h
  - pcie_scsc/sap_mlme.c
  - pcie_scsc/sap_mlme.h
  - pcie_scsc/sap_ma.c
  - pcie_scsc/sap_ma.h
  - pcie_scsc/sap_dbg.c
  - pcie_scsc/sap_dbg.h
  - pcie_scsc/sap_test.c
  - pcie_scsc/sap_test.h
last_synced_sha: null
last_synced: null
sources: []
---

# SAP Dispatch (Service Access Points)

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. sap.h defines the sap_api contract (sap_class, sap_handler, sap_txdone, sap_notifier) and the four classes MLME/MA/DBG/TST. Each sap_*.c registers a sap_api with slsi_hip_sap_register and demuxes inbound skbs for its class. They share the same dispatch contract and are the boundary between HIP transport and upper-layer code.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/sap.h`
- `pcie_scsc/sap_mlme.c`
- `pcie_scsc/sap_mlme.h`
- `pcie_scsc/sap_ma.c`
- `pcie_scsc/sap_ma.h`
- `pcie_scsc/sap_dbg.c`
- `pcie_scsc/sap_dbg.h`
- `pcie_scsc/sap_test.c`
- `pcie_scsc/sap_test.h`
