---
title: debug_frame
kind: entity
covers:
  - pcie_scsc/debug_frame.c
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-16T15:31:11Z"
sources:
  - pcie_scsc/debug_frame.c
  - pcie_scsc/debug.h#L207-L246
  - pcie_scsc/fapi.h#L1195-L1197
  - pcie_scsc/fapi.h#L6579
  - pcie_scsc/mgt.h#L798
---

# debug_frame

> Human-readable 802.11 / L3 frame decoder for runtime WLAN debugging. Every management, control, data, and A-MSDU sub-frame that flows through the driver can be inspected here — fields are parsed and emitted as a single `SLSI_DBG4` log line showing MAC addresses, frame subtype, and decoded protocol payload.

## Purpose

`debug_frame.c` provides a **runtime frame-inspection** facility gated by the Kconfig option `CONFIG_SCSC_WLAN_DEBUG`. It decodes:

- **802.11 frames** (`FAPI_DATAUNITDESCRIPTOR_IEEE802_11_FRAME` — value `0x0000`)
- **802.3 / L3 frames** (`FAPI_DATAUNITDESCRIPTOR_IEEE802_3_FRAME` — value `0x0001`)
- **A-MSDU sub-frames** (`FAPI_DATAUNITDESCRIPTOR_AMSDU_SUBFRAME` — value `0x0002`)

into a concise human-readable summary including source/destination MAC, vif ID, RSSI (for scan results), and a decoded payload label. The verbosity is controlled by the module parameter `slsi_debug_summary_frame`:

| Value | Description |
|---|---|
| 0 | Disabled |
| 1 | Management frames only (no scan) |
| 2 | Management + important L3 (EAPOL, ARP, DHCP) |
| 3 | All frames |

Data frames at level 3 are rate-limited to 200 messages per 5 seconds via `slsi_debug_frame_ratelimited()` to prevent log flooding.

## Public API

### `slsi_debug_frame`

```c
void slsi_debug_frame(struct slsi_dev *sdev, struct net_device *dev,
                      struct sk_buff *skb, const char *prefix);
```

Declared in `debug.h`; the real body lives here. When `CONFIG_SCSC_WLAN_DEBUG` is unset, `debug.h` provides a no-op inline stub.

**Algorithm**:

1. Guard: return early if `slsi_debug_summary_frame == 0` or `len == 0`.
2. Rate limit: if `sigid` is `MA_UNITDATA_REQ` or `MA_UNITDATA_IND`, check `slsi_debug_frame_ratelimited()`.
3. Extract `frametype` from the `sk_buff`'s FAPI descriptor, keyed on `sigid` (signal ID):
   - `MLME_SEND_FRAME_REQ` / `MLME_RECEIVED_FRAME_IND` → descriptor from the message body
   - `MLME_SCAN_IND`, `MLME_CONNECT_CFM`, `MLME_CONNECT_IND`, `MLME_PROCEDURE_STARTED_IND`, `MLME_CONNECTED_IND`, `MLME_REASSOCIATE_IND`, `MLME_ROAMED_IND` → hardcoded to `FAPI_DATAUNITDESCRIPTOR_IEEE802_11_FRAME`
4. Dispatch by `frametype`:
   - **IEEE 802.11** → `slsi_decode_80211_frame()`, MACs from `ieee80211_hdr`
   - **IEEE 802.3** → `slsi_decode_l3_frame()`, MACs from `ethhdr`
   - **A-MSDU sub-frame** → `slsi_decode_amsdu_subframe()`, MACs from `ethhdr`
5. If the decoder returned `true`, emit:
   ```
   SLSI_DBG4(sdev, SLSI_SUMMARY_FRAMES, "%-5s: %s(vif:%u rssi:%-3d, s:<src> d:<dst>)->%s\n",
             dev ? netdev_name(dev) : "", prefix, vif, rssi, src, dst, frame_info);
   ```

**Callers** (selected):

- `tx.c` — TX path (`mlme_send_frame_mgmt` and related)
- `rx.c` — RX path (received frame handling)
- `mlme.c` — MLME procedure completion
- `netif.c`, `txbp.c`, `sap_mlme.c`, `sap_ma.c`, `sap_dbg.c`, `mlme_nan.c`

## Key data structures

### Dispatcher tables

```c
struct slsi_decode_entry {
    const char *name;
    void       (*decode_fn)(u8 *frame, u16 frame_length,
                           char *result, size_t result_length);
};

struct slsi_decode_snap {
    const u8   snap[8];       // ethertype prefix (first 2 bytes)
    const char *name;
    size_t     (*decode_fn)(u8 *, u16, char *, size_t);
};

struct slsi_value_name_decode {
    const u16  value;
    const char *name;
    size_t     (*decode_fn)(u8 *, u16, char *, size_t);
};
```

