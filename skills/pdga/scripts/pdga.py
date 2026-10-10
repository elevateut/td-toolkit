#!/usr/bin/env python3
"""PDGA Services API + DiscGolfScene client.

Authenticates with the PDGA Services API and provides commands for
querying events, players, and courses. Also exports registration data
from DiscGolfScene tournaments via admin cookie auth.

Usage:
    python3 pdga.py <command> [args]
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

# ---------- Config ----------

SERVICES_URL = "https://api.pdga.com/services/json"
MIN_REQUEST_INTERVAL = 0.35  # 300ms + buffer
MAX_PER_PAGE = 200
DEFAULT_STATE = os.environ.get("PDGA_STATE") or None  # e.g. "UT"; no built-in default

# Sibling skills this script shells out to (see cmd_flyover). Kept as separate
# skills on purpose: parkdly owns Parkdly data extraction, earth-flyover owns
# the headless video renderer. This script only orchestrates them.
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
PARKDLY_SCRIPT = SKILLS_DIR / "parkdly" / "scripts" / "parkdly.mjs"
FLYOVER_SCRIPT = SKILLS_DIR / "earth-flyover" / "scripts" / "render.mjs"

_session = None
_last_request_time = 0.0


def _find_credentials():
    """Find PDGA credentials.

    1. Env vars PDGA_USERNAME + PDGA_PASSWORD.
    2. A JSON config file named by the PDGA_CONFIG env var, holding either
       {"username": "...", "password": "..."} or
       {"PDGA": {"Services": {"Username": "...", "Password": "..."}}}.
    """
    username = os.environ.get("PDGA_USERNAME")
    password = os.environ.get("PDGA_PASSWORD")
    if username and password:
        return username, password

    config_env = os.environ.get("PDGA_CONFIG")
    if config_env:
        config_path = Path(config_env).expanduser()
        if not config_path.exists():
            _error(f"PDGA_CONFIG points to a missing file: {config_path}")
        with open(config_path) as f:
            cfg = json.load(f)
        if cfg.get("username") and cfg.get("password"):
            return cfg["username"], cfg["password"]
        svc = cfg.get("PDGA", {}).get("Services", {})
        if svc.get("Username") and svc.get("Password"):
            return svc["Username"], svc["Password"]
        _error(f"PDGA_CONFIG file {config_path} has no username/password")

    _error("No PDGA credentials found. Set PDGA_USERNAME and PDGA_PASSWORD env vars "
           "(or PDGA_CONFIG=/path/to/credentials.json).")


def _error(msg):
    json.dump({"error": msg}, sys.stderr)
    sys.stderr.write("\n")
    sys.exit(1)


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _authenticate():
    global _session
    if _session:
        return _session

    username, password = _find_credentials()
    data = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{SERVICES_URL}/user/login",
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
        method="POST",
    )
    _rate_limit()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _error(f"Auth failed: {e.code} {e.reason}")

    if not result.get("sessid"):
        _error(f"Auth failed: {json.dumps(result)}")

    _session = {
        "sessid": result["sessid"],
        "session_name": result["session_name"],
        "token": result["token"],
    }
    return _session


def _api_get(endpoint, params=None):
    """Make an authenticated GET request to the PDGA Services API."""
    session = _authenticate()
    if params:
        qs = urllib.parse.urlencode(params)
        url = f"{SERVICES_URL}/{endpoint}?{qs}"
    else:
        url = f"{SERVICES_URL}/{endpoint}"

    req = urllib.request.Request(
        url,
        headers={
            "Cookie": f"{session['session_name']}={session['sessid']}",
            "X-CSRF-Token": session["token"],
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
    )
    _rate_limit()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _error(f"API error: {e.code} {e.reason} on {endpoint}")


def _paginate(endpoint, params, collection_key, max_results=None):
    """Paginate through a PDGA API endpoint."""
    all_items = []
    offset = 0
    while True:
        p = {**params, "limit": MAX_PER_PAGE, "offset": offset}
        result = _api_get(endpoint, p)
        items = result.get(collection_key, [])
        if not items:
            break
        all_items.extend(items)
        if max_results and len(all_items) >= max_results:
            all_items = all_items[:max_results]
            break
        if len(items) < MAX_PER_PAGE:
            break
        offset += MAX_PER_PAGE
    return all_items


# ---------- Commands ----------

def cmd_events(args):
    """Search PDGA events."""
    params = {}
    if args.state:
        params["state"] = args.state
    if args.country:
        params["country"] = args.country
    if args.start_date:
        params["start_date"] = args.start_date
    if args.end_date:
        params["end_date"] = args.end_date
    if args.tier:
        params["tier"] = args.tier
    if args.status:
        params["status"] = args.status

    events = _paginate("event", params, "events", max_results=args.limit)

    if args.exclude_tiers:
        exclude = set(args.exclude_tiers.upper().split(","))
        events = [e for e in events if e.get("tier", "").upper() not in exclude]

    json.dump({"count": len(events), "events": events}, sys.stdout, indent=2)
    print()


def cmd_event_detail(args):
    """Get details for a specific event by tournament ID."""
    result = _api_get("event", {"tournament_id": args.tournament_id})
    events = result.get("events", [])
    if events:
        json.dump(events[0], sys.stdout, indent=2)
    else:
        json.dump({"error": f"Event {args.tournament_id} not found"}, sys.stdout)
    print()


def cmd_players(args):
    """Search PDGA players."""
    params = {}
    if args.first_name:
        params["first_name"] = args.first_name
    if args.last_name:
        params["last_name"] = args.last_name
    if args.pdga_number:
        params["pdga_number"] = args.pdga_number
    if args.state:
        params["state_prov"] = args.state
    if args.country:
        params["country"] = args.country
    if args.status:
        params["player_status"] = args.status

    players = _paginate("players", params, "players", max_results=args.limit)
    json.dump({"count": len(players), "players": players}, sys.stdout, indent=2)
    print()


def cmd_player_detail(args):
    """Get details for a specific player by PDGA number."""
    result = _api_get("players", {"pdga_number": args.pdga_number})
    players = result.get("players", [])
    if players:
        json.dump(players[0], sys.stdout, indent=2)
    else:
        json.dump({"error": f"Player #{args.pdga_number} not found"}, sys.stdout)
    print()


def cmd_event_count(args):
    """Count events by year for a state. Useful for growth tracking."""
    params = {}
    if args.state:
        params["state"] = args.state
    if args.country:
        params["country"] = args.country
    if not params:
        _error("event-count needs --state or --country (or set PDGA_STATE)")

    years = range(args.start_year, args.end_year + 1)
    counts = {}
    for year in years:
        p = {**params, "start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
        events = _paginate("event", p, "events")
        if args.exclude_tiers:
            exclude = set(args.exclude_tiers.upper().split(","))
            events = [e for e in events if e.get("tier", "").upper() not in exclude]
        counts[str(year)] = len(events)

    json.dump(counts, sys.stdout, indent=2)
    print()


def cmd_player_count(args):
    """Count total PDGA players for a state."""
    params = {}
    if args.state:
        params["state_prov"] = args.state
    if args.country:
        params["country"] = args.country
    if args.status:
        params["player_status"] = args.status

    players = _paginate("players", params, "players")
    json.dump({"state": args.state, "count": len(players)}, sys.stdout, indent=2)
    print()


def cmd_courses(args):
    """Search PDGA courses."""
    params = {}
    if args.state:
        params["state_prov"] = args.state
    if args.country:
        params["country"] = args.country
    if args.name:
        params["course_name"] = args.name

    courses = _paginate("course", params, "courses", max_results=args.limit)
    json.dump({"count": len(courses), "courses": courses}, sys.stdout, indent=2)
    print()


# ---------- DiscGolfScene ----------

DGS_BASE = "https://www.discgolfscene.com"
DGS_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Standard DGS division categorization
PRO_DIVISIONS = {"FPO", "MPO", "MP40", "MP50", "MP55", "MP60", "MP65", "MP70", "MP75",
                 "FP40", "FP50", "FP55", "FP60", "FP65", "FP70", "FP75"}


def _dgs_cookies():
    """Read DGS session cookies from env vars."""
    auth = os.environ.get("DGS_COOKIE_AUTH", "")
    cr = os.environ.get("DGS_COOKIE_CR", "")
    cm = os.environ.get("DGS_COOKIE_CM", "")
    if not all([auth, cr, cm]):
        _error("DGS cookies not set. Set DGS_COOKIE_AUTH, DGS_COOKIE_CR, DGS_COOKIE_CM in .env")
    return f"auth={auth}; c_r={cr}; c_m={cm}; desktop=1"


def _dgs_export_csv(event_slug):
    """Download registration CSV from DGS admin panel."""
    url = f"{DGS_BASE}/tournaments/{event_slug}/admin/registration-export"
    data = urllib.parse.urlencode({"privacy_agree": "1"}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Cookie": _dgs_cookies(),
            "User-Agent": DGS_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        _error(f"DGS export failed: {e.code} {e.reason}")

    if body.lstrip().startswith("<!DOCTYPE") or body.lstrip().startswith("<html"):
        _error("DGS returned HTML — session cookies expired. Re-authenticate and update .env")

    first_line = body.split("\n", 1)[0]
    if not first_line.startswith("Division"):
        _error(f"Unexpected CSV format. First line: {first_line[:120]}")

    return body


def _parse_dgs_csv(raw_csv):
    """Parse a DGS registration CSV into structured data."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = [r for r in reader if r.get("Division", "").strip() != "Totals"]

    confirmed = [r for r in rows if not r.get("Waitlist", "").strip()]
    waitlisted = [r for r in rows if r.get("Waitlist", "").strip()]

    # Division breakdown (confirmed only)
    divisions = {}
    for r in confirmed:
        div = r.get("Division", "").strip()
        if not div:
            continue
        if div not in divisions:
            divisions[div] = {"count": 0, "entry_fees": 0.0, "is_pro": div.upper() in PRO_DIVISIONS}
        divisions[div]["count"] += 1
        fee_str = r.get("Entry fee $", "0").strip().replace(",", "")
        try:
            divisions[div]["entry_fees"] += float(fee_str)
        except ValueError:
            pass

    pro_count = sum(d["count"] for d in divisions.values() if d["is_pro"])
    am_count = sum(d["count"] for d in divisions.values() if not d["is_pro"])
    pro_fees = sum(d["entry_fees"] for d in divisions.values() if d["is_pro"])
    am_fees = sum(d["entry_fees"] for d in divisions.values() if not d["is_pro"])

    # Add-ons (all rows — waitlisted players may have purchased add-ons)
    addon_columns = _detect_addon_columns(rows)
    addons = {}
    for col_name, dollar_col in addon_columns.items():
        count = 0
        total = 0.0
        for r in rows:
            val_str = r.get(dollar_col, "0").strip().replace(",", "")
            try:
                val = float(val_str)
            except ValueError:
                val = 0.0
            # != 0, not > 0: a DGS add-on can be a DISCOUNT carrying a negative
            # amount (e.g. a -$25 side-event entry). Filtering on > 0 reports it
            # as {count: 0, total: 0.0} and silently overstates add-on revenue.
            if val != 0:
                count += 1
                total += val
        addons[col_name] = {"count": count, "total": round(total, 2)}

    addon_revenue = sum(a["total"] for a in addons.values())

    return {
        "total_rows": len(rows),
        "confirmed": len(confirmed),
        "waitlisted": len(waitlisted),
        "pro_count": pro_count,
        "am_count": am_count,
        "pro_entry_fees": round(pro_fees, 2),
        "am_entry_fees": round(am_fees, 2),
        "total_entry_fees": round(pro_fees + am_fees, 2),
        "addon_revenue": round(addon_revenue, 2),
        "addons": addons,
        "divisions": {k: {"count": v["count"], "entry_fees": round(v["entry_fees"], 2),
                          "is_pro": v["is_pro"]} for k, v in sorted(divisions.items())},
        "waitlisted_players": [
            {"name": r.get("Name", "").strip(), "division": r.get("Division", "").strip()}
            for r in waitlisted
        ],
    }


