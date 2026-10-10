#!/usr/bin/env python3
"""Generate printable tournament scorecards from normalized layout JSON.

Consumes layout files produced by `pdga.py layout` (source: PDGA Live or
Parkdly). Each layout becomes one HTML file: page 1 = scorecard (3-up),
page 2 = hole notes (3-up). Print duplex, cut into thirds.

The notes page aligns behind its scorecard by one of two equivalent duplex
schemes (`--flip`):
  * long  (default) — notes upright, print duplex flipping on the LONG edge.
                      Reads right-side-up on screen; the digital-friendly default.
  * short            — notes rotated 180°, flip on the SHORT edge (legacy
                      behavior; the PDF's notes page is upside down on screen).

Usage:
    python3 build-scorecards.py layout-*.json --title "2026 My Open" --out-dir ./scorecards --pdf
"""

import argparse
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Default header colors, cycled across input files. Override with --colors.
DEFAULT_COLORS = [
    "#2C4A2E",  # forest green
    "#1E3A5C",  # creek blue
    "#6B5B2E",  # meadow gold
    "#4A2C44",  # plum
    "#5C2E1E",  # rust
    "#2E4A4A",  # slate
]


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(rgb, other, ratio):
    """Mix rgb toward other by ratio (0 = rgb, 1 = other)."""
    return "#" + "".join(f"{round(c + (o - c) * ratio):02x}" for c, o in zip(rgb, other))


def derive_colors(bg_hex):
    """Build a full color set (header text, accent text, tints) from one bg color.

    Light backgrounds (e.g. brand yellows) get dark header text and a darkened
    accent so titles/par numbers stay readable on white.
    """
    rgb = _hex_to_rgb(bg_hex)
    luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    is_light = luminance > 0.55
    return {
        "bg": bg_hex,
        "fg": "#1a1a1a" if is_light else "#ffffff",
        "accent": _mix(rgb, (0, 0, 0), 0.55) if is_light else bg_hex,
        "light": _mix(rgb, (255, 255, 255), 0.88),
        "stripe": _mix(rgb, (255, 255, 255), 0.93),
    }

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome"),
    shutil.which("chromium"),
]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "x").lower()).strip("-") or "x"


def clean_note(text):
    """Collapse tee-sign note paragraphs into one compact line."""
    if not text:
        return ""
    lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    joined = " ".join(lines)
    joined = re.sub(r"^hole notes:\s*", "", joined, flags=re.I)
    return html.escape(joined)


def note_type_scale(layout):
    """Pick note font size/line-height so heavy note sets fit the 1/3-page card."""
    total = sum(len(clean_note(h.get("notes"))) for h in layout["holes"])
    if total <= 2600:
        return "8px", "1.3"
    if total <= 4500:
        return "7px", "1.25"
    return "6.4px", "1.2"


def card_meta(layout, subtitle):
    t = layout["totals"]
    parts = [layout["layout"]]
    used = layout.get("used_by") or []
    rounds = sorted({u["round"] for u in used if u.get("round")})
    if rounds:
        parts.append("Rd " + "/".join(str(r) for r in rounds))
    parts.append(f'{t["holes"]}h')
    parts.append(f'Par {t["par"]}')
    if t.get("distance_ft"):
        parts.append(f'{t["distance_ft"]:,}ft')
    if subtitle:
        parts.append(subtitle)
    return " &bull; ".join(html.escape(str(p)) for p in parts)


