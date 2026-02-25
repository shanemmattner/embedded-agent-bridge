# BLE Interview Prep — OpenAI Embedded Device Team
*Shane Mattner | 2026-02-25*

---

## 1. BLE Stack Architecture

### Layers (bottom to top)
```
┌─────────────────────────────────────────┐
│  Application (your firmware)            │
├─────────────────────────────────────────┤
│  GAP  │  GATT  │  SMP                   │  Host
├───────┴────────┴─────────────────────────┤
│  L2CAP (Logical Link Control)           │
├─────────────────────────────────────────┤
│  HCI (Host Controller Interface)        │
├─────────────────────────────────────────┤
│  LL (Link Layer)                        │  Controller
├─────────────────────────────────────────┤
│  PHY (Physical Layer — 2.4 GHz RF)     │
└─────────────────────────────────────────┘
```

### nRF5340 Dual-Core Split
- **Network core** (Cortex-M33 @ 64 MHz): runs BLE controller (LL + HCI). Ships Nordic's `hci_rpmsg` image or Zephyr `hci_ipc`.
- **App core** (Cortex-M33 @ 128 MHz): runs BLE host (L2CAP, GAP, GATT, SMP) + your application.
- They communicate over **IPC** (inter-processor communication) using shared memory + doorbell interrupts.
- **Practical implication**: OTA update must update **both** cores. Forgetting to update `hci_rpmsg` after a BLE controller change is a real bug — you'll get HCI version mismatches.

### SoftDevice vs Zephyr BT Stack
| | SoftDevice | Zephyr BT |
|---|---|---|
| Vendor | Nordic | Open-source |
| API | `sd_ble_*` proprietary | `bt_*` standard |
| Cert | Pre-certified (QDID) | Per-product cert needed |
| Config | Runtime API calls | Kconfig compile-time |
| Reliability | Battle-tested | Very good, actively developed |
| Use when | Need prebuilt certification, legacy NCS projects | Zephyr RTOS projects, open source, newer NCS |

**Interview answer**: "I use the Zephyr stack in NCS because it integrates cleanly with Zephyr's power management, kernel, and logging. SoftDevice is better when you need to ship with a pre-existing QDID."

---

## 2. GAP — Advertising & Scanning

### Advertising PDU Types
| PDU | Connectable | Scannable | Directed | Use Case |
|-----|-------------|-----------|----------|----------|
| `ADV_IND` | ✅ | ✅ | ❌ | Normal peripheral advertising |
| `ADV_DIRECT_IND` | ✅ | ❌ | ✅ | Fast reconnect to known central |
| `ADV_NONCONN_IND` | ❌ | ❌ | ❌ | Beacons, iBeacon, Eddystone |
| `ADV_SCAN_IND` | ❌ | ✅ | ❌ | Non-connectable but accepts scan requests |

**BLE 5.0 Extended Advertising** (`ADV_EXT_IND`):
- Payload up to **254 bytes** (vs 31 bytes legacy)
- Coded PHY (125 kbps / 500 kbps) for long range (4× / 2× range)
- Multi-PHY: advertise on 1M, switch connection to 2M for throughput
- Zephyr: `bt_le_ext_adv_create()`, `bt_le_ext_adv_start()`

### Scanning
```
Scan interval: how often to open the scan window
Scan window:   how long to listen each interval
Duty cycle = window/interval → power vs. discovery speed

Passive scan: just receive ADV packets → lower power
Active scan:  send SCAN_REQ → get SCAN_RSP → more data (device name etc.)
```

**Pitfall**: If scan window = scan interval, the radio is on 100% of the time → battery drain. Fast scan (100%): quick discovery, then drop to 10% duty cycle.

### Connection Establishment
1. Central calls `bt_conn_le_create()` → sends `CONNECT_IND` PDU
2. Peripheral stops advertising, both enter connected state
3. Connection parameters negotiated: `interval`, `latency`, `timeout`

```c
// From nrf5340-ble-hub: central connecting to EAB-ESP32C6
static void scan_recv_cb(const struct bt_le_scan_recv_info *info,
                         struct net_buf_simple *ad)
{
    // ... parse ad data for name "EAB-ESP32C6" ...
    bt_le_scan_stop();
    struct bt_conn *conn = NULL;
    int err = bt_conn_le_create(info->addr,
                                BT_CONN_LE_CREATE_CONN,
                                BT_LE_CONN_PARAM_DEFAULT,
                                &conn);
    bt_conn_unref(conn);  // CRITICAL: unref immediately, stack holds its own ref
}
```

