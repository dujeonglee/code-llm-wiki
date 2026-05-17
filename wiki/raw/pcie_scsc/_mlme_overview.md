---
title: MLME Control Path
kind: subsystem
covers:
  - pcie_scsc/mlme.c
  - pcie_scsc/mlme.h
  - pcie_scsc/mlme_nan.c
  - pcie_scsc/sap_mlme.c
  - pcie_scsc/sap_mlme.h
last_synced_sha: null
last_synced: null
sources: []
---

# MLME Control Path

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. MLME (MAC sub-layer management entity) issues FAPI req signals to firmware and dispatches cfm/ind responses via SAP_MLME. mlme.c/.h hold the request builders (slsi_mlme_*), sap_mlme.c is the rx demultiplexer for MLME-SAP signals, and mlme_nan.c specializes the same machinery for NAN. They share waiter/timeout infrastructure (sig_wait) and the fapi signal helpers, forming one tightly coupled control plane.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/mlme.c`
- `pcie_scsc/mlme.h`
- `pcie_scsc/mlme_nan.c`
- `pcie_scsc/sap_mlme.c`
- `pcie_scsc/sap_mlme.h`
