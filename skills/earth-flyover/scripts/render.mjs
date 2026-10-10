#!/usr/bin/env node
// Render a caddie-book (or arbitrary lat/lng) flythrough video from a Parkdly
// course JSON (the `parkdly.mjs --format json` shape). Headless ArcGIS SceneView
// (Esri World Imagery on real terrain) -> Playwright screenshots -> ffmpeg -> MP4.
//
// Alongside <out>.mp4 this also writes <out>.segments.json -- a manifest of labeled
// time ranges within the video (e.g. one entry per hole, with par/distance/note),
// consumed by scripts/stitch.mjs to embed MP4 chapter markers and emit SRT/CSV
// sidecars for post-processing (adding lower-thirds/graphics in an NLE).
//
// Usage:
//   node render.mjs <course.json> [options]
//
// Options:
//   --mode establish|holes|transit   camera path style (default: establish)
//   --to FILE                transit mode: the SECOND course json to fly to (required)
//   --transit-seconds N      transit mode: length of the flight between courses (default: 5)
//   --hold-start N           transit mode: seconds parked over course A first (default: 1)
//   --hold-end N             transit mode: seconds parked over course B after landing (default: 1.5)
//   --transit-apex N         transit mode: extra metres of altitude at mid-flight
//                            (default: half the gap, clamped 1.5k-60k)
//   --start-brg N            transit mode: camera bearing at the start (default: trailing the travel axis)
//   --overlays on|off        draw flight paths/OB/tees/baskets/hole#s/amenities (default: on)
//   --hud on|off             burn in readable hole/par/distance/notes text (default: on)
//   --hole N                 holes mode only: render just this one hole number instead
//                            of the whole course (still does the full pan+settle cinematic)
//   --from-hole N            holes mode only: start the tour at this hole number and
//                            continue through the rest (e.g. to pick up where an
//                            establish-mode --settle-hole intro left off, without
//                            re-touring the same hole). Ignored if --hole is given.
//   --seconds-per-hole N     holes mode: seconds of video per hole (default: 10)
//   --frames-per-hole N      holes mode: exact frames per hole (overrides --seconds-per-hole)
//   --seconds N              establish mode: duration in seconds (default: 4)
//   --start-alt N            establish mode: starting altitude in metres above the course
//                            center (default: ~1x the course footprint -- a local orbit).
//                            Set into the millions for a "from space" zoom-in.
//   --start-radius N         establish mode: starting horizontal offset in metres from the
//                            course center (default: ~1.5x the course footprint). Pair with
//                            --start-alt for a from-space shot (e.g. 4500000 / 1200000).
//   --end-alt N --end-radius N  establish mode: where the zoom finishes (default: a local
//                            establishing view derived from the course footprint). Set these to
//                            near the start values for a high drift that never descends.
//   --start-center lat,lng   establish mode: centre the opening frame here and ease onto the
//                            course during the dive (e.g. the centroid of a set of markers you
//                            want fully in frame at the start). Default: course centre throughout.
//   --sweep N                establish mode: total heading sweep in degrees during the zoom-in
//                            (default: 110). Lower it (e.g. 30-40) for a from-space zoom so
//                            it reads as a dive-in rather than a wide orbit.
//   --orbit-seconds N        establish mode: after the zoom-in lands, keep rotating around
//                            the course at that same framing for this many extra seconds
//                            (default: 0 -- no orbit tail). Eases in right as the zoom eases
//                            to a stop, so there's no velocity jump at the seam.
//   --orbit-frames N         establish mode: exact extra frames for the orbit tail (overrides
//                            --orbit-seconds).
//   --orbit-sweep N          establish mode: extra heading degrees to rotate through during
//                            the orbit tail (default: 90).
//   --settle-hole N          establish mode: after the zoom+orbit, glide onto this hole's
//                            tee-pad view looking down the fairway at the basket (same vantage
//                            as `holes` mode's settle shot). Default: none (shot ends on the orbit).
//   --settle-seconds N       establish mode: duration of the glide onto --settle-hole (default: 3).
//                            Not the same thing as --settle-ms (that's a per-frame tile-load wait).
//   --settle-frames N        establish mode: exact frames for the --settle-hole glide (overrides
//                            --settle-seconds).
//   --frames N               establish mode: exact frames for the zoom-in phase (overrides --seconds)
//                            holes mode: total frames, divided evenly across holes
//                            (overridden by --seconds-per-hole/--frames-per-hole if given)
//   --aspect 16:9|9:16       convenience resolution preset (default: 16:9 = 1280x720;
//                            9:16 = 720x1280). Ignored if --width/--height given.
//   --width N --height N     output resolution (overrides --aspect; default: 1280x720)
//   --fps N                  output frame rate (default: 30)
//   --out FILE               output mp4 path (default: <course-name>-<mode>.mp4 in cwd)
//   --settle-ms N            per-frame max tile-settle wait (default: 900)
//   --keep-frames            don't delete the intermediate PNG frames dir
import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync, rmSync, mkdtempSync } from 'fs';
import { execFileSync } from 'child_process';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.dirname(__dirname);

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) { out[key] = true; }
      else { out[key] = next; i++; }
    } else out._.push(a);
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const courseFile = args._[0];
if (!courseFile) {
  console.error('Usage: node render.mjs <course.json> [--mode establish|holes|transit] [--overlays on|off] [--hud on|off] [--hole N] [--from-hole N] [--seconds-per-hole N] [--frames-per-hole N] [--seconds N] [--start-alt N] [--start-radius N] [--sweep N] [--orbit-seconds N] [--orbit-frames N] [--orbit-sweep N] [--settle-hole N] [--settle-seconds N] [--settle-frames N] [--frames N] [--aspect 16:9|9:16] [--width N] [--height N] [--fps N] [--out FILE] [--settle-ms N] [--keep-frames]');
  process.exit(1);
}

