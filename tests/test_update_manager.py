"""
Tests for src/update_manager.py — state management and version comparison.
"""

import json
import os
import pytest

from update_manager import (
    read_state,
    write_state,
    check_version_newer,
    get_update_info,
    DEFAULT_STATE,
)


# ---------------------------------------------------------------------------
# read_state
# ---------------------------------------------------------------------------

class TestReadState:
    def test_missing_file_returns_defaults(self, tmp_path):
        state = read_state(str(tmp_path / 'nonexistent.json'))
        assert state == DEFAULT_STATE

    def test_corrupt_json_returns_defaults(self, tmp_path):
        p = tmp_path / 'bad.json'
        p.write_text('{not valid json!!!')
        state = read_state(str(p))
        assert state == DEFAULT_STATE

    def test_valid_file_merges_with_defaults(self, tmp_path):
        p = tmp_path / 'state.json'
        p.write_text(json.dumps({
            'status': 'updated',
            'current_version': '0.3.0',
        }))
        state = read_state(str(p))
        assert state['status'] == 'updated'
        assert state['current_version'] == '0.3.0'
        # defaults preserved for keys not in file
        assert state['consecutive_failures'] == 0
        assert state['channel'] == 'stable'

    def test_extra_keys_preserved(self, tmp_path):
        p = tmp_path / 'state.json'
        p.write_text(json.dumps({'custom_key': 'hello'}))
        state = read_state(str(p))
        assert state['custom_key'] == 'hello'

    def test_permission_error_returns_defaults(self, tmp_path):
        p = tmp_path / 'noperm.json'
        p.write_text('{}')
        p.chmod(0o000)
        try:
            state = read_state(str(p))
            assert state == DEFAULT_STATE
        finally:
            p.chmod(0o644)


# ---------------------------------------------------------------------------
# write_state
# ---------------------------------------------------------------------------

class TestWriteState:
    def test_creates_file_and_parent_dirs(self, tmp_path):
        p = str(tmp_path / 'sub' / 'dir' / 'state.json')
        write_state(p, status='up_to_date', current_version='0.2.5')
        assert os.path.exists(p)
        with open(p) as f:
            data = json.load(f)
        assert data['status'] == 'up_to_date'
        assert data['current_version'] == '0.2.5'

    def test_merges_with_existing_state(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, status='up_to_date', current_version='0.2.5')
        write_state(p, status='updating', latest_available='0.3.0')
        with open(p) as f:
            data = json.load(f)
        assert data['status'] == 'updating'
        assert data['current_version'] == '0.2.5'  # preserved
        assert data['latest_available'] == '0.3.0'  # new

    def test_atomic_write_no_partial(self, tmp_path):
        """Verify .tmp file doesn't linger after successful write."""
        p = str(tmp_path / 'state.json')
        write_state(p, status='updated')
        assert not os.path.exists(p + '.tmp')

    def test_returns_merged_state(self, tmp_path):
        p = str(tmp_path / 'state.json')
        result = write_state(p, status='updated', current_version='1.0.0')
        assert result['status'] == 'updated'
        assert result['current_version'] == '1.0.0'
        assert result['channel'] == 'stable'  # from defaults


# ---------------------------------------------------------------------------
# check_version_newer
# ---------------------------------------------------------------------------

class TestCheckVersionNewer:
    def test_patch_bump(self):
        assert check_version_newer('0.2.5', '0.2.6') is True

    def test_minor_bump(self):
        assert check_version_newer('0.2.5', '0.3.0') is True

    def test_major_bump(self):
        assert check_version_newer('0.2.5', '1.0.0') is True

    def test_same_version(self):
        assert check_version_newer('0.2.5', '0.2.5') is False

    def test_older_version(self):
        assert check_version_newer('0.3.0', '0.2.5') is False

    def test_prerelease_less_than_release(self):
        # 0.3.0-beta.1 < 0.3.0
        assert check_version_newer('0.3.0-beta.1', '0.3.0') is True

    def test_release_not_less_than_prerelease(self):
        assert check_version_newer('0.3.0', '0.3.0-beta.1') is False

    def test_strips_v_prefix(self):
        assert check_version_newer('v0.2.5', 'v0.3.0') is True

    def test_mixed_prefix(self):
        assert check_version_newer('0.2.5', 'v0.3.0') is True


# ---------------------------------------------------------------------------
# get_update_info
# ---------------------------------------------------------------------------

class TestGetUpdateInfo:
    def test_no_state_file(self, tmp_path):
        info = get_update_info(str(tmp_path / 'missing.json'))
        assert info['status'] == 'unknown'
        assert info['update_available'] is False

    def test_update_available(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, current_version='0.2.5', latest_available='0.3.0',
                    status='up_to_date')
        info = get_update_info(p)
        assert info['update_available'] is True
        assert info['current_version'] == '0.2.5'
        assert info['latest_available'] == '0.3.0'

    def test_no_update_when_same_version(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, current_version='0.3.0', latest_available='0.3.0')
        info = get_update_info(p)
        assert info['update_available'] is False

    def test_no_update_when_no_latest(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, current_version='0.3.0', latest_available='')
        info = get_update_info(p)
        assert info['update_available'] is False

    def test_includes_consecutive_failures(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, consecutive_failures=2)
        info = get_update_info(p)
        assert info['consecutive_failures'] == 2
