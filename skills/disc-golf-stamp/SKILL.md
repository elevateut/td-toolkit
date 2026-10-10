---
name: disc-golf-stamp
description: "Generate disc golf stamp artwork — single-color line art designs for hot stamping onto disc golf discs, generated as black art on a magenta background and chromakeyed to a transparent PNG. Use when the user says /disc-golf-stamp, 'create a disc stamp', 'design a disc golf stamp', 'make a stamp for a disc', or 'generate disc artwork'."
---

# Disc Golf Stamp Design Skill

Generate disc golf stamp artwork — single-color line art designs for hot stamping onto disc golf discs. Output is monochrome art on magenta background, ready for chromakey to transparent PNG.

## Trigger

`/disc-golf-stamp`, "create a disc stamp", "design a disc golf stamp", "make a stamp for a disc", "generate disc artwork"

## How Hot Stamps Work

A hot stamp is **one color of metallic foil** pressed onto plastic. The artwork is binary — foil or no foil. The disc's plastic color shows through everywhere the stamp isn't. This means:

- **Single stamp:** One foil color (most common — gold, silver, black, holographic, etc.)
- **Double stamp:** Two foil colors, applied in separate passes with slight registration gaps
- **Triple stamp:** Three foil colors (rare, premium)

We generate the artwork as **black line art on magenta (#FF00FF) background**, then chromakey the magenta to transparency. The resulting transparent PNG can be colorized to any foil color digitally.

## Workflow

### Phase 1: Research

1. Read `references/stamp-design-principles.md` for composition rules, line weight constraints, and what makes stamps iconic.
2. Read `references/prompt-templates.md` for stamp-specific prompt templates.
3. If the stamp is for a brand with its own style guide, read it (path in `$STAMP_STYLE_GUIDE`, or ask the user). Otherwise skip — the user's own description drives the style.
4. Chromakey is ALWAYS used for stamps; the exact post-process command is in Phase 5.

### Phase 2: Define the Stamp Brief

Work with the user to nail down these decisions:

**1. Stamp Type**

| Type | Purpose | Typical Elements |
|------|---------|-----------------|
| **Tournament** | Commemorates a specific event | Course landmarks, event name, year, location flavor |
| **Series** | Branding for a recurring league series | Series logo/mascot, thematic motif, consistent style across editions |
| **Limited Edition** | Collectible/special release | High-detail artwork, narrative scene, collector appeal |
| **Player Signature** | Pro player tribute | Player personality/style, signature elements |
| **Club/Team** | Club or team identity | Team mascot, local identity, group personality |
| **Custom/Fun** | One-off creative stamps | Anything goes — memes, mashups, absurdist themes |

**2. Stamp Complexity**

| Complexity | Colors | Notes |
|------------|--------|-------|
| **Single stamp** | 1 foil color | Default. One layer of artwork. |
| **Double stamp** | 2 foil colors | Two separate artwork layers. Must maintain 1/16" gap between color regions. |
| **Triple stamp** | 3 foil colors | Three layers. Rare — high cost and registration difficulty. |

For double/triple stamps, generate each color layer as a separate image.

**3. Composition Approach**

| Approach | When to Use | Notes |
|----------|-------------|-------|
| **Full-bleed circular** | Design fills the entire disc face | Embrace the circle; most dramatic |
| **Central medallion** | Framed emblem with breathing room | Classic tournament stamp feel |
| **Vignette scene** | Narrative illustration fading to edges | Storytelling stamps, limited editions |
| **Bold silhouette** | Single strong shape dominates | High readability, iconic look |
| **Split composition** | Divided design (top/bottom, radial) | Good for contrasting themes |

**4. Subject & Theme** — What is the stamp depicting? The best stamps aren't "disc golf scenes" — they're bold artwork with a point of view. A phoenix, a skull king, a mountain storm, a surreal landscape. The disc is the canvas, not the subject.

**5. Visual Style** — Let the user describe what they want. Don't suggest from a catalog. Ask: "What should this look and feel like?" If they need help, ask about mood, era, or reference points (e.g., "tattoo flash sheet energy", "vintage travel poster", "dark and gritty", "clean and minimal").

### Phase 3: Compose the Prompt

Build the prompt using templates from `references/prompt-templates.md`. Every stamp prompt must:

1. **Specify monochrome line art** — black ink on magenta background, no color, no gradients
2. **Describe the visual style** — specific techniques, mood, and aesthetic feel (from the user's own words)
3. **Describe the subject** — what the stamp depicts, with narrative detail
4. **Specify composition** — how elements are arranged within the circular canvas
5. **Enforce line art constraints** — no gradients, no halftones, no grayscale shading; all detail through line weight, crosshatching, stipple, or solid fills
6. **End with format instructions** — If the design has NO intentional text, end with `NO TEXT OR WORDS`. If text is part of the design, explicitly state what text should appear and add `NO OTHER TEXT OR WORDS besides [the intended text]`.

**Critical Line Art Rules:**
- All detail must come from **lines, fills, and textures** — not tonal shading
- Line weight minimum ~1pt, maximum ~18pt
- Large solid areas should be broken up with texture to avoid air-trap dropouts in real stamping
- The result must look like it could be cut as a single-color stamp plate

**Circular Canvas Reminders:**
- The stamp lives on a ~5.25" circular disc face
- Avoid critical detail in the dead center (sprue area)
- Designs that echo or embrace the circular shape feel natural
- Leave a thin breathing margin at the outer edge for print tolerance

### Phase 4: Generate

Use whatever image generator is available in this environment, in this order of preference:

1. An image-generation skill or MCP server already installed (e.g. a Gemini / "nano banana" or
   OpenAI image tool). Pass the full prompt, **1:1 aspect ratio**, and — for an edit or a series —
   the reference image.
2. A generator script of your own, if `$STAMP_GENERATOR` is set. It is called as
   `"$STAMP_GENERATOR" --aspect-ratio 1:1 --filename <stamp-name> --prompt "<prompt>" [--source-image <ref>]`
   and should write a PNG; adapt the flags to your script.
3. The provider API directly, with `GEMINI_API_KEY` or `OPENAI_API_KEY` from the environment.

Gemini image models follow the magenta-background instruction well; whichever you use, request a
square image at the highest available resolution.

**Series:** generate each stamp from the same base prompt with only the subject changed, and pass
the first approved stamp as a reference image for the rest so line weight and texture stay consistent.

### Phase 5: Post-Process (ALWAYS)

Stamps **always** require post-processing. Use this single pipeline command:

```bash
magick <input.png> -fuzz 30% -transparent '#FF00FF' -modulate 100,0 -level 25%,75% <output.png>
```

This does three things in one pass:
1. **Chromakey** — removes magenta (#FF00FF) background to transparency (30% fuzz handles Gemini's imperfect magenta)
2. **Desaturate** — kills any magenta tint Gemini bleeds into the "black" line art
3. **Contrast boost** — snaps the desaturated art to pure black

> **Order matters:** Chromakey must happen BEFORE desaturation. Desaturating first converts magenta to gray, making it impossible to chromakey by color.

The result is a transparent PNG with black artwork — ready to be colorized to any foil color digitally.

### Phase 6: Review & Iterate

1. Preview the generated stamp inline.
2. Evaluate against the **Stamp Quality Checklist** below.
3. Check: does it read as **single-color line art**? If there are gradients, shading, or multiple colors, regenerate with stronger line-art constraints in the prompt.
4. Offer iteration — adjust prompt, tweak composition, try a different direction.
5. If creating a series, ensure visual consistency across all stamps before finalizing.
6. Confirm final placement and naming.

## Stamp Quality Checklist

- [ ] **True line art** — no gradients, no halftones, no color fills; all detail through lines, crosshatching, stipple, or solid black fills
- [ ] **Reads in a circle** — composition works within the disc's round format
- [ ] **Clear focal point** — one dominant element draws the eye
- [ ] **Avoids dead center** — critical detail isn't in the sprue zone
- [ ] **Bold at thumbnail size** — silhouette/shape reads at 64px
- [ ] **Not generic** — has narrative, personality, or storytelling; avoids stock-art blandness
- [ ] **Not a "disc golf scene"** — the artwork stands on its own; disc golf motifs are optional, not mandatory
- [ ] **Line weights appropriate** — no lines thinner than ~1pt, no solid areas large enough to cause air trapping
- [ ] **Text handled correctly** — if no intentional text, prompt ends with `NO TEXT OR WORDS`. If text is part of the design, only the intended text appears.
- [ ] **Magenta background clean** — solid magenta (#FF00FF) with no gradient or lighting artifacts
- [ ] **Would you throw it?** — the ultimate gut check

## Configuration

| Env var | Purpose |
|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | Provider keys when calling an image API directly. Never hard-code or commit them. |
| `STAMP_GENERATOR` | Optional path to your own generator script (see Phase 4) |
| `STAMP_STYLE_GUIDE` | Optional path to a brand style guide to honour |
| `STAMP_OUT_DIR` | Where finished stamps go (default `./stamps`) |

Requires ImageMagick (`magick`) for the post-process.

## Key Files

| File | Purpose |
|------|---------|
| `references/stamp-design-principles.md` | Composition rules, line-weight constraints, what makes stamps iconic |
| `references/prompt-templates.md` | Stamp prompt templates (standard, silhouette, collectible, minimalist, text, double stamp) |

## Output Naming Convention

```
<context>-<subject>.png
```

Save to `${STAMP_OUT_DIR:-./stamps}/`. Examples:
- `spring-open-2026-eagle.png`
- `winter-series-snowchain.png`
- `ace-fund-phoenix.png`
- `league-night-chill.png`
