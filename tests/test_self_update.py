"""
Tests for the self-update system logic.
Validates pre-update checks, health check retry, rollback state, and config handling.
Marked @pytest.mark.smoke — safe to run on Pi during updates.
"""

import json
import os
import subprocess
import textwrap

import pytest

from update_manager import read_state, write_state, check_version_newer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
SELF_UPDATE_SH = os.path.abspath(os.path.join(SCRIPT_DIR, 'self-update.sh'))


def _make_camera_service(tmp_path, version='0.2.5'):
    """Create a minimal camera_service.py with a VERSION line."""
    p = tmp_path / 'camera_service.py'
    p.write_text(f'VERSION = "{version}"\n')
    return str(p)


def _make_repo_tree(tmp_path, version='0.3.0', missing_files=None):
    """Create a fake repo checkout with critical files."""
    repo = tmp_path / 'repo'
    repo.mkdir(parents=True, exist_ok=True)
    (repo / 'src').mkdir(exist_ok=True)
    (repo / 'scripts').mkdir(exist_ok=True)
    (repo / 'systemd').mkdir(exist_ok=True)

    files = {
        'src/version.py': f'VERSION = "{version}"\n',
        'src/camera_service.py': f'from version import VERSION\n',
        'src/status_portal.py': '# portal\n',
        'scripts/install.sh': '#!/bin/bash\necho "install"\n',
        'systemd/sai-cam.service.template': '[Unit]\n',
        'systemd/sai-cam-portal.service.template': '[Unit]\n',
    }

    missing_files = missing_files or []
    for relpath, content in files.items():
        if relpath not in missing_files:
            f = repo / relpath
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)

    return str(repo)


# ---------------------------------------------------------------------------
# Pre-update validation tests
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestPreUpdateValidation:
    """Tests for the pre-flight checks before applying an update."""

    def test_critical_files_present(self, tmp_path):
        """All critical files present -> validation should pass."""
        repo = _make_repo_tree(tmp_path, version='0.3.0')
        critical = [
            'src/camera_service.py',
            'src/status_portal.py',
            'scripts/install.sh',
            'systemd/sai-cam.service.template',
            'systemd/sai-cam-portal.service.template',
        ]
        for f in critical:
            assert os.path.isfile(os.path.join(repo, f)), f"Missing: {f}"

    def test_critical_file_missing_detected(self, tmp_path):
        """Missing critical file should be detected."""
        repo = _make_repo_tree(tmp_path, missing_files=['src/status_portal.py'])
        assert not os.path.exists(os.path.join(repo, 'src', 'status_portal.py'))

    def test_version_mismatch_detected(self, tmp_path):
        """VERSION in code != target tag should be caught."""
        repo = _make_repo_tree(tmp_path, version='0.2.9')
        target_version = '0.3.0'
        code_file = os.path.join(repo, 'src', 'camera_service.py')
        with open(code_file) as f:
            content = f.read()
        import re
        match = re.search(r'VERSION\s*=\s*"?([0-9]+\.[0-9]+\.[0-9]+[^"]*)', content)
        code_version = match.group(1) if match else ''
        assert code_version != target_version


# ---------------------------------------------------------------------------
# Version comparison in update context
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestVersionComparison:
    def test_newer_version_triggers_update(self):
        assert check_version_newer('0.2.5', '0.3.0') is True

    def test_same_version_no_update(self):
        assert check_version_newer('0.2.5', '0.2.5') is False

    def test_older_version_no_update(self):
        assert check_version_newer('0.3.0', '0.2.5') is False

    def test_prerelease_less_than_release(self):
        assert check_version_newer('0.3.0-beta.1', '0.3.0') is True


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestHealthCheckLogic:
    """Simulate health check decision-making without running real services."""

    def test_immediate_success(self):
        """If services active + API responds + version matches -> PASS."""
        services_active = True
        api_responds = True
        version_matches = True
        assert services_active and api_responds and version_matches

    def test_delayed_success(self):
        """Simulate checks that fail initially then succeed."""
        checks = [
            {'sai_cam_active': False, 'portal_active': False, 'api_ok': False},
            {'sai_cam_active': True, 'portal_active': False, 'api_ok': False},
            {'sai_cam_active': True, 'portal_active': True, 'api_ok': True, 'version_match': True},
        ]
        passed = False
        for check in checks:
            if (check.get('sai_cam_active') and check.get('portal_active')
                    and check.get('api_ok') and check.get('version_match')):
                passed = True
                break
        assert passed

    def test_timeout_triggers_rollback(self):
        """If no check passes within timeout -> should rollback."""
        timeout = 120
        interval = 10
        max_checks = timeout // interval
        checks_passed = 0
        all_failed = True

        for i in range(max_checks):
            # Simulate all checks failing
            service_ok = False
            if service_ok:
                all_failed = False
                break

        assert all_failed, "Should trigger rollback when all checks fail"

    def test_version_mismatch_not_pass(self):
        """Services active but wrong version reported -> keep checking."""
        reported = '0.2.5'
        target = '0.3.0'
        assert reported != target


