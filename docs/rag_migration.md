# RAG Data Migration Plan

## Goal

Build a repeatable data acquisition and ingestion pipeline for Xiangqi knowledge so the ChromaDB-backed coaching tools can retrieve high-quality opening plans, middlegame themes, endgame principles, and beginner guidance.

This plan is intentionally acquisition-first. It defines:

- which sources to collect
- how each source should be extracted
- how raw assets should be stored
- how content should be normalized and chunked
- how documents should map into the existing RAG collections
- what order to implement sources in

This document does not require code changes yet. It is the migration blueprint for the missing knowledge-ingestion layer.

## Current Repo Baseline

The recovered workspace already has the retrieval side:

- ChromaDB retriever: [server/chess_coach/tools/chromadb_retriever.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/chromadb_retriever.go)
- RAG tools mapped to collections: [server/chess_coach/tools/rag_tools.go](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/chess_coach/tools/rag_tools.go)
- Embedding service: [server/embedding_service/app.py](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/embedding_service/app.py)

The acquisition side is incomplete:

- there is an annotated game scraper for training data: [server/web_scraper/scrape_games.py](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/server/web_scraper/scrape_games.py)
- there is no recovered knowledge-ingestion pipeline yet for RAG articles, PDFs, puzzles, or external APIs

So the migration work should create a new knowledge pipeline rather than force it into the existing game-commentary scraper.

## Target ChromaDB Collections

The current Go coach expects these collections:

| Collection | Purpose | Typical Query Source |
|---|---|---|
| `openings` | named openings, early development principles, opening plans | position description |
| `tactics` | middlegame themes, tactical motifs, attacking plans, defensive patterns | position features |
| `endgames` | practical endgames, mating nets, composed studies, puzzle principles | position features |
| `beginner_principles` | general advice, simple explanations, puzzle objectives, tactic explanations | user question / puzzle context |

Recommended metadata-only staging collections outside ChromaDB:

- `resource_catalog`: source inventory and crawl manifest
- `normalized_documents`: cleaned page-level documents before chunking
- `ingestion_runs`: ingestion logs, hashes, counts, and failure details

## Migration Principles

1. Preserve raw source artifacts before cleaning.
2. Attach strong metadata to every document and chunk.
3. Prefer smaller, source-faithful chunks over aggressive summarization.
4. Keep source attribution so responses can cite provenance.
5. Separate acquisition from transformation from ingestion.
6. Start with easy, high-signal HTML sources before hard sources like apps and dynamic sites.
7. Ingest only content we are comfortable retrieving and paraphrasing; do not rely on long verbatim reproduction.

## Proposed Repository Layout

Recommended new structure under `server/web_scraper/`:

```text
server/web_scraper/
├── knowledge/
│   ├── sources.yaml
│   ├── raw/
│   │   ├── xqinenglish/
│   │   ├── xiangqi_com/
│   │   ├── chessdb/
│   │   ├── wxf/
│   │   ├── github/
│   │   ├── brainking/
│   │   └── pychess/
│   ├── normalized/
│   │   ├── documents.jsonl
│   │   ├── puzzles.jsonl
│   │   └── openings.jsonl
│   ├── chunks/
│   │   ├── openings.jsonl
│   │   ├── tactics.jsonl
│   │   ├── endgames.jsonl
│   │   └── beginner_principles.jsonl
│   └── manifests/
│       ├── acquisition_runs.jsonl
│       └── ingestion_runs.jsonl
```

## Standard Document Schema

Every normalized document should use one stable schema:

```json
{
  "doc_id": "xqinenglish/opening/introduction_to_opening",
  "source_name": "xqinenglish",
  "source_type": "html",
  "title": "Introduction to the Xiangqi Opening",
  "url": "https://...",
  "phase": "opening",
  "topic": "opening principles",
  "language": "en",
  "content": "cleaned text content",
  "summary": "optional short source summary",
  "tags": ["opening", "development", "center_control"],
  "difficulty": "beginner",
  "license_note": "public web content, attributed",
  "extraction_method": "html_content_div",
  "retrieval_collections": ["openings", "beginner_principles"],
  "metadata": {
    "site_section": "Basics of Xiangqi",
    "author": "Peter Donnelly",
    "published_at": null,
    "board_fen": null,
    "solution": null
  },
  "content_hash": "sha256:...",
  "captured_at": "2026-04-22T00:00:00Z"
}
```

