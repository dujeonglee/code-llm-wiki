---
title: TX Data Plane
kind: subsystem
covers:
  - pcie_scsc/tx.c
  - pcie_scsc/tx.h
  - pcie_scsc/tx_api.h
  - pcie_scsc/txbp.c
  - pcie_scsc/txbp.h
  - pcie_scsc/scsc_wifi_fcq.c
  - pcie_scsc/scsc_wifi_fcq.h
  - pcie_scsc/traffic_monitor.c
  - pcie_scsc/traffic_monitor.h
last_synced_sha: null
last_synced: null
sources: []
---

# TX Data Plane

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. Two mutually-exclusive TX implementations live behind CONFIG_SCSC_WLAN_TX_API: legacy tx.c + scsc_wifi_fcq (per-peer flow-controlled queues) vs. the newer txbp.c (TX back-pressure/zero-copy path) exposed by tx_api.h. traffic_monitor feeds AC/throughput signals consumed by both. Together they form the host-side data path before HIP.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/tx.c`
- `pcie_scsc/tx.h`
- `pcie_scsc/tx_api.h`
- `pcie_scsc/txbp.c`
- `pcie_scsc/txbp.h`
- `pcie_scsc/scsc_wifi_fcq.c`
- `pcie_scsc/scsc_wifi_fcq.h`
- `pcie_scsc/traffic_monitor.c`
- `pcie_scsc/traffic_monitor.h`