**Connection parameters**:
```
interval:  7.5ms – 4000ms  (units: 1.25ms)
latency:   0–499 connection events (peripheral can skip)
timeout:   100ms – 32s     (units: 10ms)
Rule: timeout > (1 + latency) * interval * 2
```

**Zephyr peripheral advertising**:
```c
static const struct bt_data ad[] = {
    BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
    BT_DATA_BYTES(BT_DATA_UUID16_ALL, BT_UUID_16_ENCODE(BT_UUID_HRS_VAL)),
};
static const struct bt_data sd[] = {
    BT_DATA(BT_DATA_NAME_COMPLETE, DEVICE_NAME, DEVICE_NAME_LEN),
};
bt_le_adv_start(BT_LE_ADV_CONN, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
```

---

## 3. GATT — Generic Attribute Profile

### Roles
- **GATT Server**: holds the attribute database (peripheral, usually)
- **GATT Client**: reads/writes/subscribes (central, usually)
- These are **independent** of GAP roles. A central can be a GATT server.

### Attribute Structure
```
Service (UUID 0x180D — Heart Rate)
  └── Characteristic (UUID 0x2A37 — HR Measurement)
        ├── Value (the actual data bytes)
        ├── CCCD (0x2902 — Client Characteristic Config Descriptor)
        └── Characteristic User Description (0x2901 — optional)
```

### UUID Types
- **16-bit SIG**: assigned by Bluetooth SIG (e.g., `0x180D` HRS, `0x2A37` HR Measurement)
- **128-bit custom**: for proprietary services

```c
// Custom 128-bit UUID in Zephyr (from nrf5340-ble-hub)
static struct bt_uuid_128 svc_uuid = BT_UUID_INIT_128(
    BT_UUID_128_ENCODE(0xEAB10001, 0x0000, 0x1000, 0x8000, 0x00805F9B34FB)
);
```

### Characteristic Properties
| Property | Direction | ACK? | Use |
|---|---|---|---|
| Read | Client ← Server | Yes | Poll current value |
| Write | Client → Server | Yes | Commands, config |
| Write Without Response | Client → Server | No | High-speed, fire-and-forget |
| Notify | Server → Client | No | Streaming data |
| Indicate | Server → Client | Yes | Reliable delivery |

### CCCD — Client Characteristic Config Descriptor
- 2-byte descriptor at handle `char_handle + 2` (usually)
- Client **must write** `0x0001` (notify) or `0x0002` (indicate) to subscribe
- Server does NOT automatically push data — client enables it

**Common bug**: Client connects but forgets to write CCCD → no notifications received.

```c
// Server side: Zephyr GATT service definition
BT_GATT_SERVICE_DEFINE(my_svc,
    BT_GATT_PRIMARY_SERVICE(&svc_uuid),
    BT_GATT_CHARACTERISTIC(&chr_uuid.uuid,
        BT_GATT_CHRC_NOTIFY,
        BT_GATT_PERM_NONE,
        NULL, NULL, NULL),
    BT_GATT_CCC(ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

// Send notification
static uint8_t my_data[20];
bt_gatt_notify(conn, &my_svc.attrs[1], my_data, sizeof(my_data));
```

### MTU Negotiation
```
Default ATT_MTU = 23 bytes
ATT overhead = 3 bytes (opcode + handle)
Default payload = 23 - 3 = 20 bytes per notification

After MTU exchange (e.g., ATT_MTU = 247):
Payload = 247 - 3 = 244 bytes

BLE 5.0 DLE (Data Length Extension):
LL PDU payload up to 251 bytes (vs 27 legacy)
ATT_MTU can be up to 512 bytes but LL limits effective throughput
```

**Pitfall**: Both sides must request large MTU. If only the peripheral requests 247 but the central doesn't, negotiation takes the minimum.

```c
// Client: request larger MTU after connection
static void mtu_exchange_cb(struct bt_conn *conn, uint8_t err,
                            struct bt_gatt_exchange_params *params)
{
    if (err) {
        LOG_ERR("MTU exchange failed: %u", err);
    } else {
        LOG_INF("MTU exchanged: %u", bt_gatt_get_mtu(conn));
    }
}

static struct bt_gatt_exchange_params mtu_params;
mtu_params.func = mtu_exchange_cb;
bt_gatt_exchange_mtu(conn, &mtu_params);
```

