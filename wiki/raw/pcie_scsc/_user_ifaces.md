---
title: User Interfaces (procfs / ioctl / UDI / mmap)
kind: subsystem
covers:
  - pcie_scsc/procfs.c
  - pcie_scsc/procfs.h
  - pcie_scsc/ioctl.c
  - pcie_scsc/ioctl.h
  - pcie_scsc/udi.c
  - pcie_scsc/udi.h
  - pcie_scsc/unifiio.h
  - pcie_scsc/scsc_wlan_mmap.c
  - pcie_scsc/scsc_wlan_mmap.h
  - pcie_scsc/dpd_mmap.c
  - pcie_scsc/dpd_mmap.h
last_synced_sha: null
last_synced: null
sources: []
---

# User Interfaces (procfs / ioctl / UDI / mmap)

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. All non-cfg80211 entrypoints from userspace: procfs.c exposes status nodes; ioctl.c handles private SIOCDEVPRIVATE/Android wifi ioctls; udi.c is the unifiio character device for raw signal injection; the mmap files expose firmware shared memory (incl. host-DPD) to user space. They are sibling user-facing surfaces but otherwise independent of each other.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/procfs.c`
- `pcie_scsc/procfs.h`
- `pcie_scsc/ioctl.c`
- `pcie_scsc/ioctl.h`
- `pcie_scsc/udi.c`
- `pcie_scsc/udi.h`
- `pcie_scsc/unifiio.h`
- `pcie_scsc/scsc_wlan_mmap.c`
- `pcie_scsc/scsc_wlan_mmap.h`
- `pcie_scsc/dpd_mmap.c`
- `pcie_scsc/dpd_mmap.h`
