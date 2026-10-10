#!/usr/bin/env python3
"""
layout-drift — detect drift between the *sanctioned* league layout for a course and the
*current* basket positions published on UDisc, and say what has to change at the PDGA level.

Sources (the report says which ones it had):
  UDisc      current pins: per-hole pin label, GPS, published + straight-line distance, par, tee label
  PDGA Live  the sanctioned layout(s) a tournament actually plays (public API, no auth)

Stdlib only. Reuses the sibling `udisc` skill (../../udisc/scripts/udisc.py) for the UDisc fetch;
set CLAUDE_SKILLS_ROOT to point at a different skills directory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS_ROOT = Path(os.environ.get("CLAUDE_SKILLS_ROOT", HERE.parent.parent))
sys.path.insert(0, str(SKILLS_ROOT / "udisc" / "scripts"))
try:
    import udisc  # type: ignore
except ImportError:  # pragma: no cover
    udisc = None

LIVE_API = "https://www.pdga.com/apps/tournament/live-api"
# Look like the TD's own Chrome session. PDGA rate-limits/blocks non-browser clients hard, so every
# client here shares this identity and human pacing.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0.0.0 Safari/537.36")
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}
_last_request_at = 0.0


def pace(min_gap: float = 1.2, jitter: float = 0.8) -> None:
    """Human-like spacing between requests to the same host."""
    global _last_request_at
    import random
    wait = min_gap + random.random() * jitter - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.time()


def read_body(resp) -> str:
    import gzip, zlib
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc:
        raw = gzip.decompress(raw)
    elif "deflate" in enc:
        raw = zlib.decompress(raw, -zlib.MAX_WBITS) if raw[:2] != b"\x78\x9c" else zlib.decompress(raw)
    return raw.decode("utf-8", "replace")


# ----------------------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


def haversine_ft(lat1, lng1, lat2, lng2) -> float | None:
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a)) * 3.28084


def cache_path(cache_dir: Path, name: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / name


def load_cache(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
    return None


def cache_age(path: Path) -> str:
    if not path.exists():
        return "none"
    age = time.time() - path.stat().st_mtime
    return f"{age / 3600:.1f}h old"


def to_int(v) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- UDisc

def resolve_udisc_slug(value: str) -> str:
    value = value.strip()
    if value.startswith("http"):
        slug = udisc.slug_from_url(value) if udisc else None
        if not slug:
            m = re.search(r"/courses/([^/?#]+)", value)
            slug = m.group(1) if m else None
        if not slug:
            die(f"Could not parse a UDisc course slug from {value}")
        return slug
    return value


def fetch_udisc_layouts(slug: str, cache_dir: Path, offline: bool) -> tuple[list, str]:
    path = cache_path(cache_dir, f"udisc-{slug}.json")
    if offline:
        data = load_cache(path)
        if data is None:
            die(f"--offline but no UDisc cache at {path}")
        return data, f"cache ({cache_age(path)})"
    if udisc is None:
        die(f"udisc skill not found; expected {SKILLS_ROOT / 'udisc' / 'scripts' / 'udisc.py'} (set CLAUDE_SKILLS_ROOT)")
    try:
        data = udisc.course_layouts(slug)
    except Exception as exc:  # network / decode
        cached = load_cache(path)
        if cached is not None:
            log(f"UDisc fetch failed ({exc}); using cache {cache_age(path)}")
            return cached, f"cache after fetch error ({cache_age(path)})"
        die(f"UDisc fetch failed and no cache: {exc}")
    path.write_text(json.dumps(data))
    return data, "live"


def normalize_udisc_layout(layout: dict) -> dict:
    holes = []
    for h in (layout.get("holes") or []):
        if not isinstance(h, dict):
            continue
        tp = h.get("targetPosition") or {}
        te = h.get("teePosition") or {}
        pin_labels = [l.get("name") or l.get("labelType") for l in (tp.get("targetPositionLabels") or [])]
        tee_labels = [l.get("name") or l.get("labelType") for l in (te.get("teePositionLabels") or [])]
        tt = tp.get("targetType") or {}
        published_ft = to_int((h.get("holeDistance") or {}).get("feet"))
        if published_ft is None and h.get("distance") is not None:
            published_ft = to_int(h["distance"] * 3.28084)
        gps_ft = haversine_ft(te.get("latitude"), te.get("longitude"), tp.get("latitude"), tp.get("longitude"))
        holes.append({
            "label": str(h.get("name") or "").strip(),
            "par": h.get("par"),
            "published_ft": published_ft,
            "gps_ft": to_int(gps_ft) if gps_ft is not None else None,
            "pin": "/".join(x for x in pin_labels if x) or None,
            "pin_status": tp.get("status"),
            "basket": (tp.get("latitude"), tp.get("longitude")),
            "basket_model": (tt.get("basketModel") or {}).get("name"),
            "tee": "/".join(x for x in tee_labels if x) or None,
            "tee_type": (te.get("teeType") or {}).get("teeType"),
            "tee_gps": (te.get("latitude"), te.get("longitude")),
            "temporary": bool(h.get("isTemporary")) or bool(tp.get("isTemporary")),
            "status": h.get("status"),
        })
    if all(h["label"].isdigit() for h in holes):
        holes.sort(key=lambda h: int(h["label"]))
    return {
        "source": "udisc",
        "layout_id": layout.get("layoutId"),
        "name": layout.get("name"),
        "type": layout.get("type"),
        "status": layout.get("status"),
        "play_count_30d": layout.get("playCount30"),
        "holes": holes,
        "totals": {
            "holes": len(holes),
            "par": sum(h["par"] or 0 for h in holes),
            "published_ft": sum(h["published_ft"] or 0 for h in holes),
        },
    }


# ----------------------------------------------------------------------------- PDGA Live

def live_get(endpoint: str, params: dict, retries: int = 2) -> dict:
    url = f"{LIVE_API}/{endpoint}?{urllib.parse.urlencode(params)}"
    headers = dict(BROWSER_HEADERS, **{
        "Accept": "application/json, text/plain, */*", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
        "Referer": f"https://www.pdga.com/apps/tournament/live/event?eventId={params.get('TournID', '')}",
    })
    headers.pop("Upgrade-Insecure-Requests", None); headers.pop("Sec-Fetch-User", None)
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries + 1):
        pace(0.8, 0.6)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return (json.loads(read_body(resp)) or {}).get("data") or {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                wait = 5 * (attempt + 1)
                log(f"PDGA Live 429 on {endpoint}; backing off {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"PDGA Live {exc.code} on {endpoint}") from exc


def normalize_live_layout(layout: dict, division: str, rnd: int) -> dict:
    units = (layout.get("Units") or "Feet").lower()
    holes = []
    for h in layout.get("Detail") or []:
        length = h.get("Length")
        if length is not None and units.startswith("meter"):
            length = length * 3.28084
        holes.append({
            "label": str(h.get("Label") or h.get("Hole") or "").strip(),
            "par": h.get("Par"),
            "ft": to_int(length),
            "seq": h.get("HoleOrdinal") or h.get("Ordinal"),
        })
    return {
        "source": "pdga-live",
        "pdga_layout_id": layout.get("LayoutID"),
        "name": (layout.get("Name") or "").strip(),
        "course": (layout.get("CourseName") or "").strip(),
        "notes": (layout.get("Notes") or "").strip() or None,
        "used_by": [{"division": division, "round": rnd}],
        "holes": holes,
        "totals": {"holes": layout.get("Holes"), "par": layout.get("Par"),
                   "ft": to_int(layout.get("Length") * 3.28084 if units.startswith("meter") and layout.get("Length") else layout.get("Length"))},
    }


def fetch_live_layouts(tourn_id: str, cache_dir: Path, offline: bool, all_rounds: bool) -> tuple[dict, str]:
    """One request per division (latest round only) unless all_rounds — PDGA Live rate-limits fan-outs."""
    path = cache_path(cache_dir, f"pdga-live-{tourn_id}.json")
    if offline:
        data = load_cache(path)
        if data is None:
            die(f"--offline but no PDGA Live cache at {path}")
        return data, f"cache ({cache_age(path)})"
    try:
        event = live_get("live_results_fetch_event", {"TournID": tourn_id})
        divisions = event.get("Divisions") or []
        if not divisions:
            raise RuntimeError("no PDGA Live data (event may not use live scoring yet)")
        by_id: dict = {}
        for div in divisions:
            code = div.get("Division")
            latest = div.get("LatestRound") or event.get("LatestRound") or 1
            rounds = range(1, int(latest) + 1) if all_rounds else [int(latest)]
            for r in rounds:
                data = live_get("live_results_fetch_round", {"TournID": tourn_id, "Division": code, "Round": r})
                for layout in data.get("layouts") or []:
                    lid = layout.get("LayoutID")
                    if lid in by_id:
                        used = by_id[lid]["used_by"]
                        if not any(u["division"] == code and u["round"] == r for u in used):
                            used.append({"division": code, "round": r})
                    else:
                        by_id[lid] = normalize_live_layout(layout, code, r)
        result = {
            "tourn_id": tourn_id,
            "event": event.get("SimpleName") or event.get("Name"),
            "start": event.get("StartDate"), "end": event.get("EndDate"),
            "latest_round": event.get("LatestRound"), "rounds": event.get("Rounds"),
            # HighestCompletedRound is the scored-round signal; LatestRound only says which round is OPEN.
            "highest_completed_round": event.get("HighestCompletedRound"),
            "layouts": list(by_id.values()),
            "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(result))
        return result, "live"
    except Exception as exc:
        cached = load_cache(path)
        if cached is not None:
            log(f"PDGA Live {tourn_id}: {exc}; using cache {cache_age(path)}")
            return cached, f"cache after fetch error ({cache_age(path)}): {exc}"
        return {"tourn_id": tourn_id, "layouts": [], "error": str(exc)}, f"unavailable: {exc}"


# ----------------------------------------------------------------------------- comparison

def hole_key(label: str, number: int | None = None) -> str:
    text = (label or "").strip()
    m = re.fullmatch(r"(?:H|Hole\s*)?(\d+)([A-Za-z]?)", text, re.IGNORECASE)
    if m:
        return (m.group(1) + m.group(2).upper()) if m.group(2) else m.group(1)
    return text or (str(number) if number is not None else "")


def choose_udisc_layout(layouts: list[dict], sanctioned_holes: list[dict] | None, wanted: str | None) -> tuple[dict | None, list]:
    candidates = [normalize_udisc_layout(l) for l in layouts if (l.get("status") or "active") == "active"]
    if wanted:
        for c in candidates:
            if wanted.lower() in (c["name"] or "").lower():
                return c, candidates
        die(f"UDisc layout '{wanted}' not found; have: {[c['name'] for c in candidates]}")
    if not sanctioned_holes:
        # most played smart layout wins
        candidates.sort(key=lambda c: (-(c["play_count_30d"] or 0)))
        return (candidates[0] if candidates else None), candidates
    sanct = {hole_key(h["label"], h.get("number")): h for h in sanctioned_holes}
    scored = []
    for c in candidates:
        uh = {hole_key(h["label"]): h for h in c["holes"]}
        if len(uh) != len(sanct):
            scored.append((10**9 + abs(len(uh) - len(sanct)), c))
            continue
        total = 0
        for k, s in sanct.items():
            u = uh.get(k)
            if not u or u["published_ft"] is None or s["ft"] is None:
                total += 10**6
                continue
            total += abs(u["published_ft"] - s["ft"])
            # tee label agreement (Long/Short) is a strong tiebreaker
            s_tee = (s.get("tee") or "").lower()
            u_tee = (u.get("tee") or "").lower()
            if s_tee and s_tee not in ("main",) and not s_tee.startswith("tee ") and s_tee not in u_tee:
                total += 250
        scored.append((total, c))
    scored.sort(key=lambda x: x[0])
    return (scored[0][1] if scored else None), [c for _, c in scored]


def compare(udisc_layout: dict, sanctioned: dict, tol_ft: int, tol_pct: float) -> dict:
    uh = {hole_key(h["label"]): h for h in udisc_layout["holes"]}
    rows, drift_count, par_drift, dist_drift, missing = [], 0, 0, 0, 0
    for s in sanctioned["holes"]:
        k = hole_key(s["label"], s.get("number"))
        u = uh.pop(k, None)
        if u is None:
            rows.append({"hole": k, "verdict": "MISSING-ON-UDISC", "sanctioned": s, "udisc": None})
            missing += 1
            drift_count += 1
            continue
        reasons = []
        if u["par"] is not None and s["par"] is not None and u["par"] != s["par"]:
            reasons.append(f"par {s['par']}→{u['par']}")
            par_drift += 1
        delta = None
        if u["published_ft"] is not None and s["ft"] is not None:
            delta = s["ft"] - u["published_ft"]
            tol = max(tol_ft, u["published_ft"] * tol_pct / 100.0)
            if abs(delta) > tol:
                reasons.append(f"{s['ft']}→{u['published_ft']} ft ({delta:+d})")
                dist_drift += 1
        s_tee = (s.get("tee") or "").strip().lower()
        u_tee = (u.get("tee") or "").strip().lower()
        tee_named = s_tee and not s_tee.startswith("tee ") and s_tee != "main"
        if tee_named and s_tee not in u_tee:
            reasons.append(f"tee '{s.get('tee')}' vs UDisc '{u.get('tee')}'")
        if u["temporary"]:
            reasons.append("UDisc marks this hole/pin TEMPORARY")
        verdict = "DRIFT" if reasons else "match"
        if reasons:
            drift_count += 1
        rows.append({"hole": k, "verdict": verdict, "reasons": reasons, "delta_ft": delta,
                     "sanctioned": s, "udisc": u})
    extra = [{"hole": k, "verdict": "EXTRA-ON-UDISC", "udisc": u, "sanctioned": None} for k, u in uh.items()]
    return {
        "rows": rows + extra,
        "summary": {
            "holes_compared": len(rows), "drifted": drift_count, "par_drift": par_drift,
            "distance_drift": dist_drift, "missing_on_udisc": missing, "extra_on_udisc": len(extra),
            "sanctioned_total_ft": sum(h["ft"] or 0 for h in sanctioned["holes"]),
            "udisc_total_ft": udisc_layout["totals"]["published_ft"],
            "sanctioned_par": sum(h["par"] or 0 for h in sanctioned["holes"]),
            "udisc_par": udisc_layout["totals"]["par"],
            "tolerance": f"±{tol_ft} ft or {tol_pct:g}%",
        },
    }


def history_ranking(udisc_layout: dict, layouts: list[dict], limit: int = 6) -> list[dict]:
    """Rank every PDGA layout seen (across all --tourn events) by closeness to today's UDisc pins."""
    uh = {hole_key(h["label"]): h["published_ft"] for h in udisc_layout["holes"]}
    ranked = []
    for lay in layouts:
        if not lay["holes"] or len(lay["holes"]) != len(uh):
            continue
        total, n = 0, 0
        for h in lay["holes"]:
            u = uh.get(hole_key(h["label"], h.get("seq")))
            if u is None or h["ft"] is None:
                continue
            total += abs(h["ft"] - u)
            n += 1
        if n:
            ranked.append({"name": lay["name"], "pdga_layout_id": lay["pdga_layout_id"],
                           "tournaments": lay.get("tournaments") or [],
                           "total_abs_delta_ft": total, "mean_abs_delta_ft": round(total / n, 1)})
    ranked.sort(key=lambda r: r["total_abs_delta_ft"])
    return ranked[:limit]


