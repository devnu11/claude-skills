"""Generate the fake run behind the dashboard mock (`?mock`).

Usage: python scripts/make_dashboard_fixture.py agile_team/dashboard/fixtures/snapshot.json
"""

import json
import random
import sys

rng = random.Random(7)
T0 = 1791450000.0  # 2026-10-08 ~09:00 UTC
t = T0
events, ledger, messages, answers = [], [], [], []

PRICE = {  # $/Mtok: input, output, cache read, cache write
    "opus": (5, 25, 0.5, 6.25),
    "sonnet": (3, 15, 0.3, 3.75),
    "haiku": (1, 5, 0.1, 1.25),
    "qwen3-coder": (0, 0, 0, 0),
}
ROLES = {
    "product-owner": ("opus", "anthropic"),
    "architect": ("opus", "anthropic"),
    "unit-tester": ("sonnet", "anthropic"),
    "developer-cli": ("sonnet", "anthropic"),
    "quality-czar": ("qwen3-coder", "local"),
    "code-reviewer": ("opus", "anthropic"),
    "integration-tester": ("sonnet", "anthropic"),
    "customer-proxy": ("sonnet", "anthropic"),
    "manager": ("sonnet", "anthropic"),
    "scribe": ("qwen3-coder", "local"),
}


def tick(lo=40, hi=420):
    global t
    t += rng.uniform(lo, hi)
    return round(t, 1)


def ev(kind, role=None, story=None, **data):
    events.append(
        {
            "id": f"e{len(events) + 1}",
            "at": tick(),
            "kind": kind,
            "role": role,
            "story": story,
            "data": data,
        }
    )


def tokens(role):
    big = role in ("architect", "code-reviewer", "developer-cli")
    k = 2.0 if big else 1.0
    return {
        "input": int(rng.uniform(3e3, 14e3) * k),
        "output": int(rng.uniform(1.5e3, 7e3) * k),
        "cache_read": int(rng.uniform(40e3, 180e3) * k),
        "cache_creation": int(rng.uniform(8e3, 25e3) * k),
    }


def cost(model, tok):
    p = PRICE[model]
    parts = (tok["input"], tok["output"], tok["cache_read"], tok["cache_creation"])
    return round(sum(n * r / 1e6 for n, r in zip(parts, p, strict=True)), 4)


def charge(role, story, at):
    model = ROLES[role][0]
    tok = tokens(role)
    c = cost(model, tok)
    turns = rng.randint(4, 40)
    ledger.append(
        {
            "at": at,
            "role": role,
            "model": model,
            "story": story,
            "cost_usd": c,
            "tokens": tok,
            "turns": turns,
        }
    )
    return tok, c, turns


def step(role, story, brief, status="done", summary="", next_role=None, oq=(), **extra):
    ev("step-start", role, story, brief=brief)
    at = tick(90, 600)
    tok, c, turns = charge(role, story, at)
    events.append(
        {
            "id": f"e{len(events) + 1}",
            "at": at,
            "kind": "step-end",
            "role": role,
            "story": story,
            "data": {
                "status": status,
                "summary": summary,
                "next_role": next_role,
                "open_questions": list(oq),
                "tokens": tok,
                "cost_usd": c,
                "turns": turns,
                "commit": f"{rng.getrandbits(28):07x}",
                **extra,
            },
        }
    )


def gate(story, step_, verdict, now_at, rounds, status="active", reason=""):
    ev(
        "gate",
        None,
        story,
        step=step_,
        verdict=verdict,
        now_at=now_at,
        rounds=rounds,
        story_status=status,
        reason=reason,
    )


def po_turn():
    charge("product-owner", None, tick(5, 30))


def msg(kind, text, stories=(), answer=None):
    mid = f"m{len(messages) + 1}"
    at = tick(10, 60)
    messages.append({"id": mid, "kind": kind, "text": text, "stories": list(stories), "at": at})
    events.append(
        {
            "id": f"e{len(events) + 1}",
            "at": at,
            "kind": "message",
            "role": "product-owner",
            "story": None,
            "data": {"message": mid},
        }
    )
    if answer:
        a_at = tick(120, 900)
        answers.append({"id": mid, "text": answer, "at": a_at})
        events.append(
            {
                "id": f"e{len(events) + 1}",
                "at": a_at,
                "kind": "answer",
                "role": None,
                "story": None,
                "data": {"message": mid},
            }
        )
    return mid


