---
title: Virtual Interface & Peer Model
kind: concept
covers:
  - pcie_scsc/dev.h
  - pcie_scsc/const.h
last_synced_sha: null
last_synced: null
sources: []
---

# Virtual Interface & Peer Model

> Seed page (`kind: concept`) — `scripts/apply_layout.py`가 생성. struct slsi_dev / netdev_vif / slsi_peer / slsi_vif_sta etc. are declared in dev.h and the associated enums in const.h; almost every .c file dereferences them. They define the cross-cutting state model (per-radio, per-VIF, per-peer) that the rest of the driver mutates — not a runnable subsystem but the central data-model contract.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/dev.h`
- `pcie_scsc/const.h`
