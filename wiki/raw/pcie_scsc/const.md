---
title: const
kind: entity
covers:
  - pcie_scsc/const.h
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T04:47:31Z"
sources:
  - pcie_scsc/const.h
  - pcie_scsc/dev.h#L1440-L1444
  - pcie_scsc/mgt.h#L546-L574
  - pcie_scsc/mgt.c#L5878-L6125
---

# const

`const.h` defines the **peer connection limits and index ranges** for the SLSI (Samsung Linux Stack Interface) PCIe WLAN driver. The constants bound the statically allocated `peer_sta_record` array in `struct netdev_vif` (declared in `dev.h`) and the index ranges used when iterating over peers in station, AP, TDLS, and P2P-GO modes.

## Key constants

| Macro | Value | Meaning |
|---|---|---|
| `SLSI_AP_PEER_CONNECTIONS_MAX` | 10 | Maximum AP peer connections (documented limit) |
| `SLSI_ADHOC_PEER_CONNECTIONS_MAX` | 16 | Array bound for `netdev_vif->peer_sta_record[]` — the actual compile-time allocation size |
| `SLSI_TDLS_PEER_INDEX_MIN` | 2 | Minimum AID reserved for TDLS peers |
| `SLSI_TDLS_PEER_INDEX_MAX` | 15 | Maximum AID reserved for TDLS peers |
| `SLSI_PEER_INDEX_MIN` | 1 | Minimum peer index (AP/P2P-GO iteration) |
| `SLSI_PEER_INDEX_MAX` | 16 | Maximum peer index (AP/P2P-GO iteration) |
| `SLSI_STA_PEER_QUEUESET` | 0 | Special slot 0: dedicated STA peer used by the station-mode queue-set path |

The header comment warns that raising `SLSI_ADHOC_PEER_CONNECTIONS_MAX` beyond 16 requires migrating `peer_sta_record[]` from static to dynamic allocation, because the current layout allocates the full array inline inside `struct netdev_vif`.

## Layout in `struct netdev_vif`

In `dev.h`, the peer table is declared as:

```c
struct slsi_peer *peer_sta_record[SLSI_ADHOC_PEER_CONNECTIONS_MAX];
```

This single array is multiplexed across VIF types:
- **Station** (`FAPI_VIFTYPE_STATION`): Uses slot 0 (`SLSI_STA_PEER_QUEUESET`) via `slsi_get_peer_from_qs()` — e.g. in `mgt.c` connect/disconnect paths.
- **TDLS**: Scans indices 1..14 (`SLSI_TDLS_PEER_INDEX_MIN` to `SLSI_TDLS_PEER_INDEX_MAX` − 1).
- **AP / P2P-GO**: Scans indices 0..15 (`SLSI_PEER_INDEX_MAX` slots).

## Include reach

`const.h` is included by 12 source files across the driver — core modules (`mgt.c`, `rx.c`, `txbp.c`, `lls.c`, `netif.c`, `sap_ma.c`, `cfg80211_ops.c`, `tdls_manager.c`, `src_sink.c`, `nl80211_vendor_nan.c`, `procfs.c`) plus `dev.h` (propagating to every `.c` that includes it) and the kunit test suite.

## Related

- [[raw/pcie_scsc/dev|dev]] — `struct netdev_vif` and peer table ownership
- [[raw/pcie_scsc/mgt|mgt]] — Peer lookup (`slsi_get_peer_from_qs`, `slsi_is_tdls_peer`) and cleanup
- [[raw/pcie_scsc/rx|rx]] — Uses peer index for RX steering

## Recent changes

- Initial seed page from `const.h` source.
