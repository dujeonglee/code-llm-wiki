---
title: cm_if — Chip Manager Interface
kind: entity
covers:
  - pcie_scsc/cm_if.c
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T04:24:15Z"
sources:
  - pcie_scsc/cm_if.c
  - pcie_scsc/scsc_wifi_cm_if.h
  - pcie_scsc/dev.h#L1901
  - pcie_scsc/mgt.h#L327-L330
  - pcie_scsc/mgt.c#L1181-L1256
---

# cm_if — Chip Manager Interface

> Core lifecycle controller for the SCSC WLAN service: probes, opens, starts, stops, closes, and recovers the firmware service on the PCIe Maxwell chip. Implements a state machine with a `blocking_notifier` fan-out so other subsystems ([[raw/pcie_scsc/mgt|mgt]], [[raw/pcie_scsc/hip|hip]], [[raw/pcie_scsc/mlme|mlme]]) react to service transitions.

## Purpose

`cm_if` sits between the Maxwell manager (`scsc_mx`) and the upper driver layers. It:

1. **Registers as a Maxwell module client** (`struct scsc_mx_module_client wlan_driver`), receiving `probe`/`remove` callbacks when the firmware service comes and goes.
2. **Manages the service lifecycle** — a 9-state FSM tracked in `sdev->cm_if.cm_if_state` — protecting every transition with `slsi_start_mutex`.
3. **Handles firmware failures** — classifies errors into *reset levels* (1–8), dispatches notifications via a `blocking_notifier_head`, and initiates recovery (stop → close → open → start) when the firmware panics.
4. **Exposes a blocking notifier chain** so [[raw/pcie_scsc/hip|hip]] and other modules receive `SCSC_WIFI_STOP`, `SCSC_WIFI_FAILURE_RESET`, `SCSC_WIFI_CHIP_READY`, `SCSC_WIFI_SUSPEND`, and `SCSC_WIFI_RESUME` events.
5. **Optional runtime-PM sysfs** (`/sys/wifi/runtime_pm`) for controlling the firmware power-management timer.

## Key data structures

### State machine

The 9 states live in `enum scsc_wifi_cm_if_state` (`scsc_wifi_cm_if.h`):

```c
enum scsc_wifi_cm_if_state {
    SCSC_WIFI_CM_IF_STATE_STOPPED,
    SCSC_WIFI_CM_IF_STATE_PROBING,
    SCSC_WIFI_CM_IF_STATE_PROBED,
    SCSC_WIFI_CM_IF_STATE_STARTING,
    SCSC_WIFI_CM_IF_STATE_STARTED,
    SCSC_WIFI_CM_IF_STATE_STOPPING,
    SCSC_WIFI_CM_IF_STATE_REMOVING,
    SCSC_WIFI_CM_IF_STATE_REMOVED,
    SCSC_WIFI_CM_IF_STATE_BLOCKED
};
```

Typical lifecycle: `STOPPED → PROBING → PROBED → STARTING → STARTED` on power-on, and the reverse on teardown. `BLOCKED` is set during failures; `REMOVING`/`REMOVED` during detach.

### `struct scsc_wifi_cm_if` (embedded in `struct slsi_dev`)

Defined in `scsc_wifi_cm_if.h`, embedded at `sdev->cm_if`:

| Member | Type | Role |
|---|---|---|
| `cm_if_state` | `atomic_t` | Current FSM state |
| `recovery_state` | `int` | Sub-state during recovery (see below) |
| `reset_level` | `atomic_t` | Firmware error severity (1–8; 8 = panic) |
| `cm_if_mutex` | `struct mutex` | Per-operation mutex |
| `kref` | `struct kref` | Reference counting |

### Recovery sub-states

Defined in `mgt.h`:

```c
#define SLSI_RECOVERY_SERVICE_STARTED   0
#define SLSI_RECOVERY_SERVICE_STOPPED   1
#define SLSI_RECOVERY_SERVICE_CLOSED    2
#define SLSI_RECOVERY_SERVICE_OPENED    3
```

### Notifier events

```c
enum scsc_wifi_cm_if_notifier {
    SCSC_WIFI_STOP,
    SCSC_WIFI_FAILURE_RESET,
    SCSC_WIFI_SUSPEND,
    SCSC_WIFI_RESUME,
    SCSC_WIFI_SUBSYSTEM_RESET,
    SCSC_WIFI_CHIP_READY,
    SCSC_MAX_NOTIFIER
};
```

Delivered via `slsi_wlan_notifier`, a `BLOCKING_NOTIFIER_HEAD`. [[raw/pcie_scsc/hip|hip]] registers with `slsi_wlan_service_notifier_register()`.

### Service client callbacks

The `struct scsc_service_client mx_wlan_client` (embedded in `slsi_dev`) defines the callbacks that the Maxwell manager invokes:

| Callback | Handler in `cm_if.c` |
|---|---|
| `failure_notification` | `wlan_failure_notification()` |
| `stop_on_failure_v2` | `wlan_stop_on_failure_v2()` |
| `failure_reset_v2` | `wlan_failure_reset_v2()` |
| `check_reset_level` | `wlan_check_reset_level()` |
| `suspend` | `wlan_suspend()` |
| `resume` | `wlan_resume()` |

## Key entry points

### Module registration / unregistration

```c
int slsi_sm_service_driver_register(void);
void slsi_sm_service_driver_unregister(void);
```

`slsi_sm_service_driver_register` initialises `slsi_start_mutex` and registers the `wlan_driver` module client with `scsc_mx_module_register_client_module()`. This is the **bootstrap entry point** called during driver init.

### Probe / Remove (Maxwell callbacks)

