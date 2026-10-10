---
name: layout-drift
description: "Detect drift between the PDGA-sanctioned layout a league or event plays and the current basket positions on UDisc, report exactly which holes must change at the sanctioned level, then (on request) create a matching PDGA Tournament Manager layout and assign every division to it for the next round and all rounds after — with played-week protection and read-back verification. Use when the user asks whether a course's league layout is out of date, whether baskets moved, 'is there drift at <course>', 'update the PDGA layout to match UDisc', 'fix the sanctioned layout', or after a UDisc course edit lands."
argument-hint: "detect --udisc <slug|url> --tourn <TournID> | apply --tourn <TournID> --udisc <slug> [--execute]"
metadata:
  version: "1.1.0"
---

# Layout Drift — sanctioned layout vs. current pins

Composes the `udisc` skill (current pins, per-hole GPS) and PDGA's own sources (PDGA Live,
Tournament Manager, v3 `layouts_read`) to answer one question — **does the layout PDGA thinks this
event plays match where the baskets are today?** — and then fix it at the sanctioned level.

Two scripts, stdlib only. Both expect the `udisc` skill to sit next to this one
(`<skills>/udisc/scripts/udisc.py`); set `CLAUDE_SKILLS_ROOT` if it lives elsewhere.

| Script | Writes? | What it does |
|---|---|---|
| `scripts/layout-drift.py` | never | UDisc pins → PDGA Live sanctioned layout(s) → per-hole drift table + "what must change" |
| `scripts/layout-apply.py` | only with `--execute` | creates a TM layout from UDisc, fills holes, assigns every division for rounds N..last, verifies via `layouts_read` |

Inputs are always passed explicitly — the skill has no built-in course, event or league mappings:

| Input | How |
|---|---|
| UDisc course | `--udisc <slug or URL>` (the slug is the last path segment of the UDisc course URL) |
| PDGA event(s) | `--tourn <TournID>` (repeatable) or env `PDGA_TOURN_IDS=111111,222222` |
| TM update password | env `PDGA_TM_PASSWORD` (or name another var with `--password-env`) |
| v3 API app (verification) | env `PDGA_TM_APP_NAME`, `PDGA_TM_APP_TOKEN`; optional `PDGA_TM_V3_BASE` |
| Cache / journal dir | `--cache-dir` or env `LAYOUT_DRIFT_CACHE` (default `~/.cache/layout-drift`) |

## Detect

```bash
SK=<skills-dir>/layout-drift/scripts   # e.g. ~/.claude/skills/layout-drift/scripts

# Compare a PDGA event's live layout(s) against UDisc, with the "which PDGA layout matches
# today's pins" ranking across several events at the same course
python3 $SK/layout-drift.py --udisc <udisc-course-slug> --tourn <TournID> --tourn <OtherTournID> \
  --history --markdown ./drift.md --json ./drift.json
```

What it pulls, in order:

1. **UDisc** — every active layout with per-hole pin label (A/B/C), basket + tee GPS, published distance
   (may be a course-admin custom value) and the GPS straight-line distance. Picks the layout whose
   distances and tee labels (e.g. `Long`) best match the sanctioned layout; `--udisc-layout Gold` overrides.
