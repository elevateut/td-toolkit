---
name: parkdly
description: "Extract everything from a Parkdly disc golf caddie book / course map — holes (par, distance, elevation, tees, baskets, flight paths, tee-sign notes & rules), course layouts (FPO/FP40/etc.), amenities with exact lat/long (restrooms, water, medical, parking, info boards), OB & required-relief boundaries, background terrain, map bounds, and publish/share links. Reads Parkdly's React Router .data payload and decodes the turbo-stream encoding — no screen-scraping, full float-precision coordinates. Use when the user gives a parkdly.com caddie-book URL/token or a parkdly.com/p/<dest>/<slug> page, or asks for restroom/amenity coordinates, hole data, or course intel from Parkdly. Also documents the verified UPLOAD flow: building a course in Parkdly Studio from bulk tee/basket GPS (e.g. pulled from UDisc via the udisc skill's `layouts --format parkdly`), for requests like: upload this course to Parkdly, import UDisc layout into Parkdly, build a Parkdly course from coordinates. Also covers BRANDING a course: theme colours (signage, holes, map), the Advanced theme JSON editor, saved theme libraries, tee-sign templates (built-in and custom block designer), logo and sponsor placement, contour density, terrain elevation auto-fill, and the unpublished public page. Use for: theme this Parkdly course, put our logo on the tee signs, change the sign colours, remove the Parkdly watermark, export hole map PNGs. Also covers EDITING AN EXISTING COURSE IN PLACE (no rebuild): writing tee / target / flight-path lat-lng from UDisc or a field walk through each object's Position panel via Konva node ids, the save-on-blur and fetcher traps, re-running terrain elevation, and renaming a course, project, template and saved theme."
argument-hint: "<parkdly url | caddie-book token | slug url> [--format summary|json|amenities|csv|geojson|raw]"
metadata:
  version: "1.2.0"
---

# Parkdly Caddie Book Extractor

Parkdly (parkdly.com) is a disc golf course design app that produces tee signs, course
maps, and interactive digital caddie books. Every map element — tees, baskets, flight
paths, OB lines, trees, and **amenities like restrooms** — is stored with real
GPS coordinates. This skill pulls that structured data out of any caddie book.

## How it works (the data path)

Parkdly is a React Router v7 app. Each caddie-book page has a **single-fetch `.data`
endpoint** that returns the full loader payload in **turbo-stream** encoding:

```
https://parkdly.com/caddie-books/<token>          ->  append ".data"  ->
https://parkdly.com/caddie-books/<token>.data
```

`scripts/parkdly.mjs` fetches that endpoint, decodes it with the vendored
`scripts/turbo-stream.mjs` (the exact library React Router uses, MIT, zero-dep), then
normalizes it. **Do not regex-scrape the page** — object types have varied field layouts
and a positional regex silently under-counts amenities (e.g. it found 1 restroom at a
course that actually has 2). Always decode.

## Usage

```bash
node "/absolute/path/to/the/active/parkdly-skill/scripts/parkdly.mjs" <input> [--format FMT] [--out FILE]
```

`<input>` accepts any of:
- `https://parkdly.com/caddie-books/<uuid>`  (a published caddie book)
- `https://parkdly.com/caddie-books/<uuid>.data`
- `https://parkdly.com/p/<destination>/<slug>`  (the public slug page)
- a bare `<uuid>` caddie-book token

`--format` (default `summary`):
| format | output |
|--------|--------|
| `summary` | Markdown overview: hole table (par/length/elev/tee-sign notes), amenities with coords + Google Maps links, boundaries, layouts, object inventory, publish/share links |
| `amenities` | Tab-separated facility list (restroom/water/medical/parking/info board) with lat/lng + Maps links |
| `csv` | Amenities as CSV (`course,type,label,lat,lng,google_maps,id`) |
| `geojson` | A `FeatureCollection` of ALL geometry: tees, baskets, flight-path lines, amenities, play elements, OB/relief polygons, background terrain, info boards. Drop into geojson.io / QGIS / a Leaflet map |
| `json` | Full normalized model (every field below) |
| `raw` | The raw decoded turbo-stream loader object (everything Parkdly sent, undocumented fields included) |

`--out FILE` writes to a file instead of stdout.

### Examples
```bash
# Restroom + all amenity coordinates for one course
node scripts/parkdly.mjs <caddie-book-uuid> --format amenities

# Full human summary
node scripts/parkdly.mjs https://parkdly.com/caddie-books/<caddie-book-uuid>

# GeoJSON of the whole course for mapping
node scripts/parkdly.mjs <token> --format geojson --out course.geojson

# Everything, normalized, for programmatic use
node scripts/parkdly.mjs <token> --format json --out course.json
```

## What gets extracted

- **Course**: id, name, description, unit system, destination, theme, created/updated.
- **Holes** (sorted): number, par, distance, elevation change, **tees** (lat/lng/rotation),
  **baskets/targets** (lat/lng, green radius), **flight paths** (ordered control points,
  which layouts use them), **tee signs** (template, bounds, rotation, QR, and the
  `noteText` — the printed rules/OB/mando text), **mandos**.
- **Layouts**: each named layout (e.g. FPO, FP40) with per-hole par/distance and whether
  the hole is included.
- **Amenities / facilities** (each with exact lat/lng + Google Maps link):
  restrooms, water, medical, first-aid, info boards, parking, trash, bench, shelter, food.