const mode = args.mode || 'establish';
const overlaysOn = args.overlays !== 'off';
const hudOn = args.hud !== 'off';
const ASPECT_PRESETS = { '16:9': [1280, 720], '9:16': [720, 1280] };
const [presetW, presetH] = ASPECT_PRESETS[args.aspect] || ASPECT_PRESETS['16:9'];
const W = parseInt(args.width || String(presetW), 10);
const H = parseInt(args.height || String(presetH), 10);
const FPS = parseInt(args.fps || '30', 10);
const SETTLE_MS = parseInt(args['settle-ms'] || '900', 10);
const KEEP_FRAMES = !!args['keep-frames'];

const course = JSON.parse(readFileSync(courseFile, 'utf8'));
const courseName = (course.course?.name || path.basename(courseFile, '.json') || 'course')
  .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
const holeFilter = args.hole ? parseInt(args.hole, 10) : null;
const fromHole = args['from-hole'] ? parseInt(args['from-hole'], 10) : null;

const defaultOutName = holeFilter ? `${courseName}-hole${holeFilter}.mp4` : `${courseName}-${mode}.mp4`;
const OUT_FILE = path.resolve(args.out || defaultOutName);
const FRAMES_DIR = mkdtempSync(path.join(os.tmpdir(), `flyover-${courseName}-`));

