# Disc Golf Stamp Design Principles

> Distilled from manufacturer guidelines (Innova, Discraft, MVP, DGA, Dynamic Discs), acclaimed stamp artists (Skulboy, Les White, Thought Space Athletics, Handeye Supply Co.), and community wisdom.

## The Core Insight

**The best disc golf stamps aren't disc golf scenes.** They're bold, compelling artwork that happens to live on a disc. Skulboy's stamps are dark fantasy characters. TSA's are philosophical abstractions. Kastaplast's are Scandinavian minimalism. The disc is the canvas, not the subject.

## Stamps Are Line Art

A hot stamp is **one color of metallic foil** pressed onto plastic. The artwork is binary — foil or no foil. There are no gradients, no halftones, no grayscale. Every detail comes from:

- **Line weight variation** — thick lines for emphasis, thin for detail
- **Crosshatching** — layered lines to create the illusion of tone
- **Stipple** — dots at varying density for texture and shading
- **Solid fills** — areas completely filled with foil
- **Negative space** — the disc plastic showing through as part of the design

This is the fundamental constraint. When we generate stamp art with AI, we must enforce this: **black ink on magenta background, no color, no gradients.**

### Multi-Color Stamps

Some manufacturers offer multi-pass stamping:

| Type | Process | Constraint |
|------|---------|-----------|
| **Single stamp** | One foil color, one pass | Most common. One artwork layer. |
| **Double stamp** | Two foil colors, two passes | Each color is a separate plate. Must maintain **1/16" minimum gap** between color regions for registration. |
| **Triple stamp** | Three foil colors, three passes | Rare and expensive. Same gap requirement. |

For double/triple stamps, each color layer is a separate piece of artwork. They're designed together but manufactured as independent plates.

## The Circular Canvas

A disc golf stamp lives on a **~5.25" diameter circular flight plate**. This is your canvas.

### Composition Rules

- **Embrace the circle.** Designs that echo, frame, or radiate from the round shape feel native. Designs that ignore the circle feel like cropped rectangles.
- **Avoid the dead center.** The sprue (center injection point) varies in size and causes print dropouts. Keep the center ~1.25" clear of critical detail.
- **Use negative space.** The bare disc plastic is part of the design. In hot stamping, the disc color shows through — gold foil on dark blue plastic hits differently than gold on white.
- **Fill or float — commit to one.** Full-bleed designs that embrace the edges look intentional. Centered medallions with breathing room look classic. Designs that hover between look unfinished.

### Readability

- **Bold silhouettes first.** A great stamp reads as a clear shape from across the room before any detail resolves.
- **High contrast.** Line art on a contrasting disc color = maximum visibility.
- **Test at thumbnail.** If the stamp doesn't read at 64px, it won't read in a bag or on a shelf.

## Line Art Technical Constraints

| Constraint | Detail |
|------------|--------|
| **Line weight minimum** | ~1pt (1/72 inch). Thinner lines disappear or bridge. |
| **Line weight maximum** | ~18pt. Thicker lines cause pressure inconsistency. |
| **Fine lines near solid areas** | Lines <1pt adjacent to solid fills cause cut-through from uneven pressure. |
| **Large solid areas** | Fills larger than a thumbnail cause air trapping → dropouts. Break them up with texture, crosshatching, or convert to outlined shapes. |
| **Line spacing** | Lines too close together bridge into each other. Maintain minimum gap equal to line weight. |
| **Text** | 12pt minimum for sans-serif, 28pt+ for decorative/script fonts. |
| **File format** | Vector preferred (.ai, .eps). Raster at 1200 ppi bitmap (not 300 ppi). |

## What Makes Stamps Iconic

### Narrative & Personality

The best stamps tell a story or convey a specific mood. They have a point of view.

- **Nate Sexton Firebird:** Each annual edition tells a different story, creating collector anticipation.
- **Skulboy's dark fantasy:** Every stamp has a character with implied backstory — not just "cool skull" but a specific personality.
- **TSA's philosophical themes:** Disc names and stamps reference concepts from philosophy, science, and spirituality.

### Owning a Niche

Iconic stamps commit fully to a visual identity:

- **Skulboy:** Dark fantasy, hand-drawn grit. Signature palette: candy apple red, baby blue, black, hint of white.
- **Kastaplast:** Scandinavian minimalism. Clean, restrained, instantly recognizable.
- **Thought Space Athletics:** Intricate dual-foil work. "Each disc a work of art."
- **Les White:** Naturalistic detail with classical illustration roots.

### The Les White Principle

> "Don't try to crush it with anyone's style but your own because that's the one you do best and the one you should develop."

Applied to AI generation: Don't prompt for "Skulboy style" or "TSA style." Describe the mood, techniques, and aesthetic you want in your own terms.

## Stamp Categories

| Category | Key Characteristics | Design Focus |
|----------|-------------------|--------------|
| **Tournament** | Commemorates a specific event | Course landmarks, event branding, year, location flavor |
| **Series** | Recurring league/event branding | Consistent style, evolving motifs, recognizable identity |
| **Limited Edition** | Collectible, small run | Maximum artistic expression, narrative depth, "gallery piece" |
| **Pro Player Signature** | Annual player tribute | Player personality, signature elements, aspirational feel |
| **Stock** | Standard manufacturer mold ID | Clean, iconic, timeless — the mold's "face" |
| **Club/Custom** | Team or event identity | Local flavor, inside jokes, community personality |
