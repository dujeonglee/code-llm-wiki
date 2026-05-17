---
title: Local Packet Capture (LPC)
kind: concept
covers:
  - pcie_scsc/local_packet_capture.c
  - pcie_scsc/local_packet_capture.h
last_synced_sha: null
last_synced: null
sources: []
---

# Local Packet Capture (LPC)

> Seed page (`kind: concept`) — `scripts/apply_layout.py`가 생성. Optional pcap-style intercept enabled by CONFIG_SLSI_WLAN_LPC. It taps both tx.c/txbp.c egress and rx.c ingress, builds radiotap frames, and ships them to a monitor netdev. Cross-cuts the data plane without owning a pipeline of its own.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/local_packet_capture.c`
- `pcie_scsc/local_packet_capture.h`
