#!/usr/bin/env python3
"""
course_photos.py — pull your own photos of a disc golf course out of the Apple Photos library,
matched by GPS against the course's UDisc location and per-hole layout.

Subcommands
  scan   <slug|--lat LAT --lng LNG> [--radius M] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
         List geotagged library assets within RADIUS metres of the course, with the nearest hole.
  dates  <slug> --since YYYY-MM-DD --until YYYY-MM-DD
         List ALL assets in a date window (for iCloud-only assets whose location is not in the local DB).
  export <slug|--lat --lng> --out DIR [scan/dates filters] [--limit N] [--dry-run]
         Export matching originals through Photos.app (forces the iCloud download), convert HEIC to JPEG,
         read EXIF GPS off the export, assign a hole, rename, and write _index.json + _index.csv.
  sheet  <DIR> [--cols 6] [--size 230]
         Labelled contact sheet(s) of a folder of exported JPEGs.

Hole assignment: distance from the photo to the closest point on each hole's tee→basket segment
(first active UDisc layout with GPS). <= 60 m: "h<N>". <= 150 m: "near-h<N>". Else "course".

Reads the library read-only. The DB is snapshotted to a temp dir before querying.

Environment
  PHOTOS_LIBRARY     path to the .photoslibrary (default ~/Pictures/Photos Library.photoslibrary; or --library)
  CLAUDE_SKILLS_ROOT directory holding the sibling `udisc` skill (default: two levels above this script)
"""
import argparse, csv, datetime, glob, json, math, os, re, shutil, sqlite3, subprocess, sys, tempfile

LIB = os.path.expanduser(os.environ.get("PHOTOS_LIBRARY", "~/Pictures/Photos Library.photoslibrary"))
_SKILLS_ROOT = os.environ.get("CLAUDE_SKILLS_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UDISC_SCRIPTS = os.path.join(_SKILLS_ROOT, "udisc", "scripts")
EPOCH = datetime.datetime(2001, 1, 1)
FONT = next((f for f in ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
                         "/Library/Fonts/Arial.ttf"] if os.path.exists(f)), None)


# ── UDisc ─────────────────────────────────────────────────────────────────────

def _udisc():
    sys.path.insert(0, UDISC_SCRIPTS)
    import udisc  # noqa
    return udisc


def course_info(slug):
    u = _udisc()
    d = u.course_detail(slug)
    if "error" in d:
        raise SystemExit(f"UDisc: {d['error']}")
    holes = []
    try:
        for lay in u.course_layouts(slug):
            if lay.get("type") != "smart" and not lay.get("holes"):
                continue
            hs = []
            for h in lay.get("holes", []):
                t = h.get("teePosition") or h.get("tee") or {}
                b = h.get("targetPosition") or h.get("basket") or h.get("target") or {}
                tl = _latlng(t); bl = _latlng(b)
                if tl and bl:
                    hs.append({"n": h.get("holeNumber") or h.get("number") or h.get("name") or len(hs) + 1,
                               "tee": tl, "basket": bl, "par": h.get("par"), "dist": h.get("distance")})
            if len(hs) >= 3:
                holes = hs
                break
    except Exception as e:  # layouts are optional
        print(f"  (layouts unavailable: {e})", file=sys.stderr)
    return {"slug": slug, "name": d.get("name"), "lat": d.get("latitude"), "lng": d.get("longitude"),
            "holeCount": d.get("holeCount"), "year": d.get("yearEstablished"), "holes": holes}


def _latlng(o):
    if not isinstance(o, dict):
        return None
    if "latitude" in o and "longitude" in o:
        return (float(o["latitude"]), float(o["longitude"]))
    if "lat" in o and "lng" in o:
        return (float(o["lat"]), float(o["lng"]))
    c = o.get("coordinates")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        return (float(c[1]), float(c[0]))
    return None


# ── geometry ──────────────────────────────────────────────────────────────────

def _m(lat1, lng1, lat2, lng2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1; dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _seg_dist(p, a, b):
    """metres from point p to segment a-b, in a local flat projection"""
    k = 111320.0; kx = k * math.cos(math.radians(p[0]))
    px, py = (p[1] - a[1]) * kx, (p[0] - a[0]) * k
    bx, by = (b[1] - a[1]) * kx, (b[0] - a[0]) * k
    L2 = bx * bx + by * by
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / L2))
    return math.hypot(px - t * bx, py - t * by)


def nearest_hole(lat, lng, holes):
    if not holes:
        return ("course", None, None)
    best = min(((_seg_dist((lat, lng), h["tee"], h["basket"]), h["n"]) for h in holes), key=lambda x: x[0])
    d, n = best
    tag = f"h{n}" if d <= 60 else (f"near-h{n}" if d <= 150 else "course")
    return (tag, n, round(d))


# ── Photos library ────────────────────────────────────────────────────────────

def snapshot_db():
    tmp = tempfile.mkdtemp(prefix="photos-db-")
    for f in ("Photos.sqlite", "Photos.sqlite-wal", "Photos.sqlite-shm"):
        src = os.path.join(LIB, "database", f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(tmp, f))
    return sqlite3.connect(os.path.join(tmp, "Photos.sqlite"))


