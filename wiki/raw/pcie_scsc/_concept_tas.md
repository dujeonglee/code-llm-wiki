---
title: Transmit Adaptive Control (TAS family)
kind: concept
covers:
  - pcie_scsc/dctas.c
  - pcie_scsc/dctas.h
last_synced_sha: null
last_synced: null
sources: []
---

# Transmit Adaptive Control (TAS family)

> Seed page (`kind: concept`) — `scripts/apply_layout.py`가 생성. TAS / ICTAS / DCTAS are three mutually-exclusive Tx-power adaptive-scaling schemes (dev.h enforces only-one-TAS-configuration via #error). dctas.c is the in-tree implementation; the concept page should document the FAPI signaling and policy choice rather than just the one file, because the same SAR/back-off contract is consumed by mlme.c, mgt.c, and the HIP layers when applying per-band power caps.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/dctas.c`
- `pcie_scsc/dctas.h`
