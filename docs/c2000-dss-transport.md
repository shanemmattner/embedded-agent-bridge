# C2000 DSS Transport Architecture

## Overview

The DSS (Debug Server Scripting) transport provides persistent JTAG sessions
for high-frequency memory reads on TI C2000 targets. Instead of spawning a
DSLite subprocess per read (~60ms), it keeps a session open and sends commands
over websockets (~1.7ms per read = 33x faster).

## Architecture

```
                                   CCS 2041 Stack

  EAB Python   ──websocket──>  Cloud Agent (Node.js)  ──websocket──>  DSLite (C++)
  (dss.py)                     port auto-assigned                     port auto-assigned
                                   │                                      │
                                   │ manages lifecycle                    │ JTAG
                                   │ type conversions                     │ XDS110
                                   ▼                                      ▼
                               ccs_base/cloudagent/                   F280039C
```

### Three Access Methods

| Method | Latency | Complexity | Best For |
|--------|---------|------------|----------|
| DSLite subprocess | ~60 ms | Low | Single reads, scripts |
| Cloud Agent (Python API) | ~1.8 ms | Medium | **Default — use this** |
| Direct DSLite websocket | ~1.65 ms | High | If you need async/pipelining |

The cloud agent adds only ~0.15ms overhead — the XDS110 JTAG hardware is the
bottleneck, not the software stack. Use the Python API unless you need raw
websocket access.

## Performance (LAUNCHXL-F280039C, XDS110 USB)

| Operation | Time | Throughput |
|-----------|------|------------|
| Single 16-bit word | 1.8 ms | 555 reads/sec |
| 4-word bulk (8 bytes) | 2.2 ms | 454 reads/sec |
| 32-word bulk (64 bytes) | 3.4 ms | 18.8 KB/s |
| 200-word bulk (400 bytes) | 12.8 ms | 31.2 KB/s |
| 800-word bulk (1.6 KB) | 41 ms | 39 KB/s |
| DLOG 4-ch capture (3.2 KB) | 83 ms | 12 Hz snapshots |
| DSLite subprocess (baseline) | 60 ms | 17 reads/sec |

**Key insight**: Per-command overhead is ~1.5ms (websocket round-trip). Bulk
reads add ~0.05ms/word (JTAG transfer). For maximum throughput, read in large
chunks.

## CCS 2041 vs CCS 12.x (Eclipse)

CCS 2041 is Theia-based (not Eclipse). The old Rhino/Java DSS API
(`ScriptingEnvironment.instance()`, `debugSession.memory.readData()`) **does
not work**. The old `dss.sh` falls back to bare Rhino without DSS classes.

### Old API (CCS 12.x, Eclipse-based) — BROKEN on CCS 2041
```javascript
// dss_bridge.js — requires Eclipse runtime, won't work headless
importPackage(Packages.com.ti.debug.engine.scripting);
var script = ScriptingEnvironment.instance();  // FAILS: abstract class
var ds = script.getServer("DebugServer.1");
ds.setConfig(ccxml);
var session = ds.openSession(".*");
session.target.connect();
var words = session.memory.readData(0, addr, 16, numWords);
```

### New API (CCS 2041, Theia-based) — WORKS
```python
# Python — uses cloud agent + websockets under the hood
from scripting import initScripting, ScriptingOptions
ds = initScripting(ScriptingOptions(ccsRoot="/Applications/ti/ccs2041/ccs"))
ds.configure(ccxml_path)
session = ds.openSession(".*")
session.target.connect()
value = session.memory.readOne(0x7060)        # single word
words = session.memory.read(0x8000, 200)      # bulk read
session.memory.write(0x8000, [0x1234, 0x5678]) # write
ds.shutdown()
```

## DSLite WebSocket Protocol (Advanced)

DSLite (`ccs_base/DebugServer/bin/DSLite`) starts a WebSocket server when
invoked with no arguments:

```bash
$ DSLite
{ "port" : 55591 }
```

### Protocol: JSON over WebSocket

**Request**: `{"id": <int>, "command": "<string>", "data": [<args>]}`
**Response**: `{"response": <id>, "data": <result>}`
**Error**: `{"error": <id>, "data": {"message": "<string>"}}`
**Event**: `{"event": "<name>", "data": <payload>}` (progress, status, etc.)

