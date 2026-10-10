---
name: earth-flyover
description: "Render cinematic aerial flythrough videos of any place on Earth from real satellite imagery draped on real 3D terrain — fully headless, no Google Earth Studio / browser login needed. Given lat/lng coordinates (e.g. from the parkdly skill's course JSON), produces an MP4: a descending establishing orbit of an area, a per-hole cinematic tour (slow pan around the fairway, then settle onto a tee-pad view tilted at the basket) with flight-path/OB/amenity overlays and burned-in hole/par/distance/notes text, or a TRANSIT that flies from one course to a different course when an event spans multiple venues. Supports 16:9 landscape and 9:16 portrait/vertical output. Use when the user asks for a flyover, flythrough, aerial video, course tour video, a fly-from-one-course-to-another shot, or a Google-Earth-Studio-style render of a place."
argument-hint: "<course.json> [--mode establish|holes|transit] [--to <course-b.json>] [--overlays on|off] [--hud on|off] [--aspect 16:9|9:16] [--frames-per-hole N] [--out FILE]"
metadata:
  version: "2.1.0"
---

# Earth Flyover

Renders an aerial flythrough MP4 from a set of coordinates, entirely headless — no
Google Earth Studio, no browser login, no watermark to remove. Built on the **ArcGIS
Maps SDK for JavaScript** `SceneView` (Esri World Imagery draped on real world
elevation), driven by **Playwright** (headless Chromium), captured frame-by-frame,
and stitched with **ffmpeg**.

## Why this exists

Google Earth Studio requires a live browser session behind a Google login and can't
be automated — there's no API. This skill is a fully-scriptable substitute for the
common case of "fly the camera over this place and give me a video": point it at any
lat/lng data and it renders headlessly, no human in a browser required.

It was built to turn **Parkdly disc golf caddie books** (see the `parkdly` skill)
into flyover videos for tournament coverage, but the renderer itself only needs a
course-shaped JSON with holes/coordinates — it's not disc-golf-specific at its core.

## Relationship to other skills

- **`parkdly`** is the data source. Run `parkdly.mjs <caddie-book-url> --format json`
  to get the course JSON this skill consumes (holes with `tees`/`baskets`/
  `flightPaths`, `boundaries`, `amenities`, `map.center`/`bounds`). This skill does
  not fetch Parkdly data itself — that stays owned by the `parkdly` skill.
