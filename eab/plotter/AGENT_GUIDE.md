# EAB RTT Plotter — Status

Live plotting of RTT data was explored but proved difficult to get working reliably. Instead, RTT data is saved to structured file formats via RTTStreamProcessor:

- `rtt.log` — cleaned text (ANSI stripped, log rotation)
- `rtt.csv` — `DATA: key=value` records as CSV columns
- `rtt.jsonl` — structured JSON records (one per line)

These files can be opened in any plotting tool (Python/matplotlib, Excel, etc.) after capture.

## Data Flow

```
JLinkRTTLogger (C binary)
    └─ writes raw RTT text to rtt-raw.log
Tailer thread (Python)
    └─ tails rtt-raw.log, feeds RTTStreamProcessor
RTTStreamProcessor
    ├─ rtt.log   (cleaned text)
    ├─ rtt.jsonl (structured records)
    └─ rtt.csv   (DATA key=value rows)
```

## Future

A more efficient binary capture format could replace CSV for high-throughput scenarios.