def _detect_addon_columns(rows):
    """Auto-detect add-on columns by finding columns ending in ' $' that aren't 'Entry fee $'."""
    if not rows:
        return {}
    addons = {}
    for key in rows[0].keys():
        stripped = key.strip()
        if stripped.endswith("$") and stripped != "Entry fee $":
            label = stripped.rstrip("$").strip()
            addons[label] = key
    return addons


def cmd_dgs_registrations(args):
    """Export and parse registrations from a DiscGolfScene tournament."""
    slug = args.event_slug or os.environ.get("DGS_EVENT_SLUG", "")
    if not slug:
        _error("No event slug. Pass --event-slug or set DGS_EVENT_SLUG in .env")

    # Auto-download or read from file
    if args.file:
        with open(args.file) as f:
            raw_csv = f.read()
    else:
        raw_csv = _dgs_export_csv(slug)

    if args.raw:
        sys.stdout.write(raw_csv)
        return

    if args.output:
        Path(args.output).write_text(raw_csv)
        sys.stderr.write(f"CSV saved to {args.output}\n")

    parsed = _parse_dgs_csv(raw_csv)
    parsed["event_slug"] = slug
    parsed["source"] = args.file or f"dgs-export-{slug}"

    json.dump(parsed, sys.stdout, indent=2)
    print()