# ----- the run -------------------------------------------------------------

msg(
    "question",
    "Kickoff: should CSV export cover only `report run`, or also `report schedule`? "
    "And is Excel on Windows a target consumer?",
    answer="Only `report run` for now. Yes, Excel on Windows matters: finance opens these.",
)
po_turn()
STORIES = [
    ("s1", "Export a report as CSV"),
    ("s2", "Choose which columns to export"),
    ("s3", "Stream large exports without loading them into memory"),
    ("s4", "Excel-friendly encoding"),
    ("s5", "Export through the HTTP API"),
    ("s6", "Scheduled exports"),
]
for sid, title in STORIES:
    ev("story-opened", "product-owner", sid, title=title, step="design")
ev(
    "sprint-start",
    "product-owner",
    None,
    sprint=1,
    goal="CSV export from the CLI, safe for big reports and Excel",
    stories=["s1", "s2", "s3", "s4"],
)
step(
    "manager",
    None,
    "Sprint 1 start: 4 stories, $20 budget.",
    summary="Scope fits the budget if s3 stays CLI-only. Approved.",
)
msg("update", "Sprint 1 started: s1-s4. s5 and s6 stay in the backlog.", ["s1", "s2", "s3", "s4"])

# s1 all the way through
step(
    "architect",
    "s1",
    "Design CSV output for `report run --format csv`.",
    summary="Added REQ-001 (RFC 4180 output) and REQ-002 (schema column order). "
    "Needs developer-cli.",
    next_role="unit-tester",
    requirements_added=["REQ-001", "REQ-002"],
)
ev(
    "requirement-changed",
    "architect",
    "s1",
    id="REQ-001",
    change="added",
    reason="New: CSV output format",
)
ev(
    "requirement-changed",
    "architect",
    "s1",
    id="REQ-002",
    change="added",
    reason="New: column order",
)
gate("s1", "design", "pass", "tests", 0, reason="all ACs traced")
step(
    "unit-tester",
    "s1",
    "Red tests for CSV writer per REQ-001/002.",
    summary="12 failing tests in tests/test_csv_export.py.",
)
gate("s1", "tests", "pass", "implement", 0, reason="tests fail as expected")
step(
    "developer-cli", "s1", "Implement CSV writer.", summary="Added export/csv.py and --format csv."
)
gate("s1", "implement", "pass", "quality", 0, reason="coverage 96.4%")
step("quality-czar", "s1", "Lint and static checks.", summary="Clean; renamed one helper.")
gate("s1", "quality", "pass", "review", 0)
step("code-reviewer", "s1", "Review against REQ-001/002.", summary="LGTM. Quoting matches REQ-001.")
gate("s1", "review", "pass", "design-review", 0)
step("architect", "s1", "Design review.", summary="Code matches the design.")
gate("s1", "design-review", "pass", "e2e", 0)
step("integration-tester", "s1", "E2E on a 1k-row report.", summary="3 e2e tests pass.")
gate("s1", "e2e", "pass", "acceptance", 0)
step(
    "customer-proxy",
    "s1",
    "Accept s1 as a finance user.",
    summary="Exported a report and opened it; AC1-AC3 met.",
)
gate("s1", "acceptance", "pass", "acceptance", 0, status="done")
ev("po-session", "product-owner", None, path="compact", reasons=["s1 done"], pre_tokens=182000)
step("scribe", None, "Record s1 decisions.", summary="ADR 0003: csv module over pandas.")
po_turn()

# s3 starts, then bounces at implement until the round cap
step(
    "architect",
    "s3",
    "Design streaming export.",
    summary="Added REQ-003 (bounded memory) and REQ-004 (progress on stderr).",
    requirements_added=["REQ-003", "REQ-004"],
)
ev(
    "requirement-changed",
    "architect",
    "s3",
    id="REQ-003",
    change="added",
    reason="New: memory bound",
)
ev("requirement-changed", "architect", "s3", id="REQ-004", change="added", reason="New: progress")
gate("s3", "design", "pass", "tests", 0, reason="all ACs traced")
step("unit-tester", "s3", "Red tests for streaming.", summary="Memory-bound test with 2M rows.")
gate("s3", "tests", "pass", "implement", 0)