def build_front_card(layout, title, subtitle, players, logo_html=""):
    holes = layout["holes"]
    has_tee_row = any(h.get("tee") for h in holes)

    hole_cells = "".join(f'<th class="hole-col">{html.escape(h["label"])}</th>\n' for h in holes)
    tee_cells = "".join(f'<td class="info-cell tee-cell">{html.escape(str(h.get("tee") or ""))}</td>\n' for h in holes)
    par_cells = "".join(f'<td class="info-cell par-cell">{h["par"]}</td>\n' for h in holes)
    dist_cells = "".join(f'<td class="info-cell dist-cell">{h["distance_ft"] or ""}</td>' for h in holes)

    # label/total header cells span the rows above the dist-row (which has its own header cells)
    header_rowspan = 3 if has_tee_row else 2
    tee_row = f'<tr class="info-row">{tee_cells}</tr>\n' if has_tee_row else ""

    player_rows = ""
    for _ in range(players):
        score_cells = "".join('<td class="score-cell"></td>\n' for _ in holes)
        player_rows += f'<tr class="player-row"><td class="name-cell"></td>\n{score_cells}<td class="score-cell total-score"></td></tr>\n'

    return f"""<div class="card">
  <div class="card-header">
    <div class="card-title">{html.escape(title)} &mdash; {html.escape(layout["course"])}</div>
    <div class="card-meta">{card_meta(layout, subtitle)}</div>
    {logo_html}
  </div>
  <table>
    <tr>
      <th class="label-col" rowspan="{header_rowspan}"></th>
      {hole_cells}
      <th class="total-header" rowspan="{header_rowspan}">Tot</th>
    </tr>
    {tee_row}<tr class="info-row">{par_cells}</tr>
    <tr class="dist-row">
      <th class="name-header">Player</th>
      {dist_cells}
      <td class="total-info">{layout["totals"]["par"]}</td>
    </tr>
    {player_rows}
  </table>
</div>"""


def build_notes_card(layout, title, subtitle, logo_html=""):
    holes = layout["holes"]
    mid = (len(holes) + 1) // 2

    def note_rows(items):
        return "".join(
            f'<tr>\n  <td class="note-hole">{html.escape(h["label"])}</td>\n'
            f'  <td class="note-text">{clean_note(h.get("notes"))}</td>\n</tr>\n'
            for h in items
        )

    layout_note = ""
    if layout.get("notes"):
        layout_note = f'<div class="layout-note">{clean_note(layout["notes"])}</div>'

    return f"""<div class="card notes-card">
  <div class="card-header">
    <div class="card-title">{html.escape(title)} &mdash; {html.escape(layout["course"])}</div>
    <div class="card-meta">{card_meta(layout, subtitle)} &bull; Hole Notes</div>
    {logo_html}
  </div>
  {layout_note}
  <div class="notes-columns">
    <table class="notes-table">
      {note_rows(holes[:mid])}
    </table>
    <table class="notes-table">
      {note_rows(holes[mid:])}
    </table>
  </div>
</div>"""