```c
void slsi_wlan_service_probe(struct scsc_mx_module_client *module_client,
                             struct scsc_mx *mx,
                             enum scsc_module_client_reason reason);
static void slsi_wlan_service_remove(struct scsc_mx_module_client *module_client,
                                     struct scsc_mx *mx,
                                     enum scsc_module_client_reason reason);
```

`probe` fires on initial attach (reason `SCSC_MODULE_CLIENT_REASON_NONE`) or on recovery (`SCSC_MODULE_CLIENT_REASON_RECOVERY`). On initial probe it calls `slsi_dev_attach()` to create the device context; on recovery it notifies registered listeners and signals `recovery_completed`. `remove` handles the reverse, including waiting on `recovery_remove_completion` and sending hang events for level-8 panics.

### Normal service lifecycle (called by [[raw/pcie_scsc/mgt|mgt]])

```c
int slsi_sm_wlan_service_open(struct slsi_dev *sdev);
int slsi_sm_wlan_service_start(struct slsi_dev *sdev);
int slsi_sm_wlan_service_stop(struct slsi_dev *sdev);
void slsi_sm_wlan_service_close(struct slsi_dev *sdev);
```

- **open**: calls `scsc_mx_service_open()` to acquire a service handle. Downloads firmware into the chip's MIF memory.
- **start**: allocates MIF RAM (`HIP_MIFRAM_ALLOC_SIZE` ≈ 2.75–4.65 MB depending on config), starts HIP (`slsi_hip_start`), converts the control pointer to a MIF address, calls `scsc_mx_service_start()`, then runs HIP extension setup (`slsi_hip_setup_ext`) and SAP version negotiation (`slsi_hip_sap_setup`).
- **stop**: transitions to `STOPPING`, calls `scsc_mx_service_stop()`, retries up to `SLSI_RETRY_STOP_COUNT_ERROR` times if `-EILSEQ` (recovery in progress), or triggers `slsi_sm_service_failed` on `-EIO` (firmware unresponsive).
- **close**: frees MIF RAM, calls `scsc_mx_service_close()`, clears `sdev->service`.

### Recovery lifecycle (called by [[raw/pcie_scsc/mgt|mgt]] during error paths)

```c
int slsi_sm_recovery_service_stop(struct slsi_dev *sdev);
int slsi_sm_recovery_service_close(struct slsi_dev *sdev);
int slsi_sm_recovery_service_open(struct slsi_dev *sdev);
int slsi_sm_recovery_service_start(struct slsi_dev *sdev);
```

Mirrors the normal lifecycle but is invoked on the recovery path (typically from `mgt.c`'s subsystem reset handler). Same sequence: stop → close → open → start.

### Failure reporting

```c
void slsi_sm_service_failed(struct slsi_dev *sdev, const char *reason, bool is_work);
```

Reports a fatal error to the Maxwell core, dumps MIF registers, and blocks further HIP traffic. Only fires once per failure (`sdev->fail_reported` guard).

### Notifier chain

```c
int slsi_wlan_service_notifier_register(struct notifier_block *nb);
int slsi_wlan_service_notifier_unregister(struct notifier_block *nb);
```

Standard `blocking_notifier_chain_register/unregister` wrappers.

### Convenience accessor

```c
struct slsi_dev *slsi_get_sdev(void);   // returns cm_ctx.sdev
bool slsi_is_test_mode_enabled(void);   // module param: EnableTestMode
```

### Factory-test hook (optional)

```c
module_param_cb(factory_wifi_disable, &slsi_factory_test_ops, ...);
```

When written, closes the WLAN netdev for factory test mode.

## Internal flow

### Service start sequence

```mermaid
sequenceDiagram
    participant MX as scsc_mx
    participant CM as cm_if
    participant MGT as mgt
    participant HIP as hip
    participant DEV as dev

    MGT->>CM: slsi_sm_wlan_service_open(sdev)
    CM->>MX: scsc_mx_service_open(core, SCSC_SERVICE_ID_WLAN, ...)
    MX-->>CM: service handle
    Note over CM: state = PROBED → STOPPED

    MGT->>CM: slsi_sm_wlan_service_start(sdev)
    Note over CM: state = STOPPED → STARTING
    CM->>MX: scsc_mx_service_mifram_alloc(size, &ref, align)
    CM->>HIP: slsi_hip_start(sdev)
    CM->>MX: scsc_mx_service_mif_ptr_to_addr(service, hip_control, &ref)
    CM->>MX: scsc_mx_service_start(service, ref)
    CM->>HIP: slsi_hip_setup_ext(sdev)
    CM->>HIP: slsi_hip_sap_setup(sdev)
    Note over CM: state = STARTED; wlan_service_on = 1
```

### Failure and recovery path

```mermaid
sequenceDiagram
    participant MX as scsc_mx
    participant CM as cm_if
    participant MGT as mgt

    MX->>CM: mx_wlan_client.failure_notification(err)
    Note over CM: reset_level = err->level
    MX->>CM: mx_wlan_client.stop_on_failure_v2(err)
    Note over CM: recovery_in_progress = 1; state = BLOCKED
    CM->>CM: blocking_notifier_call(SCSC_WIFI_STOP)

    MGT->>CM: slsi_sm_recovery_service_stop()
    MGT->>CM: slsi_sm_recovery_service_close()
    MGT->>CM: slsi_sm_recovery_service_open()
    MGT->>CM: slsi_sm_recovery_service_start()

    MX->>CM: slsi_wlan_service_probe(RECOVERY)
    CM->>CM: blocking_notifier_call(SCSC_WIFI_CHIP_READY)
    Note over CM: recovery_in_progress = 0; state restored
