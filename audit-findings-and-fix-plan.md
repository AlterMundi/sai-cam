# SAI-Cam IPFS/Kafka Audit Findings and Fix Plan

## Scope
This document captures the current audit findings from local changes and a practical implementation plan to resolve them with minimal regression risk.

## Findings

### 1) High: IPFS/Kafka items are dropped on failure and circuit-open paths
- File: `src/camera_service.py`
- Areas:
  - `process_ipfs_queue()` consumes queue items and does not requeue on:
    - IPFS circuit breaker open
    - IPFS upload failure
    - Kafka circuit breaker open
    - Kafka publish failure
- Impact:
  - A transient outage can permanently skip some images unless a manual retry endpoint is executed later.

### 2) Medium: Config options are documented but not honored in runtime
- Files:
  - `src/ipfs_client.py`
  - `src/camera_service.py`
  - `config/config.yaml(.example)`
- Problem:
  - `ipfs.cid_version` and `ipfs.pin` are present in config, but upload params are hardcoded to CIDv1 and pin=true.
  - `ipfs.cleanup_grace_hours` is present in config, but storage cleanup always uses `72`.
- Impact:
  - Operators cannot tune behavior as documented.

### 3) Medium: Fleet status endpoint reports IPFS/Kafka metrics that are not produced
- Files:
  - `src/status_portal.py`
  - `src/camera_service.py`
- Problem:
  - `/api/fleet/status` expects `health.ipfs` and `health.kafka` sections from the camera service health socket.
  - `_get_health_data()` currently does not include those sections.
- Impact:
  - Endpoint returns default zeros/null values that may be interpreted as real telemetry.

---

## Implementation Plan

## Phase 1: Make delivery reliable (highest priority)

### 1.1 Add retry-safe queue behavior in `process_ipfs_queue()`
- Introduce bounded retry metadata per file (in-memory map keyed by filename):
  - `ipfs_attempts`, `kafka_attempts`, `next_eligible_at`.
- On retryable failure or circuit-open:
  - Requeue item with backoff if attempts remain.
  - Move to dead-letter state after max attempts and record an explicit error in metadata.
- Keep queue bounded:
  - Use `put_nowait` and fallback to a small deferred list if full, drained periodically.

### 1.2 Persist delivery state in metadata
- Extend metadata fields:
  - `ipfs_status`: `pending|success|failed`
  - `kafka_status`: `pending|success|failed|disabled`
  - `ipfs_error`, `kafka_error`
  - `ipfs_attempts`, `kafka_attempts`
- Update these fields atomically via `update_metadata_fields()`.

### 1.3 Define retry policy constants
- Add config-backed defaults:
  - `ipfs.max_retries` (default 5)
  - `kafka.max_retries` (default 5)
  - `ipfs.retry_backoff_seconds` (default 10)
  - `kafka.retry_backoff_seconds` (default 10)

## Phase 2: Wire documented config values

### 2.1 Use `ipfs.cid_version` and `ipfs.pin` in `IPFSClient`
- Update `IPFSClient.__init__()` to store validated values from config.
- Build `/add` params from configured values (with sane defaults).

### 2.2 Use `ipfs.cleanup_grace_hours` in `StorageManager`
- Pass `cleanup_grace_hours` from service config into `StorageManager` constructor.
- Remove hardcoded `72` default in `StorageManager` where runtime config is available.

## Phase 3: Expose real observability in health socket

### 3.1 Add runtime counters in `CameraService`
- Track:
  - IPFS: `queue_depth`, `success_count`, `fail_count`, `circuit_breaker_open`, `last_error`
  - Kafka: same shape
- Update counters in success/failure branches.

### 3.2 Include counters in `_get_health_data()`
- Add `ipfs` and `kafka` sections so `/api/fleet/status` reports real data.

### 3.3 Align status portal semantics
- In `/api/fleet/status`, if feature disabled:
  - return explicit `"state": "disabled"` for each integration.