## Standard Chunk Schema

Each chunk inserted into ChromaDB should carry retrieval-oriented metadata:

```json
{
  "chunk_id": "xqinenglish/opening/introduction_to_opening#chunk-003",
  "doc_id": "xqinenglish/opening/introduction_to_opening",
  "collection": "openings",
  "text": "In the opening, rapid development and central control ...",
  "title": "Introduction to the Xiangqi Opening",
  "phase": "opening",
  "topic": "opening principles",
  "tags": ["opening", "development"],
  "url": "https://...",
  "source_name": "xqinenglish",
  "quality_score": 0.92,
  "chunk_index": 3
}
```

## Collection Mapping Rules

Use deterministic routing from source material into the four active collections.

### `openings`

Include:

- opening principles
- named opening systems
- opening line explanations
- ChessDB opening continuations
- introductory early-game lessons

Exclude:

- purely tactical combinations unless they are explicitly framed as opening traps

### `tactics`

Include:

- middlegame strategic themes
- tactical motifs like forks, pins, clearance, dislodging
- attack-defense plans
- transcripts or articles about concrete tactical patterns

### `endgames`

Include:

- endgame theory
- practical endgames
- mating methods
- endgame puzzle explanations
- endgame tablebase-derived guidance

### `beginner_principles`

Include:

- simple advice for novices
- general strategy and proverbs
- broad “how should I think here?” explanations
- simplified tactic and puzzle explanations
- all-phase beginner material

A single source document can feed multiple collections if chunked by section.

## Acquisition Pipeline Stages

### Phase 0. Build the Source Inventory

Create `server/web_scraper/knowledge/sources.yaml` containing one entry per resource:

- `source_id`
- `title`
- `canonical_url`
- `site_name`
- `phase`
- `format`
- `extraction_method`
- `priority`
- `expected_collections`
- `status`
- `notes`

Important note:

- Your curated list names many pages, but only some entries include explicit URLs in the note.
- For named resources without an explicit URL in this message, the first migration task is to resolve and record the canonical URL in `sources.yaml`.
- Do not start scraping unnamed or unresolved URLs directly from memory.

### Phase 1. Acquire Raw Artifacts

For each resource, save the untouched source artifact:

- HTML page as `.html`
- PDF as `.pdf`
- PowerPoint as `.pptx`
- API response as `.json`
- transcript as `.json` or `.txt`

For every acquisition, record:

- request timestamp
- HTTP status
- final URL after redirects
- content hash
- content type
- fetch tool used

### Phase 2. Normalize to Clean Documents

Transform raw artifacts into cleaned, structured JSONL documents:

- strip navigation, cookie banners, footers, and unrelated sidebar content
- preserve headings and section boundaries
- preserve numbered lists and puzzle solutions
- preserve board state references, FENs, move strings, and named openings
- capture source attribution fields

### Phase 3. Split Into Retrieval Chunks

Chunk by semantic structure, not fixed page size only:

- heading-based chunks for articles
- puzzle-by-puzzle chunks for endgame studies
- principle-by-principle chunks for proverb lists
- line-by-line chunks for opening reference data when needed

Recommended defaults:

- 400 to 800 tokens per chunk
- 10 to 15 percent overlap
- always include title, phase, and source in chunk metadata

### Phase 4. Quality Review

Before ingesting into ChromaDB:

- remove duplicate chunks
- reject empty or low-text chunks
- reject chunks dominated by boilerplate
- spot-check metadata routing
- verify that beginner content did not leak into the wrong collection

### Phase 5. Embed and Ingest

Ingest cleaned chunks into ChromaDB using the embedding service already present in the repo.

Each ingestion run should record:

- collection name
- chunk count
- source counts
- failed chunks
- duplicate count
- embedding model used
- run timestamp

## Source-by-Source Acquisition Plan

The table below is the main execution checklist.

