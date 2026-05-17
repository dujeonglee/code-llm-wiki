---
title: FAPI Signaling Protocol
kind: concept
covers:
  - pcie_scsc/fapi.h
last_synced_sha: null
last_synced: null
sources: []
---

# FAPI Signaling Protocol

> Seed page (`kind: concept`) — `scripts/apply_layout.py`가 생성. fapi.h is the auto-generated wire format describing every host<->firmware signal (FAPI_SIG_TYPE_REQ/CFM/RES/IND, FAPI_SAP_TYPE_MA/MLME/DEBUG/TEST, all IE/attribute constants). It is included by ~25 .c files spanning MLME, SAPs, HIP, debug, and vendor code; it owns no implementation files itself, so it is a contract rather than a subsystem.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/fapi.h`
