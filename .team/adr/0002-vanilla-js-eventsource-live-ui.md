# ADR-0002: Vanilla JS with EventSource for live dashboard updates

**Date:** 2026-10-10  
**Status:** Accepted  
**Affected:** Dashboard frontend (s5)

## Context

The dashboard needs to display live updates without requiring manual page refresh. The backend (s4) provides a read-only snapshot contract and SSE stream at `/api/stream`.

Two main approaches:
1. **Polling:** Fetch `/api/snapshot` on an interval
2. **Server-Sent Events:** Use `EventSource` API to push updates from the server

## Decision

Use vanilla JavaScript with the `EventSource` API for live updates. The browser opens `EventSource("api/stream")`, receives full snapshots as `data:` lines, and re-renders on each push.

**Key choices:**
- **Vanilla JS:** No build step, no framework dependencies. The page is a classic `<script>` that runs directly in the browser.
- **Relative URLs:** Snapshot and stream URLs are relative (`api/snapshot`, `api/stream`) so they resolve correctly whether the dashboard runs on localhost or a remote address.
- **Auto-reconnect with exponential backoff:** When the stream closes, wait 1–10 seconds and reconnect. The first push after server restart carries the full snapshot, so no separate refetch is needed.
- **Snapshot structure as-is:** Render every snapshot without aggregation or transformation in Python. All logic to derive views (board, flow, tokens) from the raw snapshot lives in the browser.

## Consequences

**Safe:**
- No network secrets or keys ever leave the backend
- EventSource is natively secure (no CORS bypass, no auth needed for same-origin)

**Predictable:**
- Users see live updates as soon as files change
- Reconnect is automatic; users need not understand downtime recovery

**Trade-offs:**
- Every snapshot push sends the entire state, not deltas (acceptable at run-state size)
- Offline (no internet) does not affect other tabs, only the Flow tab (Mermaid requires CDN)
- No update is guaranteed if the browser tab is closed or the user navigates away

## Implementation

**U1, U2 (architecture.md):**
- `boot()` fetches `/api/snapshot` first, renders, then calls `connectLive()` to open the stream
- If the initial fetch fails, still call `connectLive()` because the stream's first tick sends the full snapshot
- `connectLive()` opens one `EventSource` and never opens a second (close any existing one first)
- On `onopen`: set status to "live", reset backoff to 1 s
- On `onmessage`: parse JSON, normalize, render (drop bad JSON; keep last snapshot)
- On `onerror`: set status to "reconnecting", close `es` if `readyState === CLOSED`, wait `backoff` (doubled up to 10 s), then `connectLive()` again
- No active polling; rely on the stream and the browser's own EventSource retry

**D12 (s4 design):**
- Server computes snapshot fingerprint on each tick (1 s default)
- If fingerprint changed: send full snapshot JSON as `data: <snapshot>\n\n`
- If fingerprint same: send keepalive comment `: keepalive\n\n`
- Loop ends when socket write raises `BrokenPipeError` or `ConnectionResetError`
