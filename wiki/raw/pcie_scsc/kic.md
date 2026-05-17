---
title: kic — SLSI Wi-Fi KIC Recovery Trigger
kind: entity
covers:
  - pcie_scsc/kic.c
  - pcie_scsc/kic.h
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-17T01:19:17Z"
sources:
  - pcie_scsc/kic.c
  - pcie_scsc/kic.h
  - pcie_scsc/dev.c#L30-L32
  - pcie_scsc/dev.c#L679-L681
  - pcie_scsc/dev.c#L836-L837
  - pcie_scsc/dev.h#L1904
  - pcie_scsc/dev.h#L1923
  - pcie_scsc/dev.h#L1667-L1671
  - pcie_scsc/cm_if.c#L780-L813
  - pcie_scsc/kunit/kunit-mock-kic.h
---

# kic

> Minimal glue module that registers a KIC (Kernel Integration Component) recovery callback into the external KIC framework. The framework can invoke `trigger_recovery` to deliberately induce a firmware panic or host-side service-failure event for test and diagnostics purposes. Gated behind `CONFIG_SCSC_WLAN_KIC_OPS`.

## Purpose

The KIC subsystem provides a **controlled crash-and-recovery injection** interface used during driver bring-up, CI validation, and field diagnostics. Rather than implementing recovery logic itself, `kic.c` exposes a single `trigger_recovery` operation that the external KIC framework can call at runtime.

Two recovery modes are supported:

| Recovery type | What happens |
|---|---|
| `slsi_kic_test_recovery_type_subsystem_panic` | Calls `scsc_service_force_panic(sdev->service)` to force the Wi-Fi firmware into a panic state. |
| `slsi_kic_test_recovery_type_emulate_firmware_no_response` | Calls `slsi_sm_service_failed(sdev, reason, false)` to transition the CM_IF state machine into `BLOCKED`, mimicking a firmware death scenario. |

Modes `slsi_kic_test_recovery_type_watch_dog` and `slsi_kic_test_recovery_type_chip_crash` are not yet implemented (return `-EINVAL`).

The trigger is **guarded** by `sdev->device_state`: it only fires when the device is fully started (`SLSI_DEVICE_STATE_STARTED`), returning `-EAGAIN` otherwise.

## Key data structures

### `struct slsi_kic_wifi_ops`

Defined in the external header `<pcie_scsc/kic/slsi_kic_wifi.h>`. The driver instantiates a static instance:

```c
static struct slsi_kic_wifi_ops kic_ops = {
    .trigger_recovery = wifi_kic_trigger_recovery,
};
```

The framework holds a pointer to this ops struct and invokes callbacks through it.

### `enum slsi_kic_test_recovery_type`

Also from `<pcie_scsc/kic/slsi_kic_wifi.h>`. Known values:

- `slsi_kic_test_recovery_type_subsystem_panic`
- `slsi_kic_test_recovery_type_emulate_firmware_no_response`
- `slsi_kic_test_recovery_type_watch_dog`
- `slsi_kic_test_recovery_type_chip_crash`

## Public API

### `int wifi_kic_register(struct slsi_dev *sdev)`

Registered in `kic.h`. Called from `slsi_dev_start()` in `dev.c` during device bring-up. Stores the `sdev` pointer as private data in the KIC framework and registers the `kic_ops` table. Returns `< 0` on failure (logged but not fatal — the driver continues without KIC).

```c
int wifi_kic_register(struct slsi_dev *sdev)
{
    return slsi_kic_wifi_ops_register((void *)sdev, &kic_ops);
}
```

### `void wifi_kic_unregister(void)`

Registered in `kic.h`. Called from `slsi_dev_stop()` in `dev.c` during teardown. Unregisters the ops table from the framework.

```c
void wifi_kic_unregister(void)
{
    return slsi_kic_wifi_ops_unregister(&kic_ops);
}
```

## Internal flow

```mermaid
sequenceDiagram
    participant FW as KIC Framework
    participant kic as kic.c
    participant dev as slsi_dev
    participant svc as scsc_service
    participant cmif as CM_IF state machine

    FW->>kic: ops->trigger_recovery(priv, type)
    kic->>kic: guard: sdev->device_state == STARTED?
    alt subsystem_panic
        kic->>svc: scsc_service_force_panic(sdev->service)
        svc-->>kic: firmware panics
    else emulate_firmware_no_response
        kic->>cmif: slsi_sm_service_failed(sdev, reason, false)
        cmif->>cmif: state -> BLOCKED
        cmif->>svc: scsc_mx_service_service_failed(...)
    else watch_dog / chip_crash
        kic-->>FW: -EINVAL (not implemented)
    end
