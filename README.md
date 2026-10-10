# td-toolkit

Claude Code skills for disc golf tournament directors and league operators: PDGA and
Disc Golf Scene operations, course data from UDisc and Parkdly, layout drift checks,
aerial course flyovers, player stats, and PDGA governance research.

Every skill is organisation-neutral. Credentials, IDs and paths come from environment
variables or command-line flags — nothing private is baked in.

## Skills

| Skill | What it does | Configuration |
|---|---|---|
| [`pdga`](skills/pdga/SKILL.md) | PDGA API queries (events, players, courses, growth counts), DGS registration export and tournament management, tee times with pools and card requests, Google Sheets publishing, layouts, printable scorecards, PDGA Live share images, flyovers, and payout calculation checked against Tournament Manager | `PDGA_USERNAME`, `PDGA_PASSWORD` (or `PDGA_CONFIG`), `DGS_PASSWORD`, `DGS_COOKIE_FILE`, `PDGA_STATE` |
| [`layout-drift`](skills/layout-drift/SKILL.md) | Compare the PDGA-sanctioned layout with current UDisc basket positions; optionally create a matching Tournament Manager layout and assign divisions | `PDGA_TM_PASSWORD`, `PDGA_TM_APP_NAME`, `PDGA_TM_APP_TOKEN`, `PDGA_TOURN_IDS` |
| [`udisc`](skills/udisc/SKILL.md) | Course data, reviews, nearby courses, stores, and per-hole tee/basket GPS from UDisc | none |
| [`parkdly`](skills/parkdly/SKILL.md) | Extract and build Parkdly caddie books: holes, layouts, amenities, OB lines, theming, tee signs | none |
| [`course-research`](skills/course-research/SKILL.md) | Deep research profile of a course (UDisc + web + images) as JSON | optional `COURSE_ID_MAP`, `COURSE_PLATFORM_URL` |
| [`course-photos`](skills/course-photos/SKILL.md) | Find your own photos of a course in Apple Photos by GPS and assign them to holes (macOS) | optional `PHOTOS_LIBRARY` |
| [`earth-flyover`](skills/earth-flyover/SKILL.md) | Headless cinematic aerial flyover videos from satellite imagery on 3D terrain | `npm install` in the skill folder; ffmpeg |
| [`statmando`](skills/statmando/SKILL.md) | Player result history with per-event field-strength ratings | none |
| [`disc-golf-stamp`](skills/disc-golf-stamp/SKILL.md) | Single-colour hot-stamp artwork for discs | `GEMINI_API_KEY` or `OPENAI_API_KEY`; optional `STAMP_*` |
| [`pdga-lightrag`](skills/pdga-lightrag/SKILL.md) | Query a local LightRAG knowledge base of PDGA rules, minutes and financials | `LIGHTRAG_URL`, `LIGHTRAG_DIR`, `PDGA_MINUTES_DIR` |

### Commands

Companions to `pdga-lightrag`:

- [`/pdga-minutes`](commands/pdga-minutes.md) — download new PDGA Board of Directors minutes and extract text
- [`/pdga-mindmap`](commands/pdga-mindmap.md) — update the PDGA mind map from new minutes

## Install

Skills that call each other (`pdga` → `parkdly`/`earth-flyover`, `layout-drift` and
`course-photos` → `udisc`) expect to sit side by side in one skills folder.

```bash
git clone https://github.com/elevateut/td-toolkit.git ~/td-toolkit
mkdir -p ~/.claude/skills ~/.claude/commands
for s in ~/td-toolkit/skills/*/; do ln -sfn "$s" ~/.claude/skills/"$(basename "$s")"; done
for c in ~/td-toolkit/commands/*.md; do ln -sf "$c" ~/.claude/commands/; done
```

If a real folder with the same name already exists in `~/.claude/skills`, remove or rename
it first — otherwise `ln` places the link *inside* that folder.

Put credentials in your shell profile or a `.env` file that is never committed
(`.env*` and cookie files are in `.gitignore`).
