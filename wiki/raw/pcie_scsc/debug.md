---
title: debug
kind: entity
covers:
  - pcie_scsc/debug.c
  - pcie_scsc/debug.h
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T05:48:35Z"
sources:
  - pcie_scsc/debug.c#L1-L320
  - pcie_scsc/debug.h#L1-L305
  - pcie_scsc/debug_frame.c#L1-L20
  - pcie_scsc/debug_frame.c#L1008-L1118
---

# debug

> Samsung Linux Wi-Fi (SLSI) driver debug logging framework. Provides per-module, level-gated kernel log macros, sysfs-tunable filter parameters, and a unified formatting layer for error/warning/info output across all subsystems.

## Purpose

The debug infrastructure in `debug.h` / `debug.c` is the **central logging subsystem** for the entire `pcie_scsc` Wi-Fi driver. Every C file in the tree includes `debug.h` (directly or transitively through `dev.h`) and uses its macros for all diagnostic output. It provides:

- **29 independently tunable log filters** (e.g. `SLSI_TX`, `SLSI_MLME`, `SLSI_HIP_SDIO_OP`), each exposed as a `module_param_cb` parameter readable/writable via sysfs.
- **Four debug levels** (0 = off, 1–4 = increasingly verbose). Each filter has a default level; a level-1 macro (`SLSI_DBG1`) emits only when `1 <= filter_value`.
- **Three severity macros** (`SLSI_ERR`, `SLSI_WARN`, `SLSI_INFO`) that always emit (never gated by level).
- **Hex-dump variants** (`SLSI_ERR_HEX`, `SLSI_DBG_HEX`) that combine a formatted message with `print_hex_dump`.
- **Three device-context variants**: per-`slsi_dev` (`SLSI_ERR`), per-`net_device` (`SLSI_NET_ERR`), and no-device (`SLSI_ERR_NODEV`), producing different `dev_*` / `pr_*` call paths.
- A **global override** (`slsi_dbg_lvl_all`) that resets every filter to a single value.
- **`CONFIG_SCSC_WLAN_DEBUG`**: when unset, all `SLSI_DBG*` macros become empty `do {} while (0)` no-ops and `slsi_debug_frame` becomes an inline stub — zero runtime cost in production builds.
- **`CONFIG_SCSC_DEBUG_COMPATIBILITY`**: alternate logging path that routes through `SCSC_TAG_DBG*_SDEV` and `SCSC_BIN_TAG_DEBUG` macros defined in an external `<pcie_scsc/scsc_warn.h>` header.

## Key data structures

### Filter constants (`debug.c` lines 16–49)

```c
const int   SLSI_INIT_DEINIT          =  0;
const int   SLSI_NETDEV               =  1;
const int   SLSI_CFG80211             =  2;
const int   SLSI_MLME                 =  3;
const int   SLSI_SUMMARY_FRAMES       =  4;
const int   SLSI_HYDRA                =  5;
const int   SLSI_TX                   =  6;
const int   SLSI_RX                   =  7;
const int   SLSI_UDI                  =  8;
const int   SLSI_WIFI_FCQ             =  9;
const int   SLSI_HIP                  = 10;
const int   SLSI_HIP_INIT_DEINIT      = 11;
const int   SLSI_HIP_FW_DL            = 12;
const int   SLSI_HIP_SDIO_OP          = 13;
const int   SLSI_HIP_PS               = 14;
const int   SLSI_HIP_TH               = 15;
const int   SLSI_HIP_FH               = 16;
const int   SLSI_HIP_SIG              = 17;
const int   SLSI_FUNC_TRACE           = 18;
const int   SLSI_TEST                 = 19;
const int   SLSI_SRC_SINK             = 20;
const int   SLSI_FW_TEST              = 21;
const int   SLSI_RX_BA                = 22;
const int   SLSI_TDLS                 = 23;
const int   SLSI_GSCAN                = 24;
const int   SLSI_MBULK                = 25;
const int   SLSI_FLOWC                = 26;
const int   SLSI_SMAPPER              = 27;
const int   SLSI_PM                   = 28;
```

