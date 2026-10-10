#!/usr/bin/env python3
"""StatMando data client — disc golf player history, field strength, and stats.

StatMando (statmando.com) publishes, per player, a full result history with an
`evt_rtg` column = the numeric STRENGTH OF FIELD for each event (DGPT/Elite Series
~1000-1022, Majors ~970, regional/masters ~900-910). That field rating is the key
datum: it lets you weight a result by how strong the field actually was, instead of
relying on PDGA tier labels.

robots.txt allows all; pages are server-rendered HTML (no JS execution needed).
This is a polite, single-threaded scraper (~1s spacing). Be a good citizen.

Commands (all emit JSON to stdout):
  player <name|slug> [--since YEAR]   full profile: history (with evt_rtg) + totals
  resolve <name>                      name -> {slug, statmando_name, url, found}
  directory <query>                   /players directory search -> [{name, slug, division}]

Importable: to_slug, fetch, parse_history, parse_totals, resolve, player_profile.
"""
import html as _html
import json, re, sys, time, urllib.parse, urllib.request

BASE = "https://statmando.com"
UA = {"User-Agent": "Mozilla/5.0"}
HIST_COLS = ["event", "month", "year", "evt_rtg", "place", "strokes", "cash",
             "state", "country", "division", "tier", "tour", "date"]


# ---------------------------------------------------------------- http + text
def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")


def clean(s):
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", s))).strip()


def to_slug(name):
    """StatMando slug: drop non-ASCII chars entirely, lowercase, hyphenate.
    e.g. 'Anneli Tõugjas-Männiste' -> 'anneli-tugjas-mnniste'."""
    s = name.encode("ascii", "ignore").decode().lower().replace("'", "").replace(".", "")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def _tokens(s):
    return [t for t in re.sub(r"[^a-z0-9]+", " ",
            s.encode("ascii", "ignore").decode().lower()).split() if t]


def _fold(s):
    return set(_tokens(s))


def looks_like_slug(arg):
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", arg))


# ---------------------------------------------------------------- parsing
def h1_name(html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    return clean(m.group(1)) if m else ""


def name_matches(expected, got):
    et, gt = _tokens(expected), _tokens(got)
    e, g = set(et), set(gt)
    if not g or not et:
        return False
    return et[-1] in g and len(e & g) >= min(2, len(e))


def parse_history(html, since_year=None):
    m = re.search(r'<table id="history"[^>]*>(.*?)</table>', html, re.S)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) != 13:
            continue
        rec = dict(zip(HIST_COLS, (clean(x) for x in tds)))
        try:
            rec["year"] = int(rec["year"])
        except ValueError:
            continue
        if since_year and rec["year"] < since_year:
            continue
        for k in ("evt_rtg", "place", "strokes"):
            try:
                rec[k] = int(rec[k])
            except (ValueError, TypeError):
                rec[k] = None
        out.append(rec)
    return out


def parse_totals(html):
    """totals-table: WINS / PODIUM / TOP-10 / CASHED / EVENTS (career or filtered)."""
    m = re.search(r'<table id="totals-table"[^>]*>(.*?)</table>', html, re.S)
    if not m:
        return {}
    cells = [clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", m.group(1), re.S)]
    cells = [c for c in cells if c != ""]
    out = {}
    labels = {"WINS": "wins", "PODIUM": "podiums", "TOP-10": "top10",
              "CASHED": "cashed", "EVENTS": "events"}
    for i, c in enumerate(cells):
        key = labels.get(c.upper())
        if key and i + 1 < len(cells):
            try:
                out[key] = int(re.sub(r"[^\d]", "", cells[i + 1]) or 0)
            except ValueError:
                pass
    return out


def pdga_number(html):
    m = re.search(r"pdga\.com/player/(\d+)", html, re.I)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- resolution
def directory(query):
    """Search the /players directory -> [{name, slug, division}]."""
    try:
        html = fetch(f"{BASE}/players?q={urllib.parse.quote(query)}")
    except Exception:
        return []
    out, seen = [], set()
    for m in re.finditer(r'/player/([a-z0-9\-]+)/profile"[^>]*>(.*?)</a>', html, re.S):
        slug = m.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        txt = clean(m.group(2))
        mm = re.match(r"(.*?)\s+(MPO|FPO|[MF][AP]\d+|[MF][JP]\d+|MA\d+|FA\d+)?\s*$", txt)
        out.append({"name": (mm.group(1) if mm else txt).strip(),
                    "slug": slug, "division": (mm.group(2) if mm and mm.group(2) else None)})
    return out


def _is_index_page(html):
    """Unknown slugs 302-redirect to the /players index (h1 'StatMando Player Profiles')."""
    return "StatMando Player Profiles" in h1_name(html)


def _profile_html(name_or_slug):
    """Resolve to (slug, html, method) with a single fetch in the common case.
    Returns (slug, None, None) if no matching profile."""
    if looks_like_slug(name_or_slug):
        slug = name_or_slug
        try:
            html = fetch(f"{BASE}/player/{slug}/profile")
        except Exception:
            return slug, None, None
        return (slug, None, None) if (not h1_name(html) or _is_index_page(html)) else (slug, html, "slug")
    name = name_or_slug
    slug = to_slug(name)
    try:
        html = fetch(f"{BASE}/player/{slug}/profile")
        if name_matches(name, h1_name(html)):
            return slug, html, "slug"
    except Exception:
        pass
    # directory fallback by last name (featured-players list only)
    toks = _tokens(name)
    last_tok = toks[-1] if toks else ""
    want = set(toks)
    best, score = None, 0
    for row in directory(last_tok):
        st = set(row["slug"].split("-"))
        sc = len(want & st)
        if last_tok in st and sc > score:
            best, score = row["slug"], sc
    if best and best != slug:
        try:
            html = fetch(f"{BASE}/player/{best}/profile")
            if name_matches(name, h1_name(html)):
                return best, html, "directory"
        except Exception:
            pass
    return slug, None, None


def resolve(name):
    """name -> {slug, statmando_name, url, found, method}."""
    slug, html, method = _profile_html(name)
    found = bool(html and method)
    return {"slug": slug, "statmando_name": h1_name(html) if found else None,
            "url": f"{BASE}/player/{slug}/profile", "found": found, "method": method}


def player_profile(name_or_slug, since_year=None):
    slug, html, method = _profile_html(name_or_slug)
    if not html:
        return {"query": name_or_slug, "found": False, "slug": slug}
    return {
        "query": name_or_slug, "found": True, "slug": slug, "name": h1_name(html),
        "url": f"{BASE}/player/{slug}/profile", "pdga": pdga_number(html),
        "resolution": method, "totals": parse_totals(html),
        "history": parse_history(html, since_year),
    }


# ---------------------------------------------------------------- cli
def main(argv):
    if not argv:
        print(__doc__); return 1
    cmd, rest = argv[0], argv[1:]
    since = None
    if "--since" in rest:
        i = rest.index("--since")
        since = int(rest[i + 1]); rest = rest[:i] + rest[i + 2:]
    arg = " ".join(rest).strip()
    if cmd == "player":
        out = player_profile(arg, since)
    elif cmd == "resolve":
        out = resolve(arg)
    elif cmd == "directory":
        out = directory(arg)
    else:
        print(json.dumps({"error": f"unknown command '{cmd}'"})); return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