### Connection Sequence

1. Connect to DSLite main websocket at `ws://127.0.0.1:<port>`
2. `scripting.configure` with CCXML path → returns `{cores: [...], nonDebugCores: [...]}`
3. `createSubModule` with core name → returns `{port: <int>}` for per-core websocket
4. Connect to per-core websocket at `ws://127.0.0.1:<core_port>`
5. `scripting.target.connect` → connects JTAG
6. `scripting.memory.readOne`/`scripting.memory.read`/`scripting.memory.write`

### Available Core Commands (190 total)

Key commands for debug:
- `scripting.target.{connect,disconnect,halt,run,reset,isHalted}`
- `scripting.memory.{read,readOne,write,fill,getPages,loadProgram}`
- `scripting.registers.{read,write,getBitfields,getRegisterGroups}`
- `scripting.expressions.evaluate` — evaluate C expressions
- `scripting.breakpoints.{add,remove}`
- `scripting.symbols.{load,lookupSymbols,getAddress}`
- `scripting.clock.{read,reset,enable}` — cycle counter
- `scripting.flash.performOperation` — flash programming

### Data Format Quirk

Direct DSLite returns values with format prefixes:
- `readOne` returns `"!bi:1"` (string with `!bi:` prefix for binary integer)
- `read` returns `["!bi:0", "!bi:0", ...]`
- The cloud agent's Python wrapper strips these and converts to `int`

## EAB Implementation

`eab/transports/dss.py` uses TI's Python scripting wrapper which handles:
- Cloud agent lifecycle (auto-start, auto-shutdown)
- WebSocket connection management
- Type conversion (strips `!bi:` prefixes)
- Error handling and timeouts

```python
from eab.transports.dss import DSSTransport

with DSSTransport(ccxml="~/.eab/ccxml/TMS320F280039C_XDS110.ccxml") as t:
    data = t.memory_read(0x7060, 2)  # Returns bytes, same as XDS110Probe
    t.memory_write(0x8000, b'\x34\x12')
    t.halt()
    t.resume()
```

## Source Code Locations

| Component | Path | Language |
|-----------|------|----------|
| EAB DSS transport | `eab/transports/dss.py` | Python |
| TI Python scripting | `ccs/scripting/python/site-packages/scripting/` | Python |
| TI sync agent | `scripting/python/site-packages/scripting/syncAgent.py` | Python |
| Cloud agent | `ccs_base/cloudagent/src/` | Node.js |
| DSLite module | `ccs_base/cloudagent/src/modules/dslite.js` | Node.js |
| DSLite binary | `ccs_base/DebugServer/bin/DSLite` | C++ (closed) |
| Old bridge (deprecated) | `eab/transports/dss_bridge.js` | Rhino JS |

## Could We Build Our Own Faster Transport?

**Short answer: No meaningful improvement possible.**

We benchmarked three approaches:
1. TI's Python API (cloud agent): **1.80 ms/read**
2. Direct DSLite websocket: **1.65 ms/read**
3. DSLite subprocess per read: **60 ms/read**

The cloud agent only adds 0.15ms. The bottleneck is the XDS110 USB-JTAG
hardware (~1.5ms per transaction). To go faster, you'd need:

- A different debug probe (J-Link at ~0.3ms/read)
- Batch/DMA reads in firmware (write results to known RAM, read once)
- ERAD hardware profiling (no reads needed — hardware captures autonomously)

Pipelining (sending multiple requests before waiting for responses) showed
no improvement because DSLite processes them serially.

## Practical Implications for Data Logging

| Use Case | Method | Rate |
|----------|--------|------|
| Single variable poll | `readOne()` | ~555 Hz |
| 4 variables per sample | 4x `readOne()` | ~140 Hz |
| DLOG 4-ch snapshot (200 samples each) | 4x `read(addr, 400)` | ~12 Hz |
| Register dump (20 registers) | 20x `readOne()` | ~28 Hz |

For real-time waveform capture at ISR rates (10-100 kHz), use DLOG_4CH in
firmware — it captures at full ISR speed into circular buffers, then you
read the frozen buffer once via DSS. The 12 Hz snapshot rate is for
reading completed buffers, not the capture rate.
