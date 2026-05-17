---
title: Netdev / VIF Lifecycle
kind: subsystem
covers:
  - pcie_scsc/netif.c
  - pcie_scsc/netif.h
  - pcie_scsc/if_vif.c
  - pcie_scsc/cfg80211_ops.c
  - pcie_scsc/cfg80211_ops.h
last_synced_sha: null
last_synced: null
sources: []
---

# Netdev / VIF Lifecycle

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. cfg80211_ops.c registers the wiphy callbacks (scan/connect/AP/etc.) and is the entry point from the kernel's cfg80211 layer; netif.c/.h and if_vif.c implement struct net_device + netdev_vif creation, queue mapping, and lifecycle. They cooperate to materialize each virtual interface (STA/AP/P2P/NAN) on top of the firmware.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/netif.c`
- `pcie_scsc/netif.h`
- `pcie_scsc/if_vif.c`
- `pcie_scsc/cfg80211_ops.c`
- `pcie_scsc/cfg80211_ops.h`
