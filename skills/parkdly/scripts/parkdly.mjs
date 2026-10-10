#!/usr/bin/env node
// Parkdly caddie-book extractor.
// Fetches a Parkdly caddie book's React Router single-fetch (.data) payload,
// decodes the turbo-stream encoding, and emits structured course intelligence:
// holes (par/distance/tees/baskets/flight paths/tee-sign notes), layouts,
// amenities (restrooms/water/medical/info boards), OB & relief boundaries,
// background terrain, map bounds, publish/share URLs, and full metadata.
//
// Usage:
//   node parkdly.mjs <url|token|slug-url> [--format summary|json|amenities|csv|geojson|raw] [--out FILE]
//
// Input forms accepted:
//   https://parkdly.com/caddie-books/<uuid>
//   https://parkdly.com/caddie-books/<uuid>.data
//   https://parkdly.com/p/<destination>/<slug>            (published slug page, single course)
//   https://parkdly.com/p/<destination>                   (destination page, no slug — lists
//                                                            its caddie books instead of erroring;
//                                                            pass one of the listed URLs back in)
//   <uuid>                                                (bare caddie-book token)
//
// Auth (only needed for unpublished/private books): set PARKDLY_COOKIE env var to a
// full Cookie header copied from an authenticated browser session.
//
// Distance note: hole `distance` / `elevationChange` are stored in METERS regardless
// of the course `unitSystem`. This tool reports meters raw plus a display value
// converted to feet when unitSystem === "IMPERIAL".

import { decode } from "./turbo-stream.mjs";
import { writeFileSync } from "node:fs";

const M_TO_FT = 3.280839895;

// ---- Facility / point classification ---------------------------------------
// Curated human-facing labels. Anything not listed still passes through in the
// full JSON; this map only drives the "amenities" convenience view + labels.
const TYPE_LABELS = {
  "wc": "Restroom",
  "toilet": "Restroom",
  "restroom": "Restroom",
  "water-point": "Water",
  "water": "Water",
  "medical-services": "Medical",
  "first-aid": "First aid",
  "info-board-location": "Info board",
  "parking": "Parking",
  "trash": "Trash",
  "thrash-bin": "Trash bin",
  "post": "Pole",
  "custom-rectangle": "Rectangle",
  "custom-object": "Custom SVG",
  "practice-tee": "Practice tee",
  "practice-target": "Practice target",
  "bench": "Bench",
  "shelter": "Shelter",
  "food": "Food / concessions",
  "shop": "Pro shop",
  "tee-pad": "Tee pad",
  "next-tee": "Next-tee marker",
  "drop-zone": "Drop zone",
  "distance-marker": "Distance marker",
  "bridge": "Bridge",
  "stairs": "Stairs",
  "mando": "Mandatory",
  "text": "Text label",
  "tree": "Tree",
  "rock": "Rock",
  "bush": "Bush",
};
// Types treated as "facilities/amenities" (player services, not terrain/play geometry).
const FACILITY_TYPES = new Set([
  "wc", "toilet", "restroom", "water-point", "water", "medical-services",
  "first-aid", "info-board-location", "parking", "trash", "thrash-bin", "bench", "shelter",
  "food", "shop",
]);
// Terrain decoration we summarize by count rather than enumerate by default.
const TERRAIN_TYPES = new Set(["tree", "rock", "bush"]);

function label(type) {
  return TYPE_LABELS[type] || (type ? type.replace(/[-_]/g, " ") : "unknown");
}

// ---- Input → .data URL ------------------------------------------------------
function resolveDataUrl(input) {
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (UUID.test(input.trim())) {
    return { dataUrl: `https://parkdly.com/caddie-books/${input.trim()}.data`, token: input.trim() };
  }
  let u;
  try { u = new URL(input); } catch {
    throw new Error(`Not a URL or UUID token: ${input}`);
  }
  if (u.hostname && !/parkdly\.com$/.test(u.hostname)) {
    // allow other hosts but warn implicitly; keep going
  }
  let path = u.pathname.replace(/\/+$/, "");
  let token = null;
  const m = path.match(/\/caddie-books\/([0-9a-f-]{36})/i);
  if (m) token = m[1];
  if (!path.endsWith(".data")) path = path + ".data";
  return { dataUrl: `${u.protocol}//${u.host}${path}${u.search}`, token };
}