### Priority Legend

- `P0`: easiest and highest value, do first
- `P1`: high value, moderate extraction effort
- `P2`: valuable but specialized or harder
- `P3`: optional or research-heavy

### Opening Phase Sources

| Source | Phase | Format | Extraction | Target Collections | Priority | Acquisition Notes |
|---|---|---|---|---|---|---|
| xqinenglish - Basics of Xiangqi 05 The Opening Phase | opening | HTML | parse main article content, likely `div#content` | `openings`, `beginner_principles` | P0 | Save raw HTML and normalized article text with heading structure |
| xqinenglish - Choosing your Xiangqi Opening | opening | HTML | standard HTML parsing | `openings`, `beginner_principles` | P0 | Capture comparisons between openings as separate chunks |
| xqinenglish - Introduction to the Xiangqi Opening | opening | HTML | standard HTML parsing | `openings`, `beginner_principles` | P0 | Chunk by principle or section |
| Xiangqi.com - 10 Most Important Opening Principles | opening | HTML | CSS selector extraction | `openings`, `beginner_principles` | P0 | Prefer one chunk per principle plus one article overview chunk |
| BoardGameArena - Tips xiangqi | opening | HTML | standard HTML parsing | `beginner_principles`, `openings` | P1 | Treat as beginner-facing guidance |
| Xiangqi Cloud Database (ChessDB) | opening | JSON API | `cdb_api/?action=queryall&board={fen}` | `openings` | P1 | Seed with curated FENs from common openings; store returned move stats and continuations |
| Xiangqi Master - Modern Two Horses Defense | opening | HTML | standard HTML parsing | `openings` | P1 | Tag as named opening system and preserve move-order references |

### Midgame Phase Sources

| Source | Phase | Format | Extraction | Target Collections | Priority | Acquisition Notes |
|---|---|---|---|---|---|---|
| Xiangqi.com - Step-by-step: How to win Chinese Chess Midgame | middlegame | HTML | CSS selector extraction | `tactics`, `beginner_principles` | P0 | Chunk by strategic theme |
| Xiangqi.com - How to capture pieces in Chinese Chess midgame | middlegame | HTML | CSS selector extraction | `tactics` | P0 | Promote forks, skewers, and capture motifs into separate chunks |
| xqinenglish - Strategical Advice in the Xiangqi Middle Game | middlegame | HTML | standard HTML parsing | `tactics`, `beginner_principles` | P0 | Keep strategic and tactical subsections distinct |
| xqinenglish - Introduction to the Xiangqi Midgame | middlegame | HTML | standard HTML parsing | `tactics`, `beginner_principles` | P0 | Good beginner bridge source |
| xqinenglish - Tactics 01c - Clearance Tactic | middlegame | HTML | standard HTML parsing | `tactics`, `beginner_principles` | P0 | One chunk for definition, one for examples |
| xqinenglish - Tactics 07c - Dislodge | middlegame | HTML | standard HTML parsing | `tactics`, `beginner_principles` | P0 | Preserve terminology variants like dislodging and chasing away |
| WXF - Xiangqi and the 36 Stratagems | middlegame | video/transcript | transcript extraction when available | `tactics`, `beginner_principles` | P2 | If transcript quality is poor, store metadata and defer ingestion |

### Endgame Phase Sources

| Source | Phase | Format | Extraction | Target Collections | Priority | Acquisition Notes |
|---|---|---|---|---|---|---|
| xqinenglish - Basics of Xiangqi 08 The Endgame | endgame | HTML | standard HTML parsing | `endgames`, `beginner_principles` | P0 | Useful general primer |
| xqinenglish - Puzzles by Henry Hong Congfa | endgame | HTML table | parse table rows into puzzle records | `endgames` | P0 | Extract board state, problem statement, solution, and commentary per puzzle |
| xqinenglish - Introduction to Endgame puzzles with Chinese Characters | endgame | HTML | specialized parsing | `endgames` | P2 | Likely manual normalization because board-shape meaning matters |
| xqinenglish - TJM Practical Endgames | endgame | HTML | standard HTML parsing | `endgames` | P0 | Chunk by endgame type |
| Xiangqi.com - The Eleven Endgame Compositions | endgame | HTML | CSS selector extraction | `endgames` | P1 | Preserve corrected solutions and composition names |
| Felicity Xiangqi endgame tablebase | endgame | GitHub/code/data | direct integration or derived text docs | `endgames` | P1 | Prefer generated explanatory docs over raw binary/state dumps |
| Chinese Chess - easy to expert app | endgame | app data | emulator or API analysis | `endgames` | P3 | Defer unless licensing and extraction path are clear |

