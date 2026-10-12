# ADR-0026: Proxy sandbox can reach local services via allowLocalBinding

**Decision:** Service deliveries (those with `Start.BACKGROUND`) get `network.allowLocalBinding: true` in their OS sandbox settings. All other deliveries keep filesystem-only settings. The network dict is always a fresh copy to prevent callers from mutating the module constant. E2E verification runs on macOS only with clear platform skip messaging.

**Date:** 2026-10-11

## Context

The Customer Proxy's acceptance tests failed repeatedly with "connection refused" when trying to curl the delivery's local service from inside the OS sandbox. The liaison reproduced it: the service is running and probed successfully from outside the sandbox, but `curl` from inside the Bash sandbox exits 7 (connection refused).

Testing with the bundled claude CLI and real sandbox settings showed that `"network": {"allowLocalBinding": true}` in the Seatbelt (macOS) sandbox permits loopback access, while `"network": {"allowedDomains": ["127.0.0.1", "localhost"]}` does not help. Linux bubblewrap sandbox has its own network namespace and was not verified.

## Decision

### Rules for network sandbox settings (N1–N4)

- **N1 Delivery kind determines binding:** A delivery that serves locally (kind with `Start.BACKGROUND`) gets the network setting. The delivery table already defines this: `DeliveryKind.start`. No new field on `DeliveryKind`; a new module constant maps start modes to network settings.

- **N2 Filesystem-only for non-service kinds:** Kinds without `Start.BACKGROUND` (`package`, `script`, `library`, `harness`, `manual`) have no `network` key in their sandbox settings. The other four keys (`enabled`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `filesystem`) are unchanged for all kinds.

- **N3 Fresh copy each time:** The network dict is always a new `dict` object created per call (`{"allowLocalBinding": True}` passed through `dict()`), never the module constant itself. This prevents callers that edit the settings (e.g., the e2e test removes the key) from mutating the shared module state.

- **N4 Only allowLocalBinding:** Only this setting is added. `allowedDomains`, `allowUnixSockets`, and other network keys were either tried (no effect on macOS) or would widen the sandbox unnecessarily. The Playwright MCP server runs outside the Bash sandbox and is not affected.

### Verification (V1–V2)

- **V1 Platform-specific e2e:** The e2e test `tests/e2e/test_proxy_sandbox_e2e.py` runs on macOS only. It starts a scripted model (stdlib `http.server.ThreadingHTTPServer`) and a real service on loopback, invokes the bundled claude CLI with the real sandbox settings, and verifies that a sandboxed `curl` gets 200 with the network key and exits 7 without it. The test is skipped on non-macOS platforms with the reason in the skip message. A missing bundled CLI is a failure, not a skip.

- **V2 Linux not verified:** The bubblewrap sandbox on Linux has its own network namespace; `allowLocalBinding` is documented for macOS Seatbelt. Documentation states this explicitly.

### Service lifecycle (L1)

- **L1 Fresh service per Proxy step:** `Trial.liveness` (run as the e2e gate trial) starts the service, probes it, and stops it **by design** (a gate must not leave processes running). The Proxy step does not reuse it. `Runtime.plan()` → `_attach_delivery` → `prepare_fn` starts a fresh one. From `plan()` return to `_execute`'s `finally`, nothing stops the service. Consequence: the Proxy curl'ing the service is guaranteed a fresh, probed process. No code change; documented to clarify the lifecycle.

### Implementation

**New constants in `agile-team/runner/agile_team/sandbox.py` (after `DELIVERY_KINDS`, before `MCP_SERVERS`):**

```python
LOCAL_SERVICE_NETWORK: dict[str, Any] = {"allowLocalBinding": True}
NETWORK_BY_START: dict[Start, dict[str, Any]] = {Start.BACKGROUND: LOCAL_SERVICE_NETWORK}
```

**New helper `_network(prepared)` (private):**

```python
def _network(prepared: Prepared) -> dict[str, Any]:
    """The ``network`` key for a delivery that serves locally; nothing for the rest."""
    network = NETWORK_BY_START.get(prepared.kind.start)
    return {"network": dict(network)} if network else {}
```

**Updated `_sandbox_section(config, prepared)`:** Merge result with `**_network(prepared)`:

```python
return {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    "allowUnsandboxedCommands": ...,
    "filesystem": {...},
    **_network(prepared),
}
```

**Updated docstring for `os_sandbox_settings(config, prepared)`:**

```python
"""Claude Code settings for the Proxy's OS sandbox.

The sandbox denies reading the repo except the allowed paths and, for a
delivery that serves locally (``NETWORK_BY_START``), allows reaching it on
loopback. ``tests/e2e/test_proxy_sandbox_e2e.py`` runs the bundled claude
CLI with these settings on macOS (Seatbelt): a sandboxed ``curl`` gets 200
from a live local service, and exits 7 when the ``network`` key is removed.
The Linux (bubblewrap) sandbox is not verified end to end.
"""
```

### Tests (from design checklist)

**Unit tests (test_sandbox.py):**
- `web` delivery has `network` key with `allowLocalBinding: True`
- Non-service kinds (package, script, library, harness, manual) have no `network` key
- Filesystem keys unchanged for `web` delivery
- Changing the returned network dict leaves module constant unchanged
- `os_sandbox_settings.__doc__` lacks "Not verified" and names the e2e test

**Unit tests (dispatch.py Proxy plan tests):**
- `Prepared.stop` not called before `query_fn`, called once after it returns
- Same when `query_fn` raises

**E2E test (test_proxy_sandbox_e2e.py):**
- Runs on macOS only (pytest mark with stated reason)
- Scripted model on free loopback port, real service on another port
- Settings built with `web` delivery, real sandbox settings
- With network key: CLI exits 0, recorded tool result contains `200 exit=0`
- Without network key: recorded tool result contains `exit=7` (proving sandbox was active)

## Consequences

**Positive:**
- Proxy acceptance tests can curl local services from inside the sandbox without "connection refused" bounces.
- Service lifecycle is now explicit: gate starts and stops, Proxy gets a fresh one.
- E2E verification (macOS) proves the setting works; documentation clarifies why Linux is not verified.
- Module constants and helper keep the code DRY and testable.

**Tradeoffs:**
- E2E test is skipped on Linux. A unit test pins the network key presence for peace of mind on that platform.
- Only macOS Seatbelt is verified. If Claude Code's sandbox changes, this ADR and e2e test serve as a contract.

**Implementation notes:**
- `_network()` returns a fresh dict every time; callers cannot pollute the module constant.
- The e2e test uses a scripted model (stdlib HTTP server in a thread) to stay offline and deterministic.
- `NETWORK_BY_START` is a mapping, so adding a new start mode that serves locally is a single table entry.

## References

- Story: `.team/stories/s58.md`
- Design: `agile-team/docs/design/s58.md`
- Review: `.team/reviews/s58.md`
