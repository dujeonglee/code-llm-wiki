---
title: HIP Transport (Host Interface Protocol)
kind: subsystem
covers:
  - pcie_scsc/hip.c
  - pcie_scsc/hip.h
  - pcie_scsc/hip_bh.h
  - pcie_scsc/hip4.c
  - pcie_scsc/hip4.h
  - pcie_scsc/hip5.c
  - pcie_scsc/hip5.h
  - pcie_scsc/hip4_sampler.c
  - pcie_scsc/hip4_sampler.h
  - pcie_scsc/hip4_smapper.c
  - pcie_scsc/hip4_smapper.h
  - pcie_scsc/mbulk.c
  - pcie_scsc/mbulk.h
  - pcie_scsc/mbulk_def.h
last_synced_sha: null
last_synced: null
sources: []
---

# HIP Transport (Host Interface Protocol)

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. hip.c is the OS-facing HIP wrapper (slsi_hip_init/setup/start/transmit_frame); hip4/hip5 are the two alternative low-level shared-memory transports selected by CONFIG_SCSC_WLAN_HIP5; mbulk is the shared memory buffer pool both use; hip4_sampler/smapper are HIP4-side profiling/SMAPPER helpers. Together they implement the host<->firmware bus.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/hip.c`
- `pcie_scsc/hip.h`
- `pcie_scsc/hip_bh.h`
- `pcie_scsc/hip4.c`
- `pcie_scsc/hip4.h`
- `pcie_scsc/hip5.c`
- `pcie_scsc/hip5.h`
- `pcie_scsc/hip4_sampler.c`
- `pcie_scsc/hip4_sampler.h`
- `pcie_scsc/hip4_smapper.c`
- `pcie_scsc/hip4_smapper.h`
- `pcie_scsc/mbulk.c`
- `pcie_scsc/mbulk.h`
- `pcie_scsc/mbulk_def.h`
