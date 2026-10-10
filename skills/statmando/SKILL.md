---
name: statmando
description: "Pull disc golf player data from StatMando (statmando.com) — full result history with the per-event field-strength rating (evt_rtg), plus wins/podiums/top-10 totals. The evt_rtg column is the key datum: a numeric strength-of-field value per event (DGPT/Elite Series ~1000-1022, Majors ~970, regional/masters ~900-910), so you can weight a result by how strong the field actually was instead of relying on PDGA tier labels. Use when you need player form / hot-streak analysis, strength-of-field weighting, recent results, or to compare how stacked an event's field was. Resolves a player name to their StatMando profile (slug) automatically."
argument-hint: "[player <name|slug> [--since YEAR] | resolve <name> | directory <query>]"
metadata:
  version: "1.0.0"
---

# StatMando Data Skill

[StatMando](https://statmando.com) is a disc golf statistics platform. Its per-player
profile carries a **full result history with an `evt_rtg` column = the numeric strength
of field for each event**. That is the headline value of this skill: a real
field-strength number per result, far better than PDGA tier labels for "who's hot" and
"how strong was that win."

`robots.txt` allows all and pages are server-rendered HTML, so no JS execution or API
key is needed. This skill is a **polite, single-threaded scraper** (~1s between
requests). Do not parallelize it across agents.

## Commands

Run via `python3 <skill-dir>/scripts/statmando.py <command> [args]`. All emit JSON to stdout.

### player

Full profile for a player (resolves a name to a slug automatically, or pass a slug).

```bash
python3 scripts/statmando.py player "Ohn Scoggins"            # by name
python3 scripts/statmando.py player "silva-saarinen"          # by slug
python3 scripts/statmando.py player "Eveliina Salonen" --since 2025
```

Returns: `{found, slug, name, url, pdga, resolution, totals, history[]}` where each
history row is:

```json
{"event": "...", "month": "Jun", "year": 2026, "evt_rtg": 1010, "place": 1,
 "strokes": 236, "cash": 7500, "state": "Oregon", "country": "USA",
 "division": "FPO", "tier": "NT", "tour": "DGPT", "date": "2026-06-04"}
```

`--since YEAR` trims history to that year and later (use it — full histories can be
hundreds of events for veterans).

### resolve

Name → StatMando slug, with a profile name-match check.

```bash
python3 scripts/statmando.py resolve "Anneli Tõugjas-Männiste"
# -> {"slug":"anneli-tugjas-mnniste","statmando_name":"Anneli Tõugjas-Männiste","found":true,"method":"slug"}
```

### directory

Search the StatMando featured-players directory (note: this is a ~180-player featured
list, not the full database).

```bash
python3 scripts/statmando.py directory "saarinen"   # -> [{name, slug, division}]
```

## How `evt_rtg` (field strength) is used

Weight a result by `place` × a function of `evt_rtg` × recency. A 2nd at a 1006-rated
DGPT event outranks a win at a 903-rated regional automatically. Rough field-strength
bands (FPO/MPO):

| evt_rtg | field strength |
|---|---|
| ~1000–1022 | Elite Series / National Tour (the world's best) |
| ~960–1000 | Majors, strong A-tiers |
| ~910–950 | solid regional |
| ~850–910 | local / masters / smaller fields |

## Resolution model (how name → slug works)

- **Deterministic slug:** drop non-ASCII chars, lowercase, hyphenate
  (`Anneli Tõugjas-Männiste` → `anneli-tugjas-mnniste`). Works for the large majority.
- **Verification:** the profile `<h1>` name must match. Unknown slugs 302-redirect to
  the `/players` index (h1 "StatMando Player Profiles"), which fails the check, so a
  player not on StatMando (or with an unguessable transliteration, e.g. Spanish `ñ→n`
  vs Estonian `õ` dropped) correctly returns `found:false`.
- **Fallback:** searches the featured directory by last name. Limited (the directory is
  not a full index), so some non-featured players with quirky slugs stay unresolved.
  Callers should treat `found:false` as "no StatMando field-strength data; fall back to
  tier weighting."

## Limitations / roadmap

- No public JSON API; `/players/search` is gated and returns `[]`. This is HTML scraping.
- `totals` reflects the profile's default filtered view, not always career totals; the
  `history` rows are the reliable data.
- Not yet implemented: `event <id>` (full event field + per-player evt_rtg) and
  `rankings` (the Power Rankings page loads its data via AJAX). Add when needed.
- Be polite: cache results, ~1s spacing, never agent-parallelize.
