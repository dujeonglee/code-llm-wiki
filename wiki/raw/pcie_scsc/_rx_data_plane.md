---
title: RX Data Plane
kind: subsystem
covers:
  - pcie_scsc/rx.c
  - pcie_scsc/ba.c
  - pcie_scsc/ba.h
  - pcie_scsc/ba_replay.c
  - pcie_scsc/sap_ma.c
  - pcie_scsc/sap_ma.h
last_synced_sha: null
last_synced: null
sources: []
---

# RX Data Plane

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. Inbound data from firmware enters via SAP_MA (sap_ma.c), goes through rx.c (slsi_rx_*) which delivers to the netif, and is reordered/deduplicated by ba.c/ba_replay.c (BlockAck reorder buffer). They form one cohesive ingress pipeline for 802.11 data frames.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/rx.c`
- `pcie_scsc/ba.c`
- `pcie_scsc/ba.h`
- `pcie_scsc/ba_replay.c`
- `pcie_scsc/sap_ma.c`
- `pcie_scsc/sap_ma.h`