### GATT Discovery (Client Side)
```c
// From nrf5340-ble-hub: discover characteristic, then subscribe
static struct bt_gatt_discover_params disc_params;

static uint8_t discover_cb(struct bt_conn *conn,
                           const struct bt_gatt_attr *attr,
                           struct bt_gatt_discover_params *params)
{
    if (!attr) {
        LOG_INF("GATT discovery complete");
        return BT_GATT_ITER_STOP;
    }
    if (params->type == BT_GATT_DISCOVER_CHARACTERISTIC) {
        struct bt_gatt_chrc *chrc = attr->user_data;
        notify_value_handle = chrc->value_handle;
        // now subscribe...
        return BT_GATT_ITER_STOP;
    }
    return BT_GATT_ITER_CONTINUE;
}

disc_params.uuid = &chr_notify_uuid.uuid;
disc_params.func = discover_cb;
disc_params.start_handle = BT_ATT_FIRST_ATTRIBUTE_HANDLE;
disc_params.end_handle   = BT_ATT_LAST_ATTRIBUTE_HANDLE;
disc_params.type = BT_GATT_DISCOVER_CHARACTERISTIC;
bt_gatt_discover(conn, &disc_params);
```

---

## 4. Security Manager Protocol (SMP)

### Pairing Methods
| Method | MITM Protection | Use Case |
|---|---|---|
| Just Works | ❌ | Headless devices, low-security |
| Passkey Entry | ✅ | One side displays, other enters 6-digit PIN |
| OOB (Out-of-Band) | ✅ (if OOB channel is secure) | NFC-based pairing |
| LESC (LE Secure Connections) | ✅ | BLE 4.2+, ECDH key exchange |

**LESC** uses Elliptic Curve Diffie-Hellman — even if passive observer captures all air packets, they can't derive the session key.

### Bonding vs Pairing
- **Pairing**: exchange keys for current session
- **Bonding**: store keys persistently → reconnect without re-pairing

**Key types distributed**:
- **LTK** (Long-Term Key): encrypts future connections
- **IRK** (Identity Resolving Key): resolves Resolvable Private Addresses (RPAs)
- **CSRK** (Connection Signature Resolving Key): signs data

```c
// Zephyr: set security level on connection
bt_conn_set_security(conn, BT_SECURITY_L2);  // L2 = encrypted, no MITM
bt_conn_set_security(conn, BT_SECURITY_L4);  // L4 = LESC + MITM

// Callbacks
static struct bt_conn_auth_cb auth_cbs = {
    .passkey_display = passkey_display,
    .passkey_confirm = passkey_confirm,
    .cancel = auth_cancel,
};
bt_conn_auth_cb_register(&auth_cbs);
```

**Critical pitfall**: Bond keys stored in NVS/settings subsystem. If settings not initialized, keys lost on reboot → forced re-pair every boot. Fix:
```c
settings_load();  // MUST call before bt_enable()
```

### RPA (Resolvable Private Addresses)
- Device rotates MAC address every ~15 minutes to prevent tracking
- Peer must have your IRK to resolve the rotating address
- If peer doesn't have IRK → can't reconnect (sees "unknown device")
- Zephyr: `CONFIG_BT_PRIVACY=y` enables RPA generation

---

## 5. L2CAP — Connection-Oriented Channels

### Why L2CAP CoC Instead of GATT for High Throughput
```
GATT path:  App → GATT layer → ATT → L2CAP → LL → RF
L2CAP CoC:  App → L2CAP → LL → RF

GATT notification overhead per packet: ~7 bytes headers
L2CAP CoC overhead: ~4 bytes (SDU length + L2CAP header)
```

L2CAP CoC uses **credit-based flow control**:
- Server grants N credits to client
- Client sends N SDUs then waits for more credits
- Prevents buffer overflow without application-level acks

**When to use L2CAP CoC**: file transfer, audio streaming, bulk sensor data >10KB/s.

```c
// Zephyr L2CAP CoC server
static struct bt_l2cap_le_chan my_chan;
static int l2cap_accept(struct bt_conn *conn, struct bt_l2cap_chan **chan) {
    my_chan.rx.mtu = 512;
    *chan = &my_chan.chan;
    return 0;
}
static struct bt_l2cap_server srv = {
    .psm = 0x0080,  // dynamic PSM
    .accept = l2cap_accept,
};
bt_l2cap_server_register(&srv);
```