### General Strategy and Principles Sources

| Source | Phase | Format | Extraction | Target Collections | Priority | Acquisition Notes |
|---|---|---|---|---|---|---|
| xqinenglish - Xiangqi Proverbs: 84 Gems of Wisdom for Play | general | HTML list | parse list items | `beginner_principles`, `tactics` | P0 | Keep one proverb per chunk and optionally a theme summary chunk |
| xqinenglish - Xiangqi Proverbs: 47 Gems of Wisdom for Life | general | HTML list | parse list items | `beginner_principles` | P1 | Keep tone and life-lesson framing in metadata |
| xqinenglish - Sun Zi's Art of War applied to Xiangqi, Chapter 06d | general | HTML | standard HTML parsing | `tactics`, `beginner_principles` | P1 | Tag as strategy and philosophy |
| xqinenglish - Basic Xiangqi Checkmate Methods | general/endgame | HTML or ebook page | standard HTML parsing | `endgames`, `beginner_principles` | P0 | Strong fit for explain-tactic and explain-puzzle-objective |
| The Chess Polyglot - Xiangqi proverbs | general | HTML | standard HTML parsing | `beginner_principles` | P1 | Deduplicate against xqinenglish proverb content by semantic similarity |
| Awesome Xiangqi (GitHub) | general | Markdown | GitHub README extraction | metadata only first | P2 | Use as resource discovery source, not direct learning corpus initially |

### Comprehensive Guides

| Source | Phase | Format | Extraction | Target Collections | Priority | Acquisition Notes |
|---|---|---|---|---|---|---|
| xqinenglish - Basics of Xiangqi Play | all phases | HTML | standard HTML parsing | `beginner_principles`, split by section into `openings` and `endgames` where relevant | P0 | Good bootstrap corpus for beginner guidance |
| xqinenglish - How to Play Xiangqi (Basics 02) | all phases | HTML | standard HTML parsing | `beginner_principles` | P0 | Focus on rule explanations and beginner coaching |
| WXF - Introduction to Xiangqi | all phases | PDF/PPTX | `pdfplumber`, `PyPDF2`, `python-pptx` | `beginner_principles`, `openings`, `endgames` | P1 | Store original file and extracted text side by side |
| Xiangqi.com Resources hub | all phases | HTML hub | CSS selectors plus follow-up crawl | metadata first, then route linked pages | P1 | Use as discovery page rather than ingesting hub text itself |
| BrainKing - Chinese Chess Forum | all phases | HTML forum | thread parsing | `beginner_principles` after manual filtering | P3 | High noise risk; manual review required |
| World Xiangqi Federation website | all phases | HTML/PDF | standard parsing plus PDF extraction | `beginner_principles`, `endgames` if technical material exists | P1 | Prioritize official rules and introductory docs |
| PyChess Xiangqi resources | all phases | dynamic web/API | network capture and endpoint analysis | `beginner_principles`, `tactics`, `endgames` depending on lesson type | P2 | Treat as a structured-source investigation task |

## Extraction Notes by Content Type

### 1. Standard HTML Articles

Use for:

- most xqinenglish pages
- many Xiangqi.com pages
- BoardGameArena tips
- blog/tutorial articles

Acquisition steps:

1. fetch HTML with polite rate limiting
2. save raw HTML
3. extract title, headings, and main content block
4. remove nav/footer/share widgets
5. preserve lists and examples
6. normalize whitespace
7. emit one normalized document

### 2. HTML Tables for Puzzles

Use for:

- xqinenglish puzzle pages

Acquisition steps:

