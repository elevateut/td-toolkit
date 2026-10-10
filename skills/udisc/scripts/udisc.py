#!/usr/bin/env python3
"""
UDisc data client -- fetches and decodes UDisc Remix Single Fetch endpoints.

UDisc uses Remix's TurboStream format (compressed JSON with a lookup table
and patch instructions). This script handles decoding transparently.

Usage:
    python3 udisc.py course-detail <slug>
    python3 udisc.py course-reviews <slug> [--limit N]
    python3 udisc.py nearby-courses <lat> <lng> [--radius M] [--limit N]
    python3 udisc.py nearby-stores <lat> <lng> [--radius M] [--limit N]
    python3 udisc.py layouts <slug> [--layout NAME] [--format json|parkdly]
    python3 udisc.py search <query>                   # searches by course name
    python3 udisc.py course-url <udisc-url>           # detail from full URL

All output is JSON to stdout. Errors go to stderr with non-zero exit.
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ── TurboStream decoder ─────────────────────────────────────────────────────

_PATCH_RE = re.compile(r"^P(\d+):")
_KEY_RE = re.compile(r"^_(\d+)$")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _parse_segments(text: str):
    segments, cur = [], None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _PATCH_RE.match(line)
        if m:
            if cur is None:
                continue
            pid = int(m.group(1))
            payload = json.loads(line[m.end() :])
            cur["patches"].append((pid, payload))
            continue
        cur = {"base": json.loads(line), "patches": []}
        segments.append(cur)
    return segments


def _decode_segment(seg):
    table = list(seg["base"])
    patches_by_id = {}
    for pid, payload in seg["patches"]:
        if len(payload) < 2:
            continue
        starts = [x for x in payload[0] if isinstance(x, int) and x >= 0]
        if not starts:
            continue
        patches_by_id[pid] = starts
        vals = payload[1:]
        vc = 0
        for i, st in enumerate(starts):
            slen = (starts[i + 1] - st) if i < len(starts) - 1 else (len(vals) - vc)
            while len(table) < st + max(slen, 0):
                table.append(None)
            for off in range(max(slen, 0)):
                if vc < len(vals):
                    table[st + off] = vals[vc]
                    vc += 1
    memo, ip = {}, set()
    return _resolve(table, patches_by_id, 0, memo, ip)


def _resolve(table, patches, idx, memo, ip):
    if idx < 0:
        return None
    if idx in memo:
        return _cp(memo[idx])
    if idx in ip:
        return None
    ip.add(idx)
    node = table[idx] if idx < len(table) else None
    d = _inline(table, patches, node, memo, ip)
    memo[idx] = d
    ip.discard(idx)
    return _cp(d)


def _inline(table, patches, node, memo, ip):
    if node is None:
        return None
    if isinstance(node, (str, float, bool)):
        return node
    if isinstance(node, int):
        return None if node in (-5, -7) else node
    if isinstance(node, list):
        if len(node) == 2 and node[0] == "D" and isinstance(node[1], (int, float)):
            return datetime.fromtimestamp(node[1] / 1000, tz=timezone.utc).isoformat()
        if len(node) == 2 and node[0] == "P" and isinstance(node[1], int):
            pid = node[1]
            return (
                [_resolve(table, patches, s, memo, ip) for s in patches[pid]]
                if pid in patches
                else None
            )
        return [
            (
                (None if v in (-5, -7) else _resolve(table, patches, v, memo, ip))
                if isinstance(v, int) and not isinstance(v, bool)
                else _inline(table, patches, v, memo, ip)
            )
            for v in node
        ]
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            m = _KEY_RE.match(k)
            prop = (
                table[int(m.group(1))]
                if m and int(m.group(1)) < len(table) and isinstance(table[int(m.group(1))], str)
                else k if not m else k
            )
            if isinstance(v, int) and not isinstance(v, bool):
                if v == -7:
                    continue
                out[prop] = None if v == -5 else _resolve(table, patches, v, memo, ip)
            else:
                out[prop] = _inline(table, patches, v, memo, ip)
        return out
    return node


def _cp(o):
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    if isinstance(o, list):
        return [_cp(x) for x in o]
    if isinstance(o, dict):
        return {k: _cp(v) for k, v in o.items()}
    return o


def decode_turbostream(text: str):
    segs = _parse_segments(text)
    if len(segs) == 1:
        return _decode_segment(segs[0])
    decoded = [_decode_segment(s) for s in segs]
    if all(isinstance(d, dict) for d in decoded):
        merged = {}
        for d in decoded:
            merged.update(d)
        return merged
    return decoded


# ── HTTP layer ───────────────────────────────────────────────────────────────

def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/x-script, application/json, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _udisc(path: str):
    base = "https://udisc.com"
    text = _fetch(f"{base}{path}")
    decoded = decode_turbostream(text)
    if (
        isinstance(decoded, list)
        and len(decoded) >= 2
        and decoded[0] == "SingleFetchRedirect"
    ):
        redir = decoded[1].get("redirect", "")
        if redir:
            if not redir.startswith("/"):
                redir = "/" + redir
            if ".data" not in redir:
                qi = path.find("?")
                qs = path[qi:] if qi >= 0 else ""
                ri = redir.find("?")
                redir = (
                    (redir[:ri] + ".data" + redir[ri:]) if ri >= 0 else redir + ".data" + qs
                )
            text2 = _fetch(f"{base}{redir}")
            decoded = decode_turbostream(text2)
    return decoded


# ── Public API ───────────────────────────────────────────────────────────────

def course_detail(slug: str) -> dict:
    """Fetch full course detail by slug (e.g. 'maple-hill-disc-golf-course-abc1')."""
    data = _udisc(f"/courses/{urllib.parse.quote(slug, safe='')}.data?_routes=root,routes/courses/$slug")
    route = data.get("routes/courses/$slug", {})
    if "error" in route:
        return {"error": route["error"]}
    return route.get("data", {}).get("course", {})


def course_reviews(slug: str, limit: int = 20) -> list:
    """Fetch reviews for a course slug."""
    data = _udisc(
        f"/courses/{urllib.parse.quote(slug, safe='')}/reviews.data"
        f"?_routes=routes/courses/$slug/reviews"
    )
    route = data.get("routes/courses/$slug/reviews", {})
    reviews = route.get("data", {}).get("reviews", [])
    return reviews[:limit]


def nearby_courses(lat: float, lng: float, radius_m: int = 50000, limit: int = 20) -> list:
    """Find courses near a lat/lng within radius (meters)."""
    data = _udisc(
        f"/api/courses/nearby.data?lat={lat}&lng={lng}"
        f"&limit={limit}&radius={radius_m}"
        f"&_routes=routes/api/courses/nearby"
    )
    return data.get("routes/api/courses/nearby", {}).get("data", {}).get("courses", [])


def nearby_stores(lat: float, lng: float, radius_m: int = 50000, limit: int = 20) -> list:
    """Find disc golf stores near a lat/lng."""
    data = _udisc(
        f"/api/stores/nearby.data?lat={lat}&lng={lng}"
        f"&limit={limit}&radius={radius_m}"
        f"&_routes=routes/api/stores/nearby"
    )
    return data.get("routes/api/stores/nearby", {}).get("data", {}).get("stores", [])


def course_layouts(slug: str) -> list:
    """
    Fetch all published layouts for a course, including per-hole tee/basket GPS.
    Layouts live on the course index child route, not the parent $slug route.
    'smart' layouts carry full teePosition/targetPosition coordinates.
    """
    data = _udisc(
        f"/courses/{urllib.parse.quote(slug, safe='')}.data"
        f"?_routes=routes/courses/$slug/index"
    )
    route = data.get("routes/courses/$slug/index", {})
    return route.get("data", {}).get("layouts", [])


def _layout_holes_in_order(layout: dict) -> list:
    holes = [h for h in (layout.get("holes") or []) if isinstance(h, dict)]
    if all(str(h.get("name", "")).isdigit() for h in holes):
        holes.sort(key=lambda h: int(h["name"]))
    return holes


def layouts_parkdly(slug: str, layout_filter: str | None = None) -> str:
    """
    Emit Parkdly 'Build course by hole coordinates' bulk-paste lines for one layout:
    one line per hole, `teeLat, teeLng | targetLat, targetLng` (decimal degrees).
    Picks the named layout (case-insensitive substring), else the first active
    smart layout with full GPS. Holes missing tee or basket GPS are skipped with
    a warning on stderr.
    """
    layouts = course_layouts(slug)
    if not layouts:
        raise RuntimeError(f"No layouts published on UDisc for '{slug}'")

    def has_gps(lay):
        holes = lay.get("holes") or []
        return holes and all(
            (h.get("teePosition") or {}).get("latitude") is not None
            and (h.get("targetPosition") or {}).get("latitude") is not None
            for h in holes
        )

    chosen = None
    if layout_filter:
        q = layout_filter.lower()
        matches = [l for l in layouts if q in (l.get("name", "") or "").lower()]
        if not matches:
            names = ", ".join(repr(l.get("name")) for l in layouts)
            raise RuntimeError(f"No layout matching {layout_filter!r}. Available: {names}")
        chosen = matches[0]
    else:
        chosen = next(
            (l for l in layouts if l.get("status") == "active" and has_gps(l)),
            layouts[0],
        )

    lines = []
    for h in _layout_holes_in_order(chosen):
        tee = h.get("teePosition") or {}
        tgt = h.get("targetPosition") or {}
        if tee.get("latitude") is None or tgt.get("latitude") is None:
            print(f"WARNING: hole {h.get('name')} missing GPS, skipped", file=sys.stderr)
            continue
        lines.append(
            f"{tee['latitude']:.6f}, {tee['longitude']:.6f}"
            f" | {tgt['latitude']:.6f}, {tgt['longitude']:.6f}"
        )
    pars = [h.get("par") for h in _layout_holes_in_order(chosen)]
    print(
        f"# layout: {chosen.get('name')} ({len(lines)} holes)  pars: {pars}",
        file=sys.stderr,
    )
    return "\n".join(lines)


def slug_from_url(url: str) -> str | None:
    """Extract course slug from a UDisc URL like https://udisc.com/courses/some-course-XYZ."""
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return None
    if "udisc.com" not in (parsed.hostname or ""):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2 or parts[0] != "courses":
        return None
    slug = urllib.parse.unquote(parts[1])
    for suffix in (".json", ".data"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
    return slug


def search_courses(query: str, lat: float = 39.8, lng: float = -98.5, radius_m: int = 5000000, limit: int = 50) -> list:
    """
    Search for courses by name. Uses the nearby endpoint with a large radius
    centered on the continental US, then filters by query match.
    """
    courses = nearby_courses(lat, lng, radius_m, limit)
    q = query.lower()
    return [c for c in courses if q in (c.get("name", "") or "").lower()]


# ── CLI ──────────────────────────────────────────────────────────────────────

def _main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        sys.exit(0)

    cmd = args[0]

    def opt(flag, default):
        if flag in args:
            i = args.index(flag)
            return type(default)(args[i + 1])
        return default

    try:
        if cmd == "course-detail":
            result = course_detail(args[1])
        elif cmd == "course-reviews":
            result = course_reviews(args[1], limit=opt("--limit", 20))
        elif cmd == "nearby-courses":
            result = nearby_courses(
                float(args[1]), float(args[2]),
                radius_m=opt("--radius", 50000), limit=opt("--limit", 20),
            )
        elif cmd == "nearby-stores":
            result = nearby_stores(
                float(args[1]), float(args[2]),
                radius_m=opt("--radius", 50000), limit=opt("--limit", 20),
            )
        elif cmd == "layouts":
            fmt = "parkdly" if "--format" in args and args[args.index("--format") + 1] == "parkdly" else "json"
            layout_name = None
            if "--layout" in args:
                layout_name = args[args.index("--layout") + 1]
            if fmt == "parkdly":
                print(layouts_parkdly(args[1], layout_name))
                sys.exit(0)
            result = course_layouts(args[1])
            if layout_name:
                q = layout_name.lower()
                result = [l for l in result if q in (l.get("name", "") or "").lower()]
        elif cmd == "search":
            result = search_courses(" ".join(args[1:]))
        elif cmd == "course-url":
            slug = slug_from_url(args[1])
            if not slug:
                print(json.dumps({"error": f"Could not extract slug from: {args[1]}"}))
                sys.exit(1)
            result = course_detail(slug)
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            print(__doc__.strip(), file=sys.stderr)
            sys.exit(1)

        print(json.dumps(result, indent=2, default=str))

    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"HTTP {e.code}: {e.reason}", "url": e.url}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