---

## 6. Power Management

### Advertising Power Ladder
```
Fast advertising:  20ms interval   → ~8mA peak, drains battery fast
                                     Use for ~30s after power-on
Slow advertising:  1280ms interval → ~0.2mA average, acceptable background
Connected, active: 7.5ms interval  → high throughput, high power
Connected, idle:   1000ms + slave latency 4 → essentially sleeping between events
```

### Connection Parameter Strategy
```
Connection interval:  7.5ms (gaming/audio) → 1000ms (IoT sensors)
Peripheral latency:   0–499 events peripheral can skip
Supervision timeout:  must be > (1 + latency) * interval * 2

Low power recipe for heart rate monitor:
  interval = 1000ms
  latency = 0 (must wake every event to check for new HR data)
  timeout = 6000ms
  → device wakes 1×/sec, sends HR, sleeps rest of time
```

### Zephyr Power Management Integration
```c
// prj.conf
CONFIG_PM=y
CONFIG_PM_DEVICE=y
CONFIG_BT_CTLR_SLEEP_CLOCK_ACCURACY=500  // 500ppm LFXO

// In firmware: allow system to sleep between BLE events
// Zephyr BT stack coordinates with PM automatically when CONFIG_PM=y
// The radio wakes on schedule for connection events
```

### Measuring Power
- **PPK2** (Nordic Power Profiler Kit 2): hardware current measurement, integrates with nRF Connect for Desktop
- **J-Link Power Profiler**: built into SEGGER tools
- Key metric: **average current**, not peak. A 5ms 20mA peak every 1s = 100µA average.

---

## 7. Common Pitfalls & Bugs

### 1. Connection Drops
**Symptom**: `disconnected (reason=0x08)` — connection timeout
**Cause**: supervision timeout expired because:
- RF interference (microwave, WiFi 2.4GHz, other BLE)
- Peripheral too slow to wake from sleep (LFXO drift)
- Supervision timeout too short vs. latency setting

**Debug**: `CONFIG_BT_DEBUG_CONN=y`, check disconnect reason codes:
- `0x08` = connection timeout
- `0x13` = remote user terminated
- `0x3B` = unacceptable connection parameters

### 2. Throughput Bottlenecks
Throughput = `(ATT_MTU - 3) * (1000ms / conn_interval_ms)`

Checklist:
1. `CONFIG_BT_L2CAP_TX_MTU=247` and `CONFIG_BT_BUF_ACL_RX_SIZE=251`
2. Both sides request MTU 247 (`bt_gatt_exchange_mtu`)
3. Enable DLE: `CONFIG_BT_CTLR_DATA_LENGTH_MAX=251`
4. Connection interval ≤ 15ms for max throughput
5. Use Write Without Response instead of Write (no ACK wait)

```c
// From nrf5340-ble-hub prj.conf (these are the right values)
CONFIG_BT_L2CAP_TX_MTU=247
CONFIG_BT_BUF_ACL_RX_SIZE=251
CONFIG_BT_BUF_ACL_TX_SIZE=251
```

### 3. Dropped Notifications — No Flow Control
**Symptom**: `bt_gatt_notify()` returns `-ENOMEM` or `-ENOBUFS`
**Cause**: TX buffer pool exhausted — you're calling notify faster than LL can send

**Fix**: Check return value and backpressure:
```c
int err = bt_gatt_notify(conn, &attr, data, len);
if (err == -ENOMEM) {
    // back off — schedule retry via k_work_schedule
}
```
Or use `bt_gatt_notify_cb()` with a sent callback to know when buffer is freed.

### 4. CCCD Not Persisted Across Reconnect
**Symptom**: Server sends notifications, client receives nothing after reconnect
**Cause**: CCCD is in volatile RAM. When client disconnects and reconnects (using bond/LTK), it expects CCCDs to be restored from non-volatile storage.

**Fix**: Enable `CONFIG_BT_SETTINGS=y` + `CONFIG_SETTINGS=y`. Zephyr's GATT layer will persist CCCDs to NVS automatically.

### 5. RPA / IRK — Peer Can't Reconnect
**Symptom**: Central can't find peripheral after initial pairing. RSSI shows device present but never resolves.
**Fix**: `CONFIG_BT_PRIVACY=y` on peripheral + ensure IRK exchanged during bonding + peer stores IRK.

