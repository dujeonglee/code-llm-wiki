---
title: Regulatory & Channel Management
kind: subsystem
covers:
  - pcie_scsc/reg_info.c
  - pcie_scsc/reg_info.h
  - pcie_scsc/channels.h
  - pcie_scsc/cac.c
  - pcie_scsc/cac.h
  - pcie_scsc/conc_modes.c
last_synced_sha: null
last_synced: null
sources: []
---

# Regulatory & Channel Management

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. reg_info.c maintains the per-country/regdomain table that filters channel/power, channels.h declares the canonical band tables they index, cac.c implements DFS/CAC (Channel Availability Check) state, and conc_modes.c arbitrates concurrent-interface channel selection. They jointly police what RF parameters are legal at any moment.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/reg_info.c`
- `pcie_scsc/reg_info.h`
- `pcie_scsc/channels.h`
- `pcie_scsc/cac.c`
- `pcie_scsc/cac.h`
- `pcie_scsc/conc_modes.c`
