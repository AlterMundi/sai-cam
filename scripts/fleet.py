#!/usr/bin/env python3
"""
Fleet Command — remote SAI-Cam node control.

Drives the /api/fleet/* endpoints exposed by each node's status portal.
Nodes and tokens are read from fleet/nodes.yaml (or --registry path).

Usage:
    ./scripts/fleet.py --ping                        # Ping all nodes
    ./scripts/fleet.py --list                        # Show registry
    ./scripts/fleet.py --update saicam3              # Trigger update on one node
    ./scripts/fleet.py --update ALL                  # Trigger update on all nodes
    ./scripts/fleet.py --restart saicam1 saicam2     # Restart services
    ./scripts/fleet.py --reboot saicam3              # Reboot a node
    ./scripts/fleet.py --set updates.channel=beta saicam3
    ./scripts/fleet.py --canary                      # Canary rollout workflow
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("fleet.py requires the 'requests' package: pip install requests")

try:
    import yaml
except ImportError:
    sys.exit("fleet.py requires the 'pyyaml' package: pip install pyyaml")


# ── ANSI helpers ──────────────────────────────────────────────────────────────

GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
CYAN = '\033[36m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'


def ok(msg):
    return f"{GREEN}✓{RESET} {msg}"


def fail(msg):
    return f"{RED}✗{RESET} {msg}"


def warn(msg):
    return f"{YELLOW}⚠{RESET} {msg}"


# ── Fleet CLI ─────────────────────────────────────────────────────────────────

class FleetCLI:
    def __init__(self, registry_path):
        path = Path(registry_path)
        if not path.exists():
            sys.exit(f"Registry not found: {path}\n"
                     f"Copy fleet/nodes.yaml.example → fleet/nodes.yaml and fill in tokens.")
        with open(path) as f:
            data = yaml.safe_load(f)
        self.nodes = data.get('nodes', [])
        if not self.nodes:
            sys.exit("No nodes defined in registry.")

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def _request(self, node, method, path, **kwargs):
        """Single HTTP request to a node with bearer auth."""
        url = f"http://{node['host']}:{node.get('port', 8090)}{path}"
        headers = {'Authorization': f"Bearer {node['token']}"}
        kwargs.setdefault('timeout', 10)
        return requests.request(method, url, headers=headers, **kwargs)

    def _get(self, node, path, **kwargs):
        """Unauthenticated GET (for ping)."""
        url = f"http://{node['host']}:{node.get('port', 8090)}{path}"
        kwargs.setdefault('timeout', 10)
        return requests.get(url, **kwargs)

    def parallel(self, nodes, fn):
        """Run fn(node) across nodes using ThreadPoolExecutor.
        Returns list of (node, result_or_exception) tuples.
        """
        results = []
        with ThreadPoolExecutor(max_workers=max(len(nodes), 1)) as pool:
            futures = {pool.submit(fn, n): n for n in nodes}
            for future in as_completed(futures):
                node = futures[future]
                try:
                    result = future.result()
                    results.append((node, result))
                except Exception as e:
                    results.append((node, e))
        return results

    def resolve_nodes(self, names):
        """Resolve node names to node dicts. 'ALL' returns all nodes."""
        if not names or names == ['ALL']:
            return list(self.nodes)
        resolved = []
        for name in names:
            matches = [n for n in self.nodes if n['name'] == name]
            if not matches:
                print(fail(f"Unknown node: {name}"))
                print(f"  Known nodes: {', '.join(n['name'] for n in self.nodes)}")
                sys.exit(1)
            resolved.extend(matches)
        return resolved

    # ── Commands ──────────────────────────────────────────────────────────

    def cmd_list(self):
        """Show all nodes in the registry."""
        print(f"\n{BOLD}Fleet Registry{RESET} ({len(self.nodes)} nodes)\n")
        print(f"  {'Name':<14} {'Host':<22} {'Port':<6} {'Role':<8}")
        print(f"  {'─'*14} {'─'*22} {'─'*6} {'─'*8}")
        for n in self.nodes:
            print(f"  {n['name']:<14} {n['host']:<22} {n.get('port', 8090):<6} {n.get('role', 'stable'):<8}")
        print()

    def cmd_ping(self):
        """Ping all nodes in parallel."""
        print(f"\n{BOLD}Pinging {len(self.nodes)} nodes…{RESET}\n")

        def ping(node):
            resp = self._get(node, '/api/fleet/ping')
            resp.raise_for_status()
            return resp.json()

        results = self.parallel(self.nodes, ping)
        # Sort by node name for consistent output
        results.sort(key=lambda x: x[0]['name'])

        for node, result in results:
            name = node['name']
            if isinstance(result, Exception):
                print(f"  {fail(f'{name:<14}')} {RED}{result}{RESET}")
            else:
                v = result.get('version', '?')
                up = _fmt_duration(result.get('uptime', 0))
                nid = result.get('node_id', '?')
                print(f"  {ok(f'{name:<14}')} v{v}  up {up}  ({nid})")
        print()

    def cmd_update(self, names):
        """Trigger update on specified nodes."""
        nodes = self.resolve_nodes(names)
        print(f"\n{BOLD}Triggering update on {len(nodes)} node(s)…{RESET}\n")

        def trigger(node):
            resp = self._request(node, 'POST', '/api/fleet/update/apply')
            resp.raise_for_status()
            return resp.json()

        results = self.parallel(nodes, trigger)
        for node, result in results:
            name = node['name']
            if isinstance(result, Exception):
                print(f"  {fail(name)} {result}")
            else:
                print(f"  {ok(name)} update triggered")
        print()

    def cmd_restart(self, names):
        """Restart sai-cam services on specified nodes."""
        nodes = self.resolve_nodes(names)
        print(f"\n{BOLD}Restarting services on {len(nodes)} node(s)…{RESET}\n")

        def restart(node):
            resp = self._request(node, 'POST', '/api/fleet/service/restart')
            resp.raise_for_status()
            return resp.json()

        results = self.parallel(nodes, restart)
        for node, result in results:
            name = node['name']
            if isinstance(result, Exception):
                print(f"  {fail(name)} {result}")
            else:
                print(f"  {ok(name)} restart triggered")
        print()

    def cmd_reboot(self, names):
        """Reboot specified nodes (1 min delay)."""
        nodes = self.resolve_nodes(names)
        print(f"\n{BOLD}Scheduling reboot on {len(nodes)} node(s)…{RESET}\n")

        def reboot(node):
            resp = self._request(node, 'POST', '/api/fleet/reboot')
            resp.raise_for_status()
            return resp.json()

        results = self.parallel(nodes, reboot)
        for node, result in results:
            name = node['name']
            if isinstance(result, Exception):
                print(f"  {fail(name)} {result}")
            else:
                delay = result.get('delay', '1 min')
                print(f"  {ok(name)} reboot scheduled ({delay})")
        print()

    def cmd_set(self, key_value, names):
        """Set a config key on specified nodes."""
        if '=' not in key_value:
            sys.exit(f"Invalid format: {key_value}\nExpected: key=value (e.g. updates.channel=beta)")
        key, value = key_value.split('=', 1)

        # Coerce value types
        if value.lower() in ('true', 'false'):
            value = value.lower() == 'true'

        nodes = self.resolve_nodes(names)
        print(f"\n{BOLD}Setting {key}={value} on {len(nodes)} node(s)…{RESET}\n")

        def set_config(node):
            resp = self._request(node, 'POST', '/api/fleet/config',
                                 json={'key': key, 'value': value})
            resp.raise_for_status()
            return resp.json()

        results = self.parallel(nodes, set_config)
        for node, result in results:
            name = node['name']
            if isinstance(result, Exception):
                print(f"  {fail(name)} {result}")
            elif 'error' in result:
                print(f"  {fail(name)} {result['error']}")
            else:
                print(f"  {ok(name)} {key} = {value}")
        print()

    def cmd_canary(self):
        """Canary rollout: update canary → verify → prompt → update fleet."""
        canaries = [n for n in self.nodes if n.get('role') == 'canary']
        stable = [n for n in self.nodes if n.get('role', 'stable') != 'canary']

        if not canaries:
            sys.exit("No canary node defined. Set role: canary in fleet/nodes.yaml.")

        canary = canaries[0]
        print(f"\n{BOLD}Canary Rollout{RESET}")
        print(f"  Canary:  {canary['name']}")
        print(f"  Fleet:   {', '.join(n['name'] for n in stable)}")
        print()

        # Step 1: Baseline ping
        print(f"{DIM}[1/5]{RESET} Pinging canary for baseline…")
        try:
            resp = self._get(canary, '/api/fleet/ping')
            resp.raise_for_status()
            baseline = resp.json()
            old_version = baseline.get('version', '?')
            cname = canary['name']
            print(f"  {ok(f'{cname}: v{old_version}')}")
        except Exception as e:
            sys.exit(f"  {fail(f'Cannot reach canary: {e}')}")

        # Step 2: Trigger update
        print(f"\n{DIM}[2/5]{RESET} Triggering update on canary…")
        try:
            resp = self._request(canary, 'POST', '/api/fleet/update/apply')
            resp.raise_for_status()
            print(f"  {ok('Update triggered')}")
        except Exception as e:
            sys.exit(f"  {fail(f'Failed to trigger update: {e}')}")

        # Step 3: Poll for version change
        print(f"\n{DIM}[3/5]{RESET} Waiting for canary to update…")
        new_version = _poll_version_change(self, canary, old_version, timeout=180)
        if not new_version:
            sys.exit(f"  {fail('Timeout waiting for canary update (3 min)')}")
        print(f"  {ok(f'{cname}: v{old_version} → v{new_version}')}")

        # Step 4: Health check
        print(f"\n{DIM}[4/5]{RESET} Checking canary health…")
        try:
            resp = self._get(canary, '/api/status')
            resp.raise_for_status()
            status = resp.json()
            cams = status.get('data', {}).get('cameras', [])
            online = sum(1 for c in cams if c.get('online'))
            total = len(cams)
            print(f"  {ok(f'{cname}: healthy, {online}/{total} cameras online')}")
        except Exception as e:
            print(f"  {warn(f'Health check failed: {e}')}")

        # Step 5: Prompt to roll out
        if not stable:
            print(f"\n{ok('No other nodes to update. Canary rollout complete.')}\n")
            return

        print(f"\n{DIM}[5/5]{RESET} {BOLD}Canary healthy. Roll to fleet? [y/N]{RESET} ", end='', flush=True)
        answer = input().strip().lower()
        if answer not in ('y', 'yes'):
            print(f"\n{warn('Aborted. Only canary was updated.')}\n")
            return

        # Roll to fleet
        print(f"\n  Triggering update on {len(stable)} node(s)…")

        # Capture pre-update versions
        pre_versions = {}

        def get_version(node):
            resp = self._get(node, '/api/fleet/ping')
            resp.raise_for_status()
            return resp.json().get('version', '?')

        ver_results = self.parallel(stable, get_version)
        for node, result in ver_results:
            if not isinstance(result, Exception):
                pre_versions[node['name']] = result

        def trigger(node):
            resp = self._request(node, 'POST', '/api/fleet/update/apply')
            resp.raise_for_status()
            return resp.json()

        self.parallel(stable, trigger)

        # Poll all stable nodes for version change
        print(f"  Waiting for fleet to update…")
        time.sleep(15)  # Give nodes time to start updating

        post_versions = {}
        for attempt in range(12):  # ~2 min of polling
            remaining = [n for n in stable if n['name'] not in post_versions]
            if not remaining:
                break
            results = self.parallel(remaining, get_version)
            for node, result in results:
                if not isinstance(result, Exception):
                    old = pre_versions.get(node['name'], '?')
                    if result != old:
                        post_versions[node['name']] = result
            if remaining:
                time.sleep(10)

        # Final report
        print(f"\n{BOLD}Rollout Report{RESET}\n")
        print(f"  {'Node':<14} {'Before':<12} {'After':<12} {'Status':<10}")
        print(f"  {'─'*14} {'─'*12} {'─'*12} {'─'*10}")

        # Canary first
        print(f"  {canary['name']:<14} {old_version:<12} {new_version:<12} {GREEN}updated{RESET}")

        for node in stable:
            name = node['name']
            old = pre_versions.get(name, '?')
            new = post_versions.get(name)
            if new:
                print(f"  {name:<14} {old:<12} {new:<12} {GREEN}updated{RESET}")
            else:
                print(f"  {name:<14} {old:<12} {'?':<12} {YELLOW}pending{RESET}")
        print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_duration(seconds):
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def _poll_version_change(cli, node, old_version, timeout=180):
    """Poll /api/fleet/ping until version changes or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(10)
        try:
            resp = cli._get(node, '/api/fleet/ping')
            resp.raise_for_status()
            data = resp.json()
            current = data.get('version', '?')
            if current != old_version and current != '?':
                return current
            sys.stdout.write('.')
            sys.stdout.flush()
        except Exception:
            sys.stdout.write('x')
            sys.stdout.flush()
    print()  # newline after dots
    return None


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Fleet Command — remote SAI-Cam node control',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s --ping                             Ping all nodes
  %(prog)s --update saicam3                   Update one node
  %(prog)s --update ALL                       Update all nodes
  %(prog)s --restart saicam1 saicam2          Restart services
  %(prog)s --reboot saicam3                   Reboot a node
  %(prog)s --set updates.channel=beta saicam3 Set config key
  %(prog)s --canary                           Canary rollout workflow