### 6. MTU Mismatch — Half-Sized Payloads
**Symptom**: Throughput exactly 20 bytes/packet despite large MTU configured
**Cause**: Only one side requested large MTU. The other kept default 23.
**Debug**: `LOG_INF("MTU: %u", bt_gatt_get_mtu(conn))` after exchange.

### 7. Race: MTU Exchange Before Discovery
From `nrf5340-ble-hub`: after `connected_cb`, we exchange MTU, then `k_msleep(500)`, then subscribe. The sleep is a workaround — proper fix is to chain: `connected → MTU exchange → MTU callback → discovery → discovery callback → subscribe`.

```c
// The ble-hub code (working but hacky):
connected_cb() → bt_gatt_exchange_mtu() → k_msleep(500) → subscribe_to_notifications()

// Proper fix:
connected_cb() → bt_gatt_exchange_mtu()
mtu_exchange_cb() → bt_gatt_discover()
discover_cb() → bt_gatt_subscribe()
```

### 8. nRF5340-Specific: Net Core OTA
When doing OTA firmware update, you have two images:
1. `app_core.hex` — your application
2. `net_core.hex` — Nordic's HCI controller (hci_rpmsg)

If you update only the app core and the BLE HCI API changed → undefined behavior, assertion failures, random disconnects. MCUboot + mcumgr handle this with a "network core update" slot.

### 9. Memory: k_mem_slab and BT Buffers
```
CONFIG_BT_RX_BUF_COUNT=8    # number of RX ACL buffers
CONFIG_BT_CONN_TX_MAX=7     # TX queue depth per connection
```
Too low → `-ENOMEM` on notify. Too high → wastes SRAM.
On nRF5340 app core: **512KB SRAM**, share with stack, heap, and BT buffers.

---

## 8. Debugging BLE on nRF5340 with Zephyr

### Enable Verbose BT Logging
```ini
# prj.conf — turn these on to debug specific issues
CONFIG_BT_LOG_LEVEL_DBG=y        # all BT logs
CONFIG_BT_DEBUG_CONN=y           # connection events, param updates
CONFIG_BT_DEBUG_GATT=y           # GATT reads/writes/notify
CONFIG_BT_DEBUG_ATT=y            # ATT protocol level
CONFIG_BT_DEBUG_SMP=y            # pairing/bonding
CONFIG_BT_DEBUG_L2CAP=y          # L2CAP channels
CONFIG_BT_DEBUG_HCI_CORE=y       # HCI commands/events
```

**Warning**: enabling all simultaneously floods RTT buffer. Enable one layer at a time.

### RTT Shell BT Commands
```bash
# via eabctl send or RTT shell:
bt init              # initialize BT (if not done at boot)
bt scan on           # start active scan
bt connect <addr>    # connect to specific device
bt security 2        # request encryption
bt gatt-show         # show own GATT database
bt auth-passkey 123456
bt disconnect
```

### EAB Workflow for BLE Debugging
```bash
# 1. Start RTT monitoring (captures all LOG_INF/ERR/DBG output)
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink

# 2. Tail live BLE stack output
eabctl rtt tail 100

# 3. When firmware crashes (BT stack assertion):
eabctl fault-analyze --device NRF5340_XXAA_APP --json
# → decodes CFSR, HFSR, PC at crash, full register dump

# 4. Hardware-in-the-loop BLE regression test
eabctl regression --test tests/hw/ble_smoke.yaml --json
```

### Example Regression YAML for BLE
```yaml
name: nRF5340 BLE Smoke Test
device: nrf5340
chip: nrf5340
timeout: 60

setup:
  - flash:
      firmware: examples/nrf5340-ble-hub
      runner: jlink

steps:
  - reset: {}
  - wait:
      pattern: "BLE initialized"
      timeout: 10
  - wait:
      pattern: "Scanning for EAB-ESP32C6"
      timeout: 5
  - fault_check:
      device: NRF5340_XXAA_APP
      expect_clean: true

teardown:
  - reset: {}
```

### nRF Sniffer (Wireshark)
1. Flash `nrf_sniffer_for_bluetooth_le` to a spare nRF52840 DK
2. Install Wireshark + Nordic's sniffer plugin
3. Capture all air packets: advertisements, connection setup, GATT transactions
4. **Best debugging tool** for: pairing failures, MTU negotiation, exact PDU timing

### Nordic nRF Connect App
- iOS/Android — scan, connect, read/write characteristics, enable notifications
- Essential for verifying your GATT database before building a client
- Can display raw hex + decoded service UUIDs