- If enabled but no samples yet:
  - return `"state": "idle"` plus zeroed counters.

---

## Test Plan

### Unit tests
- `IPFSClient`
  - respects `cid_version` and `pin`.
  - retries on timeout/connection errors.
- `KafkaPublisher`
  - publish success/failure paths update return value expectations.
- `CameraService.process_ipfs_queue`
  - requeues on circuit-open and transient failures.
  - marks dead-letter after max attempts.
  - updates metadata fields consistently.
- `StorageManager`
  - uses configured `cleanup_grace_hours`.

### Integration tests
- Simulate:
  - IPFS outage recovery
  - Kafka outage recovery
  - queue saturation
- Verify no silent drops and eventual success or explicit terminal failure state.

### API tests
- `/api/fleet/status` returns:
  - real counters when enabled
  - correct disabled/idle semantics
- `/api/fleet/retry-ipfs` remains functional and compatible with new metadata fields.

---

## Rollout Plan

1. Implement Phase 1 behind conservative defaults.
2. Add tests and run full local suite.
3. Implement Phase 2 config wiring and migration-safe defaults.
4. Implement Phase 3 telemetry and API alignment.
5. Deploy to one staging node with induced failure tests.
6. Roll out progressively to production fleet.

## Acceptance Criteria
- No image is silently dropped from IPFS/Kafka pipeline under transient failures.
- Config values for CID version, pinning, and cleanup grace period are effective at runtime.
- Fleet status endpoint reports accurate IPFS/Kafka telemetry from camera service health data.

---

## Audit Notes and Recommendations for Codex

This section provides an independent audit of the findings and plan, with actionable recommendations for the implementing agent (Codex).

### Findings Validation

All three findings have been **verified against the codebase**:

| Finding | Status | Evidence |
|---------|--------|----------|
| **1. Items dropped** | ✓ Confirmed | `process_ipfs_queue()` in `src/camera_service.py`: queue items were consumed and multiple failure/circuit-open branches exited with `continue` and no requeue path. |
| **2. Config ignored** | ✓ Confirmed | `IPFSClient.add_image()` in `src/ipfs_client.py` had hardcoded `cid-version=1` and `pin=true`. `StorageManager.__init__()` in `src/camera_service.py` used hardcoded `cleanup_grace_hours = 72` without wiring from config. |
| **3. Fleet status** | ✓ Confirmed | `_get_health_data()` in `src/camera_service.py` did not include `ipfs`/`kafka` sections, while `api_fleet_status()` in `src/status_portal.py` expected those keys and returned defaulted values. |

### Plan Corrections / Clarifications

1. **Phase 1.2 — metadata field naming**: The plan uses `ipfs_status` / `kafka_status`. Ensure `retry-ipfs` does not filter by these; it currently scans for `ipfs_cid` and `kafka_published` only. New fields are additive and compatible.

2. **Phase 2.2 — config source**: `cleanup_grace_hours` lives under `ipfs` in config, but it drives `StorageManager`. Pass it from `CameraService.setup_storage()`:
   ```python
   cleanup_grace_hours = self.config.get('ipfs', {}).get('cleanup_grace_hours', 72)
   ```
   Add `cleanup_grace_hours` as a constructor parameter to `StorageManager`; remove the hardcoded `72` inside it.

3. **Phase 3.3 — disabled vs idle semantics**: The plan says "if feature disabled: return explicit state: disabled". Currently `api_fleet_status` only adds `ipfs`/`kafka` sections when `ipfs_enabled or kafka_enabled`. When both disabled, those sections are omitted. Recommendation: When disabled, either omit the section *or* include it with `"state": "disabled"`. When enabled but no data yet, use `"state": "idle"` with zeroed counters.

### Additional Findings Not in Original Plan