# s2 design changes REQ-002 (affects done story s1)
step(
    "architect",
    "s2",
    "Design --columns.",
    summary="Changed REQ-002: column order follows --columns. s1 is affected.",
    requirement_changes={
        "REQ-002": "Order must follow --columns, not schema order; "
        "finance relies on a fixed layout."
    },
)
ev(
    "requirement-changed",
    "architect",
    "s2",
    id="REQ-002",
    change="changed",
    reason="Order must follow --columns, not schema order; finance relies on a fixed layout.",
    affected_done_stories=["s1"],
)
gate("s2", "design", "pass", "tests", 0, reason="all ACs traced")
po_turn()

step(
    "developer-cli",
    "s3",
    "Implement streaming writer.",
    status="done",
    summary="Generator-based writer.",
)
gate("s3", "implement", "bounce", "implement", 1, reason="coverage 88.1% is below 95%")
step("unit-tester", "s2", "Red tests for --columns.", summary="8 failing tests.")
gate("s2", "tests", "pass", "implement", 0)
step(
    "developer-cli",
    "s3",
    "Coverage below 95%: cover the progress path.",
    summary="Added progress tests.",
    oq=["Is pandas acceptable as a dependency for chunked reads?"],
)
gate(
    "s3",
    "implement",
    "bounce",
    "implement",
    2,
    reason="tests fail:\nFAILED tests/test_stream.py::test_memory_bound - 412MB > 256MB",
)
step("developer-cli", "s2", "Implement --columns.", summary="Columns filter + ordering.")
gate("s2", "implement", "pass", "quality", 0, reason="coverage 95.8%")
step("quality-czar", "s2", "Lint.", summary="Clean.")
gate("s2", "quality", "pass", "review", 0)
step(
    "code-reviewer",
    "s2",
    "Review --columns.",
    status="changes_requested",
    summary="Unknown column names are silently dropped; REQ-002 says error.",
    next_role="developer-cli",
)
gate("s2", "review", "bounce", "implement", 1, reason="Unknown columns silently dropped")
step(
    "developer-cli",
    "s3",
    "Memory test fails at 412MB.",
    status="done",
    summary="Switched to row iterator; still buffering in sort.",
)
gate(
    "s3",
    "implement",
    "bounce",
    "implement",
    3,
    status="needs_manager",
    reason="tests fail: 301MB > 256MB",
)
msg(
    "question",
    "s3 keeps failing the memory bound because sorting needs the whole result. "
    "May the export spill to a temp file (up to 1 GB) when --sort is used?",
    ["s3"],
)

# s4 design blocked on a question
step(
    "architect",
    "s4",
    "Design Excel-friendly encoding.",
    status="blocked",
    summary="Need a product decision on BOM default.",
    oq=["Should a UTF-8 BOM be written by default, or only with --excel?"],
    requirements_added=["REQ-005"],
)
ev(
    "requirement-changed",
    "architect",
    "s4",
    id="REQ-005",
    change="added",
    reason="New: BOM for Excel",
)
gate("s4", "design", "hold", "design", 0, reason="role reported blocked")
msg(
    "question",
    "s4: should exports write a UTF-8 BOM by default (Excel opens them correctly) "
    "or only with a new --excel flag (cleaner for scripts)?",
    ["s4"],
)
po_turn()

step("developer-cli", "s2", "Error on unknown columns per REQ-002.", summary="Raises UsageError.")
gate("s2", "implement", "pass", "quality", 1, reason="coverage 96.0%")
step("quality-czar", "s2", "Lint.", summary="Clean.")
gate("s2", "quality", "pass", "review", 1)
ev("step-start", "code-reviewer", "s2", brief="Re-review --columns after the fix.")

# ----- assemble ------------------------------------------------------------

