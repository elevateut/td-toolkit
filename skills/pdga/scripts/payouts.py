#!/usr/bin/env python3
"""Tournament payouts for PDGA events.

Computes per-place and per-player payouts from PDGA's 2019 payout table (the curves TM uses),
cross-checks them against TM's published payouts, and writes a payout plan JSON for the TD to
review and pay out however the event pays. Nothing here moves money.

    python3 payouts.py plan --event-dir <event-dir> [-o plan.json]
    python3 payouts.py division --players 12 --fees 528 [--added 0]
    python3 payouts.py test          # regression vs sampled TM payouts
"""

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_PATH = HERE.parent / "data" / "pdga_payout_table_2019.json"
LIVE = "https://www.pdga.com/apps/tournament/live-api"
UA = "Mozilla/5.0"
MISMATCH_TOLERANCE = Decimal("5")  # per-place $ diff vs TM before we hard stop

_table = None


def table():
    global _table
    if _table is None:
        _table = json.loads(TABLE_PATH.read_text())
    return _table


def _d(x):
    return Decimal(str(x))


def _round_dollar(x):
    return int(_d(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cash_line(players, pct=40):
    """Places paid. PDGA table (PaypctP) up to 400 players; ceil(pct% x players) beyond."""
    if players <= 0:
        return 0
    row = table()["places_paid"].get(str(players))
    if row:
        return int(row[str(pct)])
    return math.ceil(players * pct / 100)


def place_shares(places_paid):
    shares = table()["paypro"].get(str(places_paid))
    if shares is None:
        raise ValueError(f"{places_paid} places paid is past the 33-place table (large-field equation not encoded)")
    return shares


def division_payouts(players, entry_fees, added_cash=0, pct=40):
    """Whole-dollar payout per place, summing exactly to the purse.

    Rule C from the TM study: round the entry-fee part and the added-cash part of each place
    separately (half up), then put any remainder on 1st (positive) or take it off the last
    paid place (negative). Reproduces untouched TM output best in the sampled TM regression.
    """
    purse = _round_dollar(_d(entry_fees) + _d(added_cash))
    n_paid = cash_line(players, pct)
    if n_paid == 0 or purse == 0:
        return []
    shares = place_shares(n_paid)
    pays = [_round_dollar(_d(entry_fees) * _d(s)) + _round_dollar(_d(added_cash) * _d(s)) for s in shares]
    diff = purse - sum(pays)
    if diff > 0:
        pays[0] += diff
    elif diff < 0:
        pays[-1] += diff
    return pays


def split_ties(standings, place_pays):
    """Per-player amounts. `standings` = [{place, name, pdga, ...}] with PDGA RunningPlace
    semantics (tied players share the same place). Tied players split the money of the places
    they occupy evenly, to the cent; any leftover cent goes to the first listed. Ties for
    first never reach here: PDGA CM 1.09.B/C requires a playoff and forbids an even split of
    first-place money, so build_plan blocks a tie for first until the TD breaks it in TM."""
    groups = {}
    for s in standings:
        groups.setdefault(int(s["place"]), []).append(s)
    out = []
    for place in sorted(groups):
        grp = groups[place]
        occupied = range(place, place + len(grp))
        pot = sum((_d(place_pays[p - 1]) for p in occupied if p - 1 < len(place_pays)), Decimal(0))
        if pot == 0:
            continue
        cents = int(pot * 100)
        each, extra = divmod(cents, len(grp))
        for i, s in enumerate(grp):
            amt = Decimal(each + (1 if i < extra else 0)) / 100
            out.append({**s, "amount": float(amt), "tied_places": list(occupied) if len(grp) > 1 else None})
    return out


def compare_to_tm(ours, tm_payouts, ours_cash_line, tm_cash_line):
    """Hard-stop rules. Returns (ok, reasons, per_place_diffs)."""
    reasons = []
    if ours_cash_line != tm_cash_line:
        reasons.append(f"cash line differs: ours {ours_cash_line}, TM {tm_cash_line}")
    if abs(sum(_d(x) for x in ours) - sum(_d(x) for x in tm_payouts)) > Decimal("0.005"):
        reasons.append(f"division total differs: ours ${sum(ours)}, TM ${sum(tm_payouts)}")
    diffs = []
    for i in range(max(len(ours), len(tm_payouts))):
        o = ours[i] if i < len(ours) else 0
        t = tm_payouts[i] if i < len(tm_payouts) else 0
        diffs.append({"place": i + 1, "ours": o, "tm": t, "diff": t - o})
        if abs(_d(t) - _d(o)) > MISMATCH_TOLERANCE:
            reasons.append(f"place {i + 1} differs by more than ${MISMATCH_TOLERANCE}: ours ${o}, TM ${t}")
    return (not reasons, reasons, diffs)


# ── PDGA Live ────────────────────────────────────────────────────────────

_last = [0.0]


def _live(endpoint, **params):
    wait = 0.35 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = f"{LIVE}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        _last[0] = time.time()
        return json.load(r)["data"]


def live_event(tourn_id):
    return _live("live_results_fetch_event", TournID=tourn_id)


def live_final_standings(tourn_id, division, rounds):
    data = _live("live_results_fetch_round", TournID=tourn_id, Division=division, Round=rounds)
    scores = data["scores"] if isinstance(data, dict) else data[0]["scores"]
    out = []
    for s in scores:
        out.append({
            "place": s.get("RunningPlace"),
            "name": s.get("Name"),
            "pdga": int(s["PDGANum"]) if s.get("PDGANum") else None,
            "total": s.get("GrandTotal"),
            "completed": s.get("Played"),
        })
    return [s for s in out if s["place"] is not None]


def live_tm_payouts(tourn_id):
    # With no payouts entered, PDGA answers 404 with body {"data":[]}.
    import urllib.error
    try:
        data = _live("live_results_fetch_payouts", TournID=tourn_id)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return {}
    return data.get("divisions", {}) if isinstance(data, dict) else {}


def tm_published_prizes(tourn_id):
    """{division: {pdga#: prize}} from the public event page's Prize column. After TM
    "Publish Payouts" this is where the numbers appear first; live_results_fetch_payouts has
    been seen to stay empty (404) for 5+ minutes after publish."""
    import html as _html
    import re
    req = urllib.request.Request(f"https://www.pdga.com/tour/event/{tourn_id}", headers={"User-Agent": UA})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r'id="([A-Z]{2,4}\d{0,2})"', page):
        div = m.group(1)
        if div in out:
            continue
        end = page.find("</table>", m.end())
        prizes = {}
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page[m.end():end], re.S):
            cells = [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            num = next((c for c in cells if c.isdigit() and len(c) >= 4), None)
            money = next((c for c in cells if c.startswith("$")), None)
            if num and money:
                prizes[int(num)] = float(money.replace("$", "").replace(",", ""))
        if prizes:
            out[div] = prizes
    return out


# ── Config + plan ────────────────────────────────────────────────────────

def load_config(event_dir):
    import yaml  # PyYAML
    cfg = yaml.safe_load((Path(event_dir) / "payouts.yaml").read_text())
    for key in ("pdga_tournament_id", "divisions"):
        if key not in cfg:
            raise SystemExit(f"payouts.yaml missing `{key}`")
    return cfg


def build_plan(cfg):
    tid = int(cfg["pdga_tournament_id"])
    ev = live_event(tid)
    tm = live_tm_payouts(tid)
    tm_page = tm_published_prizes(tid) if not tm else {}
    divs_live = {d["Division"]: d for d in ev["Divisions"]}
    plan = {
        "schemaVersion": 1,
        "pdgaTournamentId": tid,
        "eventName": cfg.get("event_name") or ev.get("Name") or ev.get("TournamentName"),
        "endDate": ev.get("EndDate"),
        "divisions": [],
        "prizes": [],
        "blockers": [],
        "warnings": [],
    }
    for code, dcfg in cfg["divisions"].items():
        mode = dcfg.get("mode", "trophy")
        live = divs_live.get(code)
        if live is None:
            plan["blockers"].append(f"{code}: not on PDGA Live for #{tid}")
            continue
        players = int(live["Players"])
        rounds = int(live.get("LatestRound") or cfg.get("rounds") or 1)
        drec = {"division": code, "mode": mode, "players": players, "round": rounds}
        if mode == "trophy":
            plan["divisions"].append(drec)
            continue
        net = _d(dcfg["net_entry"])
        added = _d(dcfg.get("added_cash", 0))
        fees = net * players
        ours = division_payouts(players, fees, added)
        drec.update({"net_entry": float(net), "added_cash": float(added), "purse": sum(ours),
                     "cash_line": cash_line(players), "computed": ours, "payout_source": "computed"})
        standings = live_final_standings(tid, code, rounds)
        incomplete = [s["name"] for s in standings if s["completed"] and cfg.get("holes") and s["completed"] < cfg["holes"]]
        if incomplete:
            plan["warnings"].append(f"{code}: incomplete rounds for {', '.join(incomplete)}")
        # PDGA CM 1.09.B/C: a tie for first must be broken by a playoff and first-place money may
        # not be split evenly. Block until the TD marks the playoff result in TM (paying a tie for
        # first as an even split is a common mistake that then needs a correction).
        firsts = [s["name"] for s in standings if int(s["place"]) == 1]
        if len(firsts) > 1:
            plan["blockers"].append(f"{code}: tie for first ({', '.join(firsts)}); break it by playoff "
                                    "and mark the places in TM, then republish payouts (PDGA CM 1.09)")
        # Compare per finishing position AFTER the even tie split (ties below first only). TM's Publish page splits
        # ties itself in whole dollars (e.g. 190+129 -> 160/160, last place -$1),
        # which lands inside the tolerance, so TM's published numbers get paid.
        winners = split_ties(standings, ours)
        ours_pos = [w["amount"] for w in winners]
        drec["computed_after_ties"] = ours_pos
        tmd = tm.get(code)
        page = tm_page.get(code)
        if (tmd and tmd.get("payouts")) or page:
            if tmd and tmd.get("payouts"):
                tm_pos = [float(p["payoutValue"]) for p in sorted(tmd["payouts"], key=lambda p: p["place"])]
                tm_line = int(tmd.get("cashLine", len(tm_pos)))
                source = "tm"
            else:
                # Per player by PDGA#; a TM prize to someone we don't pay shows up as an extra position.
                tm_pos = [page.get(w["pdga"], 0.0) for w in winners]
                tm_pos += [v for k, v in page.items() if k not in {w["pdga"] for w in winners}]
                tm_line = sum(1 for v in page.values() if v > 0)
                source = "tm (event page)"
            ok, reasons, diffs = compare_to_tm(ours_pos, tm_pos, cash_line(players), tm_line)
            drec.update({"tm": tm_pos, "tm_diffs": diffs})
            if ok:
                for w, amt in zip(winners, tm_pos):
                    w["amount"] = amt
                drec["payout_source"] = source
            else:
                plan["blockers"] += [f"{code}: {r}" for r in reasons]
        else:
            drec["tm"] = None
            ties = [w["name"] for w in winners if w["tied_places"]]
            plan["warnings"].append(f"{code}: TM has no payouts published yet; check TM's Publish page against this plan and publish"
                                    + (f" (TM splits the {', '.join(ties)} tie in whole dollars; within ${MISMATCH_TOLERANCE}, TM's numbers are paid)" if ties else ""))
        if mode not in ("cash", "credit"):
            plan["blockers"].append(f"{code}: unknown mode {mode!r} (use cash, credit or trophy)")
            plan["divisions"].append(drec)
            continue
        kind = ("pro_cash" if code[:2] in ("MP", "FP") else "am_cash") if mode == "cash" else "am_credit"
        for w in winners:
            if not w["pdga"]:
                plan["blockers"].append(f"{code}: {w['name']} (place {w['place']}) has no PDGA number")
            plan["prizes"].append({
                "division": code, "place": int(w["place"]), "tiedPlaces": w["tied_places"],
                "name": w["name"], "pdgaNumber": w["pdga"], "amount": w["amount"], "kind": kind,
            })
        paid = round(sum(p["amount"] for p in plan["prizes"] if p["division"] == code), 2)
        if abs(paid - float(sum(ours))) > 0.005:
            plan["blockers"].append(f"{code}: prizes sum ${paid} != purse ${sum(ours)}")
        plan["divisions"].append(drec)
    plan["totals"] = {
        "pro_cash": round(sum(p["amount"] for p in plan["prizes"] if p["kind"] == "pro_cash"), 2),
        "am": round(sum(p["amount"] for p in plan["prizes"] if p["kind"] != "pro_cash"), 2),
    }
    plan["totals"]["total"] = round(sum(plan["totals"].values()), 2)
    return plan


def print_plan(plan, out=sys.stdout):
    w = out.write
    w(f"\n{plan['eventName']}  (PDGA #{plan['pdgaTournamentId']})\n")
    for d in plan["divisions"]:
        if d["mode"] == "trophy":
            w(f"  {d['division']:6} {d['players']:>3} players  trophy only\n")
            continue
        w(f"  {d['division']:6} {d['players']:>3} players  purse ${d['purse']}  cash line {d['cash_line']}  "
          f"source {d['payout_source']}  places {d['computed']}" + (f"  TM {d['tm']}" if d.get("tm") else "") + "\n")
    w("\n  Prizes\n")
    for p in plan["prizes"]:
        tie = f" (T, places {p['tiedPlaces']})" if p["tiedPlaces"] else ""
        w(f"    {p['division']:6} {p['place']:>2}{tie:18} {p['name']:28} #{p['pdgaNumber'] or '—':<8} ${p['amount']:>9,.2f}  {p['kind']}\n")
    t = plan["totals"]
    w(f"\n  Pro ${t['pro_cash']:,.2f}  Am ${t['am']:,.2f}  => total ${t['total']:,.2f}\n")
    for x in plan["warnings"]:
        w(f"  ⚠️  {x}\n")
    for x in plan["blockers"]:
        w(f"  ⛔ {x}\n")
    w(("  READY\n" if not plan["blockers"] else "  BLOCKED\n"))


# ── Regression ───────────────────────────────────────────────────────────

def regression(fixture):
    data = json.loads(Path(fixture).read_text())
    exact = total = 0
    # Anchor divisions (anonymised event 1062) that must reproduce TM to the dollar.
    musts = {(1062, "MPO"), (1062, "MP40"), (1062, "MP50")}
    failed_musts = []
    for d in data["divisions"]:
        if d.get("currency") != "USD" or len(d["payouts"]) < 2 or len(d["payouts"]) > 33:
            continue
        total += 1
        added = d["purse"] - d["fees"]
        ours = division_payouts(d["n"], d["fees"], added)
        hit = ours == d["payouts"]
        exact += hit
        if (d["tid"], d["div"]) in musts and not hit:
            failed_musts.append((d["tid"], d["div"], ours, d["payouts"]))
    print(f"exact TM matches: {exact}/{total}")
    for m in failed_musts:
        print("MUST-MATCH FAILED:", m)
    return exact, total, failed_musts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("division", help="Payout per place for one division")
    p.add_argument("--players", type=int, required=True)
    p.add_argument("--fees", type=float, required=True, help="entry fees in the purse (players x net entry)")
    p.add_argument("--added", type=float, default=0)
    p = sub.add_parser("plan", help="Build the payout plan for an event")
    p.add_argument("--event-dir", required=True, help="folder holding payouts.yaml")
    p.add_argument("-o", "--output", help="plan JSON path (default <event-dir>/payouts-plan.json)")
    p = sub.add_parser("test", help="Regression against sampled TM payouts")
    p.add_argument("--fixture", default=str(HERE.parent / "tests" / "fixtures" / "tm_payouts_sample.json"))
    a = ap.parse_args()

    if a.cmd == "division":
        pays = division_payouts(a.players, a.fees, a.added)
        print(json.dumps({"cash_line": cash_line(a.players), "purse": sum(pays), "payouts": pays}))
    elif a.cmd == "plan":
        plan = build_plan(load_config(a.event_dir))
        path = Path(a.output or Path(a.event_dir) / "payouts-plan.json")
        path.write_text(json.dumps(plan, indent=2) + "\n")
        print_plan(plan)
        print(f"\n  plan → {path}")
        sys.exit(1 if plan["blockers"] else 0)
    elif a.cmd == "test":
        _, _, fails = regression(a.fixture)
        sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