---

## 9. EAB — The Interview Story

### The Problem
LLM agents (Claude Code, Cursor, Copilot) operate in a read/write/run loop. Embedded dev requires **persistent sessions** — a serial monitor that stays open, a GDB connection, a JTAG interface. When an agent tries to run `minicom` or `GDB` directly:
- It blocks forever (interactive TTY)
- Loses state when it closes the session to read output
- Two tools fight for the same serial port

### The Solution
EAB turns interactive sessions into **file I/O + CLI calls**:

```
Agent ──eabctl──► RTT Daemon ──J-Link RTT──► nRF5340
  │
  ├── reads /tmp/eab-devices/nrf5340/rtt.log  (no blocking)
  ├── calls eabctl fault-analyze --json        (one-shot GDB)
  └── runs eabctl regression --json            (full HIL test suite)
```

### BLE-Specific Value
1. **RTT captures BT stack logs**: `eabctl rtt start` → agent reads `rtt.log` → sees `[BT_CONN] disconnected reason=0x08` → diagnoses supervision timeout automatically
2. **Fault analysis after BT assertion**: Nordic's BT stack will `k_oops()` on protocol violations → `eabctl fault-analyze` decodes the CFSR register, extracts PC → maps to source line via ELF
3. **Hardware regression**: `eabctl regression` YAML defines flash → boot → wait-for-pattern → assert-no-faults → deterministic BLE smoke test in CI

### How to Demo Live
```bash
# Device is connected, EAB daemon running
eabctl status --json          # show device health
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink
eabctl rtt tail 50            # show BLE log output live
# trigger a fault via shell: "fault null"
eabctl fault-analyze --device NRF5340_XXAA_APP --json
# shows: MPU FAULT, Faulting address, PC → main.c:42
```

---

## 10. Interview Q&A

### "Walk me through how a BLE connection is established"
> Peripheral advertises using `ADV_IND` PDUs every N milliseconds. Central scans — passive (just listens) or active (sends SCAN_REQ for extra data). Central finds target by name or UUID in the advertisement payload. Central sends `CONNECT_IND`, both devices transition to connected state. They negotiate connection parameters: interval, peripheral latency, supervision timeout. The first connection event is at `T_connect + interval`. After connection, the host layer exchanges ATT MTU and optionally initiates pairing/bonding.

### "How do you maximize BLE throughput?"
> Four levers: (1) **MTU**: both sides exchange MTU 247 → 244-byte payload per packet vs default 20. (2) **DLE (Data Length Extension)**: LL PDU extends to 251 bytes vs 27, enabled via `CONFIG_BT_CTLR_DATA_LENGTH_MAX=251`. (3) **Connection interval**: 7.5ms gives ~530KB/s theoretical max; 15ms for practical use. (4) **Write Without Response** instead of Write — eliminates ACK round-trip. Practical max on nRF5340 to phone: ~200-250KB/s with all four optimized.

### "How do you debug a BLE connection that drops randomly?"
> Start with disconnect reason code — `0x08` is timeout (RF/sleep issue), `0x13` is remote terminated (peer-side issue). Enable `CONFIG_BT_DEBUG_CONN=y` for detailed log. Use nRF Sniffer in Wireshark to capture air packets — verify connection events are happening on schedule, look for missing ACKs. Check supervision timeout vs. connection interval math. If using sleep: verify LFXO accuracy is within spec. With EAB: `eabctl rtt tail` shows real-time BT stack logs during the drop.

### "What's the difference between notify and indicate?"
> Both push data from server to client without the client polling. **Notify** is fire-and-forget — no acknowledgment, lower overhead, can drop packets if peer isn't ready. **Indicate** requires the client to send an ATT confirmation — guaranteed delivery but lower throughput. Use notify for streaming sensor data where occasional loss is OK (accelerometer, PPG). Use indicate for critical state changes (alarm, error status) where you need to know the client received it.

### "How does BLE pairing work, and what are the security tradeoffs?"
> Pairing is a three-phase process: (1) **Feature exchange** — both sides declare capabilities (display, keyboard, OOB support) → determines pairing method. (2) **Key generation** — Just Works generates a TK=0 (trivially attackable), Passkey Entry uses 6-digit PIN, LESC uses ECDH (not brute-forceable). (3) **Key distribution** — LTK for future encryption, IRK for address resolution, CSRK for signing. Tradeoffs: Just Works → no MITM protection, easy UX. Passkey → MITM protection, requires UI. LESC → best security, BLE 4.2+ required.