4. **Queue-full drop at capture time** (camera_service.py:209–212): When `ipfs_queue.put_nowait()` raises `queue.Full`, the item is logged as "skipping (retry will recover)" but no automatic retry exists. The only recovery is manual `POST /api/fleet/retry-ipfs`. Phase 1.1 mentions a "deferred list if full" — clarify whether this applies to:
   - (a) requeue path (when putting a failed item back), and/or
   - (b) capture path (when adding a new item to a full queue).
   Recommendation: Implement (a) first. For (b), consider a small in-memory deferred list in the capture flow, drained by the IPFS processor when the queue has capacity.

5. **Startup recovery**: If the process restarts while items are in the queue or in retry backoff, those items are lost (queue is in-memory). `retry-ipfs` can recover by scanning metadata. Consider this as a **Phase 4 enhancement**: On startup, scan pending metadata (files with `ipfs_status in (pending, None)` or missing `ipfs_cid`) and repopulate the IPFS queue.

6. **Circuit breaker configurability**: The circuit breaker uses a hardcoded threshold (3 failures) and initial backoff (300s). The plan adds `max_retries` and `retry_backoff_seconds` for per-item retries but does not address circuit breaker params. Optional: add `ipfs.circuit_breaker_threshold` (default 3) and `ipfs.circuit_breaker_initial_backoff_seconds` (default 300) if operators need tuning.

7. **Prometheus metrics**: `status_portal.py` has Prometheus gauges for cameras, health, storage — but not IPFS/Kafka. Consider this as a **Phase 4 enhancement** by adding gauges such as `saicam_ipfs_queue_depth`, `saicam_ipfs_success_total`, `saicam_ipfs_fail_total` (and Kafka equivalents) in `_update_prometheus_metrics()`.

8. **Kafka message schema**: `KafkaPublisher.publish_cid()` builds a message with `metadata.get("filename", "")`. The capture metadata does not include a top-level `filename` key (the filename is the file key). Consider adding `filename` to the metadata at `store_image()` or passing it into `publish_cid()` so Kafka messages are complete. (Lower priority; verify if consumers need it.)

### Implementation Order for Codex

1. **Phase 1.3 first** — Add config keys (`ipfs.max_retries`, etc.) to `config.yaml.example` and config loading so Phase 1.1 has values to use.
2. **Phase 1.2** — Extend metadata schema and `update_metadata_fields()` usage.
3. **Phase 1.1** — Implement retry loop with requeue, backoff, and dead-letter; integrate with 1.2 and 1.3.
4. **Phase 2** — Wire config into `IPFSClient` and `StorageManager`.
5. **Phase 3** — Add counters and health sections.

### Test Checklist for Codex

- [ ] Unit test: IPFS circuit open → item requeued, not dropped.
- [ ] Unit test: IPFS add returns `None` → item requeued with backoff; after max attempts → metadata marked failed, not requeued.
- [ ] Unit test: Kafka circuit open → item requeued (with CID already set).
- [ ] Unit test: `cleanup_grace_hours` from config is used by `StorageManager._within_ipfs_grace()`.
- [ ] Integration: Induce IPFS failure for 3+ items, then recover → verify no drops or explicit terminal state in metadata.
- [ ] API: `GET /api/fleet/status` with IPFS enabled returns non-empty `ipfs` section with real `queue_depth`, `success_count`, etc.

### Files to Modify (Summary)

| File | Changes |
|------|---------|
| `src/camera_service.py` | process_ipfs_queue retry/requeue logic; StorageManager constructor call; _get_health_data ipfs/kafka sections; in-memory retry map; optional startup queue repopulation |
| `src/ipfs_client.py` | Read cid_version, pin from config; use in add_image params |
| `src/status_portal.py` | api_fleet_status disabled/idle semantics; optional Prometheus IPFS/Kafka gauges |
| `config/config.yaml.example` | Add ipfs.max_retries, ipfs.retry_backoff_seconds, kafka.max_retries, kafka.retry_backoff_seconds (if not present) |
| `tests/` | New/updated unit and integration tests per Test Plan |
