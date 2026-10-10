---
allowed-tools: Bash, Read, Write, Glob, Grep, WebFetch
description: Download new PDGA Board of Directors meeting minute PDFs and extract text
---

Download any new PDGA BOD meeting minute PDFs that you don't already have and extract their text.

Companion of the `pdga-lightrag` skill: this command builds the board-minutes part of its corpus.
Follow up with `/pdga-mindmap` for summaries, and upload new files to LightRAG to make them queryable.

## Configuration

All paths hang off one directory (relative to the current project unless absolute):

```bash
MIN="${PDGA_MINUTES_DIR:-docs/pdga-bod-minutes}"
```

## Step 1: Determine what we have

Check existing PDFs:
```bash
for year in $(seq 2003 $(date +%Y)); do
  dir="$MIN/$year"
  if [ -d "$dir" ]; then
    count=$(find "$dir" -name "*.pdf" | wc -l | tr -d ' ')
    echo "$year: $count PDFs"
  else
    echo "$year: NO FOLDER"
  fi
done
```

## Step 2: Crawl PDGA website for each year

For years 2003-2025, the URL pattern is:
```
https://www.pdga.com/pdga-documents/bod/bod-minutes/bod-minutes-{YEAR}
```

For 2026+, the URL pattern is:
```
https://www.pdga.com/bod-minutes-{YEAR}
```

For each year from the current year back to 2003:

1. Fetch the page with curl (use a browser User-Agent):
```bash
curl -sL -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" "$URL"
```

2. Extract all PDF links:
```bash
grep -oE 'href="[^"]*\.pdf[^"]*"' | sed 's/href="//;s/"//' | sort -u
```

3. Filter out CSS/JS files (skip anything with `/css/` or `/js/` in the path)

4. For each PDF URL, check if the file already exists in `$MIN/{YEAR}/`. If it exists, skip it.

5. Download new PDFs with a 0.5 second delay between downloads to avoid rate limiting:
```bash
curl -sL -A "Mozilla/5.0 ..." -o "$dest" "$pdf_url"
```

6. Verify each download is a valid PDF by checking the header:
```bash
head -c 4 "$dest" | grep -q '%PDF'
```
Remove any files that fail validation.

**IMPORTANT:** Add a 2-second delay between year page fetches to avoid rate limiting. If a year returns no PDFs, wait 3 seconds and retry once before moving on.

## Step 3: Extract text from new PDFs

For any newly downloaded PDFs, extract text using PyPDF2:

```python
import PyPDF2
reader = PyPDF2.PdfReader(pdf_path)
text = ""
for page in reader.pages:
    page_text = page.extract_text()
    if page_text:
        text += page_text + "\n\n---PAGE BREAK---\n\n"
```

Save extracted text to `$MIN/_extracted/{YEAR}/{filename}.txt` (requires `pip install PyPDF2`).

## Step 4: Report results

Print a summary:
```
=== PDGA BOD Minutes Update ===
New PDFs downloaded: X
  2025: filename1.pdf, filename2.pdf
  2026: filename3.pdf
Text extracted: X files
Already up to date: Y years
```

## Notes

- The PDGA website rate limits after rapid requests. Always include delays.
- Some older PDFs on the PDGA server are corrupted (return HTML instead of PDF). The %PDF header check catches these.
- The 2026 URL is different from the standard pattern. Always check both patterns for the current year.
- This command only downloads and extracts. It does NOT regenerate summaries or the mind map (run `/pdga-mindmap`) and does NOT ingest into LightRAG (upload the new files to the server configured for the `pdga-lightrag` skill, `$LIGHTRAG_URL`).