def cmd_dgs_event_info(args):
    """Scrape basic event info from a DGS tournament page."""
    slug = args.event_slug or os.environ.get("DGS_EVENT_SLUG", "")
    if not slug:
        _error("No event slug. Pass --event-slug or set DGS_EVENT_SLUG in .env")

    url = f"{DGS_BASE}/tournaments/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": DGS_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode()
    except urllib.error.HTTPError as e:
        _error(f"Failed to fetch event page: {e.code} {e.reason}")

    # Extract basic info from page
    import re
    info = {"slug": slug, "url": url}

    title_match = re.search(r"<title>([^<]+)</title>", html)
    if title_match:
        info["title"] = title_match.group(1).strip().split(" - ")[0].strip()

    # Look for player count in the registration section
    reg_count = re.search(r'(\d+)\s+(?:player|registrant)s?\s+registered', html, re.I)
    if reg_count:
        info["registered_count"] = int(reg_count.group(1))

    json.dump(info, sys.stdout, indent=2)
    print()


def _run_node(script, node_args):
    """Run a sibling skill's Node script and return stdout. Raises on failure."""
    if not script.exists():
        _error(f"Missing script: {script}. Is the '{script.parent.parent.name}' skill installed?")
    proc = subprocess.run(
        ["node", str(script), *node_args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        _error(f"{script.name} {' '.join(node_args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout


def _slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "course").lower()).strip("-") or "course"


def cmd_flyover(args):
    """Render caddie-book flyover video(s) for a Parkdly destination or course URL.

    Chains two sibling skills: `parkdly` (fetches course coordinates/geometry)
    and `earth-flyover` (renders the headless ArcGIS SceneView video). This
    command only orchestrates them -- it owns no Parkdly parsing or rendering
    logic itself.
    """
    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd() / "flyovers"
    out_dir.mkdir(parents=True, exist_ok=True)

    stdout = _run_node(PARKDLY_SCRIPT, [args.destination, "--format", "json"])
    data = json.loads(stdout)

    course_jsons = []  # list of (name, data)
    if "caddieBooks" in data:
        dest_name = data.get("destination", {}).get("name", args.destination)
        for b in data["caddieBooks"]:
            if not b.get("url"):
                continue
            name = b.get("courseName") or b.get("displayTitle") or b["bookSlug"]
            if args.course and args.course.lower() not in name.lower():
                continue
            book_stdout = _run_node(PARKDLY_SCRIPT, [b["url"], "--format", "json"])
            course_jsons.append((name, json.loads(book_stdout)))
    else:
        dest_name = data.get("course", {}).get("name", "course")
        course_jsons.append((dest_name, data))

    if not course_jsons:
        _error(f"No matching courses found" + (f" for --course '{args.course}'" if args.course else ""))

    manifest = []
    for name, cdata in course_jsons:
        slug = _slugify(name)
        course_file = out_dir / f"{slug}.json"
        course_file.write_text(json.dumps(cdata))

        aspect_tag = "-9x16" if args.aspect == "9:16" else ""
        hole_tag = f"-hole{args.hole}" if args.hole else ""
        out_file = out_dir / f"{slug}-{args.mode}{hole_tag}{aspect_tag}.mp4"

        render_args = [
            str(course_file),
            "--mode", args.mode,
            "--overlays", args.overlays,
            "--hud", args.hud,
            "--aspect", args.aspect,
            "--out", str(out_file),
        ]
        if args.hole:
            render_args += ["--hole", str(args.hole)]
        if args.seconds_per_hole:
            render_args += ["--seconds-per-hole", str(args.seconds_per_hole)]
        if args.frames_per_hole:
            render_args += ["--frames-per-hole", str(args.frames_per_hole)]
        if args.frames:
            render_args += ["--frames", str(args.frames)]
        if args.width:
            render_args += ["--width", str(args.width)]
        if args.height:
            render_args += ["--height", str(args.height)]
        if args.settle_ms:
            render_args += ["--settle-ms", str(args.settle_ms)]

        sys.stderr.write(f"Rendering {name} ({args.mode}, {args.aspect}"
                          + (f", hole {args.hole}" if args.hole else "") + ")...\n")
        _run_node(FLYOVER_SCRIPT, render_args)
        manifest.append({"course": name, "mode": args.mode, "aspect": args.aspect, "hole": args.hole, "file": str(out_file)})

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"destination": dest_name, "courses": manifest}, indent=2))

    json.dump({"outDir": str(out_dir), "manifest": str(manifest_path), "courses": manifest}, sys.stdout, indent=2)
    print()