### `frame_types[4][16]` — 802.11 dispatch table

A 2D array: row = ftype category (0=Management, 1=Control, 2=Data, 3=Reserved), column = 4-bit subtype. Each entry has a name string and optional `decode_fn`:

- **Row 0 (Management)**: AssocReq, AssocRsp, ReassocReq, ProbeReq, ProbeRsp, Beacon, Auth, Deauth, Action, ActionNoAck
- **Row 1 (Control)**: BlockAckReq, BlockAck, PsPoll, RTS, CTS, Ack — all NULL decoders
- **Row 2 (Data)**: Data, QosData, Null, QosNull — Data variants call `slsi_decode_80211_data`
- **Row 3 (Reserved)**: all NULL

### `snap_types[]` — L3 protocol dispatch

Maps ethertype prefixes to protocol decoders:

| Prefix | Protocol | Decoder |
|---|---|---|
| `0x0800` | IPv4 | `slsi_decode_ipv4` |
| `0x0806` | ARP | `slsi_decode_arp` |
| `0x888e` | EAPOL | `slsi_decode_eapol` |
| `0x890d` | TDLS | `slsi_decode_tdls` |
| `0x86dd` | IPv6 | none |
| `0x88b4` | WAPI | none |

### Action category table — `action_categories[]`

Maps 802.11 Action frame category codes (byte 0 of action body) to sub-decoders. Categories with decoders: BlockAck (3), Public (4), TDLS (12).

### IPv4 protocol decoders

`slsi_decode_ipv4` dispatches on `proto` field: TCP → `slsi_decode_ipv4_tcp` (port + flags), UDP → `slsi_decode_ipv4_udp` (port + BOOTP/DHCP inspection), ICMP → `slsi_decode_ipv4_icmp` (type + echo id/seq).

### EAPOL type table

`slsi_eapol_packet_type[]` maps EAPOL packet type to `slsi_decode_eapol_packet` which further classifies by EAP method (PEAP, TLS, AKA, etc. — 30+ types).

## Internal decode flow

```mermaid
flowchart-TD
    A[slsi_debug_frame] --> B{frametype}
    B -->|IEEE802.11| C[slsi_decode_80211_frame]
    B -->|IEEE802.3| D[slsi_decode_l3_frame]
    B -->|AMSDU| E[slsi_decode_amsdu_subframe]

    C --> F[frame_types[ftype][subtype]]
    F --> G[decode_fn AssocReq/Beacon/Action/...]
    G -->|Action| H[action_categories[]]
    H --> I[BlockAck/TDLS/Public]

    D --> J[snap_types[]]
    J --> K[slsi_decode_ipv4 / slsi_decode_arp / slsi_decode_eapol]
    K -->|IPv4| L[slsi_decode_ipv4_tcp / udp / icmp]
    K -->|EAPOL| M[slsi_decode_eapol_packet]

    E --> N[snap_types[] (+20 offset)]
```

### IE extraction helper

`slsi_decode_basic_ie_info()` uses `cfg80211_find_ie()` to locate and emit: SSID, channel (from HT Operation or DS Params), country, WPA/WPA2/WPS flags. Called by AssocReq, AssocRsp, Beacon, ProbeReq, and ReassocReq decoders.

## Debug level gating

Each decoder front-end (`slsi_decode_80211_frame`, `slsi_decode_l3_frame`, `slsi_decode_amsdu_subframe`) checks `slsi_debug_summary_frame`:

- **Level 1**: only 802.11 management frames (ftype_idx == 0); all L3 decoding skipped
- **Level 2**: 802.11 management + important L3 (EAPOL, ARP, WAPI, DHCP); other IP filtered by `slsi_is_dhcp_packet()`
- **Level 3**: everything; scan frames (ProbeReq, ProbeRsp, Beacon) suppressed at levels < 3

## Module parameter

```c
static int slsi_debug_summary_frame = 3;
module_param(slsi_debug_summary_frame, int, S_IRUGO | S_IWUSR);
```

Exposed at `/sys/module/pcie_scsc/parameters/slsi_debug_summary_frame` (or the driver's module name equivalent).

## Related

- [[raw/pcie_scsc/debug|debug]] — overall debug infrastructure and `SLSI_DBG4` macro
- [[raw/pcie_scsc/fapi|fapi]] — FAPI signal extraction (`fapi_get_sigid`, `fapi_get_u16`, etc.)
- [[raw/pcie_scsc/mlme|mlme]] — MLME message IDs and send/receive frame handling
- [[raw/pcie_scsc/rx|rx]] — RX path caller of `slsi_debug_frame`
- [[raw/pcie_scsc/tx|tx]] — TX path caller of `slsi_debug_frame`

## Recent changes

- Initial seed page.
