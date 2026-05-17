---
title: if_vif — Firmware VIF ↔ Linux Interface ID Mapping
kind: entity
covers:
  - pcie_scsc/if_vif.c
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T23:01:04Z"
sources:
  - pcie_scsc/if_vif.c#L1-L96
  - pcie_scsc/dev.h#L1365-L1401
  - pcie_scsc/dev.h#L2192
  - pcie_scsc/dev.h#L1679-L1686
  - pcie_scsc/fapi.h#L1955-L1956
  - pcie_scsc/mlme.h#L137-L138
  - pcie_scsc/mgt.h#L503-L504
  - pcie_scsc/mgt.h#L992-L999
---

# if_vif

> Firmware VIF ID ↔ Linux network interface ID bidirectional mapping layer.

`if_vif.c` provides the lookup and bookkeeping between the firmware's internal
virtual interface identifiers (**VIF IDs**, range `0x0001`–`0x000F` per
`FAPI_VIFRANGE_VIF_INDEX_MIN/MAX` in [[raw/pcie_scsc/dev|dev.h]]/[[raw/pcie_scsc/fapi|fapi.h]])
and the kernel's Linux network interface indices (**ifnum** values managed by
`struct slsi_dev.netdev[]`).

The central data structure is the `vif_netdev_id_map` array inside
`struct slsi_dev` — a size-16 `u16` table indexed by firmware VIF ID, each
entry storing the corresponding Linux `ifnum`, or `SLSI_INVALID_IFNUM` (`0xFFFF`)
when idle. The reverse side of the mapping lives in each `struct netdev_vif`'s
`vifnum` (and `detect_vifnum` for NAN discovery VIFs).

## Key data structures

| Field / Struct | Location | Role |
|---|---|---|
| `struct slsi_dev.vif_netdev_id_map[16]` | `dev.h:L2192` | Primary VIF-ID → ifnum lookup table |
| `struct netdev_vif.vifnum` | `dev.h:L1400` | Reverse mapping: netdev → firmware VIF |
| `struct netdev_vif.ifnum` | `dev.h:L1399` | Linux interface index assigned to this netdev |
| `struct netdev_vif.detect_vifnum` | `dev.h:L1401` | NAN detect-VIF ID (separate from operational `vifnum`) |
| `SLSI_INVALID_VIF` | `mlme.h:L137` | Sentinel `0xFFFF` for "no VIF assigned" |
| `SLSI_INVALID_IFNUM` | `mlme.h:L138` | Sentinel `0xFFFF` for "no ifnum mapped" |

### VIF index partitioning for NAN

The `FAPI_VIFRANGE_VIF_INDEX_MAX` (15) entries are partitioned between
conventional interfaces and Wi-Fi NAN (Neighbor Awareness Networking) data
VIFs. `mgt.h` defines:

```c
#define SLSI_NAN_MGMT_VIF_NUM(sdev)   (FAPI_VIFRANGE_VIF_INDEX_MAX - sdev->nan_max_ndp_instances)
#define SLSI_NAN_DATA_VIF_NUM_START(sdev) (FAPI_VIFRANGE_VIF_INDEX_MAX - sdev->nan_max_ndp_instances + 1)
#define SLSI_NAN_DATA_IFINDEX_START  (SLSI_NET_INDEX_NAN + 1)  /* dev.h */
```

This means VIF IDs `1` through `SLSI_NAN_MGMT_VIF_NUM(sdev)` are
conventional, and higher IDs are reserved for NAN data planes.

## Public API

All 8 functions are declared in `mgt.h` (lines 992–999) and defined in
`if_vif.c`.

### Bidirectional lookup

```c
u16 slsi_get_vifnum_by_ifnum(struct slsi_dev *sdev, int ifnum)
```
Linear scan over `sdev->vif_netdev_id_map[]` to find which VIF ID maps to
`ifnum`. Returns `SLSI_INVALID_VIF` on miss.