REQS = [
    {
        "id": "REQ-001",
        "title": "CSV output follows RFC 4180",
        "status": "active",
        "covers": ["s1/AC1", "s1/AC2"],
        "text": "Fields are comma-separated, quoted when they contain a comma, quote or "
        "newline; quotes are doubled; lines end with CRLF.",
    },
    {
        "id": "REQ-002",
        "title": "Column selection and order",
        "status": "active",
        "covers": ["s1/AC3", "s2/AC1", "s2/AC2", "s2/AC3"],
        "text": "Columns appear in the order given by --columns, or schema order when "
        "omitted. An unknown column name is a usage error (exit 2).",
    },
    {
        "id": "REQ-003",
        "title": "Bounded memory while exporting",
        "status": "active",
        "covers": ["s3/AC1"],
        "text": "Peak RSS stays under 256 MB for any report size.",
    },
    {
        "id": "REQ-004",
        "title": "Progress on stderr",
        "status": "active",
        "covers": ["s3/AC2"],
        "text": "With --progress, a row counter is written to stderr at most once per second.",
    },
    {
        "id": "REQ-005",
        "title": "Excel opens UTF-8 exports correctly",
        "status": "active",
        "covers": ["s4/AC1"],
        "text": "Non-ASCII characters display correctly when the file is opened in Excel "
        "on Windows. (BOM default pending the human's answer.)",
    },
]
history = {r["id"]: [] for r in REQS}
for e in events:
    if e["kind"] == "requirement-changed":
        d = e["data"]
        history[d["id"]].append(
            {
                "at": e["at"],
                "change": d["change"],
                "reason": d["reason"],
                "role": e["role"],
                "story": e["story"],
                "sha": f"{rng.getrandbits(28):07x}",
            }
        )
for r in REQS:
    r["history"] = history[r["id"]]

AC = {
    "s1": [
        "Running `report run --format csv` writes CSV to stdout",
        "Values with commas, quotes or newlines survive a round trip",
        "Columns appear in a predictable order",
    ],
    "s2": [
        "--columns a,b,c exports only those columns",
        "Output order follows --columns",
        "An unknown column name fails with a clear message",
    ],
    "s3": [
        "A 2M-row report exports with memory under 256 MB",
        "--progress shows rows written so far",
    ],
    "s4": [
        "Accented names display correctly in Excel on Windows",
        "Scripts that read the CSV are not broken by the change",
    ],
    "s5": ["GET /reports/{id}.csv returns the export"],
    "s6": ["A schedule can attach a CSV export to its email"],
}
INITIAL = {"s1": 1, "s2": 1, "s3": 1, "s4": 1, "s5": None, "s6": None}
stories = []
for sid, title in STORIES:
    stories.append(
        {
            "id": sid,
            "title": title,
            "sprint": INITIAL[sid],
            "environment": "cli",
            "step": "design",
            "status": "active",
            "rounds": 0,
            "opened_at": None,
            "acceptance": [{"id": f"AC{i + 1}", "text": x} for i, x in enumerate(AC[sid])],
        }
    )
for e in events:
    s = next((s for s in stories if s["id"] == e["story"]), None)
    if not s:
        continue
    if e["kind"] == "story-opened":
        s["opened_at"] = e["at"]
    if e["kind"] == "gate":
        d = e["data"]
        s["step"], s["status"], s["rounds"] = d["now_at"], d["story_status"], d["rounds"]

snapshot = {
    "generated_at": t,
    "run": {
        "status": "running",
        "sprint": 1,
        "cadence": "sprint",
        "task": "Add CSV export to the reporting CLI so finance can open reports in Excel.",
        "budget_usd": 20.0,
        "manager_every_pct": 25,
        "round_cap": 3,
        "manager_due": ["story s3 hit the round cap"],
    },
    "pipeline": [
        "design",
        "tests",
        "implement",
        "quality",
        "review",
        "design-review",
        "e2e",
        "acceptance",
    ],
    "roles": [{"name": n, "model": m, "provider": p} for n, (m, p) in ROLES.items()],
    "stories": stories,
    "requirements": REQS,
    "events": events,
    "ledger": sorted(ledger, key=lambda x: x["at"]),
    "messages": messages,
    "answers": answers,
}

# ----- live meter (s44) ------------------------------------------------------
# The curated fixture (upstream, priority, boundary) outgrew the generator above,
# so the live additions are applied on top of the existing file when there is one.

