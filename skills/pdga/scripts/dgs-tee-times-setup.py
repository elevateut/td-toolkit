#!/usr/bin/env python3
"""Install a self-service Tee Time option on a DGS tournament's registration form.

Players pick their own tee time at registration; DGS enforces a per-slot player
cap and shows a public tee sheet (e.g. "8:10 am  2/4") on the registration page.
Useful for practice rounds, flex-start days, or any event that wants self-service tee times.

Optionally deletes all existing registration options and custom questions first
(--clean; use on tournaments created with dgs-copy-tournament.py, which drag the
source event's add-ons along).

Usage:
  dgs-tee-times-setup.py <slug> --start 08:00am --end 04:00pm --interval 10 \
      --group-size 4 [--clean] [--option-description "..."] [--welcome "..."] [--dry-run]

Notes:
- DGS generates slots on whole-hour boundaries from start/end hour (its own UI
  hardcodes :00 minutes), every <interval> minutes, <group-size> players each.
- The Tee Time option is set required, with public selections (visible tee sheet).
- POSTs the FULL registration form (browser-faithful serialization), so anything
  else on that page (waiver, welcome message, other options unless --clean) is
  preserved as-is.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://www.discgolfscene.com"


def cookie_header():
    cj = json.load(open(os.path.expanduser(os.environ.get("DGS_COOKIE_FILE") or "~/.dgs-cookies.json")))
    cookies = cj.get("cookies", cj)
    if isinstance(cookies, list):
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def fetch(url, headers=None):
    h = {"User-Agent": "Mozilla/5.0", "Cookie": cookie_header()}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req).read().decode("utf-8", "replace")


class FormSerializer(HTMLParser):
    """Serialize a form's controls the way a browser would on submit.

    Targets the settings form (<form ... class="container top-section">).
    Hidden/text inputs always submit; checkboxes/radios only when checked;
    selects submit the selected (or first) option; textareas submit their text.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.form_depth = 0
        self.pairs = []
        self.select_name = None
        self.select_first = None
        self.select_selected = None
        self.select_has_selected = False
        self.in_option = False
        self.option_value = None
        self.textarea_name = None
        self.textarea_buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            cls = a.get("class", "")
            if not self.in_form and "top-section" in cls:
                self.in_form = True
                self.form_depth = 1
            elif self.in_form:
                self.form_depth += 1
            return
        if not self.in_form:
            return
        if tag == "input":
            name = a.get("name")
            if not name:
                return
            typ = (a.get("type") or "text").lower()
            if typ in ("submit", "button", "file", "image"):
                return
            if typ in ("checkbox", "radio") and "checked" not in a:
                return
            self.pairs.append((name, a.get("value", "on" if typ in ("checkbox", "radio") else "")))
        elif tag == "select":
            self.select_name = a.get("name")
            self.select_first = None
            self.select_selected = None
            self.select_has_selected = False
        elif tag == "option" and self.select_name is not None:
            self.in_option = True
            self.option_value = a.get("value")
            if self.select_first is None:
                self.select_first = self.option_value if self.option_value is not None else ""
            if "selected" in a:
                self.select_has_selected = True
                self.select_selected = self.option_value if self.option_value is not None else ""
        elif tag == "textarea":
            self.textarea_name = a.get("name")
            self.textarea_buf = []

    def handle_data(self, data):
        if self.textarea_name is not None:
            self.textarea_buf.append(data)
        elif self.in_option and self.option_value is None:
            self.option_value = data.strip()
            if self.select_first is None:
                self.select_first = self.option_value

    def handle_endtag(self, tag):
        if tag == "form" and self.in_form:
            self.form_depth -= 1
            if self.form_depth <= 0:
                self.in_form = False
            return
        if not self.in_form:
            return
        if tag == "select" and self.select_name is not None:
            val = self.select_selected if self.select_has_selected else (self.select_first or "")
            self.pairs.append((self.select_name, val))
            self.select_name = None
        elif tag == "option":
            self.in_option = False
        elif tag == "textarea" and self.textarea_name is not None:
            self.pairs.append((self.textarea_name, "".join(self.textarea_buf)))
            self.textarea_name = None


