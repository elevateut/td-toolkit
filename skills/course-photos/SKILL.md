---
name: course-photos
description: Pull your own photos of a disc golf course out of the Apple Photos library on this Mac by matching GPS against the course's UDisc location and per-hole layout. Scans the library's geotag table, exports the originals through Photos.app (forces the iCloud download), converts HEIC to JPEG, reads EXIF GPS off the export, assigns each frame to a hole, renames, and writes an index plus a labelled contact sheet. Also handles a date-window pull for iCloud-only assets that carry no location in the local database. Use when a campaign, a caddie book, a presentation, a grant report or a UDisc listing needs real photos of a course you have played or worked on. Triggers - "pull my photos of <course>", "what do I have of <course>", "course photos from my library", "geotagged photos near <course>", "which hole is this photo".
---

# Course photos from the Photos library

`scripts/course_photos.py` — read-only against the Photos library
(`$PHOTOS_LIBRARY`, or `--library`, default `~/Pictures/Photos Library.photoslibrary`).
macOS only. Needs `exiftool`, `sips`, `magick`, and the sibling `udisc` skill (for course
coordinates and layouts; found next to this skill, or under `$CLAUDE_SKILLS_ROOT`).

## How it works, and the two traps

1. **Location lives in `ZEXTENDEDATTRIBUTES`, not `ZASSET`.** `ZASSET.ZLATITUDE` is `-180` for
   almost every row. Join `ZASSET.ZEXTENDEDATTRIBUTES = ZEXTENDEDATTRIBUTES.Z_PK` and read
   `ZLATITUDE/ZLONGITUDE` there. Only ~10% of assets may have a location in the local DB at all,
   because "Optimize Mac Storage" keeps the rest as cloud-only stubs. The exported originals DO
   carry EXIF GPS, so the script re-reads GPS after export.
2. **Originals are in iCloud.** `originals/<x>/<uuid>.*` is empty for cloud-only assets and the
   local derivative is 768x1024. The only reliable pull is `Photos.app` AppleScript
   `export {media item id "<uuid>/L0/001"} to folder with using originals`, one item at a time,
   240 s timeout each. Budget ~10 s per photo. Live-photo `.mov` sidecars are dropped.
3. `magick -annotate` fails with `unable to read font ''` on a bare install; the sheet command
   passes a system font (`/System/Library/Fonts/Supplemental/Arial.ttf` or similar) explicitly.

The first export triggers a macOS Automation prompt (Terminal → Photos); allow it.

## Commands

```bash
S=<skills-dir>/course-photos/scripts/course_photos.py

# what do I have near a course (geotagged only)
python3 $S scan <udisc-course-slug> --radius 400
python3 $S scan --lat 45.5200 --lng -122.6800 --name my-course --radius 1500   # no UDisc listing yet

# everything shot in a window, regardless of geotag (site-walk days, install days)
python3 $S dates <udisc-course-slug> --since 2025-10-03 --until 2025-10-03

# export: geotag mode, or --by-dates for the window mode; hole is assigned from EXIF after export
python3 $S export <udisc-course-slug> --radius 400 --out photos/my-course
python3 $S export my-course --lat 45.52 --lng -122.68 --by-dates --since 2026-08-01 --until 2026-08-01 --out photos/my-course

# labelled contact sheet(s) of any folder of jpgs
python3 $S sheet photos/my-course
```

The UDisc slug is the last path segment of the course URL (`udisc.com/courses/<slug>`); find one
with `python3 <skills-dir>/udisc/scripts/udisc.py search "<course name>"`.

Output files: `<course>_<YYYYMMDD>_<HHMM>_<h7|near-h7|course|unknown>_<uuid6>.jpg`, plus
`_index.json` / `_index.csv` with taken time, lat/lng, hole, distance in metres, and the library UUID.

## Hole assignment

First active UDisc layout with GPS. Distance from the photo to the closest point on each hole's
tee→basket segment. `h<N>` at 60 m or less, `near-h<N>` to 150 m, else `course`. Phone GPS at
a wooded course drifts 20-40 m, so treat `near-` as a hint and look at the frame.

## UDisc's own photos

The `udisc` skill only exposes `topPhoto`. The full gallery is the `photos.data` route:
`/courses/<slug>/photos.data?_routes=root,routes/courses/$slug/photos` → `routes/courses/$slug/photos.data.allPhotos[]`,
each with `fullUrl` (imagedelivery.net), `addedByUsername`, `caption`. Those are other people's
photos: credit the username, and prefer your own frames for anything outward-facing.