1. save raw HTML
2. identify puzzle table rows
3. extract puzzle label, diagram text, board state if present, solution, and notes
4. emit one normalized document per puzzle, not one per page
5. route into `endgames`

### 3. PDFs and PowerPoint Slides

Use for:

- WXF resources
- official rules or teaching decks

Acquisition steps:

1. save original file
2. extract text by page or slide
3. attach page numbers or slide numbers in metadata
4. merge broken lines carefully
5. emit section-based chunks

### 4. JSON/API Sources

Use for:

- ChessDB
- possible PyChess endpoints

Acquisition steps:

1. save request parameters and raw JSON response
2. flatten the response into stable structured records
3. add metadata such as seed FEN and returned candidate moves
4. convert records into natural-language retrieval chunks

For ChessDB specifically:

- use `https://www.chessdb.cn/cdb_api/?action=queryall&board={fen}`
- seed positions should come from a curated list of canonical opening FENs
- each returned move line should become a compact chunk like:
  - opening family
  - current FEN
  - recommended move
  - reply statistics or engine score if available

### 5. Video Transcripts

Use for:

- WXF 36 Stratagems content

Acquisition steps:

1. capture transcript if legally and technically available
2. store transcript with timestamps
3. remove sponsor and intro noise
4. chunk by topic change, not timestamp window only
5. mark low-confidence transcript passages for exclusion

### 6. GitHub Sources

Use for:

- Awesome Xiangqi
- FelicityEgtb docs

Acquisition steps:

1. pull README or docs markdown
2. preserve heading structure
3. treat repository code separately from tutorial prose
4. prefer docs and explanation pages over raw code as retrieval content

## Source Resolution Tasks

Because several entries in the curated note are names rather than explicit URLs, Phase 0 should create a resolution checklist:

- resolve canonical URL for every xqinenglish article
- resolve canonical URL for each Xiangqi.com article
- resolve exact BoardGameArena tips page
- resolve Xiangqi Master article URL
- resolve WXF lesson/video/PDF landing pages
- resolve Chess Polyglot article URL
- resolve BrainKing resource thread URLs

This should be recorded in `sources.yaml` before automated acquisition begins.

## Deduplication Strategy

RAG quality will drop quickly if proverb and principle sources duplicate one another heavily.

Use two layers of dedupe:

1. Exact dedupe using `content_hash`
2. Near-duplicate dedupe using embedding similarity or normalized text fingerprints

Apply stricter dedupe to:

- proverb collections
- mirrored articles
- copied introductory rules text

Prefer the source that is:

- clearer
- better structured
- more beginner-friendly
- more attributable

## Metadata Requirements

Every normalized document should include:

- `phase`
- `topic`
- `difficulty`
- `source_name`
- `url`
- `title`
- `retrieval_collections`
- `extraction_method`
- `captured_at`
- `content_hash`

Puzzle or position-heavy sources should also include when possible:

- `board_fen`
- `solution_moves`
- `side_to_move`
- `motifs`
- `piece_count`

Opening sources should also include when possible:

- `opening_name`
- `variation_name`
- `starting_fen`
- `example_moves`

## Chunking Strategy by Source Type

### Articles

- chunk by heading and subheading
- keep examples attached to the principle they explain

### Proverbs

- one proverb per chunk
- optional paired explanation chunk if the page includes commentary

### Puzzles

- one puzzle per chunk if short
- separate “position” and “solution explanation” chunks if long

### ChessDB Records

- one move candidate per chunk
- optionally one aggregate chunk per position

### PDFs

- chunk by section or slide title
- keep page range metadata for traceability

## Quality Gates Before Ingestion

Require the following before a source is marked complete:

1. Raw artifact saved successfully
2. Canonical URL recorded
3. Title extracted correctly
4. Boilerplate ratio below threshold
5. At least one useful chunk produced
6. Collection mapping reviewed
7. Spot-check by reading 3 sample chunks

## Implementation Order

### Wave 1: Fastest High-Value Corpus

Build first:

- xqinenglish opening pages
- xqinenglish midgame pages
- xqinenglish endgame overview pages
- xqinenglish proverb pages
- xqinenglish checkmate methods
- basics/how-to-play guides