// ---- Fetch + decode ---------------------------------------------------------
async function fetchPayload(dataUrl) {
  const headers = { "Accept": "text/x-script, text/plain, */*" };
  if (process.env.PARKDLY_COOKIE) headers["Cookie"] = process.env.PARKDLY_COOKIE;
  const res = await fetch(dataUrl, { headers, redirect: "follow" });
  if (!res.ok) {
    throw new Error(`Fetch ${dataUrl} -> HTTP ${res.status}. ${res.status === 404
      ? "Book may be unpublished/private (set PARKDLY_COOKIE) or the token is wrong."
      : ""}`);
  }
  if (!res.body) throw new Error("Empty response body");
  const decoded = await decode(res.body);
  // Drain any deferred chunks; ignore their errors.
  try { await decoded.done; } catch { /* noop */ }
  return decoded.value;
}

// Find the route branch that carries a destination's caddie-book listing
// (e.g. /p/<destination> with no book slug — lists courses instead of one course).
function findDestinationData(value) {
  if (!value || typeof value !== "object") return null;
  for (const key of Object.keys(value)) {
    const node = value[key];
    const data = node && node.data;
    if (data && typeof data === "object" && Array.isArray(data.caddieBooks)) {
      return { routeId: key, data };
    }
  }
  return null;
}

function renderDestinationListing(data, format) {
  const pub = data.publicPage || {};
  const destSlug = pub.slug || "";
  const destName = pub.destination?.name || pub.title || destSlug || "(unnamed destination)";
  const books = (data.caddieBooks || []).map((b) => ({
    courseName: b.courseName || b.displayTitle,
    displayTitle: b.displayTitle,
    bookSlug: b.bookSlug,
    url: destSlug && b.bookSlug ? `https://parkdly.com/p/${destSlug}/${b.bookSlug}` : null,
  }));
  if (format === "json") {
    return JSON.stringify({ destination: { name: destName, slug: destSlug }, caddieBooks: books }, null, 2);
  }
  if (format === "csv") {
    return ["course,bookSlug,url", ...books.map((b) => `${b.courseName},${b.bookSlug},${b.url}`)].join("\n");
  }
  const lines = [
    `# ${destName} — Parkdly destination`,
    "",
    `This is a destination listing page, not a single caddie book. It has ${books.length} course(s).`,
    `Pass one of these URLs back into this tool (any --format) to get full course data:`,
    "",
  ];
  for (const b of books) lines.push(`- **${b.courseName}** — ${b.url || "(no public url — book slug missing)"}`);
  return lines.join("\n");
}

// Find the route branch that actually carries the course (works across route ids).
function findRouteData(value) {
  if (!value || typeof value !== "object") return null;
  for (const key of Object.keys(value)) {
    const node = value[key];
    const data = node && node.data;
    if (data && typeof data === "object" && data.course && typeof data.course === "object") {
      return { routeId: key, data };
    }
  }
  // Fallback: maybe the route value IS the data object.
  for (const key of Object.keys(value)) {
    const node = value[key];
    if (node && node.course) return { routeId: key, data: node };
  }
  return null;
}

// ---- Normalization ----------------------------------------------------------
function num(v) { return typeof v === "number" && isFinite(v) ? v : null; }

function distanceDisplay(meters, unitSystem) {
  if (meters == null) return null;
  if (unitSystem === "IMPERIAL") return { value: Math.round(meters * M_TO_FT), unit: "ft" };
  return { value: Math.round(meters), unit: "m" };
}