""")

    parser.add_argument('--registry', default=None,
                        help='Path to fleet/nodes.yaml (default: auto-detect)')
    parser.add_argument('--list', action='store_true',
                        help='Show all nodes in the registry')
    parser.add_argument('--ping', action='store_true',
                        help='Ping all nodes')
    parser.add_argument('--update', nargs='*', metavar='NODE',
                        help='Trigger update on nodes (or ALL)')
    parser.add_argument('--restart', nargs='*', metavar='NODE',
                        help='Restart services on nodes (or ALL)')
    parser.add_argument('--reboot', nargs='*', metavar='NODE',
                        help='Reboot nodes (or ALL)')
    parser.add_argument('--set', nargs='+', metavar=('KEY=VALUE', 'NODE'),
                        help='Set config key on nodes (e.g. --set updates.channel=beta saicam3)')
    parser.add_argument('--canary', action='store_true',
                        help='Canary rollout: update canary → verify → roll to fleet')

    args = parser.parse_args()

    # Find registry file
    if args.registry:
        registry_path = args.registry
    else:
        # Look relative to this script: scripts/../fleet/nodes.yaml
        script_dir = Path(__file__).resolve().parent
        registry_path = script_dir.parent / 'fleet' / 'nodes.yaml'

    cli = FleetCLI(registry_path)

    # Dispatch
    if args.list:
        cli.cmd_list()
    elif args.ping:
        cli.cmd_ping()
    elif args.update is not None:
        cli.cmd_update(args.update or ['ALL'])
    elif args.restart is not None:
        cli.cmd_restart(args.restart or ['ALL'])
    elif args.reboot is not None:
        cli.cmd_reboot(args.reboot or ['ALL'])
    elif args.set:
        key_value = args.set[0]
        node_names = args.set[1:] or ['ALL']
        cli.cmd_set(key_value, node_names)
    elif args.canary:
        cli.cmd_canary()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
