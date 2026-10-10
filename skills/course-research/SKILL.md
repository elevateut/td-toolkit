---
name: course-research
description: >
  Deep-research a disc golf course. Pulls everything from UDisc (ratings, reviews, holes,
  amenities, photos), searches the web for history and context, downloads course images,
  and outputs a comprehensive course profile JSON. Repo-agnostic — works anywhere.
  Triggers on: "/course-research [course name]", "research course [name]".
argument-hint: "<course name or UDisc URL>"
allowed-tools: Read Write Edit Bash WebFetch WebSearch Glob Grep
---

# course-research: Disc Golf Course Intelligence

You are a disc golf course researcher. Given a course name (or UDisc URL), you build the most
comprehensive profile possible by pulling from every available source. Your output is a
standardized JSON file that downstream skills in specific repos can consume.

## Input

Either:
- A course name: `Riverside Park`
- A UDisc URL: `https://udisc.com/courses/riverside-park-abc1`
- A course name + location: `Riverside Park, Springfield`

## Step 1: Find the Course on UDisc

Use the sibling UDisc skill scripts. Set `SKILLS_ROOT` to the parent directory containing the active `course-research` skill that was invoked. Resolve it from this `SKILL.md`; do not choose a different platform's copy merely because both installations exist.

```bash
# If given a URL:
python3 "$SKILLS_ROOT/udisc/scripts/udisc.py" course-url "<url>"

# If given a name, search first:
python3 "$SKILLS_ROOT/udisc/scripts/udisc.py" search "<course name>"
# Then get details with the slug from results:
python3 "$SKILLS_ROOT/udisc/scripts/udisc.py" course-detail <slug>
```

If the search returns multiple matches, pick the one matching the user's location context.
If no match, note it and continue with web research only.

## Step 2: Pull UDisc Data

Once you have the slug, run these (can be parallel):

```bash
# Full course detail
python3 "$SKILLS_ROOT/udisc/scripts/udisc.py" course-detail <slug>

# Reviews (up to 20)
python3 "$SKILLS_ROOT/udisc/scripts/udisc.py" course-reviews <slug> --limit 20
```