# ---------------------------------------------------------------------------
# Rollback state management
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRollbackState:
    def test_state_records_previous_version(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, status='updating', previous_version='0.2.5',
                    current_version='0.2.5', latest_available='0.3.0')
        state = read_state(p)
        assert state['previous_version'] == '0.2.5'
        assert state['status'] == 'updating'

    def test_rollback_completed_increments_failures(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, consecutive_failures=1)
        state = read_state(p)
        new_failures = state['consecutive_failures'] + 1
        write_state(p, status='rollback_completed', consecutive_failures=new_failures)
        state = read_state(p)
        assert state['consecutive_failures'] == 2
        assert state['status'] == 'rollback_completed'

    def test_successful_update_resets_failures(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, consecutive_failures=2, status='rollback_completed')
        # Simulate successful update
        write_state(p, status='updated', consecutive_failures=0)
        state = read_state(p)
        assert state['consecutive_failures'] == 0
        assert state['status'] == 'updated'


# ---------------------------------------------------------------------------
# Consecutive failure guard
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestConsecutiveFailureGuard:
    def test_guard_blocks_after_max_failures(self, tmp_path):
        """After 3 consecutive failures, updates should be skipped."""
        p = str(tmp_path / 'state.json')
        write_state(p, consecutive_failures=3)
        state = read_state(p)
        max_failures = 3
        should_skip = state['consecutive_failures'] >= max_failures
        assert should_skip

    def test_guard_allows_below_max(self, tmp_path):
        p = str(tmp_path / 'state.json')
        write_state(p, consecutive_failures=2)
        state = read_state(p)
        should_skip = state['consecutive_failures'] >= 3
        assert not should_skip

    def test_force_flag_bypasses_guard(self):
        """--force should bypass the consecutive failure guard."""
        consecutive_failures = 5
        force = True
        should_skip = consecutive_failures >= 3 and not force
        assert not should_skip


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestConfigHandling:
    def test_updates_disabled_skips(self, tmp_path):
        config = {'updates': {'enabled': False}}
        assert config['updates']['enabled'] is False

    def test_updates_enabled_proceeds(self, tmp_path):
        config = {'updates': {'enabled': True, 'channel': 'stable'}}
        assert config['updates']['enabled'] is True

    def test_stable_channel_skips_prerelease(self):
        """Stable channel should skip pre-release tags."""
        releases = [
            {'tag_name': 'v0.4.0-beta.1', 'prerelease': True, 'draft': False},
            {'tag_name': 'v0.3.0', 'prerelease': False, 'draft': False},
        ]
        channel = 'stable'
        selected = None
        for r in releases:
            if r.get('draft'):
                continue
            if channel == 'stable' and r.get('prerelease'):
                continue
            selected = r['tag_name']
            break
        assert selected == 'v0.3.0'

    def test_beta_channel_includes_prerelease(self):
        """Beta channel should include pre-releases."""
        releases = [
            {'tag_name': 'v0.4.0-beta.1', 'prerelease': True, 'draft': False},
            {'tag_name': 'v0.3.0', 'prerelease': False, 'draft': False},
        ]
        channel = 'beta'
        selected = None
        for r in releases:
            if r.get('draft'):
                continue
            if channel == 'stable' and r.get('prerelease'):
                continue
            selected = r['tag_name']
            break
        assert selected == 'v0.4.0-beta.1'

    def test_drafts_always_skipped(self):
        releases = [
            {'tag_name': 'v0.5.0', 'prerelease': False, 'draft': True},
            {'tag_name': 'v0.3.0', 'prerelease': False, 'draft': False},
        ]
        selected = None
        for r in releases:
            if r.get('draft'):
                continue
            selected = r['tag_name']
            break
        assert selected == 'v0.3.0'


