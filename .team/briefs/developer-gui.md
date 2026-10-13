# Developer (GUI): Current context and conventions

**Last updated:** 2026-10-13 (s102 done; s101 done, P1 pending; s97 done, P1 pending; s96 done, P1 pending)

See `developer.md` for base conventions.

## s102 complete: Runner stages on Flow and Time charts (all ACs pass, P1 complete)

**Features:** Flow chart gains four stage nodes (hexagons): Prepare env, Implement gate, E2E gate, Boundary. Each shows last/total time and run count for the scope, lights up while running. Time chart now counts three sources: agent steps (work), runner stages (runner row), PO turns (model/tools/waiting segments). Agent boxes and PO node show model/tool time split as text bar (10-cell █░ graphic). All text ≥12px with 4.5:1 contrast; chart scrolls sideways at natural size (scale 1). **Implementation (design SN1–SN8, HB1–HB4, TM1–TM8, SB1–SB3, RD1–RD4):**

- **Stage nodes:** STAGE_NODES table (four entries); stageRuns/stageDrawn/stageStats functions; stageLabel/stageNodeLine/addStageNodes place hexagons in groups; stageEdges adds dotted joins to anchors.
- **Running nodes:** openStages/stageOpen read heartbeat.stages; stageRunningLine shows "⏱ running N s" with awake time; liveStageNodeId picks first running stage for active node.
- **Time chart:** Three TIME_SOURCES (stepPieces, stagePieces, turnPieces); timeBy groups pieces; stagePieces emit `runner` row; turnPieces split `{model, tools, waiting}`. poSplit/stepSplit/turnSplit compute splits for share bars.
- **Share bars:** shareLine draws "model p% ███░░ tools q%" on nodes; omitted in Story scope for PO; no line if sum=0.
- **Text:** TL_TEXT gains barLabel, barValue (12px). RD2: SVG width/height = viewBox with inline style (scale 1).

**Code review done (all ACs pass).** Coverage 99.53%, ruff clean. Gate fix: legend test assertion corrected (TM8 rule). Page tests (AC4: positions/edges/numbers in scope/running/share; AC-R: measured text size/contrast in themes) written by integration-tester. **No new ADR** (extends s96 snapshot data + s101 heartbeat patterns).

See design `agile-team/docs/design/s102.md` (all rules, test checklist, known limits).

## s101 complete: A step row expands into nested tool calls (all ACs pass, P1 pending)

[Previous s101 content unchanged...]