def build_html(layout, title, subtitle, players, colors, flip="long", logo_html=""):
    pc = colors
    note_font, note_line = note_type_scale(layout)
    front = build_front_card(layout, title, subtitle, players, logo_html)
    has_notes = any((h.get("notes") or "").strip() for h in layout["holes"]) or layout.get("notes")
    back = build_notes_card(layout, title, subtitle, logo_html) if has_notes else None

    # Only the short-edge scheme rotates the notes page 180°; the long-edge
    # default keeps it upright so it reads correctly on screen.
    back_page_class = "page back-page" + (" back-rotate" if flip == "short" else "")
    flip_comment = "rotated for short-edge flip" if flip == "short" else "upright, long-edge flip"

    front_page_class = "page page-break" if back else "page"
    back_html = f"""
  <!-- BACK: Hole Notes ({flip_comment}) -->
  <div class="{back_page_class}">
{back}
{back}
{back}
  </div>""" if back else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)} — {html.escape(layout["course"])} {html.escape(layout["layout"])} Scorecard</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 0.25in 0.3in;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 9px;
      color: #1a1a1a;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .page {{
      width: 100%;
      max-width: 8in;
      margin: 0 auto;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    /* Card container — each card fills 1/3 of the page */
    .card {{
      height: calc(100vh / 3 - 4px);
      display: flex;
      flex-direction: column;
      justify-content: center;
      border-bottom: 1px dashed #ccc;
      overflow: hidden;
    }}
    /* Notes card is dense — fill the third rather than center a short block */
    .notes-card {{
      justify-content: flex-start;
    }}
    .card:last-child {{
      border-bottom: none;
    }}

    /* Compact header */
    .card-header {{
      display: flex;
      align-items: baseline;
      gap: 8px;
      margin-bottom: 3px;
      border-bottom: 2px solid {pc["bg"]};
      padding-bottom: 2px;
    }}
    .card-title {{
      font-size: 11px;
      font-weight: 900;
      text-transform: uppercase;
      color: {pc["accent"]};
      letter-spacing: 0.02em;
      white-space: nowrap;
    }}
    .card-meta {{
      font-size: 8px;
      color: #777;
      white-space: nowrap;
    }}
    .card-logo {{
      height: 26px;
      width: auto;
      margin-left: auto;
      align-self: center;
      flex-shrink: 0;
    }}

    /* ========== SCORECARD TABLE (front) ========== */
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid #bbb;
      text-align: center;
      vertical-align: middle;
    }}

    .label-col {{
      width: 160px;
      min-width: 160px;
      background: {pc["bg"]};
      color: {pc["fg"]};
      font-weight: 700;
      font-size: 6px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 1px 2px;
      border-color: {pc["bg"]};
    }}
    .hole-col {{
      background: {pc["bg"]};
      color: {pc["fg"]};
      font-weight: 900;
      font-size: 9px;
      padding: 2px 0;
      border-color: {pc["bg"]};
      height: 18px;
    }}
    .info-row td, .info-row th {{ height: 14px; }}
    .dist-row td, .dist-row th {{ height: 16px; }}
    .info-cell {{
      padding: 1px 0;
      font-size: 8px;
      background: {pc["light"]};
    }}
    .tee-cell {{
      font-size: 7px;
      font-weight: 600;
      color: #555;
      text-transform: uppercase;
    }}
    .par-cell {{
      font-weight: 800;
      color: {pc["accent"]};
      font-size: 9px;
    }}
    .dist-cell {{
      font-size: 7px;
      color: #666;
    }}
    .name-header {{
      width: 160px;
      min-width: 160px;
      background: {pc["bg"]};
      color: {pc["fg"]};
      font-weight: 700;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 2px 6px;
      border-color: {pc["bg"]};
      text-align: left;
    }}
    .name-cell {{
      width: 160px;
      min-width: 160px;
      text-align: left;
      padding: 2px 6px;
      font-size: 12px;
    }}
    .total-header {{
      background: {pc["bg"]};
      color: {pc["fg"]};
      font-weight: 700;
      font-size: 7px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 2px 1px;
      border-color: {pc["bg"]};
      width: 28px;
      min-width: 28px;
    }}
    .total-info {{
      background: {pc["light"]};
      font-weight: 800;
      font-size: 9px;
      color: {pc["accent"]};
      padding: 1px;
    }}
    .total-score {{
      background: {pc["light"]};
      font-weight: 900;
    }}
    /* Fixed writing-line height keeps rows compact and leaves buffer above the cut line */
    .player-row td {{ height: 40px; }}
    .player-row:nth-child(even) .score-cell {{ background: {pc["stripe"]}; }}
    .player-row:nth-child(even) .name-cell {{ background: {pc["stripe"]}; }}
    .player-row:nth-child(even) .total-score {{ background: {pc["light"]}; }}

    /* ========== NOTES CARD (back) ========== */
    .notes-card {{
      padding: 0 4px;
    }}
    .layout-note {{
      font-size: 8px;
      font-weight: 600;
      color: {pc["accent"]};
      padding: 1px 4px 2px;
    }}
    .notes-columns {{
      display: flex;
      gap: 12px;
      flex: 1;
      align-items: flex-start;
    }}
    .notes-table {{
      flex: 1;
      table-layout: auto;
      border-collapse: collapse;
    }}
    .notes-table td {{
      border: none;
      border-bottom: 1px solid #ddd;
      text-align: left;
      vertical-align: top;
      padding: 3px 4px;
    }}
    .note-hole {{
      font-weight: 900;
      font-size: 10px;
      color: {pc["accent"]};
      width: 28px;
      white-space: nowrap;
      vertical-align: top;
    }}
    .note-text {{
      font-size: {note_font};
      line-height: {note_line};
      color: #333;
    }}

    /* ========== PAGE BREAK ========== */
    .page-break {{
      page-break-after: always;
      break-after: page;
    }}

    /* Back page rotated 180° only for the legacy short-edge duplex scheme */
    .back-rotate {{
      transform: rotate(180deg);
    }}

    @media print {{
      body {{ margin: 0; }}
      .page {{ max-width: none; }}
    }}
  </style>