def _ts(sec):
    return EPOCH + datetime.timedelta(seconds=sec) if sec else None


def scan_assets(con, lat, lng, radius, since=None, until=None):
    dl = radius / 111320.0; dg = radius / (111320.0 * math.cos(math.radians(lat)))
    q = """select a.ZUUID, a.ZDATECREATED, e.ZLATITUDE, e.ZLONGITUDE, a.ZFILENAME
           from ZASSET a join ZEXTENDEDATTRIBUTES e on a.ZEXTENDEDATTRIBUTES = e.Z_PK
           where a.ZKIND = 0 and e.ZLATITUDE between ? and ? and e.ZLONGITUDE between ? and ?"""
    rows = con.execute(q, (lat - dl, lat + dl, lng - dg, lng + dg)).fetchall()
    out = []
    for uuid, dc, la, lo, fn in rows:
        t = _ts(dc)
        if since and t and t.date() < since: continue
        if until and t and t.date() > until: continue
        if _m(lat, lng, la, lo) > radius: continue
        out.append({"uuid": uuid, "taken": t.isoformat(timespec="minutes") if t else None, "lat": la, "lng": lo, "file": fn})
    return sorted(out, key=lambda r: r["taken"] or "")


def date_assets(con, since, until):
    q = "select ZUUID, ZDATECREATED, ZFILENAME from ZASSET where ZKIND = 0 and ZDATECREATED between ? and ? order by ZDATECREATED"
    a = (datetime.datetime.combine(since, datetime.time()) - EPOCH).total_seconds()
    b = (datetime.datetime.combine(until, datetime.time(23, 59, 59)) - EPOCH).total_seconds()
    return [{"uuid": u, "taken": _ts(dc).isoformat(timespec="minutes"), "lat": None, "lng": None, "file": fn}
            for u, dc, fn in con.execute(q, (a, b))]


# ── export ────────────────────────────────────────────────────────────────────