function normalize(value, source) {
  const found = findRouteData(value);
  if (!found) throw new Error("Could not locate course data in payload (schema may have changed).");
  const route = found.data;
  const c = route.course;
  const unitSystem = c.unitSystem || "METRIC";

  const holes = (c.holes || []).slice().sort((a, b) => (a.number || 0) - (b.number || 0)).map((h) => ({
    number: h.number,
    par: h.par,
    distanceMeters: num(h.distance),
    distance: distanceDisplay(num(h.distance), unitSystem),
    elevationChangeMeters: num(h.elevationChange),
    tees: (h.tees || []).map((t) => ({ lat: t.lat, lng: t.lng, rotation: t.rotation })),
    baskets: (h.targets || []).map((t) => ({ lat: t.lat, lng: t.lng, greenRadius: t.greenRadius })),
    flightPaths: (h.flightPaths || []).map((fp) => ({
      type: fp.type,
      points: (fp.controlPoints || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0))
        .map((p) => ({ lat: p.lat, lng: p.lng, size: p.size })),
      layouts: (fp.courseLayouts || []).map((l) => l.name),
    })),
    teeSigns: (h.teeSigns || []).map((s) => ({
      name: s.name, template: s.template, isPrimary: s.isPrimary,
      rotation: s.rotation,
      bounds: { topLeftLat: s.topLeftLat, topLeftLng: s.topLeftLng, bottomRightLat: s.bottomRightLat, bottomRightLng: s.bottomRightLng },
      noteHeader: s.noteHeader, noteText: s.noteText,
      qrCodeUrl: s.qrCodeUrl, hideQrCode: s.hideQrCode,
    })),
    mandos: h.mandos || [],
  }));

  // courseObjects: split into facilities (amenities) and terrain/other.
  const objTypeCounts = {};
  const amenities = [];
  const playElements = [];
  for (const o of (c.courseObjects || [])) {
    objTypeCounts[o.type] = (objTypeCounts[o.type] || 0) + 1;
    if (FACILITY_TYPES.has(o.type)) {
      amenities.push({ type: o.type, label: label(o.type), lat: o.lat, lng: o.lng, id: o.id, text: o.text || null });
    } else if (!TERRAIN_TYPES.has(o.type)) {
      playElements.push({ type: o.type, label: label(o.type), lat: o.lat, lng: o.lng, rotation: o.rotation, text: o.text || null, holeId: o.holeId || null });
    }
  }

  const boundaries = (c.boundaries || []).map((b) => ({
    type: b.type, label: label(b.type), isClosed: b.isClosed, restrictedSide: b.restrictedSide,
    points: (b.points || []).slice().sort((a, b2) => (a.order || 0) - (b2.order || 0)).map((p) => ({ lat: p.lat, lng: p.lng })),
  }));

  const backgroundFeatures = (c.backgroundFeatures || []).map((f) => ({
    type: f.type, properties: f.properties || null,
    points: (f.points || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0)).map((p) => ({ lat: p.lat, lng: p.lng })),
  }));

  const infoBoards = (c.infoBoards || []).map((b) => ({
    name: b.name, template: b.template, rotation: b.rotation,
    bounds: { topLeftLat: b.topLeftLat, topLeftLng: b.topLeftLng, bottomRightLat: b.bottomRightLat, bottomRightLng: b.bottomRightLng },
    infoHeader: b.infoHeader, infoText: b.infoText, qrCodeUrl: b.qrCodeUrl,
  }));

  const layouts = (c.courseLayouts || []).map((l) => ({
    name: l.name, order: l.order,
    holes: (l.holeCourseLayoutConfig || []).slice().sort((a, b) => (a.holeNumber || 0) - (b.holeNumber || 0)).map((hc) => ({
      number: hc.holeNumber, par: hc.par, distanceMeters: num(hc.distance),
      distance: distanceDisplay(num(hc.distance), unitSystem), included: hc.isIncluded,
    })),
  }));

  const cm = c.courseMap || {};
  const map = cm.id ? {
    center: { lat: cm.mapCenterLat, lng: cm.mapCenterLng }, zoom: cm.mapZoom, bearing: cm.mapBearing,
    bounds: { topLeftLat: cm.topLeftLat, topLeftLng: cm.topLeftLng, bottomRightLat: cm.bottomRightLat, bottomRightLng: cm.bottomRightLng },
    realWidthMeters: cm.realWidthMeters, realHeightMeters: cm.realHeightMeters,
  } : null;

  const shareLinks = (c.shareLinks || []).map((s) => ({
    type: s.type, token: s.token, revokedAt: s.revokedAt,
    url: `https://parkdly.com/caddie-books/${s.token}`,
  }));
  const publishedBooks = (route.publishedBooks || []).map((p) => ({
    name: p.name, token: p.token, url: `https://parkdly.com/caddie-books/${p.token}`,
  }));

  // Totals
  const includedHoles = holes.length;
  const totalPar = holes.reduce((s, h) => s + (h.par || 0), 0);
  const totalMeters = holes.reduce((s, h) => s + (h.distanceMeters || 0), 0);

  return {
    source,
    routeId: found.routeId,
    course: {
      id: c.id, name: c.name, description: c.description, unitSystem,
      destinationId: c.destinationId, themeId: c.themeId,
      locationLat: c.locationLat, locationLng: c.locationLng,
      mapPositionsConfirmed: c.mapPositionsConfirmed,
      createdAt: c.createdAt, updatedAt: c.updatedAt,
    },
    destination: route.destination ? {
      id: route.destination.id, name: route.destination.name,
      ownerSubscriptionTier: route.destination.ownerSubscriptionTier,
      imageCount: (route.destination.images || []).length,
    } : null,
    caddieBook: route.caddieBook || null,
    canonicalSlugUrl: route.canonicalSlugUrl || null,
    map,
    totals: {
      holes: includedHoles, par: totalPar,
      distanceMeters: Math.round(totalMeters),
      distanceDisplay: distanceDisplay(totalMeters, unitSystem),
    },
    holes,
    layouts,
    amenities,
    playElements,
    boundaries,
    backgroundFeatures,
    infoBoards,
    objectTypeCounts: objTypeCounts,
    shareLinks,
    publishedBooks,
  };
}