2. **PDGA Live** — one request per division for the *latest* round only (a full round fan-out gets
   429'd; `--all-rounds` opts in). Gives the layout PDGA is actually serving, deduped by `LayoutID`.

Report: a per-hole table (sanctioned par/ft vs UDisc par/ft vs GPS ft, pin letter, tee label, Δ,
verdict), optional history ranking (`--history`: every PDGA layout seen across the given events, ranked
by closeness to today's pins), and the **sanctioned-level change list** (hole: par, ft, pin) plus the
constraints that apply to any fix. Tolerance `±20 ft or 7%` (`--tolerance-ft/--tolerance-pct`).
Exit 0 either way — read the verdict line. `--offline` re-uses the last cached pulls.

Read `U gps ft` when deciding whether a basket physically moved; read `U ft` for what the scorecard
should say. Before trusting UDisc over a sanctioned layout, cross-check against another TD's recent
sanctioned layout at the same course (pass its TournID too with `--history`): if an independent
layout matches UDisc hole-for-hole, UDisc is current.

## Apply — new sanctioned layout, every division, next round onward

```bash
export PDGA_TM_PASSWORD=...        # event update password
export PDGA_TM_APP_NAME=...        # PDGA v3 Tournament API app
export PDGA_TM_APP_TOKEN=...

# 1. Optional rehearsal on PDGA's stage host (a nightly copy of production), if you have access
python3 $SK/layout-apply.py --tourn <TournID> --udisc <udisc-course-slug> --udisc-layout Gold \
  --divisions MA3,MA40,FA3 --allow-unlisted-divisions --pdga-host stage.pdga.com --execute

# 2. Dry run against production (prints the full plan, writes nothing)
python3 $SK/layout-apply.py --tourn <TournID> --udisc <udisc-course-slug> --udisc-layout Gold \
  --divisions MA3,MA40,FA3 --allow-unlisted-divisions --played-rounds 3 --plan-json ./plan.json

# 3. Production
python3 $SK/layout-apply.py ... --execute
```

Steps, each verified before the next:

1. `password_check` → `layouts_read` (current layouts + assignment matrix), TM cookie login.
2. **Played-week guard.** First mutable round = 1 + max(PDGA Live `HighestCompletedRound`,
   `--played-rounds` from your own records). `--from-round` below that is refused unless
   `--force-from-round`. Cells below `from-round` are posted back exactly as served.
3. `layout_add` (metadata only) → TM redirects to `layout_edit?LayoutID=<new>` → that id is the layout.
   A same-name + same-hole-count layout already in the tournament is reused (idempotent re-runs;
   `--reuse-layout <id>` forces it).
4. `layout_edit` with every hole: par + published ft from UDisc, `Tee` = UDisc tee label when not
   `main` (e.g. `Long`), `Target` = pin letter (`--no-pin-target` to skip), `Notes` carried from the
   layout being replaced (`--no-notes`). Verified against `layouts_read` `Detail.H{n}` field by field.
5. `layouts` assignments: `assignments[<DIV>][_][Rd<n>] = <new>` for every division × round in range,
   then `layouts_read` must show exactly that.
6. `--plan-json` writes the plan, the per-hole tee/basket GPS and the final result, so any scoring or
   league system you run alongside PDGA can mirror the new layout. If that system keys side-game holes
   (CTP, ace pot, etc.) to a hole *id*, remap them to the same hole *number* on the new layout — and
   leave recorded scores pointing at the layout that was actually played.

### Divisions — the rule that is not obvious

TM renders assignment cells only for divisions that already have a registrant, but it **stores cells
for divisions it does not render** (verified 2026-09-17: posting `assignments[MPO][_][Rd9]` showed up
in `layouts_read` while the page still listed only the divisions with registrants). So:

- Pass `--divisions` with the event's **full** division list plus `--allow-unlisted-divisions`, so a
  division that registers next week starts on the new layout, not the old one.
- Without `--divisions`, only the divisions TM currently renders are assigned.
- With **zero registrants in the whole tournament** there is no form at all and posted cells are
  silently dropped (verified on stage). The script then stops after creating + verifying the layout and
  tells you to re-run with `--reuse-layout <id>` after the first registration.
- A cell set for an unrendered division could not be cleared: posting `''` is ignored, `0` returns 500.
  Choose the division list deliberately.

## Landmines

- **No layout write API.** v3 exposes only `layouts_read`. Everything else is TM HTML, which works
  from a laptop/residential IP but tends to 429 from cloud hosts. `layout_add` has no hole fields —
  holes are only accepted on `layout_edit`.
- **v3 throttles `password_check` bursts** (403 after ~6 in a few minutes). One token per run; back off.
- **PDGA Live `LatestRound` is the open round, not a played one.** Use `HighestCompletedRound`.
- **UDisc exposes only the pins each layout currently uses**, never the alternate A/B/C positions.
- **A new layout id is the right fix for a material pin move** — it keeps ratings from being pooled
  across two physical configurations. Rounds already played stay on the old layout.
- `<cache-dir>/journal/<tourn>-<utc>/` keeps every TM page fetched or posted in a run — check it
  before retrying anything that failed half-way.