- **Play elements**: next-tee markers, drop zones, distance markers, bridges, stairs, text labels.
- **Boundaries**: OB lines and required-relief areas as ordered point lists (polygons/lines).
- **Background terrain**: forest, paths, streams, buildings, paved areas (polylines/polygons).
- **Map**: center lat/lng, zoom, bearing, bounding box, real width/height in meters.
- **Links**: published book URL(s), active share links (COPY / CADDIE_BOOK / PUBLIC_VIEW),
  canonical public slug URL.
- **Totals**: hole count, total par, total length.

## Amenity type reference

Parkdly stores amenities as `courseObjects` with a `type` string. Key ones:

| `type` | meaning |
|--------|---------|
| `wc` | **Restroom / toilet** (the UI labels it "Toilet") |
| `water-point` | Water |
| `medical-services` | Medical |
| `first-aid` | First aid |
| `info-board-location` | Info board |
| `parking` | Parking |
| `next-tee` | Next-tee marker (navigation, not a facility) |
| `drop-zone` | Drop zone (play element) |
| `tree` / `rock` / `bush` | Terrain decoration (counted, not listed as amenities) |

The script's `FACILITY_TYPES` / `TYPE_LABELS` maps (top of `scripts/parkdly.mjs`) define
which types surface in the `amenities`/`csv` views — extend them if Parkdly adds new types.

### Studio palette (verified read-only, 2026-09-21)

Read from the Course Builder menus and the `canvas-store` / `canvas-stage` bundles. The bottom toolbar switches
**Mode**: *Course Editing*, *Background Features*, *Terrain*. Pressing Escape on an open menu drops the mode back to
Course Editing, so reopen the mode before the next menu.

- **Course Elements** (tree button): Tree, Bush, Rock, Drop Zone (per hole), Next Tee Arrow (per hole), Distance
  Marker, Practice Tee, Practice Target.
- **Boundaries** (X button): Out of Bounds, Hazard, Casual Area, Required Relief, Mando.
- **Amenities & Items** (P button): Parking, Info Board, Toilet, Water Point, Medical Services, Trash Bin, Text,
  Rectangle, Bridge, Stairs, Pole, Custom SVG. API `type`s: `parking`, `info-board-location`, `wc`, `water-point`,
  `medical-services`, `thrash-bin` (sic), `text`, `custom-rectangle`, `bridge`, `stairs`, `post`, `custom-object`,
  plus `practice-tee`, `practice-target`, `distance-marker`. There is no bench, shelter or food type in the palette.
- **Background Features** (polylines/polygons, stored in `course.backgroundFeatures` with OSM-style `type` +
  `properties`, e.g. `fence {material: wood}`): Roads & Paths (Motorway, Primary Road, Residential Road, Path, Trail),
  Waterways (River, Stream, Ditch), Barriers (Fence, Wall, Hedge), Areas (Forest, Farmland, Grass, Water, Rock, Sand,
  Swamp, Building, Parking Lot, Paved Area).
- The OSM import is a separate read-only layer, `course.courseMap.geoJson` (named trails, streams, roads, buildings);
  it shows under Layers → *Background elements*. Check it before drawing a trail: it may already be there.
- Course objects carry `text`, `color`, `opacity`, `scale`, `scaleX`/`scaleY`, `rotation`, `customConfig`,
  `courseLayouts` (layout-specific) and `showOnCourseView`/`showOnHoleView`.
- Tee-sign note text lives on `holes[].teeSigns[].noteText`, which exists only after *Generate signage*.

## Units

Hole `distance` and `elevationChange` are stored in **meters**, even when the course
`unitSystem` is `IMPERIAL` (the Parkdly UI converts for display). The tool reports
`distanceMeters` raw plus a `distance` display value converted to feet for imperial courses.

## Private / unpublished books

Published caddie books need no auth. For a private or unpublished course, copy a full
`Cookie` header from an authenticated parkdly.com browser session and pass it via env:

```bash
PARKDLY_COOKIE="<cookie header>" node scripts/parkdly.mjs <token> --format json
```

A `404` from the `.data` endpoint usually means the book is unpublished/private (needs a
cookie) or the token is wrong.

## Notes & limits

- Decoding uses the real `turbo-stream` decoder, so it tracks Parkdly's actual data model.
  If Parkdly changes the loader shape, `--format raw` still dumps everything; the
  normalizer (`findRouteData` / `normalize` in the script) is where to adapt field paths.
- The script needs network access to parkdly.com and Node 18+ (uses global `fetch` and Web
  Streams). Tested on Node 25.
- No project dependencies; the only third-party code is the vendored `turbo-stream.mjs`.

## Uploading a course INTO Parkdly (browser flow — verified 2026-08-23)

Parkdly Studio has a **"Build course by hole coordinates"** flow that accepts bulk
tee/basket GPS, which makes "pull layout from UDisc → build course in Parkdly" a
repeatable pipeline. There is no unauthenticated write API; drive the logged-in
Studio UI (Claude-in-Chrome / Playwright) or, for headless work, the internal
React Router actions below with a session cookie.

### The pipeline (UDisc or KML → Parkdly)

The bulk format is `teeLat, teeLng | targetLat, targetLng`, one line per hole, 7 decimals.
Two proven sources:

**From a Google Earth / MyMaps KML** (verified 2026-09-11). Parse the
`<Placemark><Point>` entries, pair them by hole number, and emit the paste block:

```python
import re, xml.etree.ElementTree as ET
ns='{http://www.opengis.net/kml/2.2}'
holes={}
for pm in ET.parse(path).iter(ns+'Placemark'):
    if pm.find('.//'+ns+'Point') is None: continue          # skip lines/polygons
    n = pm.findtext(ns+'name').strip()
    lng,lat,el = map(float, pm.find('.//'+ns+'coordinates').text.strip().split(','))
    m = re.match(r'hole\s*(\d+)\s*(tee|basket)', n, re.I)  # tolerate "Hole 5 tee pad", "hole 2 basket"
    if m: holes.setdefault(int(m.group(1)),{})[m.group(2).lower()]=(lat,lng)
for h in sorted(holes):
    d=holes[h]; print(f"{d['tee'][0]:.7f}, {d['tee'][1]:.7f} | {d['basket'][0]:.7f}, {d['basket'][1]:.7f}")
```