</head>
<body>
  <!-- FRONT: Scorecards -->
  <div class="{front_page_class}">
{front}
{front}
{front}
  </div>
{back_html}
</body>
</html>"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


def html_to_pdf(chrome, html_path, pdf_path):
    proc = subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not Path(pdf_path).exists():
        sys.stderr.write(f"Chrome PDF failed for {html_path}:\n{proc.stderr.strip()}\n")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate printable scorecards from layout JSON")
    parser.add_argument("files", nargs="+", help="Layout JSON files from `pdga.py layout`")
    parser.add_argument("--title", default=None, help="Event title on the card (default: layout's event name)")
    parser.add_argument("--subtitle", default=None, help="Extra meta text, e.g. a date")
    parser.add_argument("--players", type=int, default=5, help="Blank player rows per card (default 5)")
    parser.add_argument("--colors", default=None,
                        help="Comma-separated header hex colors cycled across files, e.g. '#1f3a5f,#2a9d8f,#e9c46a'. Tints and text contrast are derived automatically")
    parser.add_argument("--out-dir", dest="out_dir", default="./scorecards")
    parser.add_argument("--flip", choices=["long", "short"], default="long",
                        help="Duplex scheme: 'long' (default) keeps the notes page upright "
                             "(digitally readable; print duplex flipping on the long edge); "
                             "'short' rotates it 180° for the legacy short-edge flip")
    parser.add_argument("--logo", default=None,
                        help="Path to a logo (SVG/PNG/JPG) embedded in each card header as a "
                             "base64 data URI. Use a tightly-cropped/print-ready asset — padded "
                             "logos render small")
    parser.add_argument("--pdf", action="store_true", help="Also render PDFs via headless Chrome")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    chrome = find_chrome() if args.pdf else None
    if args.pdf and not chrome:
        sys.stderr.write("No Chrome/Chromium found for --pdf. Set CHROME_PATH or install Chrome.\n")
        sys.exit(1)

    bg_colors = [c.strip() for c in args.colors.split(",")] if args.colors else DEFAULT_COLORS
    palette = [derive_colors(c) for c in bg_colors]

    logo_html = ""
    if args.logo:
        logo_path = Path(args.logo)
        mime = {"svg": "image/svg+xml", "png": "image/png",
                "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
            logo_path.suffix.lower().lstrip("."), "image/png")
        b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        logo_html = f'<img class="card-logo" src="data:{mime};base64,{b64}" alt="">'

    manifest = []
    for i, f in enumerate(args.files):
        layout = json.loads(Path(f).read_text())
        title = args.title or layout.get("event") or "Tournament"
        colors = palette[i % len(palette)]

        stem = f'scorecard-{slugify(layout["course"])}-{slugify(layout["layout"])}'
        html_path = out_dir / f"{stem}.html"
        html_path.write_text(build_html(layout, title, args.subtitle, args.players, colors, args.flip, logo_html))
        entry = {"course": layout["course"], "layout": layout["layout"], "html": str(html_path)}

        if chrome:
            pdf_path = out_dir / f"{stem}.pdf"
            if html_to_pdf(chrome, html_path, pdf_path):
                entry["pdf"] = str(pdf_path)
        manifest.append(entry)
        sys.stderr.write(f"Generated {stem}\n")

    json.dump({"outDir": str(out_dir), "scorecards": manifest}, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
