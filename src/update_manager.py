"""
SAI-Cam Update State Manager

Manages the self-update state file used by self-update.sh and status_portal.py.
Provides version comparison, atomic state writes, and state queries.
"""

import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_PATH = '/var/lib/sai-cam/update-state.json'

DEFAULT_STATE = {
    'status': 'unknown',
    'current_version': '0.0.0',
    'latest_available': '',
    'previous_version': '',
    'last_check': '',
    'last_update': '',
    'consecutive_failures': 0,
    'channel': 'stable',
}


def read_state(path=DEFAULT_STATE_PATH):
    """Read update state from JSON file, returning defaults if missing or corrupt."""
    state = dict(DEFAULT_STATE)
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            state.update(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return state


def write_state(path=DEFAULT_STATE_PATH, **kwargs):
    """Atomically update state file. Creates parent dirs if needed.

    Reads existing state, merges kwargs, writes to .tmp, renames into place.
    """
    state = read_state(path)
    state.update(kwargs)

    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp_path, path)
    return state


def check_version_newer(current, candidate):
    """Compare semver-style version strings. Returns True if candidate > current.

    Uses packaging.version if available, falls back to tuple comparison.
    Handles pre-release tags (e.g. '0.3.0-beta.1' < '0.3.0').
    """
    try:
        from packaging.version import Version
        return Version(candidate) > Version(current)
    except ImportError:
        pass

    # Fallback: strip leading 'v', split on '.', compare tuples
    def _parse(v):
        v = v.lstrip('v')
        # Split off pre-release suffix
        base = v.split('-')[0]
        parts = []
        for p in base.split('.'):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        is_prerelease = '-' in v
        return (parts, not is_prerelease)  # releases sort after pre-releases

    return _parse(candidate) > _parse(current)


def get_update_info(path=DEFAULT_STATE_PATH):
    """Return state dict suitable for API responses."""
    state = read_state(path)
    current = state.get('current_version', '0.0.0')
    latest = state.get('latest_available', '')
    update_available = False
    if latest and latest != current:
        try:
            update_available = check_version_newer(current, latest)
        except Exception:
            pass

    return {
        'status': state.get('status', 'unknown'),
        'current_version': current,
        'latest_available': latest,
        'previous_version': state.get('previous_version', ''),
        'update_available': update_available,
        'last_check': state.get('last_check', ''),
        'last_update': state.get('last_update', ''),
        'consecutive_failures': state.get('consecutive_failures', 0),
        'channel': state.get('channel', 'stable'),
    }