# ---------- Course Layouts (PDGA Live / Parkdly) ----------

LIVE_API = "https://www.pdga.com/apps/tournament/live-api"


def _live_get(endpoint, params):
    """GET a PDGA Live API endpoint (public, no auth). Returns the 'data' object."""
    qs = urllib.parse.urlencode(params)
    url = f"{LIVE_API}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": DGS_USER_AGENT})
    _rate_limit()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _error(f"PDGA Live API error: {e.code} {e.reason} on {endpoint}")
    return payload.get("data") or {}


def _to_feet(value, units):
    if value is None:
        return None
    if (units or "").lower().startswith("meter"):
        return round(value * 3.28084)
    return round(value)


def _normalize_live_layout(event_name, layout, division, rnd):
    """Normalize one PDGA Live layout object into the common layout schema."""
    units = layout.get("Units") or "Feet"
    holes = []
    for h in layout.get("Detail") or []:
        holes.append({
            "seq": h.get("HoleOrdinal") or h.get("Ordinal"),
            "label": str(h.get("Label") or h.get("Hole") or ""),
            "par": h.get("Par"),
            "distance_ft": _to_feet(h.get("Length"), units),
            "notes": None,
        })
    return {
        "source": "pdga-live",
        "event": event_name,
        "course": (layout.get("CourseName") or "").strip(),
        "layout": (layout.get("Name") or "").strip(),
        "layout_id": layout.get("LayoutID"),
        "notes": (layout.get("Notes") or "").strip() or None,
        "used_by": [{"division": division, "round": rnd}],
        "holes": holes,
        "totals": {
            "holes": layout.get("Holes"),
            "par": layout.get("Par"),
            "distance_ft": _to_feet(layout.get("Length"), units),
        },
    }