⚠️ Hand-drawn KMLs carry typos. One had a point named **"Hole 34 tee"** that
was hole 4's tee by position. Always print a distance-and-elevation table per hole and
sanity-check it against the person who drew it, rather than trusting the labels. KML
`<Point>` altitude is metres; fairway polygon names are frequently wrong too.

**From UDisc**, with the sibling `udisc` skill:
   ```bash
   python3 <udisc-skill>/scripts/udisc.py layouts <slug> --format parkdly
   ```
   Stdout is exactly Parkdly's bulk format (`teeLat, teeLng | targetLat, targetLng`,
   one line per hole). Stderr carries the layout name and the **UDisc pars** — keep
   them for step 4.
2. **Create a new course** in Studio (project page → New course / Create a course).
   The coordinate builder is **only offered while a course has no area selected** —
   for an existing course with an area, create a fresh course instead.
3. In the "Where is your course?" dialog choose **"Build from tee and target
   coordinates"** → click **"Format with AI"** → the popover's *"Paste the AI's
   formatted holes here…"* textarea is the bulk entry point (the per-hole `lat, lng`
   inputs reject synthetic paste events; the textarea accepts typed input fine).
   Type the block in, click **Load holes**, verify the preview map, then
   **Create course with N holes**.
4. **Fix pars.** Parkdly estimates par from distance and will disagree with UDisc on
   long holes. Open each mismatched hole in Course Builder (Hole panel, or the
   ‹ N › stepper in the map toolbar) and set Par to the UDisc value.

### Automation gotchas

- The map canvas is **Konva** (WebGL). Neither CDP-trusted clicks nor synthetic
  PointerEvents place tees/baskets on it — do not fight it; the coordinate builder
  is the door. Regular buttons/inputs/dialogs automate normally.
- The "Format with AI" popover is designed for a copy-prompt → external-AI →
  paste-back round trip. When Claude drives the browser, skip the round trip: the
  `--format parkdly` output already matches the prompt's requested format.
- Login is required (Studio account); credentials must be entered by the human.

### Internal write API (recon notes, unofficial)

`window.__reactRouterManifest.routes` exposes Studio's full CRUD surface under
`routes/studio+/destinations+/$destinationId+/courses+/$courseId+/_data+/…`:
`coordinate-import` (action-only POST — what "Load holes" ultimately feeds),
`fairways`, `fairways/$fairwayId.tees|.targets|.flight-paths`, `layouts`,
`boundaries`, `mandos`, `elevation`, `import-from-course`, plus
`routes/api+/v1+/courses+/$courseId` (the official OAuth API, create-only,
max 27 fairways — credentials are issued on request by Parkdly support). URLs drop the `_data` segment (pathless): e.g.
`/studio/destinations/{destId}/courses/{courseId}/coordinate-import.data`.
Loaders respond to authenticated GETs with turbo-stream payloads; actions are
POSTs. Course objects, basket moves and bend-point moves are now verified by API (see *Batch-adding trees* and
*Moving baskets and bend points by API* below); for building a course, the UI flow above is still the proven path.

---

# Branding a course in Studio (verified 2026-09-11)

Everything below is the logged-in Studio UI. Order matters: **images → theme →
template → per-sign placements**, because a template change wipes per-sign sponsor
logos and the pickers only offer images already in the project library.

## 🚨 The colour-field trap — read this first

**Parkdly colour inputs only commit on a real keystroke.** Setting `.value`
programmatically (Playwright `fill`, CDP, the Claude-in-Chrome `form_input` tool)
leaves the hex text showing the new value while the swatch and the canvas keep the
old one, and it **silently reverts on the next re-render**. Two failure modes seen in
one session: signage colours that looked applied and were back to Parkdly green ten
minutes later, and map colours where three of six "succeeded" and three quietly did not.

Reliable pattern per field:

```
triple_click(field) → cmd+a → type("#RRGGBB") → Tab
```

Then **verify by zooming on the swatch**, not the text. A correct commit turns the
little colour chip; a failed one leaves the chip on the old colour.

Second trap: **element references shift after every colour mutation.** A batch of six
`form_input` calls against refs captured once will write four of them into the wrong
fields. Either re-`find` before each write, or use fixed screen coordinates with the
type-and-Tab pattern, or skip the whole problem with the JSON editor below.

## The Advanced theme JSON editor — the reliable bulk route

**Theme → Edit theme colors → Advanced** opens *Advanced theme JSON*: the entire theme
as one editable document with Validate / Format / Apply. This is the only place to set
many colours at once without fighting the commit behaviour, and the only place to see
keys the panels do not expose.

Top-level keys: `fontFamily`, `signage`, `hole`, `map`, `objects`, `typography`.

