---
title: mbulk_def
kind: entity
covers:
  - pcie_scsc/mbulk_def.h
last_synced_sha: de8720511fda4cd10d6d358ad754412658bf9024
last_synced: "2026-05-17T07:26:00Z"
sources:
  - pcie_scsc/mbulk_def.h
  - pcie_scsc/mbulk.h
  - pcie_scsc/mbulk.c
---

# mbulk_def

`mbulk_def.h` defines the core `struct mbulk` — the **bulk memory descriptor** used by the SCSC PCIe driver to manage shared memory buffers between the host Linux driver and the embedded firmware. The structure is `__packed` because it lives in a shared (MIF) address space visible to both CPU and firmware.

The header is designed to be a **private, in-line-friendly layer**: `mbulk.h` explicitly `#include`s it so callers can access struct members directly (enabling compiler inlining), while discouraging client code from calling `mbulk_seg_xxx()` helpers. Instead, clients should prefer the public `mbulk_xxx()` wrapper APIs in [[raw/pcie_scsc/mbulk|mbulk]].

## Buffer layout

Each mbulk segment has a fixed-on-disk memory layout:

```
+-------------+----------+--------+-----------+----------+
| struct      | optional |  reserved  | valid data |  tail  |
|  mbulk      | signal   | (headroom) |  (len bytes) |room  |
+-------------+----------+--------+-----------+----------+
  sizeof()     sig_bufsz   head-sig   len        dat-tail
```

The diagram in [[raw/pcie_scsc/mbulk|mbulk]] documents this in detail. Key size fields:

| Field | Type | Meaning |
|---|---|---|
| `dat_bufsz` | `mbulk_len_t` (u16) | Total data buffer capacity (bytes), excluding `struct mbulk` and signal |
| `sig_bufsz` | `mbulk_len_t` (u16) | Optional in-lined signal buffer size (bytes) |
| `len` | `mbulk_len_t` (u16) | Current valid data length |
| `head` | `mbulk_len_t` (u16) | Byte offset from `struct mbulk` end to the start of valid data (accounts for signal buffer + headroom) |

## Key data structures

### `struct mbulk`

```c
typedef u16 mbulk_len_t;
struct mbulk {
    scsc_mifram_ref  next_offset;       /* next free-list mbulk offset */
    u8               flag;              /* mbulk flags */
    enum mbulk_class clas;              /* bulk buffer classification */
    u8               pid;               /* mbulk pool id */
    u8               refcnt;            /* reference counter */
    mbulk_len_t      dat_bufsz;         /* data buffer size in byte */
    mbulk_len_t      sig_bufsz;         /* signal buffer size in byte */
    mbulk_len_t      len;               /* valid data length */
    mbulk_len_t      head;              /* start offset of data after mbulk struct */
    scsc_mifram_ref  chain_next_offset; /* chain next mbulk offset */
} __packed;
