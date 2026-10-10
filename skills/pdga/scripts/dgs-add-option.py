#!/usr/bin/env python3
"""Add a choice-list option (merch sizes, lodging, etc.) to a DGS registration form.

Usage:
  dgs-add-option.py <slug> --name "Sun Hoodie" [--description "..."] \
      --choice "Small:45:10" --choice "Medium:45:15" --choice "No thanks::" \
      [--required] [--public] [--dry-run]

Each --choice is "Label:amount:quantity". Amount and quantity may be blank
(blank amount = free choice, blank quantity = unlimited). Choices keep the
order given.

DGS has two add-on kinds on admin/registration-form:
  - Additional Items (tournament[addons]): one checkbox, one price.
  - Options (tournament[options]): a list of choices, each with its own price
    and quantity_available. Use this script for anything with sizes or tiers.

POSTs the FULL registration form (browser-faithful serialization, shared with
dgs-tee-times-setup.py), so every existing option, item, custom field, waiver
and welcome message goes back unchanged. Refuses if an option with the same
name already exists. After posting it re-reads the form and verifies that
every pre-existing field came back identical and the new option is present.
"""
import argparse
import importlib.util
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

_here = pathlib.Path(__file__).parent
_spec = importlib.util.spec_from_file_location("dgs_tee_times", _here / "dgs-tee-times-setup.py")
tt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tt)


def form_pairs(url):
    page = tt.fetch(url)
    ser = tt.FormSerializer()
    ser.feed(page)
    return page, ser.pairs


def option_names(pairs):
    return {m.group(1): v for n, v in pairs
            if (m := re.match(r"tournament\[options\]\[([^\]]+)\]\[name\]$", n))}


def parse_choice(spec):
    parts = spec.rsplit(":", 2)
    if len(parts) != 3 or not parts[0].strip():
        sys.exit(f"bad --choice {spec!r}: expected 'Label:amount:quantity'")
    label, amount, qty = (p.strip() for p in parts)
    for what, val in (("amount", amount), ("quantity", qty)):
        if val and not re.fullmatch(r"-?\d+(\.\d{1,2})?", val):
            sys.exit(f"bad {what} {val!r} in --choice {spec!r}")
    return label, amount, qty


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--name", required=True, help="Option title shown at checkout")
    ap.add_argument("--description", default="", help="Text shown under the title")
    ap.add_argument("--choice", action="append", required=True,
                    help="'Label:amount:quantity', repeat per choice")
    ap.add_argument("--required", action="store_true", help="Registrant must pick a choice")
    ap.add_argument("--public", action="store_true", help="Show selections publicly")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    choices = [parse_choice(c) for c in args.choice]
    url = f"{tt.BASE}/tournaments/{args.slug}/admin/registration-form"
    _, before = form_pairs(url)
    if not before:
        sys.exit(json.dumps({"error": "no form fields parsed (cookies expired?)"}))
    existing = option_names(before)
    if args.name.strip().lower() in {v.strip().lower() for v in existing.values()}:
        sys.exit(json.dumps({"error": f"option {args.name!r} already exists", "options": existing}))

    stamp = int(time.time() * 1_000_000)
    oid = f"new_{stamp}"
    p = f"tournament[options][{oid}]"
    new = [(f"{p}[priority]", "0"), (f"{p}[delete]", "0"),
           (f"{p}[name]", args.name), (f"{p}[description]", args.description)]
    for i, (label, amount, qty) in enumerate(choices, 1):
        v = f"{p}[values][new_{stamp + i}]"
        new += [(f"{v}[name]", label), (f"{v}[amount]", amount),
                (f"{v}[quantity_available]", qty), (f"{v}[priority]", str(i)),
                (f"{v}[delete]", "0")]
    new += [(f"{p}[division_selection]", "all"),
            (f"{p}[required]", "0"), *([(f"{p}[required]", "1")] if args.required else []),
            (f"{p}[public_selections]", "0"), *([(f"{p}[public_selections]", "1")] if args.public else []),
            (f"{p}[expiration][month]", "00"), (f"{p}[expiration][day]", "00"),
            (f"{p}[expiration][year]", "0000"), (f"{p}[expiration][hour]", "00"),
            (f"{p}[expiration][minute]", "00"), (f"{p}[expiration][meridiem]", "am")]

    summary = {"slug": args.slug, "name": args.name, "description": args.description,
               "choices": [{"label": l, "amount": a, "quantity": q} for l, a, q in choices],
               "required": args.required, "public": args.public,
               "existing_options": list(existing.values()), "fields_posted": len(before) + len(new) + 1}
    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2))
        return

    body = urllib.parse.urlencode(before + new + [("save", "Save Changes")]).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0", "Cookie": tt.cookie_header(),
        "Content-Type": "application/x-www-form-urlencoded", "Referer": url})
    summary["post_status"] = urllib.request.urlopen(req).status

    _, after = form_pairs(url)
    after_opts = option_names(after)
    new_ids = [k for k, v in after_opts.items() if k not in existing and v == args.name]
    kept = Counter(pr for pr in after
                   if not any(pr[0].startswith(f"tournament[options][{k}]") for k in new_ids))
    summary["existing_fields_unchanged"] = kept == Counter(before)
    if not summary["existing_fields_unchanged"]:
        summary["changed"] = {"missing": sorted(set(before) - set(kept))[:20],
                              "extra": sorted(set(kept) - set(before))[:20]}
    if new_ids:
        oid = new_ids[0]
        summary["option_id"] = oid
        summary["saved_choices"] = [
            {"label": v, **{f: dict(after).get(n.replace("[name]", f"[{f}]"), "")
                            for f in ("amount", "quantity_available")}}
            for n, v in after if re.match(rf"tournament\[options\]\[{oid}\]\[values\]\[\d+\]\[name\]$", n)]
    summary["success"] = bool(new_ids) and summary["existing_fields_unchanged"] \
        and len(summary.get("saved_choices", [])) == len(choices)
    print(json.dumps(summary, indent=2))
    if not summary["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
