#!/usr/bin/env python3
"""Export PDGA Live "Share scorecard" PNGs for named players, headless.

PDGA Live renders the share image in the browser (no image URL, no network request), so the only
way to get it is to drive the UI: expand the player's row, open the panel's ⋮ menu, click
"Share scorecard", pick a layout, click Download. One PNG per player covers every round.

    python3 live-scorecard-export.py 12345 MP50 "Jane Doe" "John Roe" --out ./scorecards
    python3 live-scorecard-export.py 12345 MPO "Alex Example" --layout summary

Layouts: "scorecards" (hole-by-hole, default) or "summary" (stat dials).
Files land as PDGA names them, e.g. jane-doe-my-tournament-2026-scorecards.png.
Uses system Chrome (channel="chrome"); the Playwright chromium bundle is not installed on this Mac.
A plain browser User-Agent is required: PDGA's edge treats HeadlessChrome differently.
"""
import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def export(page, name, layout, out):
    rows = page.locator(".player-full-name")
    idx = next((i for i in range(rows.count()) if norm(rows.nth(i).inner_text()) == norm(name)), None)
    if idx is None:
        raise SystemExit(f"{name}: not found in this division's scores")
    rows.nth(idx).click()                                   # expand the scorecard panel
    page.wait_for_timeout(1500)
    # the expanded panel's ⋮ is an <a> wrapping i.pi-options-vert (the header's icon button is event share)
    page.locator("a.btn-icon:has(i.pi-options-vert)").filter(visible=True).first.click()
    page.wait_for_timeout(1000)
    page.get_by_text("Share scorecard", exact=True).filter(visible=True).first.click()
    page.wait_for_timeout(1500)
    sheet = page.locator(".pdga-bottom-sheet").filter(visible=True)           # the share dialog
    sheet.locator(".image-type").filter(has_text=re.compile(layout, re.I)).first.click()
    with page.expect_download(timeout=30000) as dl:
        sheet.locator("button.btn-primary").filter(has_text=re.compile("Download", re.I)).first.click()
    target = out / dl.value.suggested_filename
    dl.value.save_as(target)
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    rows.nth(idx).click()                                   # collapse, so the next row is where we expect
    page.wait_for_timeout(800)
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event", help="PDGA TournID, e.g. 12345")
    ap.add_argument("division", help="e.g. MP40")
    ap.add_argument("players", nargs="+", help='full names as PDGA Live shows them, e.g. "Jane Doe"')
    ap.add_argument("--round", default="1", help="round tab to open (the PNG includes every round)")
    ap.add_argument("--layout", default="scorecards", choices=["scorecards", "summary"])
    ap.add_argument("--out", default=".", type=Path)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    url = f"https://www.pdga.com/live/event/{a.event}/{a.division}/scores?round={a.round}"
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=not a.headed)
        page = b.new_context(viewport={"width": 1320, "height": 900}, user_agent=UA,
                             accept_downloads=True).new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.locator(".player-full-name").first.wait_for(timeout=30000)
        failed = 0
        for name in a.players:
            try:
                print(export(page, name, a.layout, a.out))
            except Exception as e:                           # keep going; report at the end
                failed += 1
                print(f"FAILED {name}: {e}", file=sys.stderr)
        b.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