### "How do you handle firmware updates over BLE (OTA)?"
> On nRF5340 with Zephyr: MCUboot as the bootloader, mcumgr as the update protocol over BLE (SMP service). The update image is transferred via `BT_GATT` notifications/writes to the SMP server characteristic. MCUboot validates the image (SHA256 + signature if signing enabled), marks it as pending, reboots into it, validates again, and confirms. Key issues: (1) Must update both app core and net core images if BLE controller changed. (2) Large image transfer over BLE takes 2-5 minutes at typical throughputs — connection must be stable. (3) Power failure during update is safe if using MCUboot swap-scratch — image is only swapped after confirmed valid.

### "What are the power consumption tradeoffs in BLE peripheral design?"
> Three dominant power states: (1) **Advertising**: peak 7-10mA at TX, duty-cycled. 20ms interval = high average, 1280ms = low average. Use fast advertising for 30s after wake, slow thereafter. (2) **Connected, data**: 3-8mA during radio events. Connection interval and peripheral latency determine average. A heart rate monitor at 1000ms interval with 4 events latency is essentially sleeping. (3) **Sleep**: nRF5340 in System OFF: ~2µA. Between BLE events the MCU sleeps. Zephyr's `CONFIG_PM=y` coordinates MCU sleep with radio wakeup schedule via the power management subsystem.

### "Tell me about a hard embedded bug you debugged"
> I built EAB partly because of this class of bug. When integrating BLE notifications with a high-frequency sensor on the nRF5340, I kept seeing random drops in notification delivery. The BT stack returned `-ENOMEM` on `bt_gatt_notify()`, which I initially thought was a memory leak. Using EAB's RTT capture, I could see the BT log in real time: `CONFIG_BT_CONN_TX_MAX` was set too low, so the TX queue filled up when the sensor fired a burst. The fix was increasing `CONFIG_BT_CONN_TX_MAX` and adding backpressure in the notify path — check the return value and defer via `k_work_schedule()` if the buffer is full. Before EAB, diagnosing this required holding open a J-Link RTT Viewer session and manually reading logs — with EAB, the agent could read `rtt.log` and identify the pattern automatically.

---

## Quick Reference — prj.conf for BLE + Debugging

```ini
# Core BLE
CONFIG_BT=y
CONFIG_BT_PERIPHERAL=y          # or CENTRAL
CONFIG_BT_GATT_CLIENT=y         # for central role

# Throughput optimization
CONFIG_BT_L2CAP_TX_MTU=247
CONFIG_BT_BUF_ACL_RX_SIZE=251
CONFIG_BT_BUF_ACL_TX_SIZE=251
CONFIG_BT_CTLR_DATA_LENGTH_MAX=251

# Security / Bonding
CONFIG_BT_SMP=y
CONFIG_BT_PRIVACY=y
CONFIG_BT_SETTINGS=y
CONFIG_SETTINGS=y
CONFIG_NVS=y
CONFIG_FLASH=y
CONFIG_FLASH_PAGE_LAYOUT=y
CONFIG_FLASH_MAP=y

# RTT logging (EAB monitors this)
CONFIG_USE_SEGGER_RTT=y
CONFIG_RTT_CONSOLE=y
CONFIG_LOG=y
CONFIG_LOG_BACKEND_RTT=y
CONFIG_LOG_BACKEND_UART=n

# Debug (enable selectively)
CONFIG_BT_DEBUG_CONN=y
CONFIG_BT_DEBUG_GATT=y
CONFIG_BT_DEBUG_SMP=y
```

---

## Disconnect Reason Codes Cheat Sheet

| Code | Meaning | Likely Cause |
|------|---------|-------------|
| `0x08` | Connection timeout | RF interference, sleep clock drift |
| `0x13` | Remote user terminated | Peer app closed connection |
| `0x16` | Connection terminated by local host | You called `bt_conn_disconnect()` |
| `0x22` | LL response timeout | Peer not responding to LL control PDUs |
| `0x3A` | Controller busy | Controller overloaded |
| `0x3B` | Unacceptable connection params | Param update rejected |
| `0x3E` | Failed to establish | Connection attempt timed out |

---

*Good luck with the OpenAI interview. The EAB story is compelling — it's the right answer to "how do you integrate AI into embedded development."*