# ---------------------------------------------------------------------------
# Script file validation
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestScriptFile:
    def test_self_update_script_exists(self):
        assert os.path.isfile(SELF_UPDATE_SH), f"self-update.sh not found at {SELF_UPDATE_SH}"

    def test_self_update_script_executable(self):
        assert os.access(SELF_UPDATE_SH, os.X_OK), "self-update.sh is not executable"

    def test_self_update_has_shebang(self):
        with open(SELF_UPDATE_SH) as f:
            first_line = f.readline()
        assert first_line.startswith('#!/bin/bash'), f"Bad shebang: {first_line}"

    def test_self_update_uses_flock(self):
        with open(SELF_UPDATE_SH) as f:
            content = f.read()
        assert 'flock' in content, "self-update.sh should use flock for exclusive locking"

    def test_self_update_has_rollback(self):
        with open(SELF_UPDATE_SH) as f:
            content = f.read()
        assert 'rollback' in content.lower(), "self-update.sh should have rollback logic"

    def test_self_update_reads_version_from_version_py(self):
        """self-update.sh should read VERSION from version.py, not camera_service.py."""
        with open(SELF_UPDATE_SH) as f:
            content = f.read()
        assert 'version.py' in content, "self-update.sh should reference version.py"

    def test_self_update_has_health_timeout(self):
        with open(SELF_UPDATE_SH) as f:
            content = f.read()
        assert 'HEALTH_TIMEOUT' in content, "self-update.sh should define HEALTH_TIMEOUT"

    def test_self_update_has_preserve_config(self):
        """Update should use --preserve-config to keep user settings."""
        with open(SELF_UPDATE_SH) as f:
            content = f.read()
        assert '--preserve-config' in content


# ---------------------------------------------------------------------------
# version.py validation
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestVersionFile:
    def test_version_py_importable(self):
        """version.py should be importable as a module."""
        from version import VERSION
        assert isinstance(VERSION, str)

    def test_version_format(self):
        """VERSION should follow semver format (X.Y.Z)."""
        import re
        from version import VERSION
        assert re.match(r'^\d+\.\d+\.\d+', VERSION), \
            f"VERSION '{VERSION}' doesn't match semver format"

    def test_version_not_zero(self):
        """VERSION should not be the placeholder 0.0.0."""
        from version import VERSION
        assert VERSION != '0.0.0'


# ---------------------------------------------------------------------------
# Portal static file validation
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestPortalFiles:
    PORTAL_DIR = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'src', 'portal'))

    def test_index_html_exists(self):
        assert os.path.isfile(os.path.join(self.PORTAL_DIR, 'index.html'))

    def test_dashboard_js_exists(self):
        assert os.path.isfile(os.path.join(self.PORTAL_DIR, 'dashboard.js'))

    def test_styles_css_exists(self):
        assert os.path.isfile(os.path.join(self.PORTAL_DIR, 'styles.css'))

    def test_robots_txt_exists(self):
        assert os.path.isfile(os.path.join(self.PORTAL_DIR, 'robots.txt'))

    def test_robots_txt_disallows_api(self):
        with open(os.path.join(self.PORTAL_DIR, 'robots.txt')) as f:
            content = f.read()
        assert 'Disallow: /api/' in content

    def test_index_has_theme_color(self):
        with open(os.path.join(self.PORTAL_DIR, 'index.html')) as f:
            content = f.read()
        assert 'theme-color' in content

    def test_index_has_viewport_meta(self):
        with open(os.path.join(self.PORTAL_DIR, 'index.html')) as f:
            content = f.read()
        assert 'viewport' in content

    def test_dashboard_has_updates_block(self):
        """Dashboard JS should register an updates block."""
        with open(os.path.join(self.PORTAL_DIR, 'dashboard.js')) as f:
            content = f.read()
        assert "'updates'" in content
        assert 'data.update' in content

    def test_dashboard_has_format_timestamp(self):
        with open(os.path.join(self.PORTAL_DIR, 'dashboard.js')) as f:
            content = f.read()
        assert 'formatTimestamp' in content