// --- geo helpers (WGS84 sphere) ---
const R = 6378137, d2r = Math.PI / 180, r2d = 180 / Math.PI;
function dest(lat, lng, brg, dist) {
  const br = brg * d2r, la1 = lat * d2r, lo1 = lng * d2r, dr = dist / R;
  const la2 = Math.asin(Math.sin(la1) * Math.cos(dr) + Math.cos(la1) * Math.sin(dr) * Math.cos(br));
  const lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la1), Math.cos(dr) - Math.sin(la1) * Math.sin(la2));
  return { lat: la2 * r2d, lng: lo2 * r2d };
}
function bearing(a, b) {
  const la1 = a.lat * d2r, la2 = b.lat * d2r, dlo = (b.lng - a.lng) * d2r;
  const y = Math.sin(dlo) * Math.cos(la2);
  const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dlo);
  return (Math.atan2(y, x) * r2d + 360) % 360;
}
function haversine(a, b) {
  const la1 = a.lat * d2r, la2 = b.lat * d2r, dlat = (b.lat - a.lat) * d2r, dlng = (b.lng - a.lng) * d2r;
  const s = Math.sin(dlat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dlng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const lerp = (a, b, t) => a + (b - a) * t;
const loglerp = (a, b, t) => Math.exp(lerp(Math.log(a), Math.log(b), t));
function lerpAngle(a, b, t) { const d = ((b - a + 540) % 360) - 180; return (a + d * t + 360) % 360; }
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// --- caddie-book overlay payload (3D graphics drawn on the terrain) ---
function buildOverlayPayload(c) {
  const flightPaths = [], baskets = [], tees = [], ob = [], amenities = [];
  for (const h of c.holes || []) {
    const tee = h.tees?.[0], bk = h.baskets?.[0];
    if (tee) tees.push([tee.lng, tee.lat]);
    if (bk) baskets.push({ lng: bk.lng, lat: bk.lat, hole: h.number });
    const fp = (h.flightPaths || []).find((f) => f.type === 'PRIMARY') || h.flightPaths?.[0];
    if (fp?.points?.length >= 2) flightPaths.push(fp.points.map((pt) => [pt.lng, pt.lat]));
    else if (tee && bk) flightPaths.push([[tee.lng, tee.lat], [bk.lng, bk.lat]]);
  }
  for (const b of (c.boundaries || [])) {
    if ((b.type || '').toLowerCase().includes('ob') && b.points?.length >= 2)
      ob.push(b.points.map((pt) => [pt.lng, pt.lat]));
  }
  for (const a of (c.amenities || [])) amenities.push({ lng: a.lng, lat: a.lat, type: a.type });
  // markers ride through untouched: geo-anchored location pins, independent of hole geometry
  return { flightPaths, baskets, tees, ob, amenities, markers: c.markers || [] };
}

// --- HUD text payload for a hole (burned-in readable text, not 3D geometry) ---
function holeHudInfo(h) {
  const sign = (h.teeSigns || []).find((s) => s.isPrimary) || h.teeSigns?.[0];
  const note = sign?.noteText ? sign.noteText.replace(/\r\n/g, '\n').trim() : '';
  const distance = h.distance ? `${h.distance.value} ${h.distance.unit}` : (h.distanceMeters ? `${Math.round(h.distanceMeters)} m` : '');
  return { hole: h.number, par: h.par, distance, note };
}

async function main() {
  mkdirSync(FRAMES_DIR, { recursive: true });

  const browser = await chromium.launch({
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader']
  });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.log('PAGEERR:', e.message));

  await page.goto('file://' + path.join(SKILL_DIR, 'scene.html'));
  console.log('waiting for globe...');
  await page.evaluate(() => window.__viewReady);
  const groundZ = (lat, lng) => page.evaluate(([a, b]) => window.groundZ(a, b), [lat, lng]);

  if (overlaysOn) {
    const res = await page.evaluate((p) => window.addOverlays(p), buildOverlayPayload(course));
    console.log('overlays:', JSON.stringify(res));
  }
  if (!hudOn) await page.evaluate(() => window.hideHud());

  let FRAMES, camAt, onFrame = null, segments = [];

  if (mode === 'establish') {
    const zoomFrames = args.frames ? parseInt(args.frames, 10) : Math.round((args.seconds ? parseFloat(args.seconds) : 4) * FPS);
    const orbitFrames = args['orbit-frames']
      ? parseInt(args['orbit-frames'], 10)
      : Math.round((args['orbit-seconds'] ? parseFloat(args['orbit-seconds']) : 0) * FPS);
    const settleHole = args['settle-hole'] ? parseInt(args['settle-hole'], 10) : null;
    const settleFrames = settleHole
      ? (args['settle-frames'] ? parseInt(args['settle-frames'], 10) : Math.round((args['settle-seconds'] ? parseFloat(args['settle-seconds']) : 3) * FPS))
      : 0;
    const zoomOrbitFrames = zoomFrames + orbitFrames;
    FRAMES = zoomOrbitFrames + settleFrames;

    const c = course.map.center;
    const size = Math.max(course.map.realWidthMeters, course.map.realHeightMeters);
    const gz = await groundZ(c.lat, c.lng);
    console.log(`course center ground elevation: ${Math.round(gz)} m`);
    // Defaults are a close-in local orbit (starts ~1.5x the course footprint away).
    // Pass --start-alt/--start-radius in the millions of metres for a "from space" zoom-in.
    const startRadius = args['start-radius'] ? parseFloat(args['start-radius']) : size * 1.55;
    const startAlt = args['start-alt'] ? parseFloat(args['start-alt']) : size * 1.05;
    // --end-alt/--end-radius let a shot finish somewhere other than the local establishing view,
    // so a descent can be cut into segments (e.g. an orbit-altitude drift that never comes down,
    // then a separate low approach) instead of flying the whole altitude range in one take.
    const endRadius = args['end-radius'] ? parseFloat(args['end-radius']) : size * 0.75;
    const endAlt = args['end-alt'] ? parseFloat(args['end-alt']) : size * 0.6;
    const startBrg = 200, sweep = args.sweep ? parseFloat(args.sweep) : 110;
    // --start-center "lat,lng": open the shot centred somewhere else and ease onto the course as
    // the dive proceeds. Without it the target is centred for the whole descent, which pushes a
    // wide opening framing off to one side whenever the course sits at the edge of what you want
    // to show. Only affects the zoom phase; the orbit/settle phases stay centred on the course.
    const startCenter = args['start-center']
      ? (([la, lo]) => ({ lat: parseFloat(la), lng: parseFloat(lo) }))(String(args['start-center']).split(','))
      : null;
    const orbitSweep = args['orbit-sweep'] ? parseFloat(args['orbit-sweep']) : 90;
    const totalSweep = sweep + orbitSweep;

    const poseAtBrg = (brg, Rr, Hh, ctr) => {
      const cc = ctr || c;
      const p = dest(cc.lat, cc.lng, brg, Rr);
      const tilt = 90 - Math.atan2(Hh, Rr) * r2d;
      return { position: { longitude: p.lng, latitude: p.lat, z: gz + Hh }, heading: (brg + 180) % 360, tilt };
    };

    // Phase 3 (optional): after the zoom+orbit, glide onto a specific hole's tee-pad view,
    // tilted down the fairway at the basket -- same vantage as `holes` mode's settle shot.
    let teePose = null;
    if (settleHole) {
      const h = (course.holes || []).find((hh) => hh.number === settleHole);
      if (!h) throw new Error(`--settle-hole ${settleHole} not found in this course`);
      const tee = h.tees?.[0], bk = h.baskets?.[0];
      if (!tee || !bk) throw new Error(`hole ${settleHole} is missing tee/basket coords`);
      const B = bearing(tee, bk);
      const D = Math.max(haversine(tee, bk), 20);
      const teeBack = dest(tee.lat, tee.lng, (B + 180) % 360, 55);
      const teeHeight = clamp(D * 0.16, 35, 90);
      const gzTee = await groundZ(teeBack.lat, teeBack.lng);
      teePose = { position: { longitude: teeBack.lng, latitude: teeBack.lat, z: gzTee + teeHeight }, heading: B, tilt: 74 };
    }
    const orbitEndPose = () => poseAtBrg(startBrg + totalSweep, endRadius, endAlt);

    // Dive in from --start-alt/--start-radius down to the local establishing view, then
    // (if --orbit-seconds is given) keep that framing and continue rotating -- an "arrival"
    // beat after the zoom lands. Bearing and altitude/radius are deliberately decoupled:
    //   - altitude/radius ease out only across the zoom phase (0..zoomFrames), so the dive
    //     itself still arrives with a smooth, natural deceleration.
    //   - bearing sweeps across the WHOLE zoom+orbit span on a single ease curve, so it's
    //     already at speed as the zoom lands and flows straight into the pan -- no dead stop
    //     at the seam waiting for a second ease-in to spin back up.
    // If --settle-hole is set, a third phase glides from wherever the orbit ends onto that
    // hole's tee-view (independent ease, its own start/stop -- a deliberate new beat, not a
    // continuation of the pan's momentum).
    camAt = (u) => {
      const f = Math.round(u * (FRAMES - 1));

      if (settleFrames > 0 && f >= zoomOrbitFrames) {
        const su = settleFrames <= 1 ? 1 : (f - zoomOrbitFrames) / (settleFrames - 1);
        const e = ease(su);
        const start = orbitEndPose();
        return {
          position: {
            longitude: lerp(start.position.longitude, teePose.position.longitude, e),
            latitude: lerp(start.position.latitude, teePose.position.latitude, e),
            z: lerp(start.position.z, teePose.position.z, e)
          },
          heading: lerpAngle(start.heading, teePose.heading, e),
          tilt: lerp(start.tilt, teePose.tilt, e)
        };
      }

      const uzo = zoomOrbitFrames <= 1 ? 0 : Math.min(f, zoomOrbitFrames - 1) / (zoomOrbitFrames - 1);
      const brg = startBrg + totalSweep * ease(uzo);
      const zu = zoomFrames <= 1 ? 1 : Math.min(f, zoomFrames - 1) / (zoomFrames - 1);
      const ze = ease(zu);
      const Rr = f < zoomFrames ? loglerp(startRadius, endRadius, ze) : endRadius;
      const Hh = f < zoomFrames ? loglerp(startAlt, endAlt, ze) : endAlt;
      const ctr = startCenter && f < zoomFrames
        ? { lat: lerp(startCenter.lat, c.lat, ze), lng: lerp(startCenter.lng, c.lng, ze) }
        : c;
      return poseAtBrg(brg, Rr, Hh, ctr);
    };

    if (hudOn && course.totals) {
      const t = course.totals;
      await page.evaluate((info) => window.setCourseInfo(info), {
        name: course.course?.name || courseName,
        par: t.par, holes: t.holes,
        length: t.distanceDisplay ? `${t.distanceDisplay.value} ${t.distanceDisplay.unit}` : ''
      });
    }
    if (hudOn && settleHole) {
      const h = course.holes.find((hh) => hh.number === settleHole);
      onFrame = async (f) => {
        if (f === zoomOrbitFrames) await page.evaluate((info) => window.setHoleInfo(info), holeHudInfo(h));
      };
    }

    // Segment manifest (for chapter markers / post-processing -- see scripts/stitch.mjs).
    segments = [{ label: 'Intro', startSec: 0, endSec: zoomOrbitFrames / FPS }];
    if (settleHole) {
      const h = course.holes.find((hh) => hh.number === settleHole);
      segments.push({ label: `Hole ${settleHole}`, startSec: zoomOrbitFrames / FPS, endSec: FRAMES / FPS, ...holeHudInfo(h) });
    }
  } else if (mode === 'transit') {
    // Fly from one course to ANOTHER course: rise off course A, arc across the gap facing the
    // direction of travel, and settle into course B's establishing view. For events where a
    // division plays more than one venue and the film has to physically move between them
    // (e.g. a multi-day event where one division plays two different courses).
    const toFile = args.to;
    if (!toFile) throw new Error('--mode transit needs --to <course-b.json>');
    const courseB = JSON.parse(readFileSync(toFile, 'utf8'));
    const A = course.map.center, B = courseB.map.center;
    const sizeA = Math.max(course.map.realWidthMeters, course.map.realHeightMeters);
    const sizeB = Math.max(courseB.map.realWidthMeters, courseB.map.realHeightMeters);
    const gap = haversine(A, B);
    if (gap < 1) throw new Error('transit: the two courses are at the same point');

    const holdA = Math.round((args['hold-start'] ? parseFloat(args['hold-start']) : 1.0) * FPS);
    const holdB = Math.round((args['hold-end'] ? parseFloat(args['hold-end']) : 1.5) * FPS);
    const flyFrames = Math.round((args['transit-seconds'] ? parseFloat(args['transit-seconds']) : 5) * FPS);
    FRAMES = holdA + flyFrames + holdB;

    // Each end parks on the same local geometry `establish` mode lands on, so a transit
    // intercuts seamlessly with a plain establish render of either course.
    const Ra = sizeA * 0.75, Ha = sizeA * 0.6;
    const Rb = sizeB * 0.75, Hb = sizeB * 0.6;
    const travel = bearing(A, B);
    // Camera trails the target on the travel axis at both ends, so it is already looking
    // toward the destination before it leaves, and still facing forward when it arrives.
    const brgA = args['start-brg'] ? parseFloat(args['start-brg']) : (travel + 180) % 360;
    const brgB = (travel + 180) % 360;
    // The hop's apex. Scales with the gap so a 2 km move and a 40 km move both read as arcs.
    const apex = args['transit-apex'] ? parseFloat(args['transit-apex']) : clamp(gap * 0.5, 1500, 60000);

    // Ground elevation along the path. A groundZ() call per frame would be an extra page
    // round-trip per frame; 21 samples interpolated is visually identical across a hop.
    const SAMPLES = 21, gzs = [];
    for (let i = 0; i < SAMPLES; i++) {
      const p = dest(A.lat, A.lng, travel, gap * (i / (SAMPLES - 1)));
      gzs.push(await groundZ(p.lat, p.lng));
    }
    const gzAt = (t) => {
      const x = clamp(t, 0, 1) * (SAMPLES - 1), i = Math.min(SAMPLES - 2, Math.floor(x));
      return lerp(gzs[i], gzs[i + 1], x - i);
    };
    console.log(`transit: ${(gap / 1000).toFixed(1)} km gap, bearing ${Math.round(travel)}deg, apex +${Math.round(apex)} m`);

    camAt = (u) => {
      // The render loop hands out a NORMALISED 0..1 position, not a frame index.
      const f = Math.round(u * (FRAMES - 1));
      const t = f < holdA ? 0
        : f < holdA + flyFrames ? ease((f - holdA) / Math.max(1, flyFrames - 1))
        : 1;
      const bump = Math.sin(Math.PI * clamp(t, 0, 1));   // 0 at both ends, 1 at mid-flight
      const target = dest(A.lat, A.lng, travel, gap * t);
      const Rr = lerp(Ra, Rb, t) + apex * bump;
      const Hh = lerp(Ha, Hb, t) + apex * bump;          // R and H bump together -> tilt stays ~45deg
      const camBrg = lerpAngle(brgA, brgB, t);
      const p = dest(target.lat, target.lng, camBrg, Rr);
      return {
        position: { longitude: p.lng, latitude: p.lat, z: gzAt(t) + Hh },
        heading: (camBrg + 180) % 360,
        tilt: 90 - Math.atan2(Hh, Rr) * r2d
      };
    };

    const nameA = course.course?.name || 'Course A', nameB = courseB.course?.name || 'Course B';
    if (hudOn) {
      await page.evaluate((info) => window.setCourseInfo(info), { name: nameA, par: course.totals?.par, holes: course.totals?.holes, length: '' });
      onFrame = async (f) => {
        if (f === holdA + flyFrames) {
          await page.evaluate((info) => window.setCourseInfo(info), { name: nameB, par: courseB.totals?.par, holes: courseB.totals?.holes, length: '' });
        }
      };
    }
    segments = [
      { label: nameA, startSec: 0, endSec: holdA / FPS },
      { label: 'Transit', startSec: holdA / FPS, endSec: (holdA + flyFrames) / FPS },
      { label: nameB, startSec: (holdA + flyFrames) / FPS, endSec: FRAMES / FPS }
    ];
  } else if (mode === 'holes') {
    // Build one cinematic camera segment per hole:
    //   1) a slow pan/orbit around the fairway (reveals the hole shape)
    //   2) a glide-and-settle onto a tee-pad view, tilted down the fairway at the basket
    // Hard cuts between holes are intentional (this is a caddie-book tour, not a continuous flight).
    const holeCams = [];
    for (const h of course.holes || []) {
      if (holeFilter && h.number !== holeFilter) continue;
      if (fromHole && h.number < fromHole) continue;
      const tee = h.tees?.[0], bk = h.baskets?.[0];
      if (!tee || !bk) continue;
      const B = bearing(tee, bk);
      const D = Math.max(haversine(tee, bk), 20);
      const mid = { lat: (tee.lat + bk.lat) / 2, lng: (tee.lng + bk.lng) / 2 };

      const panRadius = Math.max(D * 0.75, 45);
      const panHeight = Math.max(D * 0.42, 42);
      const panTilt = 90 - Math.atan2(panHeight, panRadius) * r2d;
      const gzMid = await groundZ(mid.lat, mid.lng);

      const teeBack = dest(tee.lat, tee.lng, (B + 180) % 360, 55);
      const teeHeight = clamp(D * 0.16, 35, 90);
      const gzTee = await groundZ(teeBack.lat, teeBack.lng);
      const teeTilt = 74;

      // Pan sweeps toward the tee-side bearing so the hop into the settle shot is short.
      const panSweep = 85;
      const panEndBrg = B + 180;
      const panStartBrg = panEndBrg - panSweep;

      holeCams.push({
        hole: h.number, info: holeHudInfo(h),
        mid, gzMid, panRadius, panHeight, panTilt, panStartBrg, panEndBrg,
        teeBack, gzTee, teeHeight, teeTilt, teeHeading: B
      });
    }
    if (holeCams.length < 1) {
      throw new Error(holeFilter
        ? `hole ${holeFilter} not found (or missing tee/basket coords)`
        : 'not enough holes with tee+basket coords to build a path');
    }
    console.log(`built ${holeCams.length} hole camera segment(s)${holeFilter ? ` (hole ${holeFilter} only)` : fromHole ? ` (from hole ${fromHole})` : ''}`);

    let framesPerHole;
    if (args['frames-per-hole']) framesPerHole = parseInt(args['frames-per-hole'], 10);
    else if (args['seconds-per-hole']) framesPerHole = Math.round(parseFloat(args['seconds-per-hole']) * FPS);
    else if (args.frames) framesPerHole = Math.max(20, Math.round(parseInt(args.frames, 10) / holeCams.length));
    else framesPerHole = 10 * FPS; // default: 10s/hole
    FRAMES = framesPerHole * holeCams.length;

    const panPoseAt = (hc, brg) => {
      const p = dest(hc.mid.lat, hc.mid.lng, brg, hc.panRadius);
      return { position: { longitude: p.lng, latitude: p.lat, z: hc.gzMid + hc.panHeight }, heading: (brg + 180) % 360, tilt: hc.panTilt };
    };
    const teePoseOf = (hc) => ({
      position: { longitude: hc.teeBack.lng, latitude: hc.teeBack.lat, z: hc.gzTee + hc.teeHeight },
      heading: hc.teeHeading, tilt: hc.teeTilt
    });

    const PAN_FRACTION = 0.55;
    camAt = (u) => {
      const f = Math.round(u * (FRAMES - 1));
      const holeIdx = Math.min(holeCams.length - 1, Math.floor(f / framesPerHole));
      const hc = holeCams[holeIdx];
      const u2 = (f % framesPerHole) / Math.max(1, framesPerHole - 1);

      if (u2 < PAN_FRACTION) {
        const up = u2 / PAN_FRACTION;
        const brg = lerp(hc.panStartBrg, hc.panEndBrg, ease(up));
        return panPoseAt(hc, brg);
      }
      const us = (u2 - PAN_FRACTION) / (1 - PAN_FRACTION);
      const e = ease(us);
      const start = panPoseAt(hc, hc.panEndBrg);
      const end = teePoseOf(hc);
      return {
        position: {
          longitude: lerp(start.position.longitude, end.position.longitude, e),
          latitude: lerp(start.position.latitude, end.position.latitude, e),
          z: lerp(start.position.z, end.position.z, e)
        },
        heading: lerpAngle(start.heading, end.heading, e),
        tilt: lerp(start.tilt, end.tilt, e)
      };
    };

    if (hudOn) {
      onFrame = async (f) => {
        if (f % framesPerHole === 0) {
          const holeIdx = Math.min(holeCams.length - 1, Math.floor(f / framesPerHole));
          await page.evaluate((info) => window.setHoleInfo(info), holeCams[holeIdx].info);
        }
      };
    }

    // Segment manifest (for chapter markers / post-processing -- see scripts/stitch.mjs).
    segments = holeCams.map((hc, idx) => ({
      label: `Hole ${hc.hole}`,
      startSec: (idx * framesPerHole) / FPS,
      endSec: ((idx + 1) * framesPerHole) / FPS,
      ...hc.info
    }));
  } else {
    throw new Error('unknown --mode: ' + mode + ' (expected establish|holes|transit)');
  }

  console.log(`rendering ${FRAMES} frames (${mode}, overlays=${overlaysOn}, hud=${hudOn}) at ${W}x${H} -> ${FRAMES_DIR}`);
  const t0 = Date.now();
  for (let f = 0; f < FRAMES; f++) {
    const u = FRAMES === 1 ? 0 : f / (FRAMES - 1);
    if (onFrame) await onFrame(f);
    // Frame 0 needs a longer, stricter settle: it's the first tile fetch for this area,
    // with nothing cached yet, and a single not-updating read can catch a momentary
    // flicker before the full-res tile actually arrives (see setCamera's minStable).
    const settleMs = f === 0 ? Math.max(SETTLE_MS, 4500) : SETTLE_MS;
    const minStable = f === 0 ? 4 : 1;
    await page.evaluate(([c, ms, ns]) => window.setCamera(c, ms, ns), [camAt(u), settleMs, minStable]);
    await page.screenshot({ path: path.join(FRAMES_DIR, 'frame_' + String(f).padStart(4, '0') + '.png') });
    if (f % 15 === 0 || f === FRAMES - 1) console.log(`  frame ${f + 1}/${FRAMES}  (${((Date.now() - t0) / 1000).toFixed(1)}s elapsed)`);
  }
  await browser.close();

  console.log('encoding ->', OUT_FILE);
  execFileSync('ffmpeg', [
    '-y', '-framerate', String(FPS), '-i', path.join(FRAMES_DIR, 'frame_%04d.png'),
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'slow',
    '-movflags', '+faststart',
    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
    OUT_FILE
  ], { stdio: 'inherit' });

  if (!KEEP_FRAMES) rmSync(FRAMES_DIR, { recursive: true, force: true });

  const manifestPath = OUT_FILE.replace(/\.mp4$/i, '') + '.segments.json';
  writeFileSync(manifestPath, JSON.stringify({ fps: FPS, totalFrames: FRAMES, durationSeconds: FRAMES / FPS, segments }, null, 2));
  console.log('segments manifest ->', manifestPath);

  console.log(`done -> ${OUT_FILE}`);
}

main().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