Expected outcome:

- enough content to populate all four collections with useful English material

### Wave 2: Structured and Reference Sources

Build next:

- ChessDB opening query ingestion
- Xiangqi.com principle pages
- WXF PDF resources
- Xiangqi.com endgame compositions

Expected outcome:

- stronger factual coverage and better opening retrieval

### Wave 3: Specialized and Hard Sources

Build last:

- WXF transcript/video resources
- PyChess dynamic endpoints
- BrainKing forum threads
- app-based endgame resource extraction

Expected outcome:

- broader coverage, but only after the core pipeline is stable

## Suggested Deliverables

### Deliverable 1. Source Manifest

Create:

- `server/web_scraper/knowledge/sources.yaml`

Purpose:

- one source of truth for every planned acquisition target

### Deliverable 2. Raw Acquisition Layer

Create scripts/modules for:

- HTML fetch
- PDF download
- JSON/API fetch
- transcript fetch

Purpose:

- reproducible capture of raw artifacts

### Deliverable 3. Normalization Layer

Create scripts/modules for:

- article cleaner
- puzzle extractor
- PDF text extractor
- JSON-to-document transformer

Purpose:

- convert raw artifacts into consistent document JSONL

### Deliverable 4. Chunking and Ingestion Layer

Create scripts/modules for:

- semantic chunker
- deduper
- ChromaDB ingester

Purpose:

- populate `openings`, `tactics`, `endgames`, and `beginner_principles`

### Deliverable 5. Validation Suite

Create tests/checks for:

- manifest completeness
- raw artifact existence
- normalized schema validity
- duplicate detection
- collection mapping sanity
- ChromaDB insertion smoke tests

## Manual Review Checklist

Before declaring the migration complete:

- verify each collection has at least 50 to 100 good chunks to start
- verify `get_opening_plan` returns opening-specific content
- verify `get_middlegame_theme` returns tactical/middlegame guidance instead of generic advice
- verify `get_endgame_principle` returns endgame material, not general rules
- verify `get_general_advice`, `explain_tactic`, and `explain_puzzle_objective` retrieve beginner-friendly language
- verify source attribution is preserved in metadata

## Risks and Mitigations

### Risk: Source URLs drift or disappear

Mitigation:

- save raw artifacts and canonical URL snapshots immediately

### Risk: Boilerplate-heavy pages pollute embeddings

Mitigation:

- normalize aggressively and use chunk-level quality checks

### Risk: Duplicate wisdom sources overwhelm retrieval

Mitigation:

- run exact and semantic dedupe before ingestion

### Risk: Dynamic sources take too long

Mitigation:

- defer PyChess, app extraction, and forum scraping until Wave 1 and Wave 2 are complete

### Risk: Puzzle data lacks explicit FEN

Mitigation:

- store diagram text and manual notes first
- add board-state reconstruction later only where necessary

## Recommended First Execution Batch

Start with these sources first because they are English, static, and high-signal:

1. xqinenglish - Basics of Xiangqi 05 The Opening Phase
2. xqinenglish - Choosing your Xiangqi Opening
3. xqinenglish - Introduction to the Xiangqi Opening
4. xqinenglish - Strategical Advice in the Xiangqi Middle Game
5. xqinenglish - Introduction to the Xiangqi Midgame
6. xqinenglish - Basics of Xiangqi 08 The Endgame
7. xqinenglish - TJM Practical Endgames
8. xqinenglish - Xiangqi Proverbs: 84 Gems of Wisdom for Play
9. xqinenglish - Basic Xiangqi Checkmate Methods
10. xqinenglish - How to Play Xiangqi (Basics 02)

This first batch should be enough to validate the entire pipeline from acquisition to ChromaDB retrieval without starting on the harder API and transcript work yet.

## Next Step After This Plan

The next concrete implementation step should be:

1. create `server/web_scraper/knowledge/sources.yaml`
2. enter the canonical URLs and metadata for the first execution batch
3. scaffold a raw acquisition command that saves HTML snapshots and manifests
4. normalize those pages into document JSONL
5. ingest a small sample into ChromaDB and test the six Go RAG tools end to end
