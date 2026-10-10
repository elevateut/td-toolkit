---
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
description: Update the PDGA mind map from new meeting minute text extractions
---

Regenerate the PDGA BOD mind map and year-range summaries from extracted meeting minute text files.

Companion of the `pdga-lightrag` skill (alongside `/pdga-minutes`). The summaries it writes can
also be uploaded to LightRAG as higher-level documents.

## Prerequisites

Run `/pdga-minutes` first to ensure all PDFs are downloaded and text is extracted.
`markmap` CLI for Step 4 (`npm install -g markmap-cli`).

All paths hang off one directory (relative to the current project unless absolute):

```bash
MIN="${PDGA_MINUTES_DIR:-docs/pdga-bod-minutes}"
```

## Step 1: Identify what needs updating

Check which years have new or updated text extractions since the last summary was generated:

```bash
# List summary files and their dates
ls -la "$MIN"/*summary*.md "$MIN"/PDGA*.md 2>/dev/null

# Check extracted text files for each year
for year in $(seq 2003 $(date +%Y)); do
  dir="$MIN/_extracted/$year"
  if [ -d "$dir" ]; then
    count=$(ls "$dir"/*.txt 2>/dev/null | wc -l | tr -d ' ')
    newest=$(ls -t "$dir"/*.txt 2>/dev/null | head -1)
    echo "$year: $count files (newest: $(stat -f '%Sm' -t '%Y-%m-%d' "$newest" 2>/dev/null))"
  fi
done
```

Compare extraction dates against summary file dates. Only reprocess year ranges where extractions are newer than summaries.

## Step 2: Regenerate affected year-range summaries

The summaries are organized in 4-year ranges. Determine which ranges need updating based on which years have new content.

| Range | Summary File | Years |
|-------|-------------|-------|
| 2003-2006 | `2003-2006-comprehensive-summary.md` | 2003, 2004, 2005, 2006 |
| 2007-2010 | `summary-2007-2010.md` | 2007, 2008, 2009, 2010 |
| 2011-2014 | `pdga-bod-2011-2014-summary.md` | 2011, 2012, 2013, 2014 |
| 2015-2018 | `pdga-bod-summary-2015-2018.md` | 2015, 2016, 2017, 2018 |
| 2019-2022 | `pdga-bod-summary-2019-2022.md` | 2019, 2020, 2021, 2022 |
| 2023-2026 | `PDGA_BOD_Summary_2023-2026.md` | 2023, 2024, 2025, 2026 |

For each affected range, launch a background agent (subagent_type: general-purpose, model: sonnet) to read ALL text files in those years and produce a structured summary with:

1. **Key People** — Name, title/role, what they did
2. **Major Initiatives & Programs** — What the PDGA was working on
3. **Financial State** — Budget numbers, membership revenue, any financial data
4. **Organizational Needs & Challenges** — Problems, resource gaps, controversies
5. **Key Decisions & Motions** — Formal votes, policy changes
6. **Relationships & External Orgs** — WFDF, sponsors, media partners, other orgs

The agent should write the summary to the appropriate file in `$MIN/`.

Launch agents for different year ranges in parallel.

## Step 3: Regenerate the master mind map

After all year-range summaries are updated, launch a single agent to read ALL 6 summary files and compile the master document.

Write to: `$MIN/PDGA-Mind-Map-Master.md`

The master document should have these sections:

1. **PDGA People Directory** — Organized by role type, with years active and key contributions
2. **Organizational Evolution Timeline** — One-line-per-year spine
3. **Major Initiative Threads** — 11 continuous threads traced across all years (Membership, Technology, Tour, International, Media, Finance, Rules, Diversity, Youth, Courses, Governance)
4. **Non-Profit Needs & Challenges** — Consolidated recurring challenges
5. **Key Relationships Map** — All external organizations with relationship timelines
6. **Financial Journey** — Year-by-year financial table

## Step 4: Regenerate the interactive mind map

```bash
markmap "$MIN/PDGA-Mind-Map-Master.md" \
  -o "$MIN/PDGA-Mind-Map.html" --no-open
```

## Step 5: Report results

```
=== PDGA Mind Map Update ===
Year ranges regenerated: X of 6
  - 2023-2026 (3 new files from 2026)
Master mind map: Updated
Interactive HTML: Updated
```
