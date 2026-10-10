---
name: pdga-lightrag
description: Query the PDGA LightRAG knowledge base for disc golf governance, rules, financials, board minutes, and organizational information. Use when the user asks about PDGA policies, rules, history, budgets, board decisions, competition standards, or any PDGA-related question that requires searching embedded documents.
---

# PDGA LightRAG Query

Query a self-hosted [LightRAG](https://github.com/HKUDS/LightRAG) server that holds embedded PDGA
documents: board meeting minutes, financial statements, 990 filings, rules, competition manuals,
bylaws, and organizational records (a full build is ~1,300+ documents).

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `LIGHTRAG_URL` | `http://localhost:9621` | Base URL of the LightRAG server |
| `LIGHTRAG_DIR` | `./lightrag` | Directory holding the server's `docker-compose.yml` (only needed to start/stop it) |
| `LIGHTRAG_API_KEY` | unset | If your server has auth enabled, send it as `-H "X-API-Key: $LIGHTRAG_API_KEY"` |
| `PDGA_MINUTES_DIR` | `docs/pdga-bod-minutes` | Where the companion commands keep minute PDFs, extracted text and summaries |

Set once per shell: `LR=${LIGHTRAG_URL:-http://localhost:9621}`. All examples below use `$LR`.

- **Health:** `GET $LR/health`
- **Auth:** none by default (keep the server bound to localhost if so)

## Companion commands (building the corpus)

This skill only queries. Two slash commands, shipped alongside it in `commands/`, build and
maintain the board-minutes part of the corpus:

- **`/pdga-minutes`** — downloads any new PDGA Board of Directors minute PDFs from pdga.com into
  `$PDGA_MINUTES_DIR/<year>/` and extracts their text to `$PDGA_MINUTES_DIR/_extracted/<year>/`.
- **`/pdga-mindmap`** — regenerates the year-range summaries and the master mind map
  (Markdown + interactive markmap HTML) from those extracted texts.

To make new minutes queryable, upload the new PDFs or extracted `.txt` files to LightRAG
(the server's `/documents/upload` endpoint or its web UI), then confirm with
`/documents/status_counts`.

## Querying

### Primary query endpoint: `POST /query`

```bash
curl -s -X POST "$LR/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "USER_QUESTION_HERE",
    "mode": "mix",
    "include_references": true,
    "top_k": 10
  }' | python3 -m json.tool
```

### Query modes

| Mode | Use when |
|------|----------|
| `mix` | **Default.** Best overall — combines knowledge graph + vector search |
| `hybrid` | Broad questions spanning multiple topics |
| `local` | Specific entity lookups (a person, a budget line item, a specific rule) |
| `global` | High-level patterns and trends across documents |
| `naive` | Simple keyword-style search, no graph |

### Context-only mode (no LLM generation)

Use `only_need_context: true` to retrieve raw context chunks without LLM synthesis. Useful when you want to read source material directly or feed it into your own analysis.

```bash
curl -s -X POST "$LR/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "PDGA board vote on international expansion",
    "mode": "mix",
    "only_need_context": true,
    "top_k": 10
  }' | python3 -m json.tool
```

### Advanced parameters

| Param | Type | Description |
|-------|------|-------------|
| `top_k` | int | Number of entities/relations to retrieve (default 5, use 10-20 for thorough searches) |
| `chunk_top_k` | int | Number of text chunks from vector search |
| `response_type` | string | `"Multiple Paragraphs"`, `"Single Paragraph"`, `"Bullet Points"` |
| `include_references` | bool | Include source file references in response |
| `include_chunk_content` | bool | Include actual chunk text in references (for debugging) |
| `hl_keywords` | string[] | High-level keywords to guide graph traversal (bypasses LLM keyword extraction) |
| `ll_keywords` | string[] | Low-level keywords for fine-grained retrieval |
| `max_total_tokens` | int | Token budget for entire response |
| `conversation_history` | object[] | Prior messages for multi-turn queries: `[{"role": "user", "content": "..."}]` |

### Keyword-guided queries (faster, skip LLM extraction)

When you already know the key concepts, provide keywords directly to skip the LLM keyword extraction step:

```bash
curl -s -X POST "$LR/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What was the 2024 PDGA membership revenue?",
    "mode": "mix",
    "hl_keywords": ["PDGA", "membership", "revenue", "financial"],
    "ll_keywords": ["2024", "membership fees", "annual revenue", "income"],
    "include_references": true,
    "top_k": 10
  }' | python3 -m json.tool
```

## Other useful endpoints

### Document stats
```bash
curl -s "$LR/documents/status_counts" | python3 -m json.tool
```

### Knowledge graph exploration
```bash
# Popular entity labels
curl -s "$LR/graph/label/popular?limit=20" | python3 -m json.tool

# Search for a specific entity
curl -s "$LR/graph/label/search?query=TERM" | python3 -m json.tool

# Check if entity exists
curl -s "$LR/graph/entity/exists?entity_name=PDGA" | python3 -m json.tool
```

## Workflow

1. **Check server health** first if queries fail: `curl -s "$LR/health"`
2. **Start with `mode: mix`** — it covers most queries well
3. **Use `only_need_context: true`** when you need raw source text rather than synthesized answers
4. **Increase `top_k`** (to 15-20) for comprehensive research questions
5. **Use `include_references: true`** to trace answers back to source documents
6. **Provide keywords** (`hl_keywords` / `ll_keywords`) when you know the domain terms — it's faster and more precise

## Embedded document corpus

The knowledge base contains PDGA documents including:
- Board of Directors meeting minutes (multi-year)
- Annual financial statements and 990 tax filings
- Budget summaries and financial projections
- Official Rules of Disc Golf
- Competition Manual and appendices
- Bylaws and governance documents
- Tour standards and sanctioning agreements
- Mission statements and strategic plans
- Committee reports and policy documents

## Tips

- Financial queries work best with `local` or `mix` mode and specific year keywords
- Board decision queries benefit from `hybrid` mode to catch cross-meeting discussions
- Rules questions work well with `naive` or `local` mode since rules docs are well-structured
- For multi-part questions, break into separate queries for better results
- The response includes a `references` array with `file_path` pointing to source documents
- If the server is down: `cd "${LIGHTRAG_DIR:-./lightrag}" && docker compose up -d`
