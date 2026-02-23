"""eabctl multi - run commands across all registered devices."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from eab.cli.helpers import _print


def _run_on_device(device_name: str, command_args: list[str], timeout: float) -> dict:
    cmd = [sys.executable, '-m', 'eab.cli', '--device', device_name, '--json'] + command_args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = result.stdout.strip()
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        return {
            'device': device_name,
            'exit_code': result.returncode,
            'output': parsed if parsed is not None else stdout,
            'stderr': result.stderr.strip() or None,
        }
    except subprocess.TimeoutExpired:
        return {
            'device': device_name,
            'exit_code': -1,
            'output': None,
            'stderr': f'Timeout after {timeout}s',
        }
    except Exception as e:
        return {
            'device': device_name,
            'exit_code': -1,
            'output': None,
            'stderr': str(e),
        }


def cmd_multi(
    command_args: list[str],
    timeout: float = 30.0,
    json_mode: bool = False,
) -> int:
    from eab.device_registry import list_devices

    devices = list_devices()
    if not devices:
        _print({'error': 'No devices registered (use eabctl device add)'}, json_mode=json_mode)
        return 1

    device_names = [d.device_name for d in devices]
    
    results = {}
    with ThreadPoolExecutor(max_workers=len(device_names)) as pool:
        futures = {
            pool.submit(_run_on_device, name, command_args, timeout): name
            for name in device_names
        }
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()

    if json_mode:
        _print({'results': results}, json_mode=True)
    else:
        for name in sorted(results):
            r = results[name]
            status = 'OK' if r['exit_code'] == 0 else f'FAIL({r["exit_code"]})'
            out = r['output'] if isinstance(r['output'], str) else json.dumps(r['output'], indent=2) if r['output'] else ''
            print(f'[{name}] {status}')
            if out:
                for line in out.split('\n')[:5]:
                    print(f'  {line}')
            if r.get('stderr'):
                print(f'  stderr: {r["stderr"]}')

    failed = sum(1 for r in results.values() if r['exit_code'] != 0)
    return 1 if failed == len(results) else 0
