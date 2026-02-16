#!/usr/bin/env python3
"""
Multi-Device Stress Test for Embedded Agent Bridge

Orchestrates parallel high-throughput streaming from multiple dev kits:
- Auto-loads device config from devices.json
- Flashes test firmware to each device
- Starts parallel RTT/serial/apptrace streams
- Collects metrics (throughput, stability, latency, resource usage)
- Generates comprehensive report

Usage:
    python3 scripts/multi_device_stress_test.py --duration 180
    python3 scripts/multi_device_stress_test.py --devices esp32-c6,nrf5340-1 --json
"""

import argparse
import json
import subprocess
import time
import threading
import os
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List
import psutil


@dataclass
class DeviceMetrics:
    """Per-device performance metrics"""
    name: str
    chip: str
    transport: str
    bytes_received: int = 0
    messages_received: int = 0
    dropped_frames: int = 0
    reconnects: int = 0
    errors: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_sec(self) -> float:
        if self.end_time == 0:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def throughput_kbps(self) -> float:
        if self.duration_sec == 0:
            return 0.0
        return (self.bytes_received / 1024) / self.duration_sec

    @property
    def message_rate(self) -> float:
        if self.duration_sec == 0:
            return 0.0
        return self.messages_received / self.duration_sec


@dataclass
class SystemMetrics:
    """Host system resource metrics"""
    cpu_percent: List[float]
    memory_mb: List[float]
    timestamp: List[float]

    def record(self):
        """Record current system state"""
        self.cpu_percent.append(psutil.cpu_percent(interval=0.1))
        self.memory_mb.append(psutil.Process().memory_info().rss / 1024 / 1024)
        self.timestamp.append(time.time())

    @property
    def avg_cpu(self) -> float:
        return sum(self.cpu_percent) / len(self.cpu_percent) if self.cpu_percent else 0.0

    @property
    def avg_memory_mb(self) -> float:
        return sum(self.memory_mb) / len(self.memory_mb) if self.memory_mb else 0.0