Each integer indexes into `slsi_dbg_filters[]` — the dispatch table used by every `SLSI_DBG` macro.

### Filter pointer array (`debug.c` lines 104–138)

```c
int *slsi_dbg_filters[] = {
    &slsi_dbg_lvl_init_deinit,
    &slsi_dbg_lvl_netdev,
    /* … 27 more … */
    &slsi_dbg_lvl_pm,
};
```

Populated by the `ADD_DEBUG_MODULE_PARAM` macro, which declares a static int with a default value and registers a `module_param_cb` so the value is tunable via `/sys/module/<name>/parameters/slsi_dbg_lvl_*`.

### `ADD_DEBUG_MODULE_PARAM` macro (`debug.c` line 60)

```c
#define ADD_DEBUG_MODULE_PARAM(name, default_level, filter) \
    static int slsi_dbg_lvl_ ## name = default_level; \
    module_param_cb(slsi_dbg_lvl_ ## name, &param_ops_log, (void *)&filter, S_IRUGO | S_IWUSR); \
    MODULE_PARM_DESC(slsi_dbg_lvl_ ## name, " Debug levels (0~4) for the " # name " module (0 = off) default=" # default_level)
```

### Logging macro hierarchy

The core formatting layer uses three `SLSI_EWI*` macros that prepend `SCSC_PREFIX`, a severity label (`E`, `W`, `I`), the caller's `__func__`, and device/netdev identifiers:

```c
#define SLSI_EWI(output, sdev, label, fmt, ...) \
    output(SLSI_EWI_DEV(sdev), SCSC_PREFIX label ": %s: " fmt, __func__, ## __VA_ARGS__)

#define SLSI_EWI_NET(output, ndev, label, fmt, ...) \
    output(SLSI_EWI_NET_DEV(ndev), SCSC_PREFIX "%s: " label ": %s: " fmt, SLSI_EWI_NET_NAME(ndev), __func__, ## __VA_ARGS__)

#define SLSI_EWI_NODEV(output, label, fmt, ...) \
    output(SCSC_PREFIX label ": %s: " fmt, __func__, ## __VA_ARGS__)
```

Level-gated debug macros wrap these with a filter check:

```c
#define SLSI_DBG(sdev, filter, dbg_lvl, fmt, ...) \
    do { \
        if (unlikely((dbg_lvl) <= *slsi_dbg_filters[filter])) \
            SLSI_EWI(dev_info, sdev, #dbg_lvl, fmt, ## __VA_ARGS__); \
    } while (0)
```

Convenience aliases:

| Macro | Level | Device context |
|---|---|---|
| `SLSI_DBG1(sdev, filter, fmt, ...)` | 1 | `slsi_dev` |
| `SLSI_DBG2(sdev, filter, fmt, ...)` | 2 | `slsi_dev` |
| `SLSI_DBG3(sdev, filter, fmt, ...)` | 3 | `slsi_dev` |
| `SLSI_DBG4(sdev, filter, fmt, ...)` | 4 | `slsi_dev` |
| `SLSI_NET_DBG1(ndev, filter, fmt, ...)` | 1 | `net_device` |
| `SLSI_NET_DBG2(ndev, filter, fmt, ...)` | 2 | `net_device` |
| `SLSI_NET_DBG3(ndev, filter, fmt, ...)` | 3 | `net_device` |
| `SLSI_NET_DBG4(ndev, filter, fmt, ...)` | 4 | `net_device` |
| `SLSI_DBG1_NODEV(filter, fmt, ...)` | 1 | none (uses `pr_info`) |
| `SLSI_DBG2_NODEV(filter, fmt, ...)` | 2 | none |
| `SLSI_DBG3_NODEV(filter, fmt, ...)` | 3 | none |
| `SLSI_DBG4_NODEV(filter, fmt, ...)` | 4 | none |

