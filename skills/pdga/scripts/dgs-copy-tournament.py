#!/usr/bin/env python3
"""Create a new DGS tournament by copying an existing one you admin.

Usage:
  dgs-copy-tournament.py --source <slug> --name "New Tournament" --date 07/13/2026 [--public]

Prints JSON with the new tournament's slug/URL (from the redirect).
Cookies come from ~/.dgs-cookies.json (run dgs-auth.py to refresh).
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.discgolfscene.com"


def cookie_header():
    cj = json.load(open(os.path.expanduser(os.environ.get("DGS_COOKIE_FILE") or "~/.dgs-cookies.json")))
    cookies = cj.get("cookies", cj)
    if isinstance(cookies, list):
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="Slug of the tournament to copy")
    ap.add_argument("--name", required=True, help="Name for the new tournament")
    ap.add_argument("--date", required=True, help="Start date MM/DD/YYYY for the new tournament")
    ap.add_argument("--public", action="store_true",
                    help="Publish immediately (default: hidden from public view)")
    ap.add_argument("--no-registration", action="store_true",
                    help="Do not enable online registration on the new tournament")
    args = ap.parse_args()

    month, day, year = args.date.split("/")
    data = {
        "name": args.name,
        "month": month.zfill(2), "day": day.zfill(2), "year": year,
        "tournament_public": "1" if args.public else "0",
        "new_paypal_account": "",
        "save": "Copy Tournament",
    }
    if not args.no_registration:
        data["registration"] = "1"

    url = f"{BASE}/tournaments/{args.source}/copy"
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": url,
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req)
        status, location = resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        status, location = e.code, e.headers.get("Location", "")

    out = {"status": status, "location": location,
           "success": bool(location) and status in (301, 302, 303)}
    if location:
        out["slug"] = location.rstrip("/").rsplit("/", 1)[-1]
    print(json.dumps(out, indent=2))
    if not out["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
