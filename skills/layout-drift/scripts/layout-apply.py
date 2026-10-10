#!/usr/bin/env python3
"""
layout-apply — create a new PDGA Tournament Manager layout that matches UDisc's current pins and
assign EVERY division to it for the next round and all rounds after, then verify by read-back.

Dry-run by default. Nothing is written to PDGA without --execute.

Verified against the live TM markup on 2026-09-17:
  login        POST manager/{T}                      txtPassword, cmdLogonSubmit=Login   (cookie session)
  add layout   GET  manager/{T}/layout_add  → form posts to manager/{T}/layout_edit
               fields: CourseID (select), Name, Holes, Length, Units (Feet|Meters), Accuracy (M|E), AddLayout=Add Layout
               *** no per-hole fields here — TM redirects to layout_edit?LayoutID=<new> ***
  hole detail  GET/POST manager/{T}/layout_edit?LayoutID=<id>
               fields: CourseID, Name, Holes, Length, Units, Accuracy, Notes, Label{n}, Par{n}, Length{n}, Tee{n}, Target{n}, Notes{n},
               submit EditLayout=Update
  assignments  GET/POST manager/{T}/layouts   selects assignments[<DIV>][_][Rd<n>] (pool key '_' when no pools);
               only divisions WITH registrants and only layouts already added to the tournament are listed;
               the submit button is unnamed.
  verify       v3 password_check → layouts_read (form field payload=<json>, Bearer app token)

Credentials (environment only — never on the command line):
  PDGA_TM_PASSWORD    the event's Tournament Manager update password (name overridable via --password-env)
  PDGA_TM_APP_NAME    your PDGA v3 Tournament API app name   (for layouts_read verification)
  PDGA_TM_APP_TOKEN   your PDGA v3 Tournament API app token
  PDGA_TM_V3_BASE     optional, default https://www.pdga.com

Stdlib only. Reuses layout-drift.py for the UDisc pull/normalization.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("layout_drift", HERE / "layout-drift.py")
ld = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ld)  # type: ignore

UA = ld.UA
BROWSER_HEADERS = ld.BROWSER_HEADERS
ATTR = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def die(msg: str, code: int = 1) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


# ----------------------------------------------------------------------------- HTML form parsing

def parse_form(html: str, action_contains: str | None = None) -> tuple[dict, str | None]:
    """Browser-faithful serialization of the first form (or the one whose action contains a hint).
    Returns (fields, action). Submit buttons are excluded — add the one you mean to click."""
    forms = list(re.finditer(r"<form\b([^>]*)>(.*?)</form>", html, re.S | re.I))
    chosen = None
    for m in forms:
        attrs = dict(ATTR.findall(m.group(1)))
        if action_contains is None or action_contains in (attrs.get("action") or ""):
            chosen = m
            break
    if chosen is None:
        return {}, None
    attrs = dict(ATTR.findall(chosen.group(1)))
    body = chosen.group(2)
    fields: dict = {}
    for m in re.finditer(r"<input\b([^>]*)>", body, re.I):
        a = dict(ATTR.findall(m.group(1)))
        name, typ = a.get("name"), (a.get("type") or "text").lower()
        if not name or typ in ("submit", "button", "reset", "image") or "disabled" in m.group(1).lower():
            continue
        if typ in ("checkbox", "radio"):
            if "checked" in m.group(1).lower():
                fields[name] = a.get("value", "on")
            continue
        fields.setdefault(name, unescape(a.get("value", "")))
    for m in re.finditer(r"<select\b([^>]*)>(.*?)</select>", body, re.S | re.I):
        a = dict(ATTR.findall(m.group(1)))
        name = a.get("name")
        if not name or "disabled" in m.group(1).lower():
            continue
        sel = None
        for o in re.finditer(r"<option\b([^>]*)>", m.group(2), re.I):
            if "selected" in o.group(1).lower():
                sel = dict(ATTR.findall(o.group(1))).get("value", "")
                break
        if sel is not None:
            fields[name] = sel
    for m in re.finditer(r"<textarea\b([^>]*)>(.*?)</textarea>", body, re.S | re.I):
        a = dict(ATTR.findall(m.group(1)))
        name = a.get("name")
        if name and "disabled" not in m.group(1).lower():
            fields[name] = unescape(m.group(2))
    return fields, attrs.get("action")


def select_options(html: str, name: str) -> list[tuple[str, str]]:
    m = re.search(r'<select\b[^>]*name="' + re.escape(name) + r'"[^>]*>(.*?)</select>', html, re.S | re.I)
    if not m:
        return []
    return [(dict(ATTR.findall(o.group(1))).get("value", ""), unescape(re.sub("<[^>]+>", "", o.group(2)).strip()))
            for o in re.finditer(r"<option\b([^>]*)>(.*?)</option>", m.group(1), re.S | re.I)]


# ----------------------------------------------------------------------------- TM session

class TmSession:
    def __init__(self, tourn_id: str, journal_dir: Path, host: str = "www.pdga.com"):
        self.t = tourn_id
        self.host = host
        self.base = f"https://{host}/apps/tournament/manager/{tourn_id}"
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = list(BROWSER_HEADERS.items())
        self.last_url = f"https://{host}/apps/tournament/manager/"
        self.journal_dir = journal_dir
        journal_dir.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def _save(self, tag: str, html: str) -> None:
        self.n += 1
        (self.journal_dir / f"{self.n:02d}-{tag}.html").write_text(html)

    def get(self, path: str) -> tuple[str, str]:
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        ld.pace()
        req = urllib.request.Request(url, headers={"Referer": self.last_url})
        with self.op.open(req, timeout=45) as r:
            html = ld.read_body(r)
        self.last_url = r.geturl()
        self._save("GET-" + re.sub(r"[^\w]+", "_", path)[:40], html)
        return html, r.geturl()

    def post(self, path: str, data: dict) -> tuple[str, str]:
        url = path if path.startswith("http") else (
            urllib.parse.urljoin(f"https://{self.host}", path) if path.startswith("/") else f"{self.base}/{path.lstrip('/')}")
        body = urllib.parse.urlencode(data).encode()
        ld.pace(1.6, 1.0)  # a human reads the page before submitting
        req = urllib.request.Request(url, data=body, headers={
            "Referer": self.last_url, "Origin": f"https://{self.host}",
            "Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "max-age=0",
        })
        with self.op.open(req, timeout=60) as r:
            html = ld.read_body(r)
        self.last_url = r.geturl()
        self._save("POST-" + re.sub(r"[^\w]+", "_", path)[:40], html)
        return html, r.geturl()

    def login(self, password: str) -> None:
        html, _ = self.get("")
        fields, _ = parse_form(html)
        fields["txtPassword"] = password
        fields["cmdLogonSubmit"] = "Login"
        html, _ = self.post(self.base, fields)
        if "enter the event password" in html.lower() or "invalid password" in html.lower():
            die(f"Tournament Manager login failed for {self.t} (bad event update password?)")


# ----------------------------------------------------------------------------- v3 API (verification)

class V3:
    def __init__(self, tourn_id: str, host: str | None = None):
        self.t = tourn_id
        app = os.environ.get("PDGA_TM_APP_NAME")
        tok = os.environ.get("PDGA_TM_APP_TOKEN")
        base = os.environ.get("PDGA_TM_V3_BASE", "https://www.pdga.com")
        if not (app and tok):
            die("set PDGA_TM_APP_NAME and PDGA_TM_APP_TOKEN (your PDGA v3 Tournament API app) for layouts_read verification")
        if host:
            base = f"https://{host}"
        self.url = f"{base.rstrip('/')}/apps/tournament/api/{app}/{tourn_id}"
        self.tok = tok
        self.auth: str | None = None

    def call(self, method: str, payload: dict) -> dict:
        headers = dict(BROWSER_HEADERS, **{"Authorization": f"Bearer {self.tok}", "Accept": "application/json",
                                           "Content-Type": "application/x-www-form-urlencoded",
                                           "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Site": "same-site"})
        headers.pop("Upgrade-Insecure-Requests", None); headers.pop("Sec-Fetch-User", None)
        req = urllib.request.Request(f"{self.url}/{method}", data=urllib.parse.urlencode({"payload": json.dumps(payload)}).encode(), headers=headers)
        ld.pace(1.5, 1.0)
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(ld.read_body(r))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"v3 {method} HTTP {exc.code}: {exc.read().decode()[:200]}") from exc

    def login(self, password: str) -> None:
        r = self.call("password_check", {"password": password})
        if not r.get("success") or not r.get("token"):
            die(f"v3 password_check failed: {r.get('message')}")
        self.auth = r["token"]

    def layouts(self) -> dict:
        try:
            return self.call("layouts_read", {"auth": self.auth})
        except RuntimeError as exc:
            if "No layouts found" in str(exc):  # a tournament with no layouts yet answers 400, not an empty list
                return {"layouts": {}, "layout_assignments": {}}
            raise


# ----------------------------------------------------------------------------- inputs

def read_password(env_var: str) -> str:
    v = os.environ.get(env_var)
    if not v:
        die(f"env {env_var} is empty — export the event's Tournament Manager update password there")
    return v


def udisc_holes(slug: str, layout_name: str | None, cache_dir: Path, offline: bool) -> dict:
    raw, how = ld.fetch_udisc_layouts(slug, cache_dir, offline)
    chosen, cands = ld.choose_udisc_layout(raw, None, layout_name)
    if chosen is None:
        die("no active UDisc layout")
    log(f"UDisc {how}: using '{chosen['name']}' (layoutId {chosen['layout_id']}); candidates {[c['name'] for c in cands]}")
    return chosen


def build_hole_details(udisc_layout: dict, old_detail: dict | None, keep_notes: bool, pin_in_target: bool) -> list[dict]:
    details = []
    for i, h in enumerate(udisc_layout["holes"], start=1):
        old = (old_detail or {}).get(f"H{i}") or {}
        tee = (h.get("tee") or "").strip()
        tee = "" if tee.lower() in ("", "main") else tee
        details.append({
            "n": i, "label": h["label"] or str(i), "par": int(h["par"]), "length": int(h["published_ft"]),
            "tee": tee, "target": (h.get("pin") or "") if pin_in_target else "",
            "notes": (old.get("Notes") or "") if keep_notes else "",
            # informational only (not posted to TM): lets your own scoring system mirror the new layout
            "tee_gps": h.get("tee_gps"), "basket_gps": h.get("basket"),
        })
    return details


# ----------------------------------------------------------------------------- steps

def step_add_layout(tm: TmSession, pdga_course_id: str, name: str, holes: int, length: int, accuracy: str) -> str:
    html, _ = tm.get("layout_add")
    fields, action = parse_form(html, action_contains="layout_edit")
    if not fields or not action:
        die("layout_add form not found — TM markup changed; inspect the journal HTML")
    course_ids = {v for v, _ in select_options(html, "CourseID")}
    if pdga_course_id not in course_ids:
        die(f"PDGA course {pdga_course_id} is not in TM's CourseID list for this event")
    fields.update({"CourseID": pdga_course_id, "Name": name, "Holes": str(holes), "Length": str(length),
                   "Units": "Feet", "Accuracy": accuracy, "AddLayout": "Add Layout"})
    resp, final_url = tm.post(action, fields)
    m = re.search(r"LayoutID=(\d+)", final_url) or re.search(r"LayoutID=(\d+)", resp)
    if not m:
        die(f"layout added but no LayoutID in the redirect ({final_url}); check journal + TM before retrying")
    return m.group(1)


def step_update_holes(tm: TmSession, layout_id: str, name: str, length: int, accuracy: str, details: list[dict]) -> None:
    path = f"layout_edit?LayoutID={layout_id}"
    html, _ = tm.get(path)
    fields, action = parse_form(html, action_contains="layout_edit")
    if f"Par{len(details)}" not in fields:
        die(f"layout_edit for {layout_id} shows fewer hole rows than expected ({len(details)}); inspect the journal")
    fields.update({"Name": name, "Length": str(length), "Units": "Feet", "Accuracy": accuracy, "EditLayout": "Update"})
    for d in details:
        n = d["n"]
        fields[f"Label{n}"], fields[f"Par{n}"], fields[f"Length{n}"] = d["label"], str(d["par"]), str(d["length"])
        fields[f"Tee{n}"], fields[f"Target{n}"], fields[f"Notes{n}"] = d["tee"], d["target"], d["notes"]
    tm.post(action or path, fields)


def verify_holes(v3: V3, layout_id: str, details: list[dict]) -> list[str]:
    lay = (v3.layouts().get("layouts") or {}).get(str(layout_id))
    if not lay:
        return [f"layout {layout_id} not in layouts_read"]
    problems = []
    det = lay.get("Detail") or {}
    for d in details:
        h = det.get(f"H{d['n']}")
        if not h:
            problems.append(f"H{d['n']} missing")
            continue
        if int(h.get("Par") or 0) != d["par"] or int(h.get("Length") or 0) != d["length"]:
            problems.append(f"H{d['n']}: PDGA par {h.get('Par')}/{h.get('Length')} ft vs sent {d['par']}/{d['length']}")
        for k, key in (("tee", "Tee"), ("target", "Target"), ("label", "Label")):
            if (h.get(key) or "").strip() != d[k].strip():
                problems.append(f"H{d['n']}: {key} '{h.get(key)}' vs sent '{d[k]}'")
    return problems


def read_assignment_grid(tm: TmSession) -> tuple[dict, list[str], list[int], str | None, dict]:
    html, _ = tm.get("layouts")
    fields, action = parse_form(html)
    divisions, rounds = [], set()
    for k in fields:
        m = re.fullmatch(r"assignments\[([^\]]+)\]\[([^\]]*)\]\[Rd(\d+)\]", k)
        if m:
            if m.group(1) not in divisions:
                divisions.append(m.group(1))
            rounds.add(int(m.group(3)))
    available = {v: t for v, t in select_options(html, next((k for k in fields if k.startswith("assignments[")), "")) if v}
    return fields, divisions, sorted(rounds), action, available


def step_assign(tm: TmSession, layout_id: str, divisions: list[str], rounds: list[int], fields: dict, action: str | None) -> None:
    """Post the grid exactly as served, with only the target cells changed. Cells for divisions TM does not
    render are added — verified 2026-09-17: the server stores them (layouts_read shows them) even
    though the page never lists the division. Note: once set, an unrendered division's cell could not be
    cleared by posting '' — plan the division list deliberately."""
    for d in divisions:
        for r in rounds:
            fields[f"assignments[{d}][_][Rd{r}]"] = str(layout_id)
    tm.post(action or "layouts", fields)


def verify_assignments(v3: V3, layout_id: str, divisions: list[str], rounds: list[int]) -> list[str]:
    la = v3.layouts().get("layout_assignments") or {}
    problems = []
    for d in divisions:
        row = la.get(d) or {}
        for r in rounds:
            got = row.get(f"Rd{r}")
            if str(got) != str(layout_id):
                problems.append(f"{d} Rd{r} = {got}")
    return problems


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Create a UDisc-matching PDGA TM layout and assign all divisions for the next+later rounds")
    ap.add_argument("--tourn", required=True, help="PDGA TournID")
    ap.add_argument("--udisc", required=True, help="UDisc course slug or URL")
    ap.add_argument("--udisc-layout", help="UDisc layout name (default: most played smart layout)")
    ap.add_argument("--password-env", default="PDGA_TM_PASSWORD",
                    help="Env var holding the event's TM update password (default PDGA_TM_PASSWORD)")
    ap.add_argument("--pdga-course-id", help="PDGA course id (default: the currently assigned layout's CourseID)")
    ap.add_argument("--name", help="New TM layout name (default: '<UDisc layout> — pins <today>')")
    ap.add_argument("--from-round", type=int, help="First round to reassign (default: PDGA Live latest scored round + 1, else 1)")
    ap.add_argument("--to-round", type=int, help="Last round to reassign (default: last round column on the page)")
    ap.add_argument("--divisions", help="Comma list of division codes to assign (default: every division TM lists, i.e. those with a registrant). "
                                         "List every division your event offers to cover ones with no registrants yet (with --allow-unlisted-divisions)")
    ap.add_argument("--allow-unlisted-divisions", action="store_true",
                    help="Allow --divisions that TM does not render. Verified 2026-09-17: TM stores cells for unrendered divisions")
    ap.add_argument("--played-rounds", type=int, default=0,
                    help="Rounds your own records show as already played/started (feeds the played-week guard alongside PDGA Live)")
    ap.add_argument("--force-from-round", action="store_true", help="Override the played-week guard (dangerous)")
    ap.add_argument("--accuracy", default="M", choices=["M", "E"], help="TM accuracy flag: Measured or Estimated")
    ap.add_argument("--no-notes", action="store_true", help="Do not carry hole notes (OB/mando text) from the currently assigned layout")
    ap.add_argument("--no-pin-target", action="store_true", help="Do not write the UDisc pin letter into TM's Target field")
    ap.add_argument("--reuse-layout", help="Skip creation; assign this existing TM layout id instead")
    ap.add_argument("--execute", action="store_true", help="Actually write to PDGA (default: dry run)")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache-dir", default=os.environ.get("LAYOUT_DRIFT_CACHE", str(Path.home() / ".cache" / "layout-drift")))
    ap.add_argument("--pdga-host", default="www.pdga.com", help="stage.pdga.com = nightly backup of production; rehearse there first")
    ap.add_argument("--plan-json", help="Also write the plan (incl. per-hole tee/basket GPS) and final result to this path")
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    journal = cache_dir / "journal" / f"{args.tourn}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    password = read_password(args.password_env)

    slug = ld.resolve_udisc_slug(args.udisc)
    udisc_layout = udisc_holes(slug, args.udisc_layout, cache_dir, args.offline)
    holes = len(udisc_layout["holes"])

    # ---- read state
    v3 = V3(args.tourn, args.pdga_host)
    v3.login(password)
    state = v3.layouts()
    tm = TmSession(args.tourn, journal, args.pdga_host)
    log(f"PDGA host: {args.pdga_host}")
    tm.login(password)
    grid_fields, divisions, rounds, grid_action, available = read_assignment_grid(tm)
    grid_blocked = not divisions or not rounds
    if grid_blocked:
        log("TM renders no assignment grid yet ('add or upload player data before assigning layouts'): "
            "the layout can be created and filled, but assignments must wait for the first registrant.")
    if args.divisions:
        wanted = [d.strip() for d in args.divisions.split(",") if d.strip()]
        extra = [d for d in wanted if d not in divisions]
        if extra and not args.allow_unlisted_divisions:
            die(f"divisions not on TM's assignment page (no registrants?): {extra}; listed {divisions}. "
                "Pass --allow-unlisted-divisions to post them anyway (TM accepts cells for divisions it does not render).")
        divisions = wanted

    # ---- played-week guard: never reassign a round anyone has played
    live, _ = ld.fetch_live_layouts(args.tourn, cache_dir, args.offline, all_rounds=False)
    scored_round = int(live.get("highest_completed_round") or 0)  # LatestRound = open round, NOT a played one
    played_round = int(args.played_rounds or 0)
    guard = max(scored_round, played_round)
    from_round = args.from_round if args.from_round is not None else guard + 1
    log(f"played-week guard: PDGA Live highest completed round={scored_round}, --played-rounds={played_round} → first mutable round is {guard + 1}; from-round={from_round}")
    if from_round <= guard and not args.force_from_round:
        die(f"--from-round {from_round} would touch a played week (guard says rounds <= {guard} are immutable). "
            "Pass --force-from-round only if you have verified those rounds have no scores.")
    to_round = args.to_round or (rounds[-1] if rounds else from_round)
    target_rounds = [r for r in rounds if from_round <= r <= to_round] if rounds else list(range(from_round, to_round + 1))
    if not target_rounds:
        die(f"no rounds in range {from_round}..{to_round}; page has {rounds}")

    current = {}
    for d in divisions:
        for r in target_rounds:
            current[(d, r)] = grid_fields.get(f"assignments[{d}][_][Rd{r}]", "")
    old_ids = sorted({v for v in current.values() if v}, key=lambda x: -list(current.values()).count(x))
    old_layout_id = old_ids[0] if old_ids else None
    old_layout = (state.get("layouts") or {}).get(str(old_layout_id)) if old_layout_id else None
    pdga_course_id = args.pdga_course_id or (str(old_layout["CourseID"]) if old_layout else None)
    if not pdga_course_id:
        die("no currently assigned layout to infer the PDGA course id from; pass --pdga-course-id")

    details = build_hole_details(udisc_layout, (old_layout or {}).get("Detail"), not args.no_notes, not args.no_pin_target)
    name = args.name or f"{udisc_layout['name']} — pins {dt.date.today().isoformat()}"
    length = sum(d["length"] for d in details)
    par = sum(d["par"] for d in details)

    # ---- idempotency: same name + hole count already in the tournament → reuse
    reuse = args.reuse_layout
    if not reuse:
        for lid, lay in (state.get("layouts") or {}).items():
            if lay.get("Name", "").strip().lower() == name.lower() and int(lay.get("Holes") or 0) == holes:
                reuse = str(lid)
                log(f"TM already has '{name}' as layout {reuse}; will verify + assign instead of creating")

    plan = {
        "tourn": args.tourn, "pdga_course_id": pdga_course_id, "udisc_layout": {"name": udisc_layout["name"], "id": udisc_layout["layout_id"]},
        "new_layout": {"name": name, "holes": holes, "par": par, "length_ft": length, "accuracy": args.accuracy, "reuse_existing_id": reuse},
        "hole_details": details,
        "replacing": {"layout_id": old_layout_id, "name": (old_layout or {}).get("Name"), "par": (old_layout or {}).get("Par"), "length": (old_layout or {}).get("Length")},
        "divisions": divisions, "rounds": target_rounds, "rounds_on_page": rounds,
        "layouts_already_in_tournament": available,
        "current_assignments": {f"{d}/Rd{r}": v for (d, r), v in current.items()},
        "execute": args.execute, "journal": str(journal),
    }
    print(json.dumps(plan, indent=2))

    if args.plan_json:
        Path(args.plan_json).write_text(json.dumps(plan, indent=2))
    if not args.execute:
        log("\nDRY RUN — nothing written. Re-run with --execute to create/assign/verify.")
        return

    # ---- execute
    new_id = reuse
    if not new_id:
        new_id = step_add_layout(tm, pdga_course_id, name, holes, length, args.accuracy)
        log(f"created TM layout {new_id}")
    step_update_holes(tm, new_id, name, length, args.accuracy, details)
    problems = verify_holes(v3, new_id, details)
    if problems:
        die(f"hole read-back mismatch on layout {new_id}: {problems[:6]} — fix in TM before assigning; journal {journal}")
    log(f"layout {new_id} hole details verified via layouts_read")

    grid_fields, divisions_now, rounds_now, grid_action, available = read_assignment_grid(tm)
    if not available:
        # Verified on stage 2026-09-17: with zero registrants TM renders no assignments form and silently
        # ignores posted cells. The layout is created and verified; assignment has to wait.
        print(json.dumps({"ok": True, "pdga_layout_id": new_id, "assigned": False,
                          "next": f"TM has no registrants yet, so no assignment grid. After the first registration re-run with "
                                  f"--reuse-layout {new_id} to assign rounds {target_rounds[0]}..{target_rounds[-1]}.",
                          "journal": str(journal)}))
        return
    if str(new_id) not in available:
        die(f"layout {new_id} is not offered on the assignments page yet ({list(available)}); journal {journal}")
    step_assign(tm, new_id, divisions, target_rounds, grid_fields, grid_action)
    problems = verify_assignments(v3, new_id, divisions, target_rounds)
    if problems:
        die(f"assignment read-back mismatch: {problems[:10]}; journal {journal}")
    log(f"assigned layout {new_id} to {len(divisions)} division(s) for rounds {target_rounds[0]}..{target_rounds[-1]} and verified")
    result = {"ok": True, "pdga_layout_id": new_id, "divisions": divisions, "rounds": target_rounds, "journal": str(journal)}
    if args.plan_json:
        Path(args.plan_json).write_text(json.dumps(dict(plan, result=result), indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