// ---- Output renderers -------------------------------------------------------
function renderSummary(d) {
  const L = [];
  const dd = (x) => x && x.distance ? `${x.distance.value} ${x.distance.unit}` : (x && x.distanceMeters != null ? `${x.distanceMeters} m` : "?");
  L.push(`# ${d.course.name || "Course"} — Parkdly caddie book`);
  if (d.destination?.name) L.push(`Destination: ${d.destination.name}  ·  Tier: ${d.destination.ownerSubscriptionTier || "?"}`);
  L.push("");
  L.push(`- Holes: ${d.totals.holes}   Par: ${d.totals.par}   Length: ${d.totals.distanceDisplay?.value ?? "?"} ${d.totals.distanceDisplay?.unit ?? ""}`);
  L.push(`- Units: ${d.course.unitSystem}   Course id: ${d.course.id}`);
  if (d.map?.center) L.push(`- Map center: ${d.map.center.lat?.toFixed(6)}, ${d.map.center.lng?.toFixed(6)}  (zoom ${d.map.zoom}, bearing ${d.map.bearing})`);
  if (d.canonicalSlugUrl) L.push(`- Public page: ${d.canonicalSlugUrl}`);
  L.push("");

  // Holes table
  L.push("## Holes");
  L.push("| # | Par | Length | Elev (m) | Tees | Baskets | Tee-sign note |");
  L.push("|---|-----|--------|----------|------|---------|---------------|");
  for (const h of d.holes) {
    const note = (h.teeSigns.find((s) => s.noteText)?.noteText || "").replace(/\s+/g, " ").slice(0, 60);
    L.push(`| ${h.number} | ${h.par ?? "?"} | ${dd(h)} | ${h.elevationChangeMeters ?? ""} | ${h.tees.length} | ${h.baskets.length} | ${note}${note.length === 60 ? "…" : ""} |`);
  }
  L.push("");

  // Amenities
  L.push("## Amenities / facilities");
  if (!d.amenities.length) L.push("_None placed._");
  else {
    const byType = {};
    for (const a of d.amenities) (byType[a.label] ||= []).push(a);
    for (const lab of Object.keys(byType).sort()) {
      L.push(`### ${lab} (${byType[lab].length})`);
      for (const a of byType[lab]) {
        L.push(`- ${a.lat?.toFixed(7)}, ${a.lng?.toFixed(7)}  ·  https://www.google.com/maps?q=${a.lat},${a.lng}`);
      }
    }
  }
  L.push("");

  // Boundaries
  if (d.boundaries.length) {
    L.push("## Boundaries");
    const bt = {};
    for (const b of d.boundaries) bt[b.label] = (bt[b.label] || 0) + 1;
    L.push(Object.entries(bt).map(([k, v]) => `${k}: ${v}`).join("  ·  "));
    L.push("");
  }

  // Layouts
  if (d.layouts.length) {
    L.push("## Layouts");
    for (const lay of d.layouts) {
      const par = lay.holes.reduce((s, h) => s + (h.par || 0), 0);
      const m = lay.holes.reduce((s, h) => s + (h.distanceMeters || 0), 0);
      L.push(`- **${lay.name}** — ${lay.holes.length} holes, par ${par}, ${distanceDisplay(m, d.course.unitSystem)?.value} ${distanceDisplay(m, d.course.unitSystem)?.unit}`);
    }
    L.push("");
  }

  // Object inventory
  L.push("## Map object inventory");
  L.push(Object.entries(d.objectTypeCounts).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${label(k)}: ${v}`).join("  ·  "));
  L.push("");

  // Publish / share
  if (d.publishedBooks.length || d.shareLinks.length) {
    L.push("## Links");
    for (const p of d.publishedBooks) L.push(`- Published: ${p.url}`);
    for (const s of d.shareLinks.filter((s) => !s.revokedAt)) L.push(`- Share (${s.type}): ${s.url}`);
  }
  return L.join("\n");
}

function renderAmenitiesCsv(d) {
  const rows = [["course", "type", "label", "lat", "lng", "google_maps", "id"]];
  for (const a of d.amenities) {
    rows.push([d.course.name, a.type, a.label, a.lat, a.lng, `https://www.google.com/maps?q=${a.lat},${a.lng}`, a.id]);
  }
  return rows.map((r) => r.map((x) => {
    const s = x == null ? "" : String(x);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
}

function renderGeoJson(d) {
  const features = [];
  const pt = (lng, lat, props) => (lat != null && lng != null) && features.push({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: props });
  const line = (pts, props) => pts.length >= 2 && features.push({ type: "Feature", geometry: { type: "LineString", coordinates: pts.map((p) => [p.lng, p.lat]) }, properties: props });
  const poly = (pts, props) => pts.length >= 3 && features.push({ type: "Feature", geometry: { type: "Polygon", coordinates: [[...pts, pts[0]].map((p) => [p.lng, p.lat])] }, properties: props });

  for (const h of d.holes) {
    h.tees.forEach((t, i) => pt(t.lng, t.lat, { kind: "tee", hole: h.number, par: h.par, index: i }));
    h.baskets.forEach((t, i) => pt(t.lng, t.lat, { kind: "basket", hole: h.number, par: h.par, index: i }));
    h.flightPaths.forEach((fp) => line(fp.points, { kind: "flight-path", hole: h.number, type: fp.type }));
  }
  for (const a of d.amenities) pt(a.lng, a.lat, { kind: "amenity", type: a.type, label: a.label });
  for (const p of d.playElements) pt(p.lng, p.lat, { kind: "play-element", type: p.type, label: p.label, hole: p.holeId });
  for (const b of d.boundaries) (b.isClosed ? poly : line)(b.points, { kind: "boundary", type: b.type, label: b.label });
  for (const f of d.backgroundFeatures) {
    const closed = ["forest", "paved_area", "building", "residential"].includes(f.type);
    (closed ? poly : line)(f.points, { kind: "background", type: f.type });
  }
  for (const ib of d.infoBoards) {
    const lat = (ib.bounds.topLeftLat + ib.bounds.bottomRightLat) / 2;
    const lng = (ib.bounds.topLeftLng + ib.bounds.bottomRightLng) / 2;
    pt(lng, lat, { kind: "info-board", name: ib.name });
  }
  return JSON.stringify({ type: "FeatureCollection", properties: { course: d.course.name }, features }, null, 2);
}

// ---- CLI --------------------------------------------------------------------
async function main() {
  const args = process.argv.slice(2);
  if (!args.length || args.includes("-h") || args.includes("--help")) {
    console.log("Usage: node parkdly.mjs <url|token|slug-url> [--format summary|json|amenities|csv|geojson|raw] [--out FILE]");
    process.exit(args.length ? 0 : 1);
  }
  let input = null, format = "summary", out = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--format" || a === "-f") format = args[++i];
    else if (a === "--out" || a === "-o") out = args[++i];
    else if (!input) input = a;
  }
  const { dataUrl, token } = resolveDataUrl(input);
  const value = await fetchPayload(dataUrl);
  const source = { input, dataUrl, token };

  let output;
  if (format === "raw") {
    output = JSON.stringify(value, null, 2);
  } else {
    let d;
    try {
      d = normalize(value, source);
    } catch (e) {
      const dest = findDestinationData(value);
      if (!dest) throw e;
      output = renderDestinationListing(dest.data, format);
    }
    if (d) {
      if (format === "json") output = JSON.stringify(d, null, 2);
      else if (format === "amenities") output = d.amenities.length
        ? d.amenities.map((a) => `${a.label}\t${a.lat}\t${a.lng}\thttps://www.google.com/maps?q=${a.lat},${a.lng}`).join("\n")
        : "(no amenities placed)";
      else if (format === "csv") output = renderAmenitiesCsv(d);
      else if (format === "geojson") output = renderGeoJson(d);
      else output = renderSummary(d);
    }
  }

  if (out) { writeFileSync(out, output); console.error(`Wrote ${out} (${output.length} bytes)`); }
  else console.log(output);
}

main().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