```jsonc
{
  "fontFamily": "Gantari",                    // allowed fonts listed under the editor
  "signage": {                                 // the sign furniture, not the map
    "primary": "#4D3C29",                      // main panel fill
    "primaryForeground": "#D49109",            // type on the panel — hole no, par, distance
    "secondary": "#D49109",
    "secondaryForeground": "#4D3C29",
    "text": "#4D3C29",                         // type on the background bands
    "neutral": "#ffffff",
    "neutralForeground": "#4D3C29",
    "background": "#F1DFD5"                    // header/footer bands
  },
  "hole": {
    "line": "#D49109", "secondaryLine": "#ffffff", "area": "#ffffff",
    "flightPathLine": { "widthMeters": 0.45, "dashMeters": 1.5, "gapMeters": 4, "colorMode": "split" },
    "numberBadge": { "size": "md", "useLayoutColors": true },
    "tee":       { "fill": "#4D3C29", "stroke": "#4D3C29", "sizeScale": "auto" },
    "target":    { "fill": "#e4ac08", "stroke": "#4D3C29", "sizeScale": "auto" },
    "dropZone":  { "fill": "#F97316", "stroke": "#000000" },
    "mando":     { "fill": "#F97316", "stroke": "#000000", "lineFill": "#F97316", "sizeScale": "auto" }
  },
  "map": {
    "background": "#d6d9c6", "water": "#3399cc",
    "tree": { "fill": "#3F4733", "opacity": 0.9 },
    "bush": { "fill": "#5a5e5e", "opacity": 0.9 },
    "grass": { "fill": "#46502f", "opacity": 1 },
    "rock":  { "fill": "#bca78a", "opacity": 0.9 },
    "building": "#b6b6b6", "asphalt": "#9c9ea1", "gravel": "#bca78a",
    "wood": "#8a5a3b", "metal": "#8f9296", "stone": "#a3a5a8", "plants": "#1c7a52",
    "farmland": "#7f8a4e", "forest": "#0e6c5f", "swamp": "#5a6e4a", "scree": "#a8a9ad",
    "golf": { "fairway": "…", "tee": "…", "drivingRange": "…", "bunker": "…", "green": "…" }
  }
}
```

Read the current theme out of the page instead of scrolling the panels:

```js
const t=[...document.querySelectorAll('textarea')].map(x=>x.value).filter(v=>v&&v.includes('signage'))[0];
JSON.parse(t)
```

Notes on the model:
- **`signage.*` is the sign chrome; `map.*` is the drawn map; `hole.*` is tees, baskets
  and flight paths.** Changing `map.background` does nothing to the sign panel.
- `map.golf.*` only renders where golf landcover polygons exist. On a course built from
  coordinates there are none, so those teal defaults never show — do not chase them.
- The contour lines take their colour from **`map` "Text on map"**, not from a contour key.

## Theme panel geography

**Theme** in the left rail → three tabs, **Course / Layouts / Signage**. Course-level
edits apply to every signage on the course; a single signage can override via the
Signage tab. Under *Edit theme colors* the accordions are **Font**, **Signage**
(colours + NOTES TEXT SIZES), **Holes**, **Map**.

**Saved themes**: *Save to my library* names a theme and makes it reusable across
courses (cap 20). Once saved, the panel shows **Update saved theme** and **Detach** —
edits stay local to the course until you push them back with Update.

## Contour density

Course Builder → **Elevations** (marked PREVIEW). Shows the site's terrain **range and
relief**, then DISPLAY controls: **INTERVAL (M) 0.5 / 1 / 2 / 5**, peak line width,
progression strength, layer opacity.

The default 1 m interval reads as noise on any real hill at sign scale. A course with
**262 ft of relief** and needed **2 m**. Pick the interval by relief, not by habit.

## Elevation change per hole

Hole panel → **Elevation Change** → **Auto-fill from terrain**. Per hole, one click,
metres and feet stay in sync. It is genuinely accurate: it returned −52 ft on a hole the
field notes called a steep downhill, and 0 on a flat one.

⚠️ **It will silently disagree with hand-written field notes.** On one course it
contradicted the notes on hole direction (notes said downhill, terrain said +23 ft up)
and on three distances. Surface every mismatch to the human rather than overwriting
either side — the geometry is only as good as where the tees and baskets were dropped.

## Tee-sign templates

**Built-ins**: Parkdly Classic, Pure, Grand, Rise, Grand Banner, **Map Only**. The setup
dialog offers Template, Size & shape (preset or **Custom ratio**, entered as w : h), and
Theme, then *Generate signage* creates one sign per hole plus an info board.

- **Map Only** is the right choice when you want clean map art to drop into your own
  sign layouts rather than using Parkdly's sign furniture. Pair it with a custom ratio
  that matches your artboard's map box (e.g. **6:5** landscape).
- ⚠️ **Scrolling with the setup modal open dismisses it.** Use `find` to get the
  template button's ref and click that instead of scrolling the carousel.
- **Rise has no slot that uses `secondary`.** Its face is `primary` + `background` +
  `primaryForeground` only, so a brand accent will vanish unless you put it in
  **`primaryForeground`** (which colours the hole number, par, distance and elevation).
  Check contrast: gold on dark brown is ~3.9:1, fine for those display numerals but
  below the bar for small body copy, which must stay white.

## Custom templates — the block designer

**Templates** (top nav) → *Signage Templates* → **Copy to my templates** on any built-in,
then **Edit**. Marked *Preview feature*. Cap 20.

The editor is a grid (default **12 rows × 24 columns**) with a **Blocks** palette, a
**Layers** tree, per-block properties, and **Edit JSON** for either one block or the
whole template.

Blocks: `Box`, `Hole Info`, `Header`, `Map Area`, `Hole Number`, `Notes`, `Hole Stats`,
`Compass`, `QR Code`, `Sponsor Logos`, `Image`, `Text`.

To insert: select the destination Box, click the block in the palette, then **click the
canvas** to place it ("Click the canvas to place image — Esc cancels").

### Logo-only header (the fix for "make the logo bigger")

