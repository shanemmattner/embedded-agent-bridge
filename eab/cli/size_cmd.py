"""eabctl size - ELF section size analysis."""

from __future__ import annotations

import re
import subprocess
from typing import Optional

from eab.cli.helpers import _print
from eab.toolchain import which_or_sdk as _which_or_sdk


def _parse_readelf_sections(elf: str) -> dict[str, int]:
    readelf = None
    for candidate in ['arm-zephyr-eabi-readelf', 'arm-none-eabi-readelf', 'readelf']:
        readelf = _which_or_sdk(candidate)
        if readelf:
            break
    if not readelf:
        raise FileNotFoundError('readelf not found')
    
    result = subprocess.run([readelf, '-S', '-W', elf], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'readelf failed: {result.stderr}')

    sections = {}
    for line in result.stdout.splitlines():
        m = re.match(r'\s*\[\s*\d+\]\s+(\.\S+)\s+\S+\s+\S+\s+\S+\s+(\S+)', line)
        if m:
            name = m.group(1)
            size = int(m.group(2), 16)
            if size > 0:
                sections[name] = size
    return sections


def cmd_size(
    elf: str,
    compare_elf: Optional[str] = None,
    json_mode: bool = False,
) -> int:
    try:
        sections = _parse_readelf_sections(elf)
    except (FileNotFoundError, RuntimeError) as e:
        _print({'error': str(e)}, json_mode=json_mode)
        return 1

    text = sections.get('.text', 0)
    rodata = sections.get('.rodata', 0)
    data = sections.get('.data', 0)
    bss = sections.get('.bss', 0)
    flash_total = text + rodata + data
    ram_total = data + bss

    result = {
        'file': elf,
        'sections': {k: v for k, v in sorted(sections.items())},
        'summary': {
            '.text': text,
            '.rodata': rodata,
            '.data': data,
            '.bss': bss,
            'flash_total': flash_total,
            'ram_total': ram_total,
        },
    }

    if compare_elf:
        try:
            old_sections = _parse_readelf_sections(compare_elf)
        except (FileNotFoundError, RuntimeError) as e:
            _print({'error': f'Compare ELF: {e}'}, json_mode=json_mode)
            return 1

        deltas = {}
        for key in ['.text', '.rodata', '.data', '.bss']:
            old_val = old_sections.get(key, 0)
            new_val = sections.get(key, 0)
            delta = new_val - old_val
            pct = (delta / old_val * 100) if old_val != 0 else 0.0
            deltas[key] = {'old': old_val, 'new': new_val, 'delta': delta, 'pct_change': round(pct, 1)}
        
        old_flash = old_sections.get('.text', 0) + old_sections.get('.rodata', 0) + old_sections.get('.data', 0)
        old_ram = old_sections.get('.data', 0) + old_sections.get('.bss', 0)
        deltas['flash_total'] = {'old': old_flash, 'new': flash_total, 'delta': flash_total - old_flash,
                                  'pct_change': round((flash_total - old_flash) / old_flash * 100, 1) if old_flash else 0.0}
        deltas['ram_total'] = {'old': old_ram, 'new': ram_total, 'delta': ram_total - old_ram,
                                'pct_change': round((ram_total - old_ram) / old_ram * 100, 1) if old_ram else 0.0}
        result['compare'] = {'file': compare_elf, 'deltas': deltas}

    if json_mode:
        _print(result, json_mode=True)
    else:
        print(f'ELF: {elf}')
        print(f'{"Section":<16} {"Size (bytes)":>12} {"Size (KB)":>10}')
        print('-' * 40)
        for name in ['.text', '.rodata', '.data', '.bss']:
            val = sections.get(name, 0)
            print(f'{name:<16} {val:>12} {val/1024:>10.1f}')
        print('-' * 40)
        print(f'{"Flash:":<16} {flash_total:>12} {flash_total/1024:>10.1f}')
        print(f'{"RAM:":<16} {ram_total:>12} {ram_total/1024:>10.1f}')

        if compare_elf and 'compare' in result:
            print(f'\nCompare: {compare_elf}')
            print(f'{"Section":<16} {"Size":>10} {"Delta":>10} {"Change":>8}')
            print('-' * 46)
            for key in ['.text', '.rodata', '.data', '.bss', 'flash_total', 'ram_total']:
                d = result['compare']['deltas'][key]
                label = 'Flash:' if key == 'flash_total' else ('RAM:' if key == 'ram_total' else key)
                sign = '+' if d['delta'] >= 0 else ''
                print(f'{label:<16} {d["new"]:>10} {sign}{d["delta"]:>9} {sign}{d["pct_change"]:>6.1f}%')

    return 0