class FragmentSerializer(FormSerializer):
    """Same, but AJAX fragments have no <form> wrapper."""

    def __init__(self):
        super().__init__()
        self.in_form = True
        self.form_depth = 999


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--start", default="08:00am", help="First tee time, e.g. 08:00am")
    ap.add_argument("--end", default="04:00pm", help="Last tee time, e.g. 04:00pm")
    ap.add_argument("--interval", default="10", help="Minutes between tee times (5-30)")
    ap.add_argument("--group-size", default="4", help="Players per tee time (3-5)")
    ap.add_argument("--clean", action="store_true",
                    help="Delete ALL existing options and custom questions")
    ap.add_argument("--option-description", default="",
                    help="Description text shown under the Tee Time option")
    ap.add_argument("--welcome", default=None,
                    help="Replace the registration welcome message")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    regform_url = f"{BASE}/tournaments/{args.slug}/admin/registration-form"
    page = fetch(regform_url)
    ser = FormSerializer()
    ser.feed(page)
    if not ser.pairs:
        print(json.dumps({"error": "no form fields parsed (cookies expired?)"}))
        sys.exit(1)

    existing_opts = sorted({m.group(1) for m in re.finditer(r"tournament\[options\]\[(\d+)\]", page)})
    existing_custom = sorted({m.group(1) for m in re.finditer(r"tournament\[custom\]\[(\d+)\]", page)})

    out = []
    for n, v in ser.pairs:
        if args.clean and re.match(r"tournament\[(options|custom)\]\[\d+\]\[delete\]$", n):
            v = "1"
        if args.welcome is not None and n == "tournament[welcome_message]":
            v = args.welcome
        out.append((n, v))

    params = urllib.parse.urlencode(
        {"start": args.start, "end": args.end,
         "interval": args.interval, "group_size": args.group_size}
    )
    frag_html = json.loads(fetch(
        f"{BASE}/tournaments/{args.slug}/admin/new-tee-times-option?{params}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ))
    opt_ids = set(re.findall(r"tournament\[options\]\[(new_\d+)\]", frag_html))
    if len(opt_ids) != 1:
        print(json.dumps({"error": f"unexpected option ids in fragment: {sorted(opt_ids)}"}))
        sys.exit(1)
    opt_id = opt_ids.pop()
    slot_count = len(re.findall(r"\[values\]\[[^\]]+\]\[name\]", frag_html))

    fser = FragmentSerializer()
    fser.feed(frag_html)
    have_description = False
    for n, v in fser.pairs:
        if n == f"tournament[options][{opt_id}][priority]":
            v = "1"
        if n == f"tournament[options][{opt_id}][description]":
            v = args.option_description
            have_description = True
        out.append((n, v))
    if not have_description:
        out.append((f"tournament[options][{opt_id}][description]", args.option_description))
    # required + public tee sheet; duplicate keys are fine (server takes the last)
    out.append((f"tournament[options][{opt_id}][required]", "1"))
    out.append((f"tournament[options][{opt_id}][public_selections]", "1"))
    out.append(("save", "Save Changes"))

    summary = {
        "slug": args.slug,
        "clean": args.clean,
        "options_deleted": existing_opts if args.clean else [],
        "custom_deleted": existing_custom if args.clean else [],
        "tee_time_slots": slot_count,
        "start": args.start, "end": args.end,
        "interval": args.interval, "group_size": args.group_size,
        "total_fields": len(out),
    }
    if args.dry_run:
        summary["dry_run"] = True
        print(json.dumps(summary, indent=2))
        return

    req = urllib.request.Request(
        regform_url,
        data=urllib.parse.urlencode(out).encode(),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": regform_url,
        },
    )
    resp = urllib.request.urlopen(req)
    summary["post_status"] = resp.status

    page2 = fetch(regform_url)
    summary["options_after"] = {
        m.group(1): m.group(2)
        for m in re.finditer(r'tournament-settings-option-(\d+)\">.*?<strong>([^<]+)</strong>',
                             page2, flags=re.S)
    }
    summary["custom_after"] = sorted(
        {m.group(1) for m in re.finditer(r"tournament\[custom\]\[(\d+)\]", page2)}
    )
    summary["slots_after"] = len(re.findall(r"\[values\]\[\d+\]\[name\]", page2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
