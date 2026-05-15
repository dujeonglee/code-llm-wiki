---
title: SCSC MLME (MAC Layer Management Entity)
kind: entity
covers:
  - pcie_scsc/mlme.c
  - pcie_scsc/mlme.h
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-15T20:23:17Z"
sources:
  - pcie_scsc/mlme.c#L1-L7800
  - pcie_scsc/mlme.h#L1-L833
  - pcie_scsc/dev.h#L472-L500
  - pcie_scsc/rx.c#L6672-L6760
  - pcie_scsc/cfg80211_ops.c
  - pcie_scsc/mib.h
---

The MLME (MAC Layer Management Entity) module implements every MAC-layer management
primitive for the Samsung SCSC firmware. It is the primary bridge between Linux's
[[subsystems/cfg80211|cfg80211]] subsystem and the SCSC firmware, translating
nl80211/cfg80211 operations into FAPI (Firmware API) signaling messages sent over
the [[subsystems/hip|HIP]] (Host Interface Processor) transport layer.

All MLME operations follow a synchronous **request → confirm → indication** protocol.
The core mechanism is `slsi_mlme_tx_rx()`, which allocates a FAPI signal as a
`struct sk_buff`, sends it via `slsi_tx_control()`, then blocks on a
`struct completion` until the firmware responds with a matching confirm (CFM) and
optionally an indication (IND).

## Signaling Protocol

### `struct slsi_sig_send` (per-VIF and per-device)

Defined in [[dev|dev.h]], there is one `slsi_sig_send` on the global `struct slsi_dev`
and one on each VIF's `struct netdev_vif`. This is the blocking primitive:

```c
struct slsi_sig_send {
    spinlock_t        send_signal_lock;
    struct mutex      mutex;
    struct completion completion;
    u16               process_id;   /* incremented per-transaction; matched on return */
    u16               req_id;       /* FAPI signal ID of the outgoing request */
    u16               cfm_id;       /* expected confirm signal ID */
    u16               ind_id;       /* expected indication signal ID (0 = no ind) */
    struct sk_buff    *cfm;         /* confirm skb from firmware */
    struct sk_buff    *ind;         /* indication skb from firmware */
    struct sk_buff    *mib_error;   /* MIB error payload */
};
```

### Core Transaction Path

```
slsi_mlme_tx_rx(sdev, dev, skb, cfm_id, mib_error, ind_id, validate_fn)
    ├── slsi_tx_control(sdev, dev, skb)      // send via HIP [[subsystems/hip|HIP]]
    ├── slsi_mlme_wait_for_cfm()             // block on completion for cfm
    │   └── validate_cfm_wait_ind()          // if ind also expected, gate on cfm result
    └── slsi_mlme_wait_for_ind()             // block on completion for ind
```