def _live_layouts(tourn_id, division=None, rnd=None):
    """Pull unique layouts from PDGA Live for an event, deduped by LayoutID."""
    event = _live_get("live_results_fetch_event", {"TournID": tourn_id})
    if not event.get("Divisions"):
        _error(f"No PDGA Live data for TournID {tourn_id} — event may not use PDGA live scoring")
    event_name = event.get("SimpleName") or event.get("Name") or f"PDGA #{tourn_id}"

    divisions = event["Divisions"]
    if division:
        divisions = [d for d in divisions if d.get("Division", "").upper() == division.upper()]
        if not divisions:
            _error(f"Division {division} not found. Available: "
                   + ", ".join(d.get("Division", "?") for d in event["Divisions"]))

    by_id = {}
    for div in divisions:
        div_code = div.get("Division")
        rounds = [rnd] if rnd else range(1, (div.get("LatestRound") or event.get("Rounds") or 1) + 1)
        for r in rounds:
            data = _live_get("live_results_fetch_round",
                             {"TournID": tourn_id, "Division": div_code, "Round": r})
            for layout in data.get("layouts") or []:
                lid = layout.get("LayoutID")
                if lid in by_id:
                    used = by_id[lid]["used_by"]
                    if not any(u["division"] == div_code and u["round"] == r for u in used):
                        used.append({"division": div_code, "round": r})
                else:
                    by_id[lid] = _normalize_live_layout(event_name, layout, div_code, r)

    if not by_id:
        _error(f"No layouts found in PDGA Live for TournID {tourn_id}")
    return list(by_id.values())


