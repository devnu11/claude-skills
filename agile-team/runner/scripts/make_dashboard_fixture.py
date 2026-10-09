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
    ledger.append(
        {
            "at": at,
            "role": role,
            "model": model,
            "story": story,
            "cost_usd": c,
            "tokens": tok,
            "turns": rng.randint(4, 40),
        }
    )
    return tok, c


def step(role, story, brief, status="done", summary="", next_role=None, oq=(), **extra):
    ev("step-start", role, story, brief=brief)
    at = tick(90, 600)
    tok, c = charge(role, story, at)
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
            "delivery": "cli",
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
with open(sys.argv[1], "w") as out:
    json.dump(snapshot, out, indent=1)
print(
    len(events),
    "events,",
    len(ledger),
    "ledger,",
    round(sum(x["cost_usd"] for x in ledger), 2),
    "USD",
)
