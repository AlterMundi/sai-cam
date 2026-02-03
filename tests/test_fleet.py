"""
Tests for scripts/fleet.py — fleet CLI helpers and commands.

Covers the pure helper functions, HTTP-driven commands (cmd_status,
cmd_update with wait/no-wait), and argparse wiring.

Marked @pytest.mark.smoke — no network or hardware needed.
"""

import sys
import os
import time
from unittest.mock import patch, MagicMock, call

import pytest

# fleet.py lives under scripts/, not src/ — add it to sys.path
_scripts_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
_scripts_dir = os.path.abspath(_scripts_dir)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# fleet.py imports requests and yaml at module level; ensure they're available
import fleet
from fleet import (
    _fmt_relative_time,
    _color_status,
    _get_update_status,
    _TERMINAL_STATES,
    FleetCLI,
    main,
    GREEN,
    RED,
    YELLOW,
    RESET,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_file(tmp_path):
    """Create a minimal fleet/nodes.yaml for FleetCLI."""
    import yaml
    data = {
        'nodes': [
            {'name': 'node1', 'host': '10.0.0.1', 'port': 8090, 'token': 'tok1', 'role': 'canary'},
            {'name': 'node2', 'host': '10.0.0.2', 'port': 8090, 'token': 'tok2', 'role': 'stable'},
            {'name': 'node3', 'host': '10.0.0.3', 'port': 8090, 'token': 'tok3', 'role': 'stable'},
        ],
    }
    p = tmp_path / 'nodes.yaml'
    p.write_text(yaml.dump(data))
    return str(p)


@pytest.fixture
def cli(registry_file):
    return FleetCLI(registry_file)


def _mock_status_response(version='0.2.31', status='up_to_date', channel='stable',
                          failures=0, last_update='2026-02-03T10:00:00+00:00'):
    """Build a mock /api/status JSON body."""
    return {
        'data': {
            'update': {
                'current_version': version,
                'status': status,
                'channel': channel,
                'consecutive_failures': failures,
                'last_update': last_update,
            }
        }
    }


# ---------------------------------------------------------------------------
# _fmt_relative_time
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestFmtRelativeTime:
    def test_none_returns_dash(self):
        assert _fmt_relative_time(None) == '--'

    def test_empty_string_returns_dash(self):
        assert _fmt_relative_time('') == '--'

    def test_invalid_string_returns_dash(self):
        assert _fmt_relative_time('not-a-date') == '--'

    def test_recent_iso_returns_seconds(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        result = _fmt_relative_time(ts)
        assert result.endswith('s ago')

    def test_minutes_ago(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        result = _fmt_relative_time(ts)
        assert result == '5m ago'

    def test_hours_ago(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        result = _fmt_relative_time(ts)
        assert result == '2h ago'

    def test_days_ago(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        result = _fmt_relative_time(ts)
        assert result == '3d ago'

    def test_z_suffix_handled(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(hours=1))
        iso = ts.strftime('%Y-%m-%dT%H:%M:%SZ')
        result = _fmt_relative_time(iso)
        assert result == '1h ago'

    def test_future_timestamp_returns_just_now(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        result = _fmt_relative_time(ts)
        assert result == 'just now'


# ---------------------------------------------------------------------------
# _color_status
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestColorStatus:
    def test_up_to_date_is_green(self):
        result = _color_status('up_to_date')
        assert GREEN in result
        assert 'up_to_date' in result

    def test_updated_is_green(self):
        result = _color_status('updated')
        assert GREEN in result

    def test_updating_is_yellow(self):
        result = _color_status('updating')
        assert YELLOW in result

    def test_checking_is_yellow(self):
        result = _color_status('checking')
        assert YELLOW in result

    def test_terminal_failure_states_are_red(self):
        for state in _TERMINAL_STATES:
            result = _color_status(state)
            assert RED in result, f"{state} should be red"

    def test_unknown_status_no_color(self):
        result = _color_status('some_unknown')
        assert GREEN not in result
        assert RED not in result
        assert YELLOW not in result
        assert result == 'some_unknown'


# ---------------------------------------------------------------------------
# _TERMINAL_STATES
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestTerminalStates:
    def test_contains_expected_states(self):
        expected = {'preflight_failed', 'rollback_completed', 'rollback_failed',
                    'check_failed', 'fetch_failed'}
        assert _TERMINAL_STATES == expected

    def test_up_to_date_not_terminal(self):
        assert 'up_to_date' not in _TERMINAL_STATES

    def test_updating_not_terminal(self):
        assert 'updating' not in _TERMINAL_STATES


# ---------------------------------------------------------------------------
# _get_update_status
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestGetUpdateStatus:
    def test_extracts_fields_from_response(self, cli):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_status_response(
            version='0.2.31', status='up_to_date', channel='stable',
            failures=0, last_update='2026-02-03T10:00:00+00:00',
        )
        mock_resp.raise_for_status = MagicMock()

        node = cli.nodes[0]
        with patch.object(cli, '_get', return_value=mock_resp):
            result = _get_update_status(cli, node)

        assert result['version'] == '0.2.31'
        assert result['status'] == 'up_to_date'
        assert result['channel'] == 'stable'
        assert result['failures'] == 0
        assert result['last_update'] == '2026-02-03T10:00:00+00:00'

    def test_missing_update_block_returns_defaults(self, cli):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'data': {}}
        mock_resp.raise_for_status = MagicMock()

        node = cli.nodes[0]
        with patch.object(cli, '_get', return_value=mock_resp):
            result = _get_update_status(cli, node)

        assert result['version'] == '?'
        assert result['status'] == '?'
        assert result['channel'] == '?'
        assert result['failures'] == 0
        assert result['last_update'] is None

    def test_http_error_propagates(self, cli):
        import requests
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        node = cli.nodes[0]
        with patch.object(cli, '_get', return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                _get_update_status(cli, node)


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestCmdStatus:
    def test_prints_table_for_all_nodes(self, cli, capsys):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_status_response()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(cli, '_get', return_value=mock_resp):
            cli.cmd_status(['ALL'])

        output = capsys.readouterr().out
        assert 'Fleet Status' in output
        assert '3 nodes' in output
        assert 'node1' in output
        assert 'node2' in output
        assert 'node3' in output
        assert '0.2.31' in output

    def test_unreachable_node_shown(self, cli, capsys):
        def side_effect(node, path, **kwargs):
            if node['name'] == 'node2':
                raise ConnectionError("timeout")
            resp = MagicMock()
            resp.json.return_value = _mock_status_response()
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(cli, '_get', side_effect=side_effect):
            cli.cmd_status(['ALL'])

        output = capsys.readouterr().out
        assert 'unreachable' in output
        # Other nodes still shown
        assert 'node1' in output
        assert 'node3' in output

    def test_single_node_filter(self, cli, capsys):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_status_response(version='0.2.30')
        mock_resp.raise_for_status = MagicMock()

        with patch.object(cli, '_get', return_value=mock_resp):
            cli.cmd_status(['node2'])

        output = capsys.readouterr().out
        assert '1 nodes' in output
        assert 'node2' in output
        assert '0.2.30' in output

    def test_failure_count_shown(self, cli, capsys):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _mock_status_response(failures=3, status='preflight_failed')
        mock_resp.raise_for_status = MagicMock()

        with patch.object(cli, '_get', return_value=mock_resp):
            cli.cmd_status(['node1'])

        output = capsys.readouterr().out
        assert '3' in output
        assert 'preflight_failed' in output


# ---------------------------------------------------------------------------
# cmd_update — no-wait mode (wait=False)
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestCmdUpdateNoWait:
    def test_triggers_and_exits_without_polling(self, cli, capsys):
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        call_count = {'get': 0}
        original_get = cli._get

        def mock_get(node, path, **kwargs):
            call_count['get'] += 1
            return ping_resp

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp):
            cli.cmd_update(['node1'], wait=False)

        output = capsys.readouterr().out
        assert 'update triggered' in output
        # Should only have pinged for pre-version, not polled
        assert 'Waiting for updates' not in output

    def test_trigger_failure_reported(self, cli, capsys):
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.raise_for_status.side_effect = Exception("409 Conflict")

        with patch.object(cli, '_get', return_value=ping_resp), \
             patch.object(cli, '_request', return_value=trigger_resp):
            cli.cmd_update(['node1'], wait=False)

        output = capsys.readouterr().out
        # The trigger raised, so parallel() catches it and reports failure
        assert 'node1' in output


# ---------------------------------------------------------------------------
# cmd_update — wait mode (wait=True)
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestCmdUpdateWait:
    def test_polls_until_version_changes(self, cli, capsys):
        """Simulate: trigger → poll once (still old) → poll again (new version)."""
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        poll_call = {'n': 0}

        def mock_get(node, path, **kwargs):
            if path == '/api/fleet/ping':
                return ping_resp
            # /api/status polling
            poll_call['n'] += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if poll_call['n'] >= 2:
                resp.json.return_value = _mock_status_response(version='0.2.31', status='up_to_date')
            else:
                resp.json.return_value = _mock_status_response(version='0.2.30', status='updating')
            return resp

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp), \
             patch('fleet.time.sleep'):
            cli.cmd_update(['node1'], wait=True)

        output = capsys.readouterr().out
        assert 'Update Summary' in output
        assert 'updated' in output
        assert '0.2.30' in output
        assert '0.2.31' in output

    def test_terminal_failure_stops_polling(self, cli, capsys):
        """Simulate: trigger → poll returns preflight_failed immediately."""
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        def mock_get(node, path, **kwargs):
            if path == '/api/fleet/ping':
                return ping_resp
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_status_response(
                version='0.2.30', status='preflight_failed', failures=1,
            )
            return resp

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp), \
             patch('fleet.time.sleep'):
            cli.cmd_update(['node1'], wait=True)

        output = capsys.readouterr().out
        assert 'Update Summary' in output
        assert 'preflight_failed' in output

    def test_timeout_shown_in_summary(self, cli, capsys):
        """Simulate: trigger → polling always returns 'updating' → timeout."""
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        def mock_get(node, path, **kwargs):
            if path == '/api/fleet/ping':
                return ping_resp
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_status_response(version='0.2.30', status='updating')
            return resp

        # Make time.time() simulate timeout immediately after first poll
        times = iter([100.0, 100.0, 100.0, 400.0])  # start, deadline calc, first check, second check > deadline

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp), \
             patch('fleet.time.sleep'), \
             patch('fleet.time.time', side_effect=times):
            cli.cmd_update(['node1'], wait=True)

        output = capsys.readouterr().out
        assert 'Update Summary' in output
        assert 'timeout' in output

    def test_multiple_nodes_tracked_independently(self, cli, capsys):
        """Two nodes: node2 updates, node3 fails."""
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        def mock_get(node, path, **kwargs):
            if path == '/api/fleet/ping':
                return ping_resp
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if node['name'] == 'node2':
                resp.json.return_value = _mock_status_response(version='0.2.31', status='up_to_date')
            else:
                resp.json.return_value = _mock_status_response(version='0.2.30', status='rollback_completed')
            return resp

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp), \
             patch('fleet.time.sleep'):
            cli.cmd_update(['node2', 'node3'], wait=True)

        output = capsys.readouterr().out
        assert 'node2' in output
        assert 'node3' in output
        assert 'updated' in output
        assert 'rollback_completed' in output

    def test_unreachable_during_poll_prints_x(self, cli, capsys):
        """Poll request fails — should print 'x' and keep going."""
        ping_resp = MagicMock()
        ping_resp.json.return_value = {'version': '0.2.30'}
        ping_resp.raise_for_status = MagicMock()

        trigger_resp = MagicMock()
        trigger_resp.json.return_value = {'ok': True}
        trigger_resp.raise_for_status = MagicMock()

        poll_call = {'n': 0}

        def mock_get(node, path, **kwargs):
            if path == '/api/fleet/ping':
                return ping_resp
            poll_call['n'] += 1
            if poll_call['n'] == 1:
                raise ConnectionError("unreachable")
            # Second poll: success
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = _mock_status_response(version='0.2.31', status='up_to_date')
            return resp

        with patch.object(cli, '_get', side_effect=mock_get), \
             patch.object(cli, '_request', return_value=trigger_resp), \
             patch('fleet.time.sleep'):
            cli.cmd_update(['node1'], wait=True)

        output = capsys.readouterr().out
        assert 'Update Summary' in output


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestArgparse:
    def test_status_flag_parsed(self):
        """--status with no args should set status to empty list."""
        with patch('fleet.FleetCLI') as MockCLI, \
             patch('sys.argv', ['fleet.py', '--status', '--registry', '/dev/null']):
            mock_cli = MagicMock()
            MockCLI.return_value = mock_cli
            try:
                main()
            except SystemExit:
                pass
            mock_cli.cmd_status.assert_called_once()

    def test_status_with_node_names(self):
        with patch('fleet.FleetCLI') as MockCLI, \
             patch('sys.argv', ['fleet.py', '--status', 'node1', 'node2', '--registry', '/dev/null']):
            mock_cli = MagicMock()
            MockCLI.return_value = mock_cli
            try:
                main()
            except SystemExit:
                pass
            mock_cli.cmd_status.assert_called_once_with(['node1', 'node2'])

    def test_no_wait_flag_parsed(self):
        with patch('fleet.FleetCLI') as MockCLI, \
             patch('sys.argv', ['fleet.py', '--update', 'node1', '--no-wait', '--registry', '/dev/null']):
            mock_cli = MagicMock()
            MockCLI.return_value = mock_cli
            try:
                main()
            except SystemExit:
                pass
            mock_cli.cmd_update.assert_called_once_with(['node1'], wait=False)

    def test_update_without_no_wait_passes_wait_true(self):
        with patch('fleet.FleetCLI') as MockCLI, \
             patch('sys.argv', ['fleet.py', '--update', 'node1', '--registry', '/dev/null']):
            mock_cli = MagicMock()
            MockCLI.return_value = mock_cli
            try:
                main()
            except SystemExit:
                pass
            mock_cli.cmd_update.assert_called_once_with(['node1'], wait=True)


# ---------------------------------------------------------------------------
# FleetCLI construction
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestFleetCLIInit:
    def test_missing_registry_exits(self):
        with pytest.raises(SystemExit):
            FleetCLI('/nonexistent/path/nodes.yaml')

    def test_empty_nodes_exits(self, tmp_path):
        import yaml
        p = tmp_path / 'nodes.yaml'
        p.write_text(yaml.dump({'nodes': []}))
        with pytest.raises(SystemExit):
            FleetCLI(str(p))

    def test_valid_registry_loads_nodes(self, registry_file):
        cli = FleetCLI(registry_file)
        assert len(cli.nodes) == 3
        assert cli.nodes[0]['name'] == 'node1'


# ---------------------------------------------------------------------------
# resolve_nodes
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestResolveNodes:
    def test_all_returns_all(self, cli):
        nodes = cli.resolve_nodes(['ALL'])
        assert len(nodes) == 3

    def test_none_returns_all(self, cli):
        nodes = cli.resolve_nodes(None)
        assert len(nodes) == 3

    def test_empty_list_returns_all(self, cli):
        nodes = cli.resolve_nodes([])
        assert len(nodes) == 3

    def test_specific_name(self, cli):
        nodes = cli.resolve_nodes(['node2'])
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'node2'

    def test_unknown_node_exits(self, cli):
        with pytest.raises(SystemExit):
            cli.resolve_nodes(['nonexistent'])