def photos_export(uuid, dest):
    """Export one original through Photos.app (downloads from iCloud if needed). Returns list of files."""
    before = set(os.listdir(dest))
    script = f'''
    tell application "Photos"
      set outFolder to POSIX file "{dest}" as alias
      with timeout of 240 seconds
        export {{media item id "{uuid}/L0/001"}} to outFolder with using originals
      end timeout
    end tell'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode:
        return []
    return [os.path.join(dest, f) for f in os.listdir(dest) if f not in before]


def exif_gps(path):
    r = subprocess.run(["exiftool", "-q", "-q", "-n", "-GPSLatitude", "-GPSLongitude", "-DateTimeOriginal", path],
                       capture_output=True, text=True).stdout
    la = re.search(r"GPS Latitude\s*:\s*([-\d.]+)", r); lo = re.search(r"GPS Longitude\s*:\s*([-\d.]+)", r)
    dt = re.search(r"Date/Time Original\s*:\s*(\S+ \S+)", r)
    return (float(la.group(1)) if la else None, float(lo.group(1)) if lo else None, dt.group(1) if dt else None)


def to_jpeg(path):
    base, ext = os.path.splitext(path)
    if ext.lower() in (".jpg", ".jpeg"):
        if ext != ".jpg":
            os.rename(path, base + ".jpg"); path = base + ".jpg"
        return path
    if ext.lower() in (".heic", ".heif", ".png", ".tif", ".tiff"):
        out = base + ".jpg"
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92", path, "--out", out], capture_output=True)
        if r.returncode == 0 and os.path.exists(out):
            os.remove(path); return out
    return path


def cmd_export(course, assets, out, limit=None, dry=False):
    os.makedirs(out, exist_ok=True)
    stage = os.path.join(out, "_stage"); os.makedirs(stage, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "-", (course["name"] or course["slug"]).lower()).strip("-")[:24]
    index = []
    for i, a in enumerate(assets[: limit or None]):
        if dry:
            print(a["uuid"][:8], a["taken"], a.get("hole")); continue
        files = photos_export(a["uuid"], stage)
        files = [f for f in files if not f.lower().endswith((".mov", ".mp4", ".aae"))]
        for f in [x for x in os.listdir(stage) if x.lower().endswith((".mov", ".mp4", ".aae"))]:
            os.remove(os.path.join(stage, f))
        if not files:
            print(f"  FAIL {a['uuid'][:8]}", file=sys.stderr); continue
        f = to_jpeg(files[0])
        la, lo, dt = exif_gps(f)
        lat, lng = (la, lo) if la is not None else (a.get("lat"), a.get("lng"))
        tag, n, dist = nearest_hole(lat, lng, course["holes"]) if lat is not None else ("unknown", None, None)
        t = a["taken"] or (dt or "").replace(":", "-", 2)
        stamp = re.sub(r"[^0-9]", "", t)[:12]  # YYYYMMDDHHMM
        stamp = f"{stamp[:8]}_{stamp[8:12]}" if len(stamp) >= 12 else stamp
        new = os.path.join(out, f"{key}_{stamp}_{tag}_{a['uuid'][:6]}.jpg")
        os.rename(f, new)
        rec = {"file": os.path.basename(new), "uuid": a["uuid"], "taken": t, "lat": lat, "lng": lng,
               "hole": n, "hole_tag": tag, "dist_m": dist, "original": a.get("file")}
        index.append(rec)
        print(f"  {rec['file']}  hole={tag} dist={dist}")
    if not dry:
        json.dump(index, open(os.path.join(out, "_index.json"), "w"), indent=1)
        with open(os.path.join(out, "_index.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["file", "taken", "hole_tag", "hole", "dist_m", "lat", "lng", "uuid", "original"])
            w.writeheader(); [w.writerow(r) for r in index]
        shutil.rmtree(stage, ignore_errors=True)
        print(f"exported {len(index)} → {out}")
    return index


def cmd_sheet(folder, cols=6, size=230):
    files = sorted(glob.glob(os.path.join(folder, "*.jpg")))
    if not files:
        raise SystemExit("no jpgs")
    tmp = tempfile.mkdtemp(prefix="sheet-"); thumbs = []
    for f in files:
        o = os.path.join(tmp, os.path.basename(f) + ".png")
        lab = os.path.basename(f).rsplit(".", 1)[0]
        cmd = ["magick", f, "-auto-orient", "-resize", f"{size}x{size-30}", "-gravity", "center", "-background", "black",
               "-extent", f"{size}x{size}"]
        if FONT:
            cmd += ["-font", FONT, "-fill", "white", "-pointsize", "11", "-gravity", "south", "-annotate", "+0+3", lab[-34:]]
        r = subprocess.run(cmd + [o], capture_output=True)
        if r.returncode == 0: thumbs.append(o)
    per = cols * 7; outs = []
    for s in range(0, len(thumbs), per):
        chunk = thumbs[s:s + per]; rows = []
        for r in range(0, len(chunk), cols):
            ro = os.path.join(tmp, f"row{s}_{r}.png")
            subprocess.run(["magick"] + chunk[r:r + cols] + ["+append", ro], check=True); rows.append(ro)
        o = os.path.join(folder, f"_sheet{s // per + 1}.png")
        subprocess.run(["magick"] + rows + ["-append", o], check=True); outs.append(o)
    print("\n".join(outs))


# ── main ──────────────────────────────────────────────────────────────────────

def _date(s):
    return datetime.date.fromisoformat(s) if s else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "dates", "export"):
        p = sub.add_parser(name)
        p.add_argument("slug", nargs="?")
        p.add_argument("--lat", type=float); p.add_argument("--lng", type=float); p.add_argument("--name")
        p.add_argument("--radius", type=float, default=400)
        p.add_argument("--since"); p.add_argument("--until")
        if name == "export":
            p.add_argument("--out", required=True); p.add_argument("--limit", type=int); p.add_argument("--dry-run", action="store_true")
            p.add_argument("--by-dates", action="store_true", help="use the date window instead of geotags")
        p.add_argument("--json", action="store_true")
        p.add_argument("--library", help="Photos library path (default $PHOTOS_LIBRARY or ~/Pictures/Photos Library.photoslibrary)")
    p = sub.add_parser("sheet"); p.add_argument("folder"); p.add_argument("--cols", type=int, default=6); p.add_argument("--size", type=int, default=230)
    a = ap.parse_args()
    if getattr(a, "library", None):
        global LIB
        LIB = os.path.expanduser(a.library)

    if a.cmd == "sheet":
        return cmd_sheet(a.folder, a.cols, a.size)

    if a.lat is not None and a.lng is not None:
        # explicit coordinates win; a bare positional is then just the folder/name key
        course = {"slug": None, "name": a.name or a.slug or f"{a.lat:.4f},{a.lng:.4f}", "lat": a.lat, "lng": a.lng, "holes": []}
    elif a.slug:
        course = course_info(a.slug)
    else:
        raise SystemExit("give a UDisc slug or --lat/--lng")
    print(f"course: {course['name']}  ({course['lat']:.5f}, {course['lng']:.5f})  holes with GPS: {len(course['holes'])}", file=sys.stderr)

    con = snapshot_db()
    since, until = _date(a.since), _date(a.until)
    if a.cmd == "dates" or (a.cmd == "export" and getattr(a, "by_dates", False)):
        if not (since and until):
            raise SystemExit("--since and --until required")
        assets = date_assets(con, since, until)
    else:
        assets = scan_assets(con, course["lat"], course["lng"], a.radius, since, until)
        for r in assets:
            r["hole_tag"], r["hole"], r["dist_m"] = nearest_hole(r["lat"], r["lng"], course["holes"])

    if a.cmd in ("scan", "dates"):
        if a.json:
            print(json.dumps(assets, indent=1))
        else:
            for r in assets:
                print(f"{r['uuid'][:8]}  {r['taken']}  {r.get('hole_tag','')}  {r.get('dist_m','')}  {r['file']}")
            print(f"{len(assets)} assets", file=sys.stderr)
        return
    cmd_export(course, assets, a.out, a.limit, a.dry_run)


if __name__ == "__main__":
    main()
