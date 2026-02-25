# nRF5340 BLE Peripheral Example

Standalone Zephyr BLE peripheral for the nRF5340 DK. No peer device needed — connect
with any phone running [nRF Connect](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile)
or any BLE central.

Demonstrates the three core GATT patterns:

| Characteristic | UUID | Property | What it shows |
|---|---|---|---|
| Sensor | EAB20002 | **Notify** | Server pushes data without polling; CCCD; backpressure |
| Control | EAB20003 | **Write** | Client sends commands; write handler; error responses |
| Status | EAB20004 | **Read** | Client polls state; read handler; struct encoding |

## Hardware

- nRF5340 DK (PCA10095)
- USB cable (J-Link onboard)

## Build and Flash

```bash
export ZEPHYR_BASE=~/zephyrproject/zephyr

cd examples/nrf5340-ble-peripheral
west build -b nrf5340dk_nrf5340_cpuapp
eabctl flash --chip nrf5340 --runner jlink
```

## Monitor with EAB

```bash
# Start RTT log capture (all BLE events appear here)
eabctl rtt start --device NRF5340_XXAA_APP --transport jlink

# Tail live output
eabctl rtt tail 50

# Send shell commands
eabctl send "ble status"
eabctl send "ble fast"
eabctl send "ble slow"
eabctl send "ble off"
eabctl send "ble disconnect"
```

## Connect with nRF Connect App

1. Open nRF Connect → Scan → find **EAB-Peripheral**
2. Connect
3. Go to **Client** tab → expand the EAB service (EAB20001)
4. **Enable notifications** on EAB20002 (tap the three arrows icon) → sensor data streams
5. **Write** to EAB20003: send `01` (fast), `02` (slow), or `03` (off)
6. **Read** EAB20004: shows uptime, notify count, connection count, mode

## Expected RTT Output

### Boot
```
[00:00:00.001] ========================================
[00:00:00.001]   EAB BLE Peripheral v1.0
[00:00:00.001] ========================================
[00:00:00.002] Settings loaded (bonding keys restored)
[00:00:00.010] BLE initialized
[00:00:00.011] Advertising as: EAB-Peripheral
[00:00:00.012] Ready — connect with nRF Connect app or any BLE central
```

### Connection + MTU Exchange
```
[00:00:05.210] === CONNECTED ===
[00:00:05.210]   Peer:     XX:XX:XX:XX:XX:XX (random)
[00:00:05.210]   Interval: 45 ms
[00:00:05.210]   Latency:  0 events
[00:00:05.210]   Timeout:  5000 ms
[00:00:05.210]   Security: L1
[00:00:05.211] MTU exchange requested...
[00:00:05.350] MTU exchanged: 247 (payload capacity: 244 bytes)
```

### Notification Stream
```
[00:00:06.100] CCCD: client subscribed to notifications (value=0x0001)
[00:00:06.100] DATA: counter=0 temp=24.50 notify_count=1
[00:00:07.100] DATA: counter=1 temp=24.51 notify_count=2
[00:00:07.100] DATA: counter=2 temp=24.52 notify_count=3
```

### Backpressure (TX buffer full)
```
[00:00:10.500] WRN: TX buffer full (err=-12), backoff — reduce notify rate
```
*This happens if notify rate exceeds what the LL can drain. Switch to slow mode.*

### Disconnect
```
[00:00:30.000] === DISCONNECTED ===
[00:00:30.000]   Peer:   XX:XX:XX:XX:XX:XX (random)
[00:00:30.000]   Reason: 0x13 (remote-user-terminated)
[00:00:30.001] Advertising as: EAB-Peripheral
```

## EAB Regression Test

```bash
eabctl regression --test tests/hw/nrf5340_ble_peripheral.yaml --json
```

## Key BLE Concepts Demonstrated

### CCCD (Client Characteristic Config Descriptor)
The sensor characteristic has `BT_GATT_CHRC_NOTIFY` but the client receives **nothing**
until it writes `0x0001` to the CCCD descriptor. This is the #1 "why am I not getting
notifications?" bug. The `cccd_changed()` callback fires when the client subscribes.

### MTU Negotiation
Default ATT MTU = 23 bytes → 20-byte payload. After exchange → 247 bytes → 244-byte
payload. This example requests MTU immediately in `connected_cb()`. Both sides must
request it — if only one side does, the minimum wins.

### Backpressure on Notify
`bt_gatt_notify()` returns `-ENOMEM` when TX buffers are full. Ignoring this silently
drops data. This example logs the error and backs off. Real fix: use `bt_gatt_notify_cb()`
with a "sent" callback to know when a buffer slot is freed.

### Bond Key Persistence
`settings_load()` is called **before** `bt_enable()`. Without this, bond keys are
lost on every reboot and the client must re-pair. With it, reconnection is seamless.

### Write Without Response
The control characteristic supports both `WRITE` and `WRITE_WITHOUT_RESP`. The client
can choose: Write gets an ATT acknowledgment (reliable), Write Without Response is
faster but fire-and-forget.