# ----------------------------------------------------------------------------- report

def fmt_row(r: dict) -> str:
    s, u = r.get("sanctioned"), r.get("udisc")
    sp = f"{s['par']}" if s else "—"
    sf = f"{s['ft']}" if s and s.get("ft") is not None else "—"
    up = f"{u['par']}" if u else "—"
    uf = f"{u['published_ft']}" if u and u.get("published_ft") is not None else "—"
    ug = f"{u['gps_ft']}" if u and u.get("gps_ft") is not None else "—"
    pin = (u.get("pin") or "?") if u else "—"
    tee = (u.get("tee") or "main") if u else "—"
    d = r.get("delta_ft")
    ds = f"{d:+d}" if isinstance(d, int) else "—"
    reasons = "; ".join(r.get("reasons") or []) if r["verdict"] not in ("match",) else ""
    return f"| {r['hole']} | {sp} | {sf} | {up} | {uf} | {ug} | {pin} | {tee} | {ds} | {r['verdict']}{(' — ' + reasons) if reasons else ''} |"


def render_markdown(report: dict) -> str:
    md = []
    src = report["sources"]
    md.append(f"# Layout drift — {report['course']}")
    md.append("")
    md.append(f"_Generated {report['generated_utc']} · UDisc: {src['udisc']} · PDGA Live: {src.get('pdga_live', 'not requested')}_")
    md.append("")
    u = report["udisc_layout"]
    if u:
        md.append(f"**UDisc reference layout:** {u['name']} (layoutId {u['layout_id']}, {u['type']}, {u['play_count_30d']} plays/30d) — "
                  f"{u['totals']['holes']} holes, par {u['totals']['par']}, {u['totals']['published_ft']} ft published. "
                  f"Pins: {' '.join((h['label'] + (h['pin'] or '?')) for h in u['holes'])}")
        others = [c['name'] for c in report.get("udisc_candidates", []) if c['layout_id'] != u['layout_id']]
        if others:
            md.append(f"Other active UDisc layouts: {', '.join(others)}")
        md.append("")
    for block in report["comparisons"]:
        s = block["sanctioned"]
        md.append(f"## Sanctioned layout: {s['title']}")
        md.append("")
        md.append(s["provenance"])
        md.append("")
        summ = block["result"]["summary"]
        md.append(f"**Verdict: {'DRIFT' if summ['drifted'] else 'IN SYNC'}** — {summ['drifted']}/{summ['holes_compared']} holes differ "
                  f"({summ['distance_drift']} distance, {summ['par_drift']} par, {summ['missing_on_udisc']} missing, {summ['extra_on_udisc']} extra on UDisc); "
                  f"tolerance {summ['tolerance']}. Totals: sanctioned par {summ['sanctioned_par']} / {summ['sanctioned_total_ft']} ft vs UDisc par {summ['udisc_par']} / {summ['udisc_total_ft']} ft.")
        md.append("")
        md.append("| Hole | S par | S ft | U par | U ft | U gps ft | Pin | Tee | Δ ft (S−U) | Verdict |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in block["result"]["rows"]:
            md.append(fmt_row(r))
        md.append("")
    if report.get("history"):
        md.append("## Which PDGA layout best matches today's UDisc pins")
        md.append("")
        md.append("| PDGA layout | Tournament(s) | Σ|Δ| ft | mean |Δ| ft |")
        md.append("|---|---|---|---|")
        for h in report["history"]:
            md.append(f"| {h['pdga_layout_id']} {h['name']} | {', '.join(h['tournaments']) or '—'} | {h['total_abs_delta_ft']} | {h['mean_abs_delta_ft']} |")
        md.append("")
    md.append("## What has to change at the sanctioned level")
    md.append("")
    for line in report["actions"]:
        md.append(f"- {line}")
    md.append("")
    md.append("### Constraints that apply to every fix")
    md.append("")
    for line in report["constraints"]:
        md.append(f"- {line}")
    return "\n".join(md)


def build_actions(report: dict) -> list[str]:
    actions = []
    for block in report["comparisons"]:
        s, res = block["sanctioned"], block["result"]
        drifted = [r for r in res["rows"] if r["verdict"] != "match"]
        if not drifted:
            actions.append(f"{s['title']}: no change needed.")
            continue
        edits = []
        for r in drifted:
            if r["verdict"] == "MISSING-ON-UDISC":
                edits.append(f"hole {r['hole']}: not on the UDisc layout — confirm it is still played")
            elif r["verdict"] == "EXTRA-ON-UDISC":
                edits.append(f"hole {r['hole']}: on UDisc but not in the sanctioned layout")
            else:
                u = r["udisc"]
                edits.append(f"hole {r['hole']}: par {u['par']}, {u['published_ft']} ft (pin {u.get('pin') or '?'})")
        where = f"PDGA layout {s['pdga_layout_id']}" if s.get("pdga_layout_id") else "the PDGA layout"
        tourns = ", ".join(s.get("tournaments") or []) or "its tournament"
        actions.append(f"{s['title']} — {where} on {tourns} needs {len(drifted)} hole edit(s): " + "; ".join(edits) + ".")
    if any(r["verdict"] != "match" for b in report["comparisons"] for r in b["result"]["rows"]):
        actions.append("To fix at the sanctioned level, run layout-apply.py (new TM layout from UDisc, every division, "
                       "next round onward). If your own scoring/league system mirrors this layout, update it too.")
    return actions


CONSTRAINTS = [
    "PDGA has no layout write API: v3 exposes only layouts_read; hole edits are Tournament Manager form posts, which work from a residential/laptop IP but are often 429-blocked from cloud hosts.",
    "Rounds already played are immutable. Apply corrections to the layout used by FUTURE rounds; if past rounds were rated on the wrong numbers, PDGA needs a note, not a rewrite.",
    "A material pin move should be a NEW sanctioned layout (new PDGA layout id) so ratings are not pooled across two physical configurations; same-config weeks reuse one id.",
    "UDisc's public payload carries only the pins each layout currently uses — not alternate A/B/C positions — so 'which pin is the sanctioned distance describing?' can only be inferred from distance.",
    "UDisc published distance can be a course-admin custom value; the GPS straight-line column is the physical check. Trust GPS for 'did the basket move', published for 'what the scorecard says'.",
]


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Detect league-layout drift against current UDisc basket positions")
    ap.add_argument("--udisc", required=True, help="UDisc course slug or URL")
    ap.add_argument("--udisc-layout", help="UDisc layout name filter (default: best match to the sanctioned layout)")
    ap.add_argument("--tourn", action="append", default=[],
                    help="PDGA TournID (repeatable; also reads env PDGA_TOURN_IDS, comma-separated)")
    ap.add_argument("--history", action="store_true",
                    help="Rank every PDGA layout seen across the --tourn events against today's UDisc pins")
    ap.add_argument("--all-rounds", action="store_true", help="PDGA Live: fetch every round (slow; risks 429). Default = latest round per division")
    ap.add_argument("--tolerance-ft", type=int, default=20)
    ap.add_argument("--tolerance-pct", type=float, default=7.0)
    ap.add_argument("--cache-dir", default=os.environ.get("LAYOUT_DRIFT_CACHE", str(Path.home() / ".cache" / "layout-drift")))
    ap.add_argument("--offline", action="store_true", help="Use cached UDisc/PDGA pulls only")
    ap.add_argument("--json", dest="json_out", help="Write the full report JSON here")
    ap.add_argument("--markdown", dest="md_out", help="Write the markdown report here (stdout otherwise)")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    slug = resolve_udisc_slug(args.udisc)
    report: dict = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "course": slug, "sources": {}, "pdga_live": {}, "comparisons": [],
    }

    raw_layouts, how = fetch_udisc_layouts(slug, cache_dir, args.offline)
    report["sources"]["udisc"] = how
    if not raw_layouts:
        die("UDisc returned no layouts for this course")

    env_tourns = [t.strip() for t in os.environ.get("PDGA_TOURN_IDS", "").split(",") if t.strip()]
    tourns = list(dict.fromkeys(args.tourn + env_tourns))
    live: dict = {}
    for t in tourns:
        data, how = fetch_live_layouts(t, cache_dir, args.offline, args.all_rounds)
        live[t] = data
        report["sources"].setdefault("pdga_live", "")
        report["sources"]["pdga_live"] += f"{t}: {how}; "
    report["pdga_live"] = live

    # Sanctioned layout blocks: one per distinct PDGA layout id PDGA Live is serving.
    blocks: list[dict] = []
    live_by_pdga_id: dict = {}
    for t, data in live.items():
        for lay in data.get("layouts", []):
            pid = str(lay["pdga_layout_id"])
            entry = live_by_pdga_id.setdefault(pid, {"layout": lay, "tournaments": []})
            entry["tournaments"].append(str(t))

    for pid, entry in live_by_pdga_id.items():
        lay = entry["layout"]
        holes = [{"label": h["label"], "number": h.get("seq"), "par": h["par"], "ft": h["ft"], "tee": None, "target": None} for h in lay["holes"]]
        prov = f"Source: PDGA Live layout {pid} '{lay['name']}' ({lay['course']}), used by " + \
               ", ".join(f"{u['division']} R{u['round']}" for u in lay["used_by"]) + f" on tournament(s) {', '.join(entry['tournaments'])}."
        blocks.append({"sanctioned": {"title": f"{lay['name']} (PDGA {pid})", "pdga_layout_id": pid, "holes": holes,
                                      "tournaments": entry["tournaments"], "provenance": prov}})

    ref_holes = blocks[0]["sanctioned"]["holes"] if blocks else None
    udisc_layout, candidates = choose_udisc_layout(raw_layouts, ref_holes, args.udisc_layout)
    report["udisc_layout"], report["udisc_candidates"] = udisc_layout, [{k: c[k] for k in ("name", "layout_id", "play_count_30d")} for c in candidates]
    if udisc_layout is None:
        die("no active UDisc layout to compare against")

    for b in blocks:
        b["result"] = compare(udisc_layout, b["sanctioned"], args.tolerance_ft, args.tolerance_pct)
    report["comparisons"] = blocks
    if not blocks:
        report["actions"] = ["No sanctioned layout found (no PDGA Live data for the given events). Pass --tourn <TournID>."]
    else:
        report["actions"] = build_actions(report)
    report["constraints"] = CONSTRAINTS
    if args.history:
        seen = [dict(e["layout"], tournaments=e["tournaments"]) for e in live_by_pdga_id.values()]
        report["history"] = history_ranking(udisc_layout, seen)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
    md = render_markdown(report)
    if args.md_out:
        Path(args.md_out).write_text(md)
        log(f"wrote {args.md_out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