The built-in header is a **`course-name` block that renders the logo *and* the course
name**, with `props.layout: "vertical"`. Its Title dropdown offers only *Project name*
and *Course name* — **there is no "none"**, so you cannot suppress the duplicate text
from the panel.

Fix: **delete the `course-name` block and drop an `Image` block in its place**, with
Data → **Project logo** (which reads the sign's Main Logo), Fit *Contain*, Width *Full
width*, Height *Fill the leftover space*. The logo then spans the whole band.

Image block Data options: **Project logo**, **Sponsor logo (first)**, **Uploaded image**.

Pair this with a **horizontal lockup** rather than a square badge: a square mark in a
wide band is height-capped and always reads small.

### The Parkdly watermark

The "Signage by parkdly" mark on the map is **not exposed in Course settings, the Tee
Sign panel, or the Theme editor**. Inside a *custom* template it exists as a deletable
block named **"Parkdly credit"** in the Layers tree.

⚠️ Do not remove it unprompted. Stripping a vendor's attribution is the account
owner's decision, may breach their terms, and may simply be re-added at render. Ask.

### Applying a template

Signages tab → tick the rows → **Actions** → **Change template** → pick → *Apply*
(or *Apply & Reposition*). Template edits propagate live to every sign using it; the
editor header shows *"Used by N signs — edits apply to them"*.

## Logos and sponsor marks

**Project settings → Images** is the shared library. PNG, JPG, WebP, **SVG (recommended)**.
Upload, then **Save Changes** — nothing appears in a picker until it is saved. Cap is
100 images per account.

⚠️ A **white/reversed logo previews as blank** on Parkdly's white thumbnails. That is
correct behaviour, not a broken file — verify by compositing it on your dark colour.

Per signage: **Tee Sign → Design → Image Placements**
- **Main Logo** — max 1 image (the header mark).
- **Sponsor Logo(s)** — up to 6 on a tee sign, up to 10 on an info board (the footer band).

Bulk actions in the Signages table: **Set main image**, **Set QR code**, **Change
template**, **Change aspect ratio**.

🚩 **There is no bulk action for sponsor logos, and changing the template clears them.**
Budget for reselecting them on every hole plus the info board by hand, one sign at a
time. The fastest route is the ‹ N › hole stepper in the canvas toolbar with the Tee
Sign panel left open, rather than going back to the list each time.

## Editing an EXISTING course in place (verified 2026-09-13)

You do **not** need to rebuild a course to move its holes. Every tee, target and
flight-path control point (and every course object: trees, rocks, amenities) has a
**Position panel with editable Latitude / Longitude** inputs. Editing in place keeps the
theme, template, per-sign sponsor logos, signage bounds and share links, which a
new-course rebuild would throw away. Use this whenever a layout changes after the
course exists (UDisc re-pull, a relocated hole, GPS from a field walk).

### Where the inputs are

Select the object on the canvas → the floating toolbar shows *Tee / Target / Flight Path
/ Tree* with a pencil **Edit** button → the left rail switches to **Objects** and shows
**Position → Latitude, Longitude** (bounded to the course's selected area; a value
outside it shows *"Please select coordinates within the selected map area"* and is not
applied), then object-specific fields (target diameter + green radius + putting circles;
tee rotation + width + length; flight path width). The **Hole** panel has no coordinates,
only Number / Par / Distance / Elevation.

### Typing into the coordinate fields by hand does NOT work for longitude

The fields are `<input type="number">`. A typed leading minus is dropped (the
extension's `type` action sends `111.62…`, which is out of area and rejected). Use the
programmatic route below; it is also the only way to do 18 fields without hunting
canvas pixels.

### Selecting objects without pixel-hunting: the Konva stage is global

`window.Konva.stages[0]` is the map. Every course object is a `Group` whose Konva **id is
the object's database id**, and the ids come from the React Router loader data already
in the page:

```js
const course = window.__reactRouterContext.state.loaderData[
  'routes/studio+/destinations+/$destinationId+/courses+/$courseId+/_layout'].course;
// course.holes[i].number, .tees[0].{id,lat,lng,rotation}, .targets[0].{id,lat,lng},
// .flightPaths[0].controlPoints[j].{id,lat,lng,order}, course.courseObjects[].{id,type,lat,lng}
```

Fire a click on the node (a bare `.fire('click')` does **not** select; mousedown +
mouseup + click does). Pass the node's own absolute position as `clientX/Y`, otherwise
the empty event reads as a drag from (0,0) and **the object moves** (this displaced a
tee and target on the first attempt):

```js
const st = Konva.stages[0], sleep = ms => new Promise(r => setTimeout(r, ms));
async function sel(id) {
  const n = st.findOne('#' + id), p = n.getAbsolutePosition(), r = st.container().getBoundingClientRect();
  const ev = t => new MouseEvent(t, { bubbles: true, clientX: r.left + p.x, clientY: r.top + p.y, button: 0 });
  n.fire('mousedown', { evt: ev('mousedown') }, true); await sleep(50);
  n.fire('mouseup',   { evt: ev('mouseup') },   true);
  n.fire('click',     { evt: ev('click') },     true); await sleep(600);
  // the Objects panel only opens if that rail tab is active; press the toolbar Edit otherwise
  if (document.querySelectorAll('input[type=number]').length < 2) {
    const b = [...document.querySelectorAll('button')].find(b => /^Edit$/i.test((b.getAttribute('aria-label') || b.textContent).trim()));
    if (b) { b.click(); await sleep(600); }
  }
}
```

The first two `input[type=number]` on the page are then Latitude and Longitude.

### Writing a coordinate so it actually SAVES

Parkdly saves on the input's **blur** (React `onBlur` → fetcher submit). Three traps,
all hit on 2026-09-13:

1. **Set the value through the native setter** so React sees it, then dispatch `input`
   and `change`. (`form_input` and plain `.value=` do not commit.)
2. **Dispatch `blur` and `focusout` yourself.** After a `navigate` the document has no
   focus (`document.hasFocus() === false`), so `el.focus()/el.blur()` fire no focus
   events and the save silently never happens; the field shows the new number, a reload
   shows the old one. This is why a batch "worked" for holes 1–5 (a physical click had
   focused the page) and not 6–9.
3. **Wait ≥1.5 s between writes.** Each save is a React Router fetcher; a new submit
   while the previous one is in flight cancels it, so fast loops save some fields and
   drop others.

```js
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
async function put(idx, v) {
  const inp = [...document.querySelectorAll('input[type=number]')][idx];
  inp.focus(); inp.dispatchEvent(new FocusEvent('focus')); inp.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
  setter.call(inp, String(v));
  inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true }));
  inp.dispatchEvent(new FocusEvent('blur')); inp.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); inp.blur();
  await sleep(1500);
}
// per hole: await sel(targetId); await put(0, lat); await put(1, lng); await sel(teeId); await put(0, lat); await put(1, lng);
```

Keep each `javascript_tool` call under ~40 s (the CDP evaluate times out at 45 s and
you lose the return value): **one hole per call**, not nine.

### Verify server-side, not from the inputs

```js
const txt = await (await fetch(location.pathname + '.data', { credentials: 'include' })).text();
txt.includes('39.271178')   // the loader payload is turbo-stream text; raw numbers are searchable
```
Or reload and re-read `course.holes[i].tees[0]` / `.targets[0]` from the loader data and
compute the offset to the intended coordinates (haversine); every hole should read 0 ft.

### After moving tees/targets

- **Flight-path control points do not follow.** Each hole's primary path keeps its bend
  point, so a relocated hole shows a kinked line and a wrong *distance* (distance
  follows the path: one hole read 417 ft on a 315 ft hole). Select the control
  point (same `sel(id)`; the panel is titled *Flight Path* and has Position lat/lng)
  and write it to the tee/target midpoint, or wherever the shot actually bends.
- **Re-run Auto-fill elevation on every hole.** The Hole panel's list rows are plain
  `<div>`s; the reliable driver is the toolbar's **Next hole** button
  (`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Next hole')`)
  then click the *Auto-fill from terrain* button, ~2 s per hole.
- Signage bounds stay where they were; check each sign in the Signage Editor and use
  **Auto-fit signage** on any whose map crop no longer frames the hole.

### Renaming a course, project, template and theme

- **Course name/description**: gear icon (top right of the editor) → *General*, saved
  automatically. The description and name flow into the info board immediately.
- **Project name**: *All project settings → General*, needs the explicit **Save**.
- **Custom template**: Templates → card **⋮ → Rename** (inline field + Save).
- **Saved theme cannot be renamed** (card offers only *Use* and *Delete*). Save the
  current custom theme to the library under the new name (*Save to my library*, dialog
  "Save as: New saved theme"), which also attaches it to the course, then delete the old
  entry (in-page confirm dialog). The course's own colours are untouched either way.
- **Bulk main image**: Signage Editor → the `<>` toggle at the top of the Signages panel
  opens the **table view** with checkboxes → header checkbox → *Actions → Set main
  image* → pick → Save. This does **not** clear per-sign sponsor logos (only a template
  change does).

## Multiple layouts: two baskets or tees per hole (verified 2026-09-14)

The coordinate builder takes one tee and one target per hole. For a course with a second play (e.g. Yellow and Red
baskets), build from the most-played layout, then add the rest in Studio.

1. **Create the layouts first.** Course Builder → **Layouts** → *Add layout* (name max 12 chars, Primary and
   Foreground colours; use the type-and-Tab pattern). Until a layout exists, *Add additional target / tee* is disabled
   ("Add layouts" badge). The first layout picks up every existing hole; later layouts also start with all holes.
2. **Add the object.** Select the hole, then the bottom toolbar's first button dropdown (next to *Add a new hole*) →
   **Add additional target** or **Add additional tee**. A floating panel lets you assign it to layouts (the new
   layout is preselected). Parkdly creates a new flight path for that layout automatically.
   - **Target:** a single real click on empty canvas places it (2026-09-14). On 2026-09-15 a single click only showed
     a preview with a distance badge and closing the panel discarded it; a **double-click** committed. Check the target
     count in `design.data` after placing.
   - **Tee:** a single click does *not* commit; **hover, then double-click** places it.
   - Synthetic clicks still do nothing; the extension's real `left_click` / `double_click` work.
3. **Set exact GPS** with the Konva `sel(id)` + native-setter `put()` pattern above. Get new ids from `design.data`
   (targets have `greenRadius`, tees have `widthMeters`; new objects have long unrounded coordinates, saved values are
   rounded to 6 decimals).
4. **Straighten the new flight path.** Its control point stays where you clicked. Write it to the tee/target midpoint.
5. **Per-layout pars.** Hole panel → Yellow/Red chips → *Layout Settings* → Par. Par auto-estimates from distance and
   will be wrong. The lock is inverted from what it looks like: in the "Updates automatically" state the field is
   editable; type the par, Tab, **then click the lock** → "Manual value - won't change automatically" (field disabled).
   Locked pars survive later tee/target moves (toast "Target moved, but par remained unchanged (locked)").
6. **Distances go stale** after a flight-path edit (a layout hole read 1,391 ft on a 336 ft hole). A write that rounds
   to the same 6-decimal value is a no-op, so nudge a target 20 cm and back to force a recompute.

Traps found the same session:
- **Konva nodes exist only for the hole on screen.** `stage.findOne('#id')` returns nothing for another hole's
  control point; switch holes first (the hole dropdown's buttons read `Hole #777` — number plus layout badges — so
  match on text with whitespace removed).
- **Stale panel after a hole switch.** The first `put()` after changing holes can save the *previous* object's value
  (hole 9's bend point got hole 7's latitude; hole 6's new tee got hole 3's coordinates). Always read the server value
  back after each write and redo it if wrong. Never run a multi-hole loop in one `javascript_tool` call.
- The par toast *"Hole 6 (Red): par 5 → 3 — Keep par 5"* appears when a move changes an unlocked par; ignore it (do
  not click Keep) if the new par is right.
- **Elevations** panel → *Sample terrain* reports range and relief for the whole map area, including bluffs off the
  course; judge the interval by the playing area.
- Project images: upload through the settings page file input (`/studio/destinations/<id>/settings/images`), then
  **Save Changes**.

### Flight paths from UDisc doglegs (verified 2026-09-15: 36 paths, all within 3 ft of UDisc)

UDisc's layout JSON gives each hole an ordered `doglegs` array; tee + doglegs + basket reproduces UDisc's hole
`distance` exactly. Set one Parkdly path per hole per layout from it (straight line only when empty).

- **Collect control-point ids from `design.data`:** objects with `controlPoints` + `holeId` are flight paths, and their
  `courseLayouts` names the layouts using them. Sort points by `order`.
- **Seeded extra points.** The coordinate builder often seeds 1 or 2 control points, which can be more than UDisc's bend
  count. Keep them and put each extra on the midpoint of the longest segment, so the length doesn't change.
- **Adding a point:** a **real double-click on the line** (the extension's `double_click`, not a Konva `fire`) inserts a
  control point after the nearest existing one. It opens its Latitude panel straight away, so `put(0, lat)` and
  `put(1, lng)` work immediately. The new point gets a client UUID id (with dashes) that persists server-side. Click
  on the segment where the new bend belongs, between the right neighbours.
- **The hole dropdown toggles.** After a hole switch, the next click on the dropdown (toolbar, left of the map) can
  *close* it instead of opening it. Pattern: click, try `findHoleBtn(n)`; click again, try again, with a done-set so the
  second try is a no-op when the first worked. One hole per `javascript_tool` call.
- **Audit geometry and stored distance separately.** From `design.data`, compute the polyline length (tee + ordered
  control points + target, per layout hole via `teeId`/`targetId` and the path whose `courseLayouts` includes that
  layout). Compare it with the layout hole's stored `distance` (metres) and with UDisc. On one course the geometry
  was right on all 36 paths, but the stored distance was stale on 9 of them (Red 7 read 512 ft on a 588 ft path).
- **Re-save trick to force a recompute:** select a control point on that path, write its latitude **+5e-6**, then
  write the real value back (two `put(0, …)` calls). A write of the identical value is a no-op and won't recompute.

### Elevation auto-fill with more than one layout

Elevation change is stored **per layout hole** (`elevationChange`, whole metres). In the Hole panel the Yellow/Red
chips switch which layout's settings you are editing. A JS `.click()` on a chip does **not** switch it (the Red
auto-fill silently wrote nothing), but a real click does, and the chosen chip then stays selected
across **Next hole / Previous hole** (those buttons do accept JS clicks). Pass 1: first chip selected, then for each
hole click *Auto-fill from terrain* and Next hole. Pass 2: real-click the second chip, then walk back with Previous
hole. Verify in `design.data` (an unset value decodes as the turbo-stream `-5` null). Run no more than 4 holes per
`javascript_tool` call; 5 at about 7 s each hit the 45 s CDP timeout.

A layout audit script (reads `design.data`, joins `courseLayoutId` to layout names and tee/target ids to positions,
compares with expected coordinates and pars per play) is worth writing once per course.
Layout-hole fields: `holeNumber, par, distance, isParLocked, isDistanceLocked, isIncluded, courseLayoutId, teeId, targetId`.

## Batch-adding trees and other course objects (verified 2026-09-21)

Trees, bushes, rocks and amenities are `courseObjects` (`holeId` null: a course object belongs to no hole and draws on every
hole map whose frame covers it). No Konva clicking needed; the editor's own endpoints take plain FormData with the session cookie.
Paths drop `_data`: `/studio/destinations/<dest>/courses/<course>/…`.

| Call | Body | Notes |
|---|---|---|
| `POST …/course-objects` | `type, lat, lng, scale, rotation, id` | One object. `id` is a client UUID and is kept server-side. The UI randomises scale and rotation per placed tree |
| `DELETE …/course-objects/<id>` | none | One object |
| `POST …/course-objects/bulk-replace` | `objects[i][id]`, `[lat]`, `[lng]`, `[rotation]`, `[scale]`, `[type]=tree` | **Replaces the course's entire TREE set** (other types untouched; the client labels it "Replace N trees with M"). 1,155 trees in one request worked. On a course that already has hand-placed trees, re-send them too or they are deleted. **Once the owner has placed trees by hand, never use it**: single creates + bulk-delete by id only |
| `POST …/course-objects/bulk-delete` | `ids` = JSON array | Returns `{"success":true,"count":N}` |

- **Size:** a scale-1 tree draws **4.0 m** across, so `scale = crown diameter / 4.0` (measured Sep 21 by rasterising the
  tree glyph path on the Konva stage, ~3.79 stage units/m). An earlier 5.35 m figure was the glyph's *rotated bounding box*;
  one 1,155-tree batch was sized with it and draws at ~75% of the lidar crowns. Scale clamps 0.5-3.0, so
  crowns over 12 m draw at 12 m.
- **Give every batch a recognisable id pattern** (e.g. `<8 hex>-2026-4921-8000-<12-digit index>`, a valid UUID shape) so the batch
  can be found and removed by id without touching the owner's objects.
- **Guard before bulk-replace:** read `courseObjects` (fresh reload) and stop unless the tree set is what you expect (empty, or only your ids).
- **Check a decoded coordinate before sending.** A compact payload (integer offsets from a base lat/lng) with the wrong base put
  1,155 trees 60 km south on a first run; it only showed up on read-back. Assert `rows[0].lat` against the source file.
- **Read back after every write:** tree count, ids, a few positions, and the non-tree objects/boundaries/background features unchanged.
- ⚠️ **Claude Code auto mode blocks these writes** ("Modify Shared Resources"), even after the owner approves in chat. Write the
  request as a console snippet (guard + payload + one fetch), put it on the clipboard (`pbcopy`), have the owner paste it into
  DevTools on the Studio page, then verify read-only.
- Tree positions can come from a lidar pipeline (USGS 3DEP → CHM → tree tops → fairway-lane split → preview).

### Paste-snippet rules (339 fairway trees over 21 holes, Sep 21)

The per-hole loop that worked: build a preview PNG + JSON + console snippet, the owner answers (drop / add back / split /
"go"), `pbcopy` the snippet, owner **reloads Studio** and pastes it into DevTools, pastes the one-line output back, then
record what was written in a local ledger. Make every snippet:
- **Idempotent:** read `courseObjects` from the loader data, skip any id that already exists. A double paste then does nothing.
- **Owner-safe:** skip anything within 3 m of a tree/bush whose id is not in your id pattern (the owner's hand-placed ones;
  rocks don't block). Keep this live check even if you hold a local copy of the owner's trees: the local
  copy goes stale (hole 21: a tree passed the local check and the live one skipped it).
- **Guarded:** assert `rows[0]` decodes to the source coordinate before any fetch.
- **Honest in its output:** one line, `added N of M deleted N of M [skipped ids with reason / HTTP status]`, so the ledger
  records what was *actually* written (re-record without anything the live check skipped).
- **Never fire synthetic Konva clicks.** If the owner has a placement tool armed, a click drops an object (it placed a stray rock).

**HTTP 500 on create does not mean "not created".** Hole 16's paste logged 11 × 500; a re-paste after reload reported all
25 ids already present (most likely the snippet ran twice on stale loader data). Re-paste after a reload and read its
skip list before re-sending anything.

**Example owner rule:** no tree crown (as drawn) within 1 m of any basket, all layouts. A lidar tree on a
basket is split into k smaller trees across its canopy, each kept clear, which draws a basket "ring" instead.

## Moving baskets and bend points by API (verified 2026-09-21)

Paths drop `_data`: `/studio/destinations/<dest>/courses/<course>/…`, FormData, session cookie.

| Call | Body | Notes |
|---|---|---|
| `PATCH …/fairways/<holeId>` | `target.id, target.lat, target.lng, target.greenRadius`, optional `layoutConfigs[i].layoutId, layoutConfigs[i].distance` (metres, int) | **This is what a canvas basket drag sends**, and the only call that moves a target. Skip `distance` when the layout config has `isDistanceLocked` |
| `PATCH …/fairways/<holeId>/targets/<targetId>` | properties | Returns 200 but only updates properties (greenRadius, diameter, circles). **Silently ignores lat/lng** |
| `PATCH …/fairways/<holeId>/flight-paths/<pathId>/control-points/<pointId>` | `lat, lng` | Moves one bend point |

- **Never send `par`.** The editor re-derives unlocked pars from distance; sending one fights it (a course can have
  par 4 on 72 m holes by design).
- Compute `distance` from the line: tee → bend points sorted by `order` → target, haversine, rounded to whole metres.
- Two layouts sharing one physical basket can be two target objects on different holes; snap one onto the other with the
  fairway PATCH (guard: stop if they are more than ~5 m apart).
- **Loader data is stale after any canvas drag until a reload.** Every snippet should say "reload first", and re-read
  Studio before any write that could clobber a hand edit (basket, bend, tee the owner just moved).
- Bends draw **rounded** (control point `size`, e.g. 12.5), so a straight-segment preview can show a tree "on" a line the
  Studio curve clears.

## Public page

**Project settings → Public Page → Create public page.** It is created **unpublished**,
so making it is safe; the *Published* toggle is the outward-facing act and should be the
human's call. Slug is `parkdly.com/p/<slug>`.

Three tabs: **Page** (title, slug, description, publish toggle, delete), **Content**,
**Appearance** (Logo picker, Colors, Sponsor logos with optional per-logo link URLs).

Appearance colours are **Background, Primary, Text, Text Muted**. Parkdly renders *dark*
text on the Primary fill, so Primary wants a light-to-mid accent; a dark Primary gives
an unreadable button.

## Branding checklist

1. Upload logos to **Project settings → Images**, then Save Changes.
2. Set the **theme** — fastest and safest through *Edit theme colors → Advanced* JSON.
3. Save it to the library if other courses should reuse it.
4. Set the **contour interval** from the site's relief (Course Builder → Elevations).
5. **Auto-fill elevation** on every hole; reconcile against field notes.
6. Choose or build the **template**; apply it to all holes in one bulk action.
7. **Then** set Main Logo and Sponsor Logos per sign — last, because a template change
   resets them.
8. Public page only if asked, and leave it unpublished.