def _parkdly_hole_notes(hole):
    """Pull the tee-sign note text for a Parkdly hole (primary sign preferred)."""
    signs = hole.get("teeSigns") or []
    signs = sorted(signs, key=lambda s: not s.get("isPrimary"))
    for s in signs:
        text = (s.get("noteText") or "").strip()
        if text:
            header = (s.get("noteHeader") or "").strip()
            return f"{header}: {text}" if header else text
    return None


def _parkdly_dist_ft(obj):
    """Distance in feet from a Parkdly hole/layout-hole object."""
    d = obj.get("distance") or {}
    if d.get("unit") == "ft" and d.get("value") is not None:
        return round(d["value"])
    return _to_feet(obj.get("distanceMeters"), "meters")


def _normalize_parkdly_layouts(course_data, event_name, layout_filter=None, include_base=False):
    """Normalize a Parkdly course JSON into common layout schema objects.

    Emits one object per named layout (FPO, B Pool, ...). The base course
    layout is emitted only when there are no named layouts, or when
    include_base is set.
    """
    course_name = (course_data.get("course") or {}).get("name", "course")
    base_holes = course_data.get("holes") or []
    notes_by_number = {h.get("number"): _parkdly_hole_notes(h) for h in base_holes}

    results = []
    named = course_data.get("layouts") or []
    if layout_filter:
        named = [l for l in named if layout_filter.lower() in (l.get("name") or "").lower()]

    for lay in named:
        holes = []
        for lh in lay.get("holes") or []:
            if not lh.get("included"):
                continue
            holes.append({
                "seq": len(holes) + 1,
                "label": str(lh.get("number")),
                "par": lh.get("par"),
                "distance_ft": _parkdly_dist_ft(lh),
                "notes": notes_by_number.get(lh.get("number")),
            })
        results.append({
            "source": "parkdly",
            "event": event_name,
            "course": course_name,
            "layout": lay.get("name"),
            "layout_id": None,
            "notes": None,
            "used_by": [],
            "holes": holes,
            "totals": {
                "holes": len(holes),
                "par": sum(h["par"] or 0 for h in holes),
                "distance_ft": sum(h["distance_ft"] or 0 for h in holes),
            },
        })

    if include_base or not results:
        totals = course_data.get("totals") or {}
        dist_disp = totals.get("distanceDisplay") or {}
        holes = [{
            "seq": i + 1,
            "label": str(h.get("number")),
            "par": h.get("par"),
            "distance_ft": _parkdly_dist_ft(h),
            "notes": notes_by_number.get(h.get("number")),
        } for i, h in enumerate(base_holes)]
        results.insert(0, {
            "source": "parkdly",
            "event": event_name,
            "course": course_name,
            "layout": "Base",
            "layout_id": None,
            "notes": None,
            "used_by": [],
            "holes": holes,
            "totals": {
                "holes": totals.get("holes", len(holes)),
                "par": totals.get("par", sum(h["par"] or 0 for h in holes)),
                "distance_ft": dist_disp.get("value") if dist_disp.get("unit") == "ft"
                               else _to_feet(totals.get("distanceMeters"), "meters"),
            },
        })
    return results


