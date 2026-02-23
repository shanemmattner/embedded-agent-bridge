"""eabctl defmt decode - decode defmt wire format from RTT stream."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Optional

from eab.cli.helpers import _print


def cmd_defmt_decode(
    elf: str,
    input_file: Optional[str] = None,
    base_dir: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    defmt_print = shutil.which('defmt-print')
    if not defmt_print:
        _print({
            'error': 'defmt-print not found',
            'install': 'cargo install defmt-print',
        }, json_mode=json_mode)
        return 1

    if not os.path.isfile(elf):
        _print({'error': f'ELF file not found: {elf}'}, json_mode=json_mode)
        return 1

    cmd = [defmt_print, '-e', elf]

    if input_file:
        source_path = input_file
    elif base_dir:
        source_path = os.path.join(base_dir, 'rtt.log')
    else:
        source_path = None

    try:
        if source_path:
            if not os.path.isfile(source_path):
                _print({'error': f'Input file not found: {source_path}'}, json_mode=json_mode)
                return 1
            with open(source_path, 'rb') as f:
                result = subprocess.run(cmd, stdin=f, capture_output=True, text=True)
        else:
            result = subprocess.run(cmd, stdin=sys.stdin.buffer, capture_output=True, text=True)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if 'no defmt data' in stderr.lower() or 'symbol' in stderr.lower():
                _print({'error': 'ELF does not contain defmt symbols', 'details': stderr}, json_mode=json_mode)
            else:
                _print({'error': f'defmt-print failed (exit {result.returncode})', 'details': stderr}, json_mode=json_mode)
            return 1

        lines = result.stdout.strip().splitlines()
        if json_mode:
            decoded = []
            for line in lines:
                decoded.append({'message': line})
            _print({'lines': decoded, 'count': len(decoded)}, json_mode=True)
        else:
            for line in lines:
                print(line)

        return 0

    except Exception as e:
        _print({'error': str(e)}, json_mode=json_mode)
        return 1
