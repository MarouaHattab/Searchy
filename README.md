# Searchy

Searchy makes a video collection searchable by dialogue, characters, visual descriptions, and scene-scoped knowledge. Its React workspace brings together natural-language search, video playback, a searchable library, custom character references, an interactive evidence graph, and processing activity. Results include source timestamps, matching evidence, provenance, and playback availability.

Python **3.12**, [uv](https://docs.astral.sh/uv/), Docker, and Node.js **22.12+** are supported. Frontend dependencies are pinned in `frontend/package-lock.json`; Python dependencies are pinned in `uv.lock`.

## Run locally

From this directory in PowerShell:

```powershell
uv sync
Copy-Item .env.example .env   # only for a fresh installation
# Set a new NEO4J_PASSWORD in .env before starting databases.
docker compose up -d
uv sync --extra models --extra video
uv run --extra models --extra video uvicorn searchy.main:app --reload
```

In a second terminal, run one ingestion worker:

```powershell
uv run --extra models --extra video python -m searchy.worker
```

The API starts with base `uv sync` dependencies using `uv run uvicorn searchy.main:app --reload`. Model and video extras are loaded only when their features are used. Include the extras on subsequent `uv run` commands to keep them installed. The worker also accepts `--once`. Open [API docs](http://127.0.0.1:8000/docs), [Neo4j Browser](http://localhost:7474), or [Qdrant dashboard](http://localhost:6333/dashboard).

Start the frontend in another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open [Searchy](http://127.0.0.1:5173). Vite forwards API, readiness, thumbnails, subtitles, and media requests to `http://127.0.0.1:8000`. Keep the API running. For a production build, run `npm run build`; `npm run preview` serves that build locally at port 4173 with the same API proxy. A deployed frontend needs an equivalent reverse proxy and SPA routing fallback.

The optional `frontend/.env.example` documents `VITE_API_URL` for a separately hosted API. Leave it empty for the local proxy. Backend `CORS_ORIGINS` accepts a JSON array and defaults to the two localhost origins on port 5173. Add other origins explicitly when using a direct API URL. Never put provider credentials in `VITE_` variables. The browser app uses the trusted local workspace with the optional backend `API_KEY` unset.

The workspace includes real collection metrics, collection/character search filters, evidence-based result cards, paginated video and character browsing, scene transcripts, cached source thumbnails, and a player that seeks using file-relative offsets. Uploads show actual transfer progress, then link to durable processing jobs; retries create a new job. Settings shows live database health and provider configuration without exposing secrets. Desktop navigation collapses, mobile navigation supports keyboard focus, and light/dark preferences stay in the browser.

Install [FFmpeg and FFprobe](https://ffmpeg.org/download.html), or set `FFMPEG_PATH` and `FFPROBE_PATH` to their executables. Uploaded videos require the `video` and `models` extras, FFmpeg, and a configured vision provider. Existing metadata imports need embeddings and databases; they do not call a VLM or Whisper. Docker uses isolated named volumes and localhost ports. Stop with `docker compose down`; omit `-v` to preserve data.

## Configuration

Copy `.env.example` only once and keep `.env` private. Settings are read from the current working directory. API keys and model/service validation occur at the relevant feature boundary, so health and metadata browsing remain usable without model credentials.

- Neo4j: set `NEO4J_PASSWORD`; `NEO4J_DATABASE=neo4j` works with Community Edition. No APOC plugin is required.
- Qdrant: configure URL, optional API key, and collection name. Named vectors encode model identity; incompatible model, dimension, distance, or visual configurations are rejected. Use a **new collection name and reimport** when changing models or enabling visual vectors. SQLite tracks which target/model configuration was indexed.
- Text: `LOCAL_EMBEDDING` uses Sentence Transformers. The default `google/embeddinggemma-300m` requires [accepted Hugging Face access terms](https://huggingface.co/google/embeddinggemma-300m) and an authorized `HF_TOKEN` or cached Hugging Face login. It runs in float32 and uses query/document prompts. A smaller ungated option is `sentence-transformers/all-MiniLM-L6-v2`; select it explicitly with a fresh collection.
- Hugging Face: models cache under `MODEL_CACHE_DIR`. `HF_HUB_ENABLE_HF_TRANSFER` is accepted for compatibility but ignored by modern Hub releases, which [use Xet](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables). Searchy does not install obsolete `hf-transfer`.
- Vision: choose `GOOGLE_GENAI` with `GEMINI_API_KEY` and `LLM_MODEL_ID=gemini-3.5-flash-lite`, or `GROQ` with `GROQ_API_KEY` and a currently available **vision-capable** `LLM_MODEL_ID`. [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) supports image inputs and structured output. Provider adapters share validated extraction contracts, bounded retries, and sanitized errors. Supplying dialogue does not establish speaker identity. Searchy enforces observation limits locally when a provider cannot accept that schema constraint.
- `VLM_MAX_IMAGES` limits total evidence and reference images per request (defaults: Gemini 10, Groq 3). References use remaining slots after evidence frames. Set this to your selected model's documented image limit. Canonical identity assignment requires a complete comparison batch; insufficient slots keep people unidentified.
- `VISUAL_ENABLED=true` enables CLIP frame vectors and text-to-image retrieval with `VISUAL_MODEL_ID`. Scenes without actual frames have no visual vector.
- `CHARACTER_REFERENCE_DIR` contains legacy named PNG references used for imported catalog browsing. New uploads use only registered references scoped to their collection and optional video; without usable references, people remain unidentified.
- Optional local face recognition uses OpenCV YuNet and SFace from the [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models). Set `FACE_DETECTOR_PATH` and `FACE_RECOGNIZER_PATH` to downloaded ONNX files and install the `video` extra. Keep the models' license notices with the weights. `FACE_MATCH_THRESHOLD=0.5` and `FACE_MATCH_MARGIN=0.08` control automatic candidate qualification; cosine values are not identity probabilities. Without local face models, the configured VLM can compare references. Ambiguous references require review. Upload identity assignment requires all scoped identities to fit one comparison batch within `VLM_MAX_IMAGES`; otherwise extraction keeps people unidentified.
- Set `API_KEY` to require `X-API-Key` on `/api/*`. This release is for a trusted local workspace: it has no user accounts, tenant isolation, quotas, or public hosting configuration. Bind to localhost.

## Data and timestamps

The available dataset has been copied into Searchy's own `data/` directory. `IMPORT_ROOT=data/episodes_splitted` and `CHARACTER_REFERENCE_DIR=data/meta` point to these local files; the reference project is no longer required. Keep `data/` when moving or backing up Searchy. It is excluded from Git, so a source-only checkout needs its own dataset copy. Only import media you are authorized to use.

The inspected collection contains **24 Friends season-one episodes, 550 captioned chunks with local MP4 files, 9,199 subtitle records, and six character reference PNGs**. These are separate chunk files; no full episodes or standalone SRT/VTT files are present. Earlier imports exposed six clips; reimport after adding media to refresh playback references. Aggregate captions are reused; merged summaries are excluded to avoid duplication. Generated descriptions have known character/dialogue inaccuracies and remain explicitly **unverified**, with unknown confidence. Subtitle text is stored independently, with no inferred speaker.

The original preprocessing used fixed 60-second chunks. Imported scene offsets are explicitly marked as inferred; subtitle intervals remain absolute episode seconds, including boundary overlaps. Final chunk duration can be unknown; Searchy never invents an episode duration. Uploaded video intervals come from probed media and grouped shot boundaries. Short shots are merged into bounded retrieval windows; these are not guaranteed narrative scene boundaries.

Each available chunk can be played independently. Missing or removed media produces `playback.available=false`; media endpoints return 404. `/media` serves the available source file with HTTP byte ranges and a scene offset; for uploaded videos the player should seek to `playback.start_offset` and stop at the scene end. It does not claim a full episode exists for imported clips.

Complete matching episodes can restore playback without repeating transcription or visual analysis. Keep downloaded originals under `data/source_friends/` and place browser-compatible episode files in `EPISODE_MEDIA_DIR` (default `data/episodes`). An episode filename must match its processed episode folder name, ignoring case and whitespace; ambiguous matches are rejected. Use H.264/AAC MP4 files for browser playback, converting or remuxing MKV sources as needed. Renaming an extension does not convert a video. Reimport the collection after adding files. Scene IDs, captions, dialogue, and uncertainty are preserved; playback uses the inferred episode offset and the probed full-video duration. Full episodes take priority over individual clips, and scene intervals are bounded by the actual source duration. All media directories remain excluded from Git.

The leather-pants and “don't share food” example scenes are not evidenced in this season-one dataset. An example query is not a guarantee that its scene exists.

## API examples

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/api/imports/inspect
$job = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/imports -ContentType application/json -Body '{"collection_id":"friends"}'
Invoke-RestMethod "http://127.0.0.1:8000/api/jobs/$($job.job_id)"
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/search -ContentType application/json -Body '{"query":"Rachel wearing a wedding dress","limit":5}'
curl.exe -F "file=@C:/videos/example.mp4" -F "collection_id=uploads" http://127.0.0.1:8000/api/videos/upload
```

Imports support an optional `subpath` restricted to `IMPORT_ROOT`, a scene `limit`, and `force=true` to refresh unchanged records. Reimport checks actual scene presence in both databases so removed indexes are repaired. Uploads are streamed with a size cap, probed for real video content, then queued. Poll jobs for `queued`, `running`, `completed`, or `failed`, progress, stage and errors. Retry a failed job with `POST /api/jobs/{job_id}/retry`.

Other endpoints: `GET /api/jobs`, `/api/collections`, `/api/videos`, `/api/videos/{id}/scenes`, `/api/scenes/{id}`, and `/api/scenes/{id}/media`. Lists have bounded pagination. Search supports `hybrid`, `text`, `graph`, or `visual` mode, collection filters and explicit character filters. A successful `/ready` checks database availability and existing vector compatibility; it does not prove model downloads or vision-provider access.

Frontend catalog endpoints: `GET /api/workspace`, `/api/library?q=&collection_id=&limit=&offset=`, `/api/videos/{id}`, `/api/characters`, `/api/characters/{id}/reference`, and `/api/characters/{id}/scenes`. `GET /api/scenes/{id}/thumbnail` returns a real cached frame; `/api/scenes/{id}/subtitles.vtt` maps stored dialogue onto the served media timeline. Imported subtitle alignment remains approximate because clip origins are inferred. A reference image identifies the reference label; it does not independently confirm that label in every scene.

## Evidence exploration and custom characters

Searchy AI answers use a deterministic query plan, hybrid Qdrant/Neo4j candidates, relevance-selected dialogue and observations, and bounded graph expansion. The model receives the actual scene-scoped `SUBJECT`, `DESCRIBES`, `SPOKEN_BY`, `APPEARS_IN` and lineage links. Temporal questions can include up to four neighboring scenes in the same video; this is episode timeline order, not proof of narrative chronology or causality. Outfit checks preserve ownership, and explicit non-overlapping intervals cannot establish simultaneous actions.

`POST /api/search` returns a `search_id` and query intent alongside ranked scenes. `GET /api/search/sessions/{id}` restores the ranked response and any completed answer. SQLite retains at most 200 sessions for 24 hours; changed, unindexed or deleted evidence invalidates a session. No scene data or credentials are put in URLs. Query, filters, result limit and Scenes/Graph view remain shareable URL parameters. Browser session storage retains scroll, graph filters, selection, positions and viewport. The existing player provides Back to results, Escape, and Previous/Next in result ranking, with direct-link fallback to AI Search.

`POST /api/search/answer` accepts `query`, canonical `scene_ids` (up to 12), optional `collection_id`, `character_ids` and `search_id`. Answers use up to six ranked seeds and a 42,000-character structured context budget. Every published claim must cite a real source and an exact evidence quote, then pass a separate provider entailment check. Citations use stored evidence intervals, never model timestamps. Unverified captions remain qualified, and unsupported statements are omitted. Model verification is fallible and does not replace reviewing the source video.

`POST /api/search/answer/stream` consumes Gemini or Groq's actual streaming API. It sends SSE `status`, `delta` and `answer` events. A delta is a completed, verified claim, rather than unchecked tokens or simulated word-by-word playback. Cancellation closes the upstream request; generation failures preserve scene results and any verified partial answer. The interface uses plain text with inline citations, copy, a stop action and compact evidence details. Reduced-motion preferences disable the brief reveal transition.

The Evidence graph tab displays the same selected graph context passed to generation and verification. Scene nodes open the player; character and evidence selections reveal supporting scenes. Graph reads are parameterized and bounded, and answers never write inferred facts back to Neo4j. `POST /api/search/graph` remains available for independent bounded exploration; its optional `evidence_ids` selects actual graph observation/dialogue identifiers.

On Characters, add a name and collection, optionally restrict it to a video, then upload up to five JPEG/PNG/WebP references (10 MB and 12 megapixels each). Reference preparation and recognition are separate durable worker jobs. Start recognition after preparation; only accessible media or sampled frames can be scanned. Review proposed matches using their actual frame and timestamp. Accepted matches are marked human-reviewed; qualified machine candidates stay unverified. Matching faces alone never establishes clothing ownership or who spoke.

Custom identities use immutable IDs rather than names. Renaming updates scene/index labels asynchronously; description-only edits preserve recognition revisions. Replacing references validates the new image before swapping files, invalidates old identity associations, and requires another scan. Deletion removes registered associations while retaining unrelated imported evidence. Unchanged-interval imports preserve valid reviewed evidence; changed boundaries require recognition again. Cross-store writes are not atomic: an interrupted update leaves affected scenes unindexed until repaired.

Character APIs: `POST /api/characters`, `GET/PATCH/DELETE /api/characters/{id}`, `POST /api/characters/{id}/references` (multipart `files`), `DELETE /api/characters/{id}/references/{reference_id}`, `POST /api/characters/{id}/references/{reference_id}/replace` (multipart `file`), `POST /api/characters/{id}/recognize`, `GET /api/characters/{id}/matches?limit=&offset=`, and `PATCH /api/characters/{id}/matches/{match_id}` with `status=accepted|rejected`. Reference and match-frame URLs are supplied by the API. Embeddings and managed filesystem paths are private.

## Architecture

```text
src/searchy/
  api/         request/response contracts and catalog routes
  core/        validated settings and safe service errors
  ingestion/   processed caption/subtitle/clip import
  processing/  FFprobe, shots, Whisper, frame sampling, extraction caches
  models/      text/visual/face embeddings and Gemini/Groq adapters
  graph/       constrained Neo4j writes and parameterized retrieval
  retrieval/   candidate fusion, evidence filters, deterministic reranking
  storage/     SQLite metadata/jobs/search sessions and Qdrant vectors
  services/    catalog, grounded answers, character recognition and media assets
  main.py      FastAPI application
  worker.py    durable ingestion worker
```

```text
frontend/src/
  app/         routing and responsive workspace shell
  components/  shared controls and scene cards
  features/    search, graph exploration, characters, upload and scene player
  pages/       dashboard, library, characters, jobs, settings
  services/    typed HTTP client and shared query options
  lib/         formatting utilities
  styles/      design tokens and responsive component styles
  types.ts     API domain contracts
```

React Router loads pages on demand. TanStack Query owns server state, polling, cancellation and cache refresh. Requests have bounded timeouts, and search state stays in the URL. API errors, missing source files, unknown timestamps, and unverified identity remain explicit. No user accounts, billing, or editable server configuration are implied by the interface.

Both ingestion modes produce the same validated `Video`, `Scene`, `Dialogue`, `Observation`, and provenance records. Neo4j observations belong to a scene and optionally a precise evidence interval. Explicit subject links carry clothing/actions; co-occurrence never establishes who spoke or wore something. Reindexing replaces scene facts idempotently. Queries use fixed parameterized Cypher and never change indexed knowledge.

Search fuses semantic, visual and graph candidates with reciprocal-rank fusion, then reranks with observable term coverage and attribution checks. Scores are ranking signals, not calibrated probabilities. Results expose contributing channels, evidence and provenance; unsupported constraints are rejected or marked partial. An optional AI explanation is generated separately from retrieval using bounded indexed evidence, validated citations, and server-supplied scene links. It cannot create indexed scenes or timestamps. Model-written claims still need source review; quote validation and provider entailment checks do not guarantee factual correctness. Literal outfit/quote checks favor precision and can miss synonyms; this first version has no learned cross-encoder reranker.

SQLite stores queued jobs, leases and progress. A separate heartbeat renews leases during inference; expired jobs can be reclaimed, with three attempts maximum. Only scenes successfully indexed into both external stores are searchable for the current configuration. Failed indexing is repairable by retrying. Writes across SQLite, Neo4j and Qdrant are not a distributed transaction; pending scenes are hidden from search. Run one worker for predictable local GPU/CPU memory and cache access. ASR, shot and VLM outputs are cached using media/model/settings fingerprints.

## Development validation

```powershell
uv lock --check
uv run ruff check src
uv run ruff format --check src
# Local development tests are deliberately ignored, per project policy:
uv run --extra models --extra video pytest .local-tests --basetemp .local-tests/tmp
cd frontend
npm run typecheck
npm run build
```

The lock includes base, optional and development dependency groups. PyAV is constrained below 19 for the installed faster-whisper release's audio decoding API. Model weights, media, local tests, caches, generated outputs, database files and `.env` are excluded from Git. A fresh checkout includes no test data or private test scripts. Provider schema/transport tests do not constitute live Gemini/Groq verification; actual API access requires your keys and model availability.