def cmd_layout(args):
    """Pull normalized course layout(s) from PDGA Live or Parkdly.

    Input is either a PDGA TournID (numeric -> PDGA Live API) or a Parkdly
    URL/token (-> parkdly sibling skill). Output is a common schema consumed
    by build-scorecards.py.
    """
    src = args.input.strip()
    if re.fullmatch(r"\d+", src):
        layouts = _live_layouts(src, division=args.division, rnd=args.round)
    else:
        stdout = _run_node(PARKDLY_SCRIPT, [src, "--format", "json"])
        data = json.loads(stdout)
        layouts = []
        if "caddieBooks" in data:
            event_name = data.get("destination", {}).get("name", src)
            for b in data["caddieBooks"]:
                if not b.get("url"):
                    continue
                name = b.get("courseName") or b.get("displayTitle") or b["bookSlug"]
                if args.course and args.course.lower() not in name.lower():
                    continue
                book = json.loads(_run_node(PARKDLY_SCRIPT, [b["url"], "--format", "json"]))
                layouts.extend(_normalize_parkdly_layouts(
                    book, event_name, layout_filter=args.layout, include_base=args.base))
        else:
            event_name = data.get("destination", {}).get("name") or \
                         data.get("course", {}).get("name", src)
            layouts = _normalize_parkdly_layouts(
                data, event_name, layout_filter=args.layout, include_base=args.base)

    if not layouts:
        _error("No layouts matched"
               + (f" --course '{args.course}'" if args.course else "")
               + (f" --layout '{args.layout}'" if args.layout else ""))

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = []
        for lay in layouts:
            fname = f"layout-{_slugify(lay['course'])}-{_slugify(lay['layout'])}.json"
            (out_dir / fname).write_text(json.dumps(lay, indent=2))
            manifest.append({"course": lay["course"], "layout": lay["layout"],
                             "holes": lay["totals"]["holes"], "par": lay["totals"]["par"],
                             "distance_ft": lay["totals"]["distance_ft"],
                             "file": str(out_dir / fname)})
        json.dump({"count": len(manifest), "layouts": manifest}, sys.stdout, indent=2)
    else:
        json.dump(layouts if len(layouts) > 1 else layouts[0], sys.stdout, indent=2)
    print()


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="PDGA Services API client")
    sub = parser.add_subparsers(dest="command", required=True)

    # events
    p = sub.add_parser("events", help="Search PDGA events")
    p.add_argument("--state", default=DEFAULT_STATE, help="State/province code (default: PDGA_STATE env var)")
    p.add_argument("--country", default=None)
    p.add_argument("--start-date", dest="start_date")
    p.add_argument("--end-date", dest="end_date")
    p.add_argument("--tier")
    p.add_argument("--status", default="sanctioned")
    p.add_argument("--exclude-tiers", dest="exclude_tiers", help="Comma-separated tiers to exclude, e.g. 'L,XL'")
    p.add_argument("--limit", type=int, default=500)
    p.set_defaults(func=cmd_events)

    # event-detail
    p = sub.add_parser("event-detail", help="Get event details by tournament ID")
    p.add_argument("tournament_id")
    p.set_defaults(func=cmd_event_detail)

    # players
    p = sub.add_parser("players", help="Search PDGA players")
    p.add_argument("--first-name", dest="first_name")
    p.add_argument("--last-name", dest="last_name")
    p.add_argument("--pdga-number", dest="pdga_number")
    p.add_argument("--state", default=None)
    p.add_argument("--country", default="US")
    p.add_argument("--status", default=None, help="current, expired, etc.")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_players)

    # player-detail
    p = sub.add_parser("player-detail", help="Get player by PDGA number")
    p.add_argument("pdga_number")
    p.set_defaults(func=cmd_player_detail)

    # event-count
    p = sub.add_parser("event-count", help="Count events by year for growth tracking")
    p.add_argument("--state", default=DEFAULT_STATE, help="State/province code (default: PDGA_STATE env var)")
    p.add_argument("--country", default=None)
    p.add_argument("--start-year", dest="start_year", type=int, default=2020)
    p.add_argument("--end-year", dest="end_year", type=int, default=2026)
    p.add_argument("--exclude-tiers", dest="exclude_tiers", default="L,XL", help="Exclude league tiers (default: L,XL)")
    p.set_defaults(func=cmd_event_count)

    # player-count
    p = sub.add_parser("player-count", help="Count PDGA players for a state")
    p.add_argument("--state", default=DEFAULT_STATE, help="State/province code (default: PDGA_STATE env var)")
    p.add_argument("--country", default="US")
    p.add_argument("--status", default=None)
    p.set_defaults(func=cmd_player_count)

    # courses
    p = sub.add_parser("courses", help="Search PDGA courses")
    p.add_argument("--state", default=DEFAULT_STATE, help="State/province code (default: PDGA_STATE env var)")
    p.add_argument("--country", default="US")
    p.add_argument("--name")
    p.add_argument("--limit", type=int, default=500)
    p.set_defaults(func=cmd_courses)

    # dgs-registrations
    p = sub.add_parser("dgs-registrations", help="Export registrations from a DiscGolfScene tournament")
    p.add_argument("--event-slug", dest="event_slug", default=None, help="DGS event slug (default: DGS_EVENT_SLUG env var)")
    p.add_argument("--file", default=None, help="Parse a local CSV file instead of downloading")
    p.add_argument("--raw", action="store_true", help="Output raw CSV instead of parsed JSON")
    p.add_argument("--output", "-o", default=None, help="Save downloaded CSV to this path")
    p.set_defaults(func=cmd_dgs_registrations)

    # dgs-event-info
    p = sub.add_parser("dgs-event-info", help="Get basic info from a DGS tournament page")
    p.add_argument("--event-slug", dest="event_slug", default=None, help="DGS event slug (default: DGS_EVENT_SLUG env var)")
    p.set_defaults(func=cmd_dgs_event_info)

    # flyover
    p = sub.add_parser("flyover", help="Render caddie-book flyover video(s) via the parkdly + earth-flyover skills")
    p.add_argument("destination", help="Parkdly destination URL (lists multiple courses) or a single caddie-book URL")
    p.add_argument("--course", default=None, help="Only render courses whose name contains this (case-insensitive substring)")
    p.add_argument("--mode", choices=["establish", "holes"], default="holes")
    p.add_argument("--overlays", choices=["on", "off"], default="on")
    p.add_argument("--hud", choices=["on", "off"], default="on")
    p.add_argument("--aspect", choices=["16:9", "9:16"], default="16:9")
    p.add_argument("--hole", type=int, default=None, help="Render only this hole number instead of the whole course")
    p.add_argument("--seconds-per-hole", dest="seconds_per_hole", type=float, default=None, help="Seconds of video per hole in holes mode (default: 10)")
    p.add_argument("--frames-per-hole", dest="frames_per_hole", type=int, default=None, help="Exact frames per hole (overrides --seconds-per-hole)")
    p.add_argument("--frames", type=int, default=None)
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--settle-ms", dest="settle_ms", type=int, default=None)
    p.add_argument("--out-dir", dest="out_dir", default=None, help="Output directory (default: ./flyovers)")
    p.set_defaults(func=cmd_flyover)

    # layout
    p = sub.add_parser("layout", help="Pull normalized course layout(s) from PDGA Live (TournID) or Parkdly (URL)")
    p.add_argument("input", help="PDGA TournID (numeric) or Parkdly destination/caddie-book URL")
    p.add_argument("--division", default=None, help="PDGA Live only: single division code (e.g. MPO). Default: all divisions, deduped by layout")
    p.add_argument("--round", type=int, default=None, help="PDGA Live only: single round number. Default: all rounds")
    p.add_argument("--course", default=None, help="Parkdly destination only: filter courses by name substring")
    p.add_argument("--layout", default=None, help="Parkdly only: filter named layouts by substring (e.g. 'FPO', 'B Pool')")
    p.add_argument("--base", action="store_true", help="Parkdly only: also emit the base course layout alongside named layouts")
    p.add_argument("--out-dir", dest="out_dir", default=None, help="Write one layout-<course>-<layout>.json per layout instead of stdout")
    p.set_defaults(func=cmd_layout)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
