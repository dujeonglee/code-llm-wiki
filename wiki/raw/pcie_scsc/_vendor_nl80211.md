---
title: Vendor / NL80211 Surface
kind: subsystem
covers:
  - pcie_scsc/nl80211_vendor.c
  - pcie_scsc/nl80211_vendor.h
  - pcie_scsc/nl80211_vendor_nan.c
  - pcie_scsc/nl80211_vendor_nan.h
  - pcie_scsc/lls.c
  - pcie_scsc/lls.h
last_synced_sha: null
last_synced: null
sources: []
---

# Vendor / NL80211 Surface

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. nl80211_vendor.c registers the Samsung/Google vendor subcmds (GScan, RTT, link-layer-stats, key-mgmt-offload, etc.) on top of cfg80211; nl80211_vendor_nan.c specializes the vendor interface for NAN discovery/data-path; lls.c is the Link-Layer-Stats backing data store the vendor cmds report. They share the vendor-cmd dispatch and reply marshalling.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/nl80211_vendor.c`
- `pcie_scsc/nl80211_vendor.h`
- `pcie_scsc/nl80211_vendor_nan.c`
- `pcie_scsc/nl80211_vendor_nan.h`
- `pcie_scsc/lls.c`
- `pcie_scsc/lls.h`
