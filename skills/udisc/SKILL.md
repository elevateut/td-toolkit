---
name: udisc
description: "Query UDisc for disc golf course data, reviews, nearby courses, disc golf stores, and course layouts with per-hole tee/basket GPS coordinates. No API key required. Use when the user asks about disc golf courses, course ratings, course details, nearby courses, disc golf stores, hole coordinates, course layouts, exporting a course to Parkdly, or references a UDisc URL."
argument-hint: "[course-detail|layouts|reviews|nearby|stores|search|url] <slug, coords, query, or URL>"
metadata:
  version: "1.0.0"
---

# UDisc Data Skill

Query UDisc's course database for disc golf course information, reviews, nearby courses, and stores.

This skill is read-only lookups. It does not create or edit anything on UDisc (league or
event listings are a separate, logged-in browser job).

## How it works

UDisc is a Remix app. This skill calls their Single Fetch `.data` endpoints (no API key needed) and decodes the TurboStream response format into clean JSON via a bundled Python decoder at `scripts/udisc.py`.

## Commands

All commands are run via `python3 <skill-dir>/scripts/udisc.py <command> [args]`.

### Course detail

Get full details for a course by its slug. Slugs follow the format `{name-slug}-{shortId}` (e.g., `maple-hill-disc-golf-course-abc1`). You can find the slug from a UDisc URL or from the `shortId` + `name` fields in nearby-courses results.

```bash
python3 scripts/udisc.py course-detail <slug>
```

Returns: name, location, coordinates, rating, hole count, description, amenities (bathroom, water, dog-friendly), year established, play fee type.

### Course detail from URL

Parse a UDisc URL and fetch course detail in one step:

```bash
python3 scripts/udisc.py course-url "https://udisc.com/courses/some-course-XYZ"
```

### Course layouts (per-hole GPS)

Pull every published layout for a course, including **per-hole tee and basket
coordinates** (full float precision), pars, distances, tee type, and basket model.
GPS is present on `type: "smart"` layouts; older hand-entered layouts may lack it.

```bash
python3 scripts/udisc.py layouts <slug>                          # full JSON
python3 scripts/udisc.py layouts <slug> --layout "Main"          # filter by name
python3 scripts/udisc.py layouts <slug> --format parkdly         # Parkdly paste block
```

`--format parkdly` emits Parkdly Studio's "Build course by hole coordinates"
bulk format — one line per hole, `teeLat, teeLng | targetLat, targetLng` — on
stdout (layout name + par summary go to stderr). Picks the first active layout
with full GPS unless `--layout` narrows it. **The pars on stderr matter:** paste
the block into Parkdly, then correct any hole where Parkdly's distance-based par
estimate disagrees. Full upload procedure: see the sibling `parkdly` skill's
"Uploading a course INTO Parkdly" section.

### Course reviews

```bash
python3 scripts/udisc.py course-reviews <slug> [--limit 10]
```

Returns: array of reviews with username, rating, review text, created date.

### Nearby courses

Find courses near a latitude/longitude:

```bash
python3 scripts/udisc.py nearby-courses <lat> <lng> [--radius 50000] [--limit 20]
```

Radius is in meters (default 50000 = ~31 miles). Returns: name, location, coordinates, rating, rating count, availability, difficulty, estimated duration, top photo, distance.

### Nearby stores

Find disc golf shops near a location:

```bash
python3 scripts/udisc.py nearby-stores <lat> <lng> [--radius 50000] [--limit 20]
```

Returns: name, address, city, state, category, rating, hours, logo, timezone.

### Search courses by name

Searches by fetching nearby courses from a US-centered point with a large radius, then filtering by name. Works for well-known courses but won't find every course globally.

```bash
python3 scripts/udisc.py search "maple hill"
```

## Constructing slugs

The nearby-courses endpoint returns `name` and `shortId` for each course. To get the full slug for course-detail:

1. Slugify the name: lowercase, replace spaces/special chars with hyphens, collapse multiple hyphens
2. Append `-{shortId}`

Example: Name="Beacon Hill Park Disc Golf Course", shortId="LCAP" => slug="beacon-hill-park-disc-golf-course-LCAP"

## Output format

All output is JSON to stdout. Errors are JSON to stderr with a non-zero exit code.

## Common coordinates

| Location | Lat | Lng |
|----------|-----|-----|
| Portland, OR | 45.52 | -122.68 |
| Charlotte, NC | 35.23 | -80.84 |
| Austin, TX | 30.27 | -97.74 |
| Minneapolis, MN | 44.98 | -93.27 |
| US center (for broad search) | 39.8 | -98.5 |

## Rate limiting

UDisc has no documented rate limits but be respectful. Don't blast hundreds of requests. The script uses urllib with a 30-second timeout. For batch operations, add delays between calls.

## Limitations

- No authentication/login, so only publicly visible data is available
- The search command is limited by the nearby endpoint's result cap (~50 courses per query)
- Course slugs must include the shortId suffix; name-only slugs return 404
- Review endpoint returns ~20 reviews per request (no pagination exposed)
- Store detail requires country code, admin1 name, store name, and shortId (available from nearby-stores results)