Function-trace helpers (gated at level 4, filter `SLSI_FUNC_TRACE`):

```c
#define FUNC_ENTER(sdev)  SLSI_DBG4(sdev, SLSI_FUNC_TRACE, "--->\n")
#define FUNC_EXIT(sdev)   SLSI_DBG4(sdev, SLSI_FUNC_TRACE, "<---\n")
#define FUNC_ENTER_NODEV() SLSI_DBG4_NODEV(SLSI_FUNC_TRACE, "--->\n")
#define FUNC_EXIT_NODEV()  SLSI_DBG4_NODEV(SLSI_FUNC_TRACE, "<---\n")
```

## Key entry points

### `slsi_dbg_set_param_cb` / `slsi_dbg_get_param_cb` (`debug.c` lines 264–316)

Custom `kernel_param_ops` callbacks that handle sysfs reads/writes of every filter parameter. On write, `slsi_decstr_to_int` parses the string, validates the filter index against `SLSI_DF_MAX`, and either sets an individual filter or — if `SLSI_OVERRIDE_ALL_FILTER` (`-1`) — sets **all** filters simultaneously.

### `slsi_debug_frame` (`debug_frame.c` line 1018)

```c
void slsi_debug_frame(struct slsi_dev *sdev, struct net_device *dev,
                      struct sk_buff *skb, const char *prefix);
```

Declared in `debug.h`; implemented in [[raw/pcie_scsc/debug_frame|debug_frame]]. Prints a human-readable summary of an 802.11 or Ethernet frame (decoded via `slsi_decode_80211_frame`, `slsi_decode_l3_frame`, etc.). Called from [[raw/pcie_scsc/tx|tx]], [[raw/pcie_scsc/rx|rx]], [[raw/pcie_scsc/mlme|mlme]], [[raw/pcie_scsc/sap_ma|sap_ma]], [[raw/pcie_scsc/sap_mlme|sap_mlme]], [[raw/pcie_scsc/fw_test|fw_test]], [[raw/pcie_scsc/netif|netif]], and [[raw/pcie_scsc/txbp|txbp]]. Gated by `slsi_debug_summary_frame` module parameter and rate-limited for data frames via `slsi_debug_frame_ratelimited()`.

### `slsi_dbg_on_off` (`debug.c` lines 223–233)

Only compiled under `CONFIG_SCSC_DEBUG_COMPATIBILITY`. Sets `slsi_dbg_lvl_all` to 1 or 0 to globally enable/disable the logring.

## MAC address redaction

When `CONFIG_SCSC_WLAN_DEBUG` is unset, `MAC2STR` / `MACSTR` macros hide the middle two octets (`%02x:%02x:**:**:%02x:%02x`) to avoid leaking OUI information in production builds. When the config is set, all six octets are printed.

## Configuration summary

| Kconfig | Effect |
|---|---|
| `CONFIG_SCSC_WLAN_DEBUG` | Full debug macro bodies; frame decoding active. |
| `!CONFIG_SCSC_WLAN_DEBUG` | All `SLSI_DBG*` macros compile to empty no-ops. `SLSI_ERR`/`WARN`/`INFO` still emit. `slsi_debug_frame` becomes an inline stub. |
| `CONFIG_SCSC_DEBUG_COMPATIBILITY` | Replaces all macros with `SCSC_TAG_DBG*` variants from external `<pcie_scsc/scsc_warn.h>`. Adds `slsi_dbg_on_off()` API. |

## Related

- [[raw/pcie_scsc/debug_frame|debug_frame]] — frame decoding logic called by `slsi_debug_frame`
- [[raw/pcie_scsc/dev|dev]] — `struct slsi_dev` used as device context in all logging macros
- [[raw/pcie_scsc/procfs|procfs]] — exposes runtime state often inspected alongside debug logs

## Recent changes

- Initial seed page created.