CURATED_END = 1791472260.0  # the last curated event; everything after is generated here
LIVE_STORY, LIVE_ROLE = "s3", "developer-cli"
MODEL_ID = {"opus": "claude-opus-4-1", "sonnet": "claude-sonnet-4-5-20250929"}


def live_turns(now, rnd):
    """About 40 turns in the 10 minutes before ``now``: the dev's step plus a few PO turns."""
    rows = []
    for i in range(40):
        at = round(now - 600 + i * 14.5 + rnd.uniform(0, 6), 1)
        po = i % 9 == 4
        role, story, step_ = (
            ("product-owner", None, None) if po else (LIVE_ROLE, LIVE_STORY, "implement")
        )
        family = ROLES[role][0]
        tok = {
            "input": rnd.randint(1, 9),
            "output": rnd.randint(150, 900),
            "cache_read": rnd.randint(30_000, 90_000),
            "cache_creation": rnd.randint(0, 2_500),
        }
        rows.append(
            {
                "at": at,
                "role": role,
                "story": story,
                "step": step_,
                "turn": i + 1,
                "model": MODEL_ID[family],
                "tokens": tok,
                "tools": [] if i % 3 else ["Bash"],
                "cost_usd": cost(family, tok),
                "message_id": f"msg_fixture_{i:03d}",
            }
        )
    return rows


def live_events(base, now):
    """An interrupted step-end, then the same step started again (shows as restarted)."""
    first = {"role": LIVE_ROLE, "story": LIVE_STORY}
    data = {
        "status": "interrupted",
        "reason": "exit 143 (SIGTERM)",
        "cause": "sigterm",
        "halt": "stopped by stop --now",
        "turns": 7,
        "tokens": {"input": 18, "output": 4210, "cache_read": 402_000, "cache_creation": 9_100},
        "estimate_usd": 0.0812,
        "model": MODEL_ID["sonnet"],
        "opened_at": round(now - 520, 1),
        "tool_s": 161.2,
        "model_s": 28.8,
        "waiting_s": 0.0,
    }
    rows = [
        ("step-start", now - 520, {"brief": "Memory test fails at 412MB."}),
        ("step-end", now - 330, data),
        ("step-start", now - 200, {"brief": "Memory test fails at 412MB."}),
    ]
    n = len(base)
    events = [
        {"id": f"e{n + i + 1}", "at": round(at, 1), "kind": kind, **first, "data": d}
        for i, (kind, at, d) in enumerate(rows)
    ]
    turn = {"opened_at": round(now - 400, 1), "tool_s": 312.5, "model_s": 9.5, "waiting_s": 312.5}
    po_turn = {
        "id": f"e{n + len(rows) + 1}",
        "at": round(now - 60, 1),
        "kind": "po-turn",
        "role": "product-owner",
        "story": None,
        "data": {**turn, "mono": 5400.0, "slept": 0.0},
    }
    return [*events, po_turn]


def open_call(now):
    """The one call still open in the live step (s101 N11)."""
    return {
        "role": LIVE_ROLE,
        "story": LIVE_STORY,
        "step": "implement",
        "opened_at": round(now - 200, 1),
        "tool": "Bash",
        "tool_use_id": "toolu_open",
        "label": "Dev: run the unit tests again",
        "detail": "uv run pytest -q tests/test_x.py",
        "at": round(now - 40, 1),
        "mono": 5160.0,
        "slept": 0.0,
        "status": "open",
    }


def live_heartbeat(now, turns):
    mine = [x for x in turns if x["role"] == LIVE_ROLE]
    last = mine[-1]
    tok = {k: sum(x["tokens"][k] for x in mine) for k in last["tokens"]}
    return {
        "version": 1,
        "pid": 4242,
        "beat": "beating",
        "at": round(now - 3, 1),
        "started_at": round(now - 3600, 1),
        "chore": None,
        "step": {
            "role": LIVE_ROLE,
            "story": LIVE_STORY,
            "step": "implement",
            "started_at": round(now - 200, 1),
            "turn": 14,
            "model": last["model"],
            "configured_model": "sonnet",
            "last_turn_at": min(last["at"], round(now - 8, 1)),
            "tool": {"name": "Bash", "started_at": round(now - 40, 1)},
            "tokens": tok,
            "cost_usd": round(sum(x["cost_usd"] for x in mine), 4),
        },
        "calls": [open_call(now)],
    }