```c
int slsi_get_ifnum_by_vifid(struct slsi_dev *sdev, u16 vif_id)
```
Constant-time reverse lookup. Returns `sdev->vif_netdev_id_map[vif_id]` for
conventional VIFs, `SLSI_NAN_DATA_IFINDEX_START` for NAN data VIFs, or
`SLSI_INVALID_IFNUM` out of range.

### Assignment / teardown

```c
void slsi_mlme_assign_vif(struct slsi_dev *sdev, struct net_device *dev, u16 vif_id)
```
Writes `ifnum` into `vif_netdev_id_map[vif_id]` and sets `ndev_vif->vifnum`.
Called from [[raw/pcie_scsc/mlme|mlme.c]] during `MLME_ADD_VIF_REQ` handling.

```c
void slsi_mlme_clear_vif(struct slsi_dev *sdev, struct net_device *dev, u16 vif_id)
```
Resets both sides of the mapping to `0xFFFF`. Called on `MLME_DEL_VIF_REQ`
and during VIF teardown.

### Detect-VIF (NAN discovery)

```c
void slsi_mlme_assign_detect_vif(struct slsi_dev *sdev, struct net_device *dev, u16 vif_id)
```
Assigns `ndev_vif->detect_vifnum` — a NAN-specific discovery VIF slot,
parallel to the main `vifnum`.

```c
void slsi_mlme_clear_detect_vif(struct slsi_dev *sdev, struct net_device *dev, u16 vif_id)
```
Teardown for the detect-VIF.

### Validation and monitor support

```c
bool slsi_is_valid_vifnum(struct slsi_dev *sdev, struct net_device *dev)
```
Guards callers: checks `dev` is non-NULL and `vifnum` lies within
`[FAPI_VIFRANGE_VIF_INDEX_MIN, FAPI_VIFRANGE_VIF_INDEX_MAX]`. Called at the
top of many MLME and RX paths as an early-bail guard.

```c
void slsi_monitor_set_if_with_vif(struct slsi_dev *sdev, struct netdev_vif *ndev_vif, int ifnum)
```
Sets `ndev_vif->ifnum = ifnum`. If a VIF already maps to `ifnum` in the
table, uses that VIF; otherwise falls back to `vifnum = ifnum` directly.
Used by the [[raw/pcie_scsc/cfg80211_ops|cfg80211 monitor path]] and
[[raw/pcie_scsc/mgt|mgt.c]] monitor-channel switching.

## Callers (cross-module)

| Function | Called from |
|---|---|
| `slsi_mlme_assign_vif` | `mlme.c` (ADD_VIF), `fw_test.c` |
| `slsi_mlme_clear_vif` | `mlme.c` (DEL_VIF, error paths), `mgt.c`, `fw_test.c` |
| `slsi_mlme_assign_detect_vif` | `mlme.c` (NAN detect VIF creation) |
| `slsi_mlme_clear_detect_vif` | `mlme.c`, `sap_mlme.c` |
| `slsi_is_valid_vifnum` | `mlme.c` (4 guards), `mgt.c` |
| `slsi_get_vifnum_by_ifnum` | `if_vif.c` itself (via `slsi_monitor_set_if_with_vif`) |
| `slsi_get_ifnum_by_vifid` | `rx.c`, `sap_ma.c`, `udi.c`, `txbp.c`, `sap_mlme.c` |
| `slsi_monitor_set_if_with_vif` | `cfg80211_ops.c`, `mgt.c` |

## Related

- [[raw/pcie_scsc/dev|dev]] — `struct slsi_dev` and `struct netdev_vif` definitions
- [[raw/pcie_scsc/mlme|mlme]] — VIF add/delete MLME processing that drives assignment
- [[raw/pcie_scsc/mgt|mgt]] — Device management; monitor-channel switching

## Recent changes

- Initial seed page.