The RX path in `slsi_rx_blocking_signals()` ([[rx|rx.c]]#L6672) matches incoming
FAPI signals by comparing `(id == sig_wait->cfm_id && pid == sig_wait->process_id)`,
stores the skb, calls `complete(&sig_wait->completion)`, and unblocks the caller.

### Wrapper Variants

| Function | Waits For |
|---|---|
| `slsi_mlme_req()` | Nothing (fire-and-forget) |
| `slsi_mlme_req_no_cfm()` | Nothing |
| `slsi_mlme_req_cfm()` | Confirm only |
| `slsi_mlme_req_ind()` | Indication only |
| `slsi_mlme_req_cfm_ind()` | Confirm + Indication (validated by callback) |

### Timeout & Failure Handling

The `missing_cfm_ind_panic` module parameter controls whether a lost confirm/indication
triggers a kernel panic. On timeout, `sdev->mlme_blocked` is set to `true`, blocking
all further MLME traffic, and `SLSI_FW_BUG_ON_WQ()` queues a firmware diagnostic
dump. Confirm timeouts use `*sdev->sig_wait_cfm_timeout`; scan-done indications
use the longer `SLSI_SCAN_DONE_IND_WAIT_TIMEOUT` (20 seconds).

## Key Data Structures

### Channel Information Encoding

```c
u16 slsi_compute_chann_info(struct slsi_dev *sdev, u16 width, u16 center_freq0, u16 channel_freq);
u16 slsi_get_chann_info(struct slsi_dev *sdev, struct cfg80211_chan_def *chandef);
```

Maps `NL80211_CHAN_WIDTH_*` values (20, 40, 80, 160, 320 MHz) to FAPI channel
info encoding. Primary channel position is packed in the upper byte for 80/160/320 MHz
widths.

### Security IE Handling

`struct slsi_mlme_rsse` holds cryptographic suite information passed during
connect operations:
```c
struct slsi_mlme_rsse {
    u8       group_cs_count;
    const u8 *group_cs;
    u8       pairwise_cs_count;
    const u8 *pairwise_cs;
    u8       akm_suite_count;
    const u8 *akm_suite;
    u8       pmkid_count;
    const u8 *pmkid;
    const u8 *group_mgmt_cs;  /* PMF */
};
```

### Scan Private IE

Samsung-specific vendor IEs are embedded in FAPI scan requests using
`struct slsi_mlme_parameters`:
```c
struct slsi_mlme_parameters {
    u8 element_id;           /* WLAN_EID_VENDOR_SPECIFIC (0xdd) */
    u8 length;
    u8 oui[3];              /* Samsung OUI 0x001632 */
    u8 oui_type;            /* SLSI_MLME_TYPE_SCAN_PARAM (0x01), etc. */
    u8 oui_subtype;         /* channel list, SSID filter, timing, etc. */
} __packed;
```

### SAR (Specific Absorption Rate) Power Limits

```c
struct slsi_mlme_sar_tx_power_limit {
    u8 antenna1_2g4, antenna2_2g4, antenna1_2_2g4;
    u8 antenna1_5g, antenna2_5g, antenna1_2_5g;
    u8 antenna1_6g, antenna2_6g, antenna1_2_6g;
};
```

### TWT (Target Wake Time) Setup

```c
struct twt_setup {
    int setup_id, negotiation_type, flow_type, trigger_type;
    u32 d_wake_duration, d_wake_interval, d_wake_time;
    int min_wake_interval, max_wake_interval, min_wake_duration, max_wake_duration;
    int avg_pkt_num, avg_pkt_size;
};
```

### Scheduled Power Management

```c
struct slsi_scheduled_pm_setup {
    int desired_duration, desired_interval, additional_duration;
    int minimum_interval, maximum_interval, minimum_duration, maximum_duration;
    int grace_period;
};
```

### MLO (Multi-Link Operation) — EHT

Defined under `CONFIG_SCSC_WLAN_EHT`:
```c
struct mlo_link_info {
    u16 control_mode;
    int num_links;
    struct link_active_state_descriptor links[MAX_NUM_MLD_LINKS];
};

struct link_active_state_descriptor {
    u16 link_id;
    u16 link_state;
    u16 operating_frequency;
};
```

## Key Entry Points

### VIF Lifecycle

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_add_vif()` | `MLME_ADD_VIF_REQ → MLME_ADD_VIF_CFM` | Register a VIF with firmware |
| `slsi_mlme_del_vif()` | `MLME_DEL_VIF_REQ → MLME_DEL_VIF_CFM` | Deregister a VIF |
| `slsi_mlme_add_detect_vif()` | `MLME_ADD_VIF_REQ` (type DETECT) | Add a detect-mode VIF |
| `slsi_mlme_del_detect_vif()` | `MLME_DEL_VIF_REQ` | Remove detect VIF |

`slsi_allocate_vif()` maps a logical interface index to a firmware VIF ID from
`FAPI_VIFRANGE_VIF_INDEX_MAX` slots.

### Station Connect/Disconnect

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_connect()` | `MLME_CONNECT_REQ → MLME_CONNECT_CFM` | Full connect: auth type, SSID, security IEs, MLO params |
| `slsi_mlme_disconnect()` | `MLME_DISCONNECT_REQ → MLME_DISCONNECT_CFM → MLME_DISCONNECTED_IND` | Disconnect with optional indication wait |
| `slsi_mlme_connect_resp()` | `MLME_CONNECT_RES` | Send response to confirm connection to firmware |
| `slsi_mlme_connected_resp()` | `MLME_CONNECTED_RES` | Acknowledge firmware's connected indication |
| `slsi_mlme_roam()` | `MLME_ROAM_REQ → MLME_ROAM_CFM` | Roam to new BSSID/frequency |
| `slsi_mlme_roamed_resp()` | `MLME_ROAMED_RES` | Acknowledge roaming completion |
| `slsi_mlme_reassociate()` | (internal) | Trigger firmware reassociation |
| `slsi_mlme_update_connect_params()` | (internal) | Update SSID, security, channel without full reconnect |
| `slsi_mlme_connect_scan()` | (internal) | Blocking scan before connect attempt |

`slsi_mlme_connect()` builds a FAPI connect request with: BSSID, authentication
type (mapped from `NL80211_AUTHTYPE_*` to `FAPI_AUTHENTICATIONTYPE_*`), channel
frequency (doubled for firmware encoding), SSID IE, security IEs (RSN/WPA/WPA2/WAPI/OWE/FILS),
and MLO parameters. The supported AKM types include PSK, PSK-SHA256, FILS-SHA256/SHA384,
FT-FILS, OWE, and 802.1X-SuiteB.

### AP Start

`slsi_mlme_start()` — `MLME_START_REQ → MLME_START_CFM` — starts a soft AP with
beacon parameters, DTIM, capability information, authentication type, channel info,
SSID, VHT/HE IEs, and BSS color.

### Scanning

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_add_scan()` | `MLME_ADD_SCAN_REQ → MLME_ADD_SCAN_CFM → MLME_SCAN_IND` | Autonomous scan (wraps `slsi_mlme_add_scan_mld_addr`) |
| `slsi_mlme_add_sched_scan()` | (internal) | Scheduled scan |
| `slsi_mlme_del_scan()` | `MLME_DEL_SCAN_REQ → MLME_DEL_SCAN_CFM` | Cancel scan |
| `slsi_mlme_connect_scan()` | (internal) | Blocking scan before connect |

Scan results arrive as `MLME_SCAN_IND` signals dispatched via [[rx|rx.c]] to
`slsi_rx_scan_pass_to_cfg80211()`.

### Key Management

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_set_key()` | `MLME_SETKEYS_REQ → MLME_SETKEYS_CFM` | Install key (WEP, pairwise, group, IGTK, BIGTK) |
| `slsi_mlme_get_key()` | `MLME_GET_KEY_SEQUENCE_REQ → MLME_GET_KEY_SEQUENCE_CFM` | Read key RSC (8-octet sequence counter) |

### Power Management

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_powermgt()` | `MLME_POWERMGT_REQ → MLME_POWERMGT_CFM` | Set PS mode (guarded by global `powermgt_lock`) |
| `slsi_mlme_twt_setup()` | (internal) | TWT setup negotiation |
| `slsi_mlme_twt_teardown()` | (internal) | TWT teardown |
| `slsi_mlme_twt_status_query()` | (internal) | Query TWT status |
| `slsi_mlme_sched_pm_setup()` | (internal) | Scheduled PM setup |
| `slsi_mlme_sched_pm_teardown()` | (internal) | Scheduled PM teardown |
| `slsi_mlme_set_delayed_wakeup()` | (internal) | Enable delayed wakeup |

### MIB (Management Information Base) Access

The MLME module provides the primary path for reading/writing firmware MIB values:

| Function | FAPI Signal | Description |
|---|---|---|
| `slsi_mlme_set()` | `MLME_SET_REQ → MLME_SET_CFM` | Set MIB value(s) for a VIF |
| `slsi_mlme_get()` | `MLME_GET_REQ → MLME_GET_CFM` | Read MIB value(s) |
| `slsi_mlme_get_with_vifidx()` | `MLME_GET_REQ → MLME_GET_CFM` | Read MIBs with explicit VIF index |
| `slsi_mlme_get_by_link()` | (internal, EHT) | Read MIBs per MLO link |
| `slsi_read_mibs()` | (internal) | Batch MIB read via [[mib|mib.h]] |
| `slsi_mlme_get_sinfo_mib()` | (internal) | Read station info MIBs |

MIB errors are returned via the separate `mib_error` skb field in
`slsi_mlme_req_cfm_mib()`.

### Regulatory & SAR

| Function | Description |
|---|---|
| `slsi_mlme_set_country()` | Set regulatory country code |
| `slsi_mlme_sar_set_index()` | Set SAR DSI index |
| `slsi_mlme_sar_get_tx_power_limit()` | Query per-antenna TX power limits |
| `slsi_mlme_sar_get_avg_tx_power()` | Query averaged TX power |
| `slsi_mlme_sar_get_max_tx_power()` | Query max TX power |

### Channel Management

| Function | Description |
|---|---|
| `slsi_mlme_set_channel()` | Set channel with availability duration/interval/count |
| `slsi_mlme_unset_channel_req()` | Release explicit channel hold |
| `slsi_mlme_channel_switch()` | Trigger channel switch |
| `slsi_check_channelization()` | Validate chandef against regulatory rules |
| `slsi_mlme_set_band_req()` | Set preferred band |

### Other Operations

| Function | Description |
|---|---|
| `slsi_mlme_register_action_frame()` | Register action frame categories to forward |
| `slsi_mlme_send_frame_mgmt()` | Send management frame via firmware |
| `slsi_mlme_send_frame_data()` | Send data frame via MLME path |
| `slsi_mlme_set_acl()` | Set MAC address ACL |
| `slsi_mlme_set_traffic_parameters()` | Set user-priority traffic params |
| `slsi_mlme_set_keepalive_parameters()` | Set keepalive interval |
| `slsi_mlme_synchronised_response()` | External authentication response |
| `slsi_mlme_add_info_elements()` | Add/update IEs |
| `slsi_mlme_add_range_req()` | FTM (RTT) range request |
| `slsi_mlme_del_range_req()` | Cancel range request |
| `slsi_mlme_tdls_action()` | TDLS (Direct Link Setup) action |
| `slsi_mlme_set_tdls_state()` | Enable/disable TDLS |
| `slsi_mlme_set_p2p_noa()` | P2P Notice of Absence |
| `slsi_mlme_set_rssi_monitor()` | RSSI threshold monitoring |
| `slsi_mlme_set_ext_capab()` | Extended capability bits |
| `slsi_mlme_set_ctwindow()` | Country channel time window |
| `slsi_mlme_wifisharing_permitted_channels()` | WiFi sharing channel list |
| `slsi_mlme_delba_req()` | Block-ACK teardown |
| `slsi_mlme_set_packet_filter()` | Install packet filter patterns |
| `slsi_mlme_set_multicast_ip()` | Set multicast IP list |
| `slsi_mlme_configure_monitor_mode()` | Monitor mode configuration |
| `slsi_mlme_set_host_state()` | Set host power state |
| `slsi_mlme_wtc_mode_req()` | WiFi-to-Cellular offload mode |
| `slsi_mlme_set_cached_channels()` | Cached BSS channel list |

### EHT/MLO-Specific Operations (`CONFIG_SCSC_WLAN_EHT`)

| Function | Description |
|---|---|
| `slsi_mlme_ml_link_state_query()` | Query MLO link state |
| `slsi_mlme_ml_link_state_control()` | Activate/deactivate links |
| `slsi_mlme_get_mlo_link_state()` | Get link info struct |
| `slsi_mlme_ml_tid_mapping_request()` | TID-to-link mapping |
| `slsi_mlme_get_ml_tid_mapping_status()` | Query TID mapping |
| `slsi_mlme_get_measure_ml_channel_condition()` | Channel quality measurement |
| `slsi_mlo_link_vif_to_link_id_mapping()` | Map VIF index to link ID |
| `slsi_mlme_append_link_address()` | Derive per-link MAC addresses |
| `slsi_mlme_scan_all_ml_link()` | Scan across all MLO links |

## Frequency Encoding

The firmware uses half-MHz units for frequency: `SLSI_FREQ_HOST_TO_FW(f) = f * 2`,
`SLSI_FREQ_FW_TO_HOST(f) = f / 2`.

## Call Graph

```
cfg80211_ops.c (nl80211 callbacks)
    ├── slsi_mlme_add_vif() / slsi_mlme_del_vif()      // VIF creation/destruction
    ├── slsi_mlme_connect()                             // Station connect
    ├── slsi_mlme_disconnect()                          // Station disconnect
    ├── slsi_mlme_roam()                                // Autonomous roaming
    ├── slsi_mlme_add_scan() / slsi_mlme_add_sched_scan() // Scanning
    ├── slsi_mlme_set_key()                             // Key management
    ├── slsi_mlme_channel_switch()                      // Channel operations
    ├── slsi_mlme_powermgt()                            // Power save
    └── slsi_mlme_get_sinfo_mib()                       // Station info queries
        │
        └── slsi_mlme_tx_rx()  ←  core blocking primitive
            ├── slsi_tx_control()                       // [[subsystems/hip|HIP]] TX
            ├── slsi_mlme_wait_for_cfm()                // wait for confirm
            └── slsi_mlme_wait_for_ind()                // wait for indication
                │
                └── slsi_rx_blocking_signals()  ←  HIP RX handler dispatches
```

## Module Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `missing_cfm_ind_panic` | `bool` | `true` | Panic on lost firmware confirm/indication |

## Related

- [[subsystems/cfg80211_ops|cfg80211_ops]] — nl80211 callbacks that call into MLME
- [[subsystems/hip|HIP]] — Host Interface Processor transport for FAPI signals
- [[subsystems/rx|RX Processing]] — `slsi_rx_blocking_signals()` dispatches confirm/indication responses
- [[subsystems/mib|MIB System]] — Firmware Management Information Base accessed via MLME
- [[subsystems/dev|Device Structure]] — `struct slsi_dev` and `struct netdev_vif` hold per-device and per-VIF state

## Recent changes

- Initial seed page created from full source review of mlme.c (~8200 lines) and mlme.h (~833 lines).
