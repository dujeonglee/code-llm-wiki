---
title: MIB Configuration
kind: subsystem
covers:
  - pcie_scsc/mib.c
  - pcie_scsc/mib.h
  - pcie_scsc/mib_text_convert.c
  - pcie_scsc/mib_text_convert.h
last_synced_sha: null
last_synced: null
sources: []
---

# MIB Configuration

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. mib.c implements get/set encoder/decoder for the firmware MIB (PSID/OID-style key-value store) used by mlme to push runtime config to firmware; mib_text_convert converts human-readable MIB text into the on-wire encoding. They are a self-contained codec subsystem.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/mib.c`
- `pcie_scsc/mib.h`
- `pcie_scsc/mib_text_convert.c`
- `pcie_scsc/mib_text_convert.h`