class MultiDeviceStressTest:
    """Orchestrates multi-device streaming and metrics collection"""

    def __init__(self, config_path: str = "devices.json", duration: int = 180):
        self.config_path = Path(config_path)
        self.duration = duration
        self.devices: List[Dict] = []
        self.metrics: Dict[str, DeviceMetrics] = {}
        self.system_metrics = SystemMetrics([], [], [])
        self.test_active = False

    def load_config(self, device_filter: Optional[List[str]] = None):
        """Load device configuration from JSON"""
        with open(self.config_path) as f:
            config = json.load(f)

        all_devices = config["devices"]

        # Filter devices with firmware and optionally by name
        self.devices = [
            d for d in all_devices
            if d.get("firmware") and d["firmware"] != "TBD"
            and (not device_filter or d["name"] in device_filter)
        ]

        print(f"Loaded {len(self.devices)} devices for testing:")
        for d in self.devices:
            print(f"  - {d['name']}: {d['chip']} via {d['transport']}")

    def register_device(self, device: Dict) -> bool:
        """Register device with eabctl"""
        cmd = [
            "eabctl", "device", "add",
            device["name"],
            "--type", "debug" if device["transport"] in ["rtt", "dss", "apptrace"] else "serial",
            "--chip", device["chip"]
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0

    def flash_device(self, device: Dict) -> bool:
        """Flash test firmware to device"""
        firmware_path = Path(device["firmware"])
        if not firmware_path.exists():
            print(f"  ⚠️  Firmware not found: {firmware_path}")
            return False

        # TODO: Implement per-family flash logic
        # - ESP32: idf.py build && eabctl flash
        # - nRF/STM32/NXP: west build && west flash
        # - C2000: CCS project build + XDS110 flash

        print(f"  ⚠️  Flash not implemented for {device['family']}")
        return False

    def start_stream(self, device: Dict) -> Optional[subprocess.Popen]:
        """Start data stream for device"""
        name = device["name"]
        transport = device["transport"]

        if transport == "rtt":
            # RTT via eabctl
            cmd = ["eabctl", "--device", name, "rtt", "start", "--transport", "probe-rs"]
            if device["debug_probe"] == "jlink":
                cmd[-1] = "jlink"

        elif transport == "apptrace":
            # ESP32 apptrace via OpenOCD + TCP
            # Start OpenOCD in background, then start apptrace to TCP socket
            print(f"  ⚠️  Apptrace not yet implemented")
            return None

        elif transport == "dss":
            # C2000 DSS trace via XDS110
            print(f"  ⚠️  DSS trace not yet implemented")
            return None

        elif transport == "serial":
            # Serial daemon should already be running
            return None

        else:
            print(f"  ⚠️  Unknown transport: {transport}")
            return None

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(2)  # Let stream start
            return proc
        except Exception as e:
            print(f"  ⚠️  Failed to start stream: {e}")
            return None

    def monitor_device(self, device: Dict):
        """Monitor device stream and collect metrics (runs in thread)"""
        name = device["name"]
        metrics = DeviceMetrics(
            name=name,
            chip=device["chip"],
            transport=device["transport"],
            start_time=time.time()
        )
        self.metrics[name] = metrics

        # TODO: Implement metric collection by tailing device logs
        # - For RTT: tail /tmp/eab-devices/<name>/rtt.log
        # - For serial: tail /tmp/eab-devices/<name>/latest.log
        # - For apptrace: tail TCP socket output
        # - Count bytes, messages, detect drops/errors

        while self.test_active:
            time.sleep(1)
            # Update metrics here

        metrics.end_time = time.time()

    def monitor_system(self):
        """Monitor host system resources (runs in thread)"""
        while self.test_active:
            self.system_metrics.record()
            time.sleep(1)

    def run_test(self):
        """Main test orchestration"""
        print(f"\n{'='*60}")
        print(f"Multi-Device Stress Test")
        print(f"Duration: {self.duration}s")
        print(f"Devices: {len(self.devices)}")
        print(f"{'='*60}\n")

        # Phase 1: Register devices
        print("📝 Registering devices...")
        for device in self.devices:
            success = self.register_device(device)
            status = "✅" if success else "⚠️"
            print(f"  {status} {device['name']}")

        # Phase 2: Flash firmware (optional - skip for now)
        # print("\n🔧 Flashing firmware...")
        # for device in self.devices:
        #     self.flash_device(device)

        # Phase 3: Start streams
        print("\n🚀 Starting streams...")
        stream_procs = []
        for device in self.devices:
            proc = self.start_stream(device)
            if proc:
                stream_procs.append((device["name"], proc))
                print(f"  ✅ {device['name']}")
            else:
                print(f"  ⚠️  {device['name']} (manual start required)")

        # Phase 4: Start monitoring
        print(f"\n📊 Monitoring for {self.duration}s...")
        self.test_active = True

        # Start device monitor threads
        device_threads = []
        for device in self.devices:
            t = threading.Thread(target=self.monitor_device, args=(device,))
            t.start()
            device_threads.append(t)

        # Start system monitor thread
        system_thread = threading.Thread(target=self.monitor_system)
        system_thread.start()

        # Progress bar
        start = time.time()
        try:
            while time.time() - start < self.duration:
                elapsed = time.time() - start
                progress = (elapsed / self.duration) * 100
                bar_len = 40
                filled = int(bar_len * progress / 100)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f"\r  [{bar}] {progress:.1f}% ({elapsed:.0f}s / {self.duration}s)", end='', flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n⚠️  Test interrupted by user")

        print("\n\n🛑 Stopping streams...")
        self.test_active = False

        # Wait for threads
        for t in device_threads:
            t.join(timeout=5)
        system_thread.join(timeout=5)

        # Stop stream processes
        for name, proc in stream_procs:
            proc.terminate()
            proc.wait(timeout=5)

        # Phase 5: Generate report
        self.generate_report()

    def generate_report(self):
        """Generate comprehensive test report"""
        print(f"\n{'='*60}")
        print("📊 Test Results")
        print(f"{'='*60}\n")

        # Per-device metrics
        print("Device Metrics:")
        print(f"{'Device':<15} {'Chip':<12} {'Transport':<10} {'Throughput':<12} {'Messages':<10}")
        print("-" * 70)

        total_throughput = 0.0
        for name, metrics in self.metrics.items():
            throughput_str = f"{metrics.throughput_kbps:.1f} KB/s" if metrics.bytes_received > 0 else "N/A"
            total_throughput += metrics.throughput_kbps

            print(f"{name:<15} {metrics.chip:<12} {metrics.transport:<10} {throughput_str:<12} {metrics.messages_received:<10}")

        # Aggregate metrics
        print(f"\n{'='*60}")
        print(f"Aggregate Throughput: {total_throughput:.1f} KB/s")
        print(f"Host CPU: {self.system_metrics.avg_cpu:.1f}%")
        print(f"Host Memory: {self.system_metrics.avg_memory_mb:.1f} MB")
        print(f"{'='*60}\n")

    def save_results_json(self, output_path: str):
        """Save results to JSON file"""
        results = {
            "test_config": {
                "duration_seconds": self.duration,
                "device_count": len(self.devices),
                "devices": [d["name"] for d in self.devices]
            },
            "device_metrics": {
                name: asdict(metrics)
                for name, metrics in self.metrics.items()
            },
            "system_metrics": {
                "avg_cpu_percent": self.system_metrics.avg_cpu,
                "avg_memory_mb": self.system_metrics.avg_memory_mb,
                "samples": len(self.system_metrics.cpu_percent)
            },
            "aggregate": {
                "total_throughput_kbps": sum(m.throughput_kbps for m in self.metrics.values()),
                "total_messages": sum(m.messages_received for m in self.metrics.values()),
                "total_errors": sum(m.errors for m in self.metrics.values())
            }
        }

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"💾 Results saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Multi-device stress test for EAB")
    parser.add_argument("--config", default="devices.json", help="Device config JSON path")
    parser.add_argument("--duration", type=int, default=180, help="Test duration in seconds")
    parser.add_argument("--devices", help="Comma-separated device names to test (default: all)")
    parser.add_argument("--output", default="stress_test_results.json", help="Output JSON path")
    parser.add_argument("--json", action="store_true", help="JSON output mode")

    args = parser.parse_args()

    device_filter = args.devices.split(',') if args.devices else None

    test = MultiDeviceStressTest(config_path=args.config, duration=args.duration)
    test.load_config(device_filter=device_filter)

    if len(test.devices) == 0:
        print("⚠️  No devices with firmware found in config!")
        sys.exit(1)

    test.run_test()
    test.save_results_json(args.output)


if __name__ == "__main__":
    main()
