"""Reset reason CLI commands."""

from __future__ import annotations

import json
import os

from .helpers import _print


def cmd_resets(base_dir: str, lines: int, json_mode: bool) -> int:
    """
    Show reset history and statistics.
    
    Args:
        base_dir: Session directory
        lines: Number of recent resets to show (default 10)
        json_mode: Output JSON instead of human-readable
        
    Returns:
        Exit code (0 = success, 1 = error)
    """
    status_path = os.path.join(base_dir, "status.json")
    
    if not os.path.exists(status_path):
        _print({"error": "status.json not found", "path": status_path}, json_mode=json_mode)
        return 1
    
    try:
        with open(status_path, 'r') as f:
            status = json.load(f)
    except FileNotFoundError:
        _print({"error": "status.json not found", "path": status_path}, json_mode=json_mode)
        return 1
    except Exception as e:
        _print({"error": f"Failed to read status.json: {e}"}, json_mode=json_mode)
        return 1
    
    resets = status.get("resets", {})
    
    if json_mode:
        # In JSON mode, return full reset statistics
        _print({
            "resets": resets,
        }, json_mode=True)
        return 0
    
    # Human-readable output
    last_reason = resets.get("last_reason")
    last_time = resets.get("last_time")
    history = resets.get("history", {})
    total = resets.get("total", 0)
    
    if total == 0:
        print("No resets detected yet")
        return 0
    
    print(f"Reset Statistics (total: {total})")
    print("=" * 60)
    
    if last_reason and last_time:
        print(f"Last Reset: {last_reason} at {last_time}")
        print()
    
    if history:
        print("Reset Counts by Reason:")
        # Sort by count (descending)
        sorted_reasons = sorted(history.items(), key=lambda x: x[1], reverse=True)
        for reason, count in sorted_reasons:
            print(f"  {reason:30s} : {count:4d}")
    
    return 0
