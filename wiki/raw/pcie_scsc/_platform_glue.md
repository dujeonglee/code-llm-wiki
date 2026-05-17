---
title: Platform Notifiers & OSAL
kind: subsystem
covers:
  - pcie_scsc/osal/slsi_wakelock.h
  - pcie_scsc/panel_notifier.c
  - pcie_scsc/panel_notifier.h
  - pcie_scsc/ril_notifier.c
  - pcie_scsc/ril_notifier.h
  - pcie_scsc/slsi_cpuhp_monitor.c
  - pcie_scsc/slsi_cpuhp_monitor.h
  - pcie_scsc/porting_imx.h
last_synced_sha: null
last_synced: null
sources: []
---

# Platform Notifiers & OSAL

> Seed page (`kind: subsystem`) — `scripts/apply_layout.py`가 생성. Thin OS-abstraction / platform-event consumers: slsi_wakelock wraps pm_wakeup; panel_notifier reacts to LCD on/off (suspend hints); ril_notifier listens to modem state for WLAN/CP coexistence; slsi_cpuhp_monitor watches CPU hotplug to rebind NAPI; porting_imx.h is a platform-port shim. They share react-to-a-kernel-or-SoC-event-and-poke-the-driver as their reason for existing.

## Purpose
TODO

## Scope / boundaries
TODO

## Key flows
TODO

## Source files
- `pcie_scsc/osal/slsi_wakelock.h`
- `pcie_scsc/panel_notifier.c`
- `pcie_scsc/panel_notifier.h`
- `pcie_scsc/ril_notifier.c`
- `pcie_scsc/ril_notifier.h`
- `pcie_scsc/slsi_cpuhp_monitor.c`
- `pcie_scsc/slsi_cpuhp_monitor.h`
- `pcie_scsc/porting_imx.h`