- **`pdga`** is the orchestrator for tournament use — its `flyover` command chains
  `parkdly` (list a destination's caddie books, fetch each course JSON) into this
  skill's renderer, per course, and writes a manifest. Use `pdga flyover` for
  "render flyovers for tournament X"; use this skill directly for one-off renders
  or non-PDGA use.

## Prerequisites

- Node.js 18+ (uses global `fetch`/ESM; tested on Node 25)
- `ffmpeg` on `PATH` (`brew install ffmpeg`)
- Playwright, installed locally to this skill:
  ```bash
  cd "/absolute/path/to/the/active/earth-flyover-skill" && npm install
  ```
  (Downloads/reuses the Chromium build Playwright needs. If Playwright's browser
  cache is already populated on the machine — check `~/Library/Caches/ms-playwright`
  on macOS — this is fast and adds no extra download.)

## Usage

```bash
node scripts/render.mjs <course.json> [options]
```

| Option | Default | Meaning |
|---|---|---|
| `--mode` | `establish` | `establish` = descending orbit over the whole course/area. `holes` = one cinematic segment per hole: a slow pan/orbit around the fairway, then a glide-and-settle onto a tee-pad view tilted down the fairway at the basket (hard cut to the next hole). Needs `holes[].tees`/`.baskets`. **`transit` = fly from one course to a DIFFERENT course** — see below. |
| `--to` | — | **transit mode, required.** The second course JSON to fly to. |
| `--transit-seconds` | `5` | transit mode: length of the flight between the two courses. |
| `--hold-start` / `--hold-end` | `1` / `1.5` | transit mode: seconds parked over course A before departing / over course B after landing. |
| `--transit-apex` | half the gap, clamped 1.5 km–60 km | transit mode: extra altitude at mid-flight. Scales with distance by default, so a 2 km hop and a 40 km one both read as arcs. |
| `--start-brg` | trailing the travel axis | transit mode: camera bearing at the start. The default puts the camera behind course A looking toward course B, so the shot is aimed at the destination before it leaves. |
| `--overlays` | `on` | Draw flight-path lines (yellow), OB boundaries (red dashed), tee markers (white squares), basket markers + hole numbers, and amenity markers (color-coded by type: blue=restroom, teal=water, red=medical, gray=parking, yellow=info) as 3D graphics on the terrain. Set `off` for clean unmarked imagery. |
| `--hud` | `on` | Burn in readable 2D text: in `holes` mode, hole number + par + distance + the tee-sign note text (OB/mando rules) per hole; in `establish` mode, a course title card (name, hole count, par, length) shown briefly at the start. Set `off` to omit. |
| `--hole` | (all holes) | `holes` mode only: render just this one hole number instead of the whole course. Useful for previewing pacing/framing quickly, or producing a single-hole clip, without paying for a full-course render. |
| `--seconds-per-hole` | `10` (holes mode only) | Seconds of video per hole: ~55% slow pan/orbit, ~45% glide-to-settle. This is the main pacing knob — raise it for a slower, more lingering pan; lower it for a quicker cut. |
| `--frames-per-hole` | from `--seconds-per-hole` | Exact frames per hole, overrides `--seconds-per-hole` if given (e.g. for a non-30fps `--fps`, or precise frame-count control). |
| `--seconds` | `4` (establish mode only) | Duration in seconds. Overridden by `--frames` if given. |
| `--start-alt` | `~1x` the course footprint (establish mode only) | Starting altitude in metres above the course center. Default is a local close-in orbit; set into the millions (e.g. `4500000`) for a cinematic "from space" zoom-in. |
| `--start-radius` | `~1.5x` the course footprint (establish mode only) | Starting horizontal offset in metres from the course center. Pair with `--start-alt` for a from-space shot (e.g. `1200000`). |
| `--sweep` | `110` (establish mode only) | Total heading sweep in degrees over the shot. A from-space zoom reads better with a smaller sweep (~30-40) — it should feel like a dive-in, not a wide orbit. |
| `--frames` | `120` (establish) / overrides frames-per-hole if given, divided across holes (holes) | Total output frames (legacy; prefer `--seconds`/`--seconds-per-hole`). |
| `--aspect` | `16:9` | Resolution preset: `16:9` → 1280x720, `9:16` → 720x1280 (vertical/Reels/Shorts/Stories). Ignored if `--width`/`--height` given. |
| `--width`, `--height` | from `--aspect` | Output resolution, overrides `--aspect`. |
| `--fps` | `30` | Output frame rate. |
| `--out` | `<course-name>-<mode>.mp4` in cwd | Output file path. |
| `--settle-ms` | `900` | Per-frame cap (ms) on waiting for tiles/overlays to settle before the screenshot. Lower = faster render, slightly higher risk of a soft/half-loaded tile in a frame. 900 has held up well even with overlays on. |
| `--keep-frames` | off | Keep the intermediate PNG frames (printed temp dir) instead of deleting them after encoding. |

### Examples

```bash
# Establishing orbit of a course (from a parkdly JSON export)
node scripts/render.mjs ./courses/maple-hill.json --mode establish --out maple-hill.mp4

# Hole-by-hole cinematic tour with overlays + burned-in hole/par/distance/notes, 1080p
node scripts/render.mjs ./courses/maple-hill.json --mode holes --width 1920 --height 1080 --out maple-hill-tour.mp4

# Same tour, vertical for Reels/Shorts/Stories
node scripts/render.mjs ./courses/maple-hill.json --mode holes --aspect 9:16 --out maple-hill-tour-vertical.mp4

# A single hole, at the default 10s/hole cinematic pace (for quick preview or a standalone clip)
node scripts/render.mjs ./courses/maple-hill.json --mode holes --hole 7 --out maple-hill-hole7.mp4

# A single hole, slower/more lingering pan (15s) and vertical
node scripts/render.mjs ./courses/maple-hill.json --mode holes --hole 7 --seconds-per-hole 15 --aspect 9:16 --out maple-hill-hole7-vertical.mp4

# Clean imagery, no overlays or HUD, for a title-card background
node scripts/render.mjs ./courses/maple-hill.json --mode establish --overlays off --hud off --out maple-hill-plain.mp4

# TRANSIT: fly from one course to another (an event whose division plays two venues)
node scripts/render.mjs ./courses/course-a.json --mode transit \
  --to ./courses/course-b.json --aspect 9:16 --hud off --overlays off \
  --transit-seconds 5 --out course-a-to-b.mp4
```

### `transit` mode — moving between two courses

For events where one division plays more than one venue, and the film has to physically
travel between them instead of hard-cutting. The camera parks over course A, rises and
arcs across the gap facing the direction of travel, then descends into course B.

- **Both ends park on exactly the geometry `establish` mode lands on**, so a transit clip
  intercuts seamlessly with a plain establish render of either course — you can open on
  A's from-space zoom, cut to the transit, and land on B.
- The altitude arc is a sine bump, and **radius and height bump together**, so the tilt
  holds near 45° at apex rather than flattening into a top-down map view.
- Ground elevation is sampled at 21 points along the path and interpolated, rather than
  one `groundZ()` round-trip per frame. Visually identical over a hop, much faster.
- Only needs `map.center` + `realWidthMeters`/`realHeightMeters` on both JSONs — a
  coordinates-only stub is enough at each end.
- Duration is `hold-start + transit-seconds + hold-end` (default 7.5s).
- **Caveat:** `--overlays on` currently draws only course A's overlays. Use
  `--overlays off` for transit shots until that's fixed.

Note on render time: a full 18-hole course at the 10s/hole default is 18 × 300 = 5400
frames — at roughly 1-2s/frame this can take **1.5-3 hours**. Use `--hole N` to
iterate quickly on pacing/framing for one hole before committing to a full-course
render, and expect full-course `holes`-mode renders to be a background/overnight job
at the default pacing.

## Input contract (course JSON)

Whatever produces the input JSON must match this shape (this is exactly what
`parkdly.mjs --format json` emits):

```jsonc
{
  "course": { "name": "Maple Hill" },
  "map": {
    "center": { "lat": 45.52, "lng": -122.68 },
    "realWidthMeters": 1393, "realHeightMeters": 1393
  },
  "holes": [
    {
      "number": 1,
      "par": 3,
      "distance": { "value": 335, "unit": "ft" },
      "tees": [{ "lat": 45.52, "lng": -122.68 }],
      "baskets": [{ "lat": 45.52, "lng": -122.676 }],
      "flightPaths": [{ "type": "PRIMARY", "points": [{ "lat": 45.52, "lng": -122.68 }, "..."] }],
      "teeSigns": [{ "isPrimary": true, "noteText": "White stakes and string and beyond is Out of Bounds (806.02)." }]
    }
  ],
  "boundaries": [{ "type": "ob", "points": [{ "lat": 45.52, "lng": -122.68 }, "..."] }],
  "amenities": [{ "type": "wc", "lat": 45.5193, "lng": -122.6767 }]
}
```

`--mode establish` only needs `map.center` + `realWidthMeters`/`realHeightMeters`
(plus `totals` for the HUD title card). `--mode holes` needs at least 1 hole with
both `tees[0]` and `baskets[0]`; `par`/`distance`/`teeSigns[].noteText` feed the HUD
if present but are otherwise optional. Overlays and HUD both degrade gracefully —
missing `flightPaths`/`boundaries`/`amenities`/`teeSigns` are just skipped (flight
lines fall back to a straight tee→basket line when a hole has no `flightPaths`; a
hole with no `teeSigns` just shows hole/par/distance with no notes line).

## How it works internally

1. `scene.html` is a static page that boots an ArcGIS 3D `SceneView` against public
   Esri World Imagery + world elevation (no API key required for this basemap tier),
   plus a plain DOM `<div id="hud">` overlay positioned on top of the view for
   burned-in text. It exposes `window.setCamera(cam, maxWaitMs)`,
   `window.groundZ(lat,lng)`, `window.addOverlays(payload)`, and
   `window.setHoleInfo(...)`/`window.setCourseInfo(...)`/`window.hideHud()` for
   Playwright to call.
2. `scripts/render.mjs` launches headless Chromium (`--use-gl=angle
   --use-angle=swiftshader` — needed for WebGL without a real GPU), loads
   `scene.html`, optionally injects overlays, then walks a camera path — great-circle
   orbit math for `establish`, and for `holes` a per-hole two-phase path (orbit
   around the tee/basket midpoint at a bearing/radius/height scaled to the hole's
   length, then an eased glide onto a fixed tee-pad vantage) — updating the HUD text
   once per hole and capturing each step with **`page.screenshot()`** (the *whole
   page*, not just the 3D canvas — this is what lets the DOM HUD overlay composite
   into the output frame; the 3D-only `view.takeScreenshot()` API would miss it).
3. `ffmpeg` (via `execFileSync`, not a shell string — no injection risk) encodes the
   PNG sequence to H.264 MP4 (`crf 18`, `faststart`) and the temp frame dir is deleted.

## Known limits / gotchas

- **Elevation queries add real per-hole latency** in `--mode holes` (one
  `queryElevation` network call per hole to place the camera above ground). For an
  18-hole course this is on the order of several seconds total, separate from the
  per-frame render loop.
- **`--settle-ms` matters a lot for total render time.** With overlay GraphicsLayers
  present, `view.updating` can stay true past when the frame is already visually
  correct — this is why the cap is a *soft* heuristic (one clean check *or* the cap,
  whichever comes first), not a real wait-for-idle. If you see occasional soft/blurry
  tiles in output, raise `--settle-ms`; if renders feel slow, lower it.
- **No premium imagery/3D buildings yet.** Uses the public World Imagery tile
  service. Wiring in a keyed ArcGIS Location Platform subscription (higher-res
  imagery, OSM Buildings 3D massing) is a future extension — swap the `TileLayer`
  URL / add a `SceneLayer` in `scene.html`.
- **Headless Chromium + WebGL is CPU-bound** (software rasterization via
  SwiftShader — there's no real GPU in the sandbox). Rendering is not real-time;
  budget roughly 1-2s/frame at 720p with overlays on.