def tool_row(step, label, seconds, offset):
    """One span row of the live step, in the tools.jsonl shape (s98 TC11)."""
    at = step["opened_at"] + offset
    tool = label.split(": ")[-1] if label.startswith("Dev: ") else label
    return {
        **step,
        "tool": "Bash" if label.startswith("Dev: run") else tool,
        "tool_use_id": f"toolu_{offset}",
        "label": label,
        "detail": "uv run pytest -q tests/test_x.py" if "Dev" in label else "developer",
        "at": at,
        "mono": 5000.0 + offset,
        "slept": 0.0,
        "seconds": seconds,
        "ended_at": at + seconds,
        "status": "ok",
    }


def tools_section(snap):
    """The snapshot's ``tools`` groups: interrupted step, live step, PO turn (s98 TC15, s101)."""
    now = snap["generated_at"]
    beat = snap["heartbeat"]["step"]
    key = ("role", "story", "step")
    live_step = {**{k: beat[k] for k in key}, "opened_at": beat["started_at"]}
    old_step = {**live_step, "opened_at": round(now - 520, 1)}
    po_step = {
        "role": "product-owner",
        "story": None,
        "step": "po-session",
        "opened_at": round(now - 400, 1),
    }
    cut = {**tool_row(old_step, "Dev: run the unit tests", 130.0, 60.0), "status": "unfinished"}
    slow = tool_row(live_step, "Dev: run the unit tests", 41.2, 30.0)
    timed_out = {**tool_row(live_step, "Dev: run the e2e tests", 120.0, 90.0), "status": "timeout"}
    read = {
        **tool_row(live_step, "Dev: Read", 4.0, 75.0),
        "tool": "Read",
        "detail": "agile_team/live.py",
    }
    grep = {
        **tool_row(live_step, "Dev: Grep", 3.0, 76.0),
        "tool": "Grep",
        "detail": "def heartbeat",
        "status": "error",
    }
    misc = {"count": 3, "seconds": 0.042, "tools": {"Read": 2, "Grep": 1}}
    none = {"count": 0, "seconds": 0.0, "tools": {}}
    po_call = tool_row(po_step, "po.run_role", 312.5, 10.0)
    return [
        {**old_step, "calls": [cut], "misc": none},
        {**live_step, "calls": [slow, read, grep, timed_out], "misc": misc},
        {**po_step, "calls": [po_call], "misc": none},
    ]


def with_tools_after_steps(snap, tools):
    """``snap`` with ``tools`` placed right after ``steps`` (the section order)."""
    out = {}
    for key, value in snap.items():
        if key != "tools":
            out[key] = value
        if key == "steps":
            out["tools"] = tools
    return out


def add_live(snap):
    """Add turns, a heartbeat, health and the interrupted step to a snapshot."""
    now = CURATED_END + 900  # all live events fall after CURATED_END
    base = [e for e in snap["events"] if e["at"] <= CURATED_END]
    turns = live_turns(now, random.Random(44))
    snap["events"] = base + live_events(base, now)
    snap["generated_at"] = now
    snap["turns"] = turns
    snap["heartbeat"] = live_heartbeat(now, turns)
    snap["health"] = {"level": "green", "reason": "turns arriving", "model_note": None}
    return with_tools_after_steps(snap, tools_section(snap))


def starting_point(path):
    """The existing curated fixture when there is one, else the fake run built above."""
    try:
        with open(path) as fh:
            previous = json.load(fh)
    except (OSError, ValueError):
        return snapshot
    return previous if "upstream" in previous else snapshot


result = add_live(starting_point(sys.argv[1]))  # read before the file is truncated
with open(sys.argv[1], "w") as out:
    json.dump(result, out, indent=1)
print(
    len(events),
    "events,",
    len(ledger),
    "ledger,",
    round(sum(x["cost_usd"] for x in ledger), 2),
    "USD",
)
