---
title: Load Balance & NAPI Scheduling
kind: concept
covers:
  - pcie_scsc/load_manager.c
  - pcie_scsc/load_manager.h
last_synced_sha: null
last_synced: null
sources: []
---

# Load Balance & NAPI Scheduling

> Seed page (`kind: concept`) — `scripts/apply_layout.py`가 생성. load_manager (slsi_lbm_*) is the cross-cutting CPU/NAPI placement policy: hip4/hip5 register their BHs with it, traffic_monitor and cpuhp_monitor feed it events, and netif/tx ask it where to schedule. It exposes a contract used throughout the data plane and is conditionally compiled (CONFIG_SCSC_WLAN_LOAD_BALANCE_MANAGER), so a concept page is more useful than treating it as a subsystem.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/load_manager.c`
- `pcie_scsc/load_manager.h`