Extract from course-detail:
- name, city, state, country
- coordinates (lat, lng)
- rating (1-5 scale) and ratingCount
- holeCount
- description (UDisc's course description)
- yearEstablished
- amenities (parking, restrooms, water, dogs allowed, etc.)
- playFeeType (free, pay-to-play, donation)
- availability (year-round, seasonal)
- difficulty (beginner, intermediate, advanced)
- estimatedDuration
- topPhotoUrl
- conditions (if available)

Extract from reviews:
- All reviews with: username, rating, text, createdAt
- Calculate: averageRating, reviewCount, sentiment summary
- Pick 3-5 best reviews that describe how the course plays

## Step 3: Web Research

Run 3-5 targeted searches:

1. `"{course name}" disc golf {state}` — general info, recent news
2. `"{course name}" disc golf history` — origin story, who built it
3. `site:pdga.com "{course name}"` — PDGA events hosted there
4. `"{course name}" disc golf course design` OR `"{course name}" disc golf layout` — design details
5. `"{course name}" disc golf photos` — image sources

From the results, extract:
- **Origin story**: who built it, when, why, with what money
- **Notable events**: tournaments hosted, records set
- **Course character**: how it plays, what makes it unique (elevation, water, woods, open, etc.)
- **Designer/builder**: who designed the layout
- **Ownership**: city/county/private/federal land
- **Recent changes**: renovations, new baskets, layout modifications
- **Image URLs**: note any high-quality course photos found (do NOT download yet — list them)

## Step 4: Download Images

Create a directory for this course's images:
```bash
OUT="${COURSE_RESEARCH_OUT:-/tmp/course-research}"
mkdir -p "$OUT/<slug>/images"
```

Download the UDisc top photo if available:
```bash
curl -sL -o "$OUT/<slug>/images/udisc-hero.jpg" "<topPhotoUrl>"
```

For any additional image URLs found during web research, list them in the output
but do NOT auto-download — the user decides which to keep.

## Step 4b (optional): Your Own Platform's Course ID

Skip this step unless `COURSE_ID_MAP` is set. It lets you tag the profile with the course's id
in your own system (league software, club site, etc.).

- `COURSE_ID_MAP` — path to a JSON file shaped `{"courses": [{"id": 1, "name": "Riverside Park", "slug": "riverside"}]}`
- `COURSE_PLATFORM_URL` — optional URL pattern with `{id}`, e.g. `https://example.org/courses?courseId={id}`

```bash
[ -n "$COURSE_ID_MAP" ] && cat "$COURSE_ID_MAP"
```

Match by name (case-insensitive, partial match OK). If found, add `"platformId"` (and
`"platformUrl"` when `COURSE_PLATFORM_URL` is set) to `_meta` in the profile. If no match, note it
as a gap rather than guessing.

## Step 5: Synthesize Course Character

From reviews and web research, write a concise "How It Plays" section (2-3 sentences) covering:
- Terrain type (wooded, open, mixed, mountain, desert, wetland)
- Signature features (water carries, elevation changes, tight fairways, long bombers)
- Difficulty character (punishing OB, technical, beginner-friendly, championship-length)
- Best season to play
- What kind of player this course rewards

## Step 6: Output Profile

Write the profile to `$OUT/<slug>/profile.json`, where `OUT=${COURSE_RESEARCH_OUT:-/tmp/course-research}`:

```json
{
  "_meta": {
    "generatedAt": "2026-05-01T18:30:00Z",
    "sources": ["udisc", "web", "pdga"],
    "udiscSlug": "<slug>",
    "udiscUrl": "https://udisc.com/courses/<slug>"
  },
  "name": "Riverside Park",
  "slug": "riverside",
  "location": {
    "city": "Springfield",
    "state": "OR",
    "country": "US",
    "detail": "Springfield City Parks",
    "coordinates": { "lat": 44.0462, "lng": -123.0220 }
  },
  "course": {
    "holes": 18,
    "yearEstablished": 1982,
    "designer": "Jane Designer",
    "ownership": "City of Springfield",
    "playFee": "free",
    "availability": "year-round",
    "difficulty": "intermediate",
    "estimatedDuration": "1.5 hours",
    "terrain": "wooded creek corridor",
    "acreage": null
  },
  "stats": {
    "udiscRating": 4.8,
    "udiscRatingCount": 1247,
    "roundsPlayed": { "2024": 29686, "2025": 36569 },
    "pdgaEventsHosted": 12
  },
  "amenities": {
    "parking": true,
    "restrooms": true,
    "water": false,
    "dogsAllowed": true,
    "wheelchairAccessible": false,
    "proShopNearby": false,
    "notes": "Parking lot can fill on weekends"
  },
  "layouts": [
    {
      "name": "Default",
      "holes": 18,
      "par": 54,
      "distance": "5,420 ft",
      "description": "Standard 18-hole layout"
    }
  ],
  "howItPlays": "A tight, wooded creek corridor that rewards accurate mid-range play over raw distance. Mature trees create natural hallways with elevation changes along the creek. The course punishes errant drives but offers birdie opportunities on shorter technical holes.",
  "history": {
    "origin": "Designed in 1982 by a local club, making it one of the oldest courses in the region...",
    "notableEvents": ["Riverside Open (annual)"],
    "recentChanges": "Renovation in 2023 by the local club and city parks department",
    "keyPeople": [
      { "name": "Jane Designer", "role": "Original designer (1982)" },
      { "name": "John Director", "role": "Current tournament director" }
    ]
  },
  "reviews": {
    "count": 20,
    "averageRating": 4.8,
    "highlights": [
      {
        "author": "PlayerName",
        "rating": 5,
        "text": "Best course in the state. The trees make you think about every shot.",
        "date": "2025-10-15"
      }
    ],
    "commonThemes": ["tight wooded fairways", "creek crossings", "beautiful setting", "technical shots"]
  },
  "images": {
    "hero": "<OUT>/<slug>/images/udisc-hero.jpg",
    "additional": [
      { "url": "https://example.com/photo1.jpg", "source": "web", "description": "Hole 5 from tee" }
    ]
  },
  "relatedContent": {
    "blogPostSlugs": [],
    "pdgaEvents": [],
    "externalLinks": [
      { "label": "UDisc", "url": "https://udisc.com/courses/<slug>" },
      { "label": "PDGA", "url": "https://pdga.com/course-directory/course/<id>" }
    ]
  }
}
```

Also write a human-readable summary to `$OUT/<slug>/summary.md`.

## Step 7: Report to User

Tell the user:
- What was found and from which sources
- The UDisc rating and key stats
- A brief "how it plays" summary
- How many reviews were analyzed
- What images were downloaded vs. listed for manual review
- The path to the profile JSON and summary
- Suggest next steps: "Run your repo-specific skill to import this into your project"

## Important Notes

- This skill is REPO-AGNOSTIC. It does NOT modify any project files. It outputs to `$COURSE_RESEARCH_OUT` (default `/tmp/course-research`).
- A downstream repo-specific skill (e.g. one that builds a course page) reads the profile and does the repo-specific work.
- Don't invent data. If UDisc doesn't have it and the web doesn't have it, note the gap.
- Rate limit UDisc calls — no more than 1 request per second.
- Reviews are the best source for "how it plays" — synthesize from player language, don't make it up.
- Image downloads go to the output directory only. The downstream skill decides where to copy them.
