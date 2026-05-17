---
title: conc_modes — Concurrent Interface Modes
kind: entity
covers:
  - pcie_scsc/conc_modes.c
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T04:39:04Z"
sources:
  - pcie_scsc/conc_modes.c#L1-L172
  - pcie_scsc/nl80211_vendor.h#L782-L802
  - pcie_scsc/nl80211_vendor.h#L390-L402
  - pcie_scsc/nl80211_vendor.c#L6433-L6436
  - pcie_scsc/nl80211_vendor.c#L7422-L7429
  - pcie_scsc/cfg80211_ops.h#L14
  - pcie_scsc/Makefile#L166
---

# conc_modes — Concurrent Interface Modes

`conc_modes.c` defines the **concurrency matrix** that declares which combinations of Wi-Fi interfaces can coexist on a single SoC. It exposes a single `nl80211` vendor-command handler, `slsi_get_concurrency_matrix`, which serializes the matrix into nested netlink attributes for user-space consumers (e.g. Android's `wpa_supplicant`). The module is only compiled when `CONFIG_SCSC_BB_REDWOOD` is set; on other SoCs the handler returns `-EOPNOTSUPP`.

## Key data structures

Three local structs (defined only under `CONFIG_SCSC_BB_REDWOOD`) describe the matrix hierarchy:

```c
typedef struct {
    u32 max_limit;   // max number of interfaces allowed in this bucket
    u32 iface_mask;  // BIT-mask over enum wifi_interface_type_mask
} wifi_iface_limit;

typedef struct {
    u32 max_ifaces;            // total concurrent interfaces for this combination
    u32 num_iface_limits;
    wifi_iface_limit iface_limits[MAX_IFACE_LIMITS];    // up to 8 buckets
} wifi_iface_combination;

typedef struct {
    u32 num_iface_combinations;
    wifi_iface_combination iface_combinations[MAX_IFACE_COMBINATIONS];  // up to 16
} wifi_iface_concurrency_matrix;
```

The leaf bit-mask, `iface_mask`, uses `BIT()` against `enum wifi_interface_type_mask` (declared in `nl80211_vendor.h`):

| Value | Constant | Meaning |
|---|---|---|
| 0 | `WIFI_INTERFACE_TYPE_STA` | Station (client) |
| 1 | `WIFI_INTERFACE_TYPE_AP` | Access Point |
| 2 | `WIFI_INTERFACE_TYPE_P2P` | P2P (Wi-Fi Direct) |
| 3 | `WIFI_INTERFACE_TYPE_NAN` | Neighbour Awareness Networking |
| 4 | `WIFI_INTERFACE_TYPE_AP_BRIDGED` | Bridged AP |

## Concurrency matrix (Redwood SoC)

The single `static const` instance, `iface_concurrency_matrix`, enumerates **3** supported combinations:

1. **STA + one of {DUAL\_AP / NAN / STA / AP / P2P}** — 2 interfaces total. One STA plus one interface chosen from the remaining types (or STA itself for a second-VIF scenario). Under `CONFIG_SLSI_WLAN_STA_W_BRIDGEDAP`, `AP_BRIDGED` is also in the pool.
2. **STA + NAN + one of {P2P, AP}** — 3 interfaces total. One STA, one NAN, and one P2P or AP.
3. **DUAL\_AP** — 1 interface of type `AP_BRIDGED`.

## Public API

```c
int slsi_get_concurrency_matrix(struct wiphy *wiphy,
                                struct wireless_dev *wdev,
                                const void *data, int len);
```

Declared in `nl80211_vendor.h` (line 1176). Registered as an `nl80211` vendor command in `nl80211_vendor.c` (line 7428) with:

- **OUI**: `OUI_GOOGLE`
- **subcmd**: `SLSI_NL80211_VENDOR_SUBCMD_GET_CONCURRENCY_MATRIX`
- **flags**: `WIPHY_VENDOR_CMD_NEED_WDEV | WIPHY_VENDOR_CMD_NEED_NETDEV`

### Response wire format

The reply `sk_buff` is populated with nested netlink attributes using `enum slsi_concurrency_matrix_attr` attributes:

```
SLSI_ATTRIBUTE_NUM_IFACE_COMB (u32)
├── SLSI_ATTRIBUTE_IFACE_COMB (nested)
│   ├── SLSI_ATTRIBUTE_MAX_IFACE (u32)
│   ├── SLSI_ATTRIBUTE_NUM_IFACE_LIMITS (u32)
│   └── SLSI_ATTRIBUTE_WIFI_IFACE_LIMIT (nested × num_iface_limits)
│       ├── SLSI_ATTRIBUTE_MAX_LIMIT (u32)
│       └── SLSI_ATTRIBUTE_IFACE_MASK (u32)
