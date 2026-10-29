# Searchy

Searchy indexes video scenes and searches their dialogue, visual descriptions, and scene-scoped knowledge. Results include source timestamps, matching evidence, provenance, and playback availability.

Python **3.12** and [uv](https://docs.astral.sh/uv/) are required. No frontend is included.

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

Install [FFmpeg and FFprobe](https://ffmpeg.org/download.html), or set `FFMPEG_PATH` and `FFPROBE_PATH` to their executables. Uploaded videos require the `video` and `models` extras, FFmpeg, and a configured vision provider. Existing metadata imports need embeddings and databases; they do not call a VLM or Whisper. Docker uses isolated named volumes and localhost ports. Stop with `docker compose down`; omit `-v` to preserve data.

## Configuration

Copy `.env.example` only once and keep `.env` private. Settings are read from the current working directory. API keys and model/service validation occur at the relevant feature boundary, so health and metadata browsing remain usable without model credentials.

- Neo4j: set `NEO4J_PASSWORD`; `NEO4J_DATABASE=neo4j` works with Community Edition. No APOC plugin is required.
- Qdrant: configure URL, optional API key, and collection name. Named vectors encode model identity; incompatible model, dimension, distance, or visual configurations are rejected. Use a **new collection name and reimport** when changing models or enabling visual vectors. SQLite tracks which target/model configuration was indexed.
- Text: `LOCAL_EMBEDDING` uses Sentence Transformers. The default `google/embeddinggemma-300m` requires [accepted Hugging Face access terms](https://huggingface.co/google/embeddinggemma-300m) and an authorized `HF_TOKEN` or cached Hugging Face login. It runs in float32 and uses query/document prompts. A smaller ungated option is `sentence-transformers/all-MiniLM-L6-v2`; select it explicitly with a fresh collection.
- Hugging Face: models cache under `MODEL_CACHE_DIR`. `HF_HUB_ENABLE_HF_TRANSFER` is accepted for compatibility but ignored by modern Hub releases, which [use Xet](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables). Searchy does not install obsolete `hf-transfer`.
- Vision: choose `GOOGLE_GENAI` with `GEMINI_API_KEY`, or `GROQ` with `GROQ_API_KEY` and a currently available **vision-capable** `LLM_MODEL_ID`. Provider adapters share validated extraction contracts, bounded retries, and sanitized errors. Supplying dialogue does not establish speaker identity.
- `VLM_MAX_IMAGES` limits total evidence and reference images per request (defaults: Gemini 10, Groq 3). References use remaining slots after evidence frames. Set this to your selected model's documented image limit; fewer reference slots mean fewer identifiable characters.
- `VISUAL_ENABLED=true` enables CLIP frame vectors and text-to-image retrieval with `VISUAL_MODEL_ID`. Scenes without actual frames have no visual vector.
- `CHARACTER_REFERENCE_DIR` may contain named PNG reference images. Without usable references, uploaded video people remain unidentified. These are VLM-assisted observations, not face recognition or guaranteed identification.
- Set `API_KEY` to require `X-API-Key` on `/api/*`. This release is for a trusted local workspace: it has no user accounts, tenant isolation, quotas, or public hosting configuration. Bind to localhost.

## Data and timestamps

The available dataset has been copied into Searchy's own `data/` directory. `IMPORT_ROOT=data/episodes_splitted` and `CHARACTER_REFERENCE_DIR=data/meta` point to these local files; the reference project is no longer required. Keep `data/` when moving or backing up Searchy. It is excluded from Git, so a source-only checkout needs its own dataset copy. Only import media you are authorized to use.

The inspected collection contains **24 Friends season-one episodes, 550 captioned chunks, 9,199 subtitle records, six actual MP4 clips, and six character reference PNGs**. There are 544 metadata-only chunks, no full episodes, and no standalone SRT/VTT files. Aggregate captions are reused; merged summaries are excluded to avoid duplication. Generated descriptions have known character/dialogue inaccuracies and remain explicitly **unverified**, with unknown confidence. Subtitle text is stored independently, with no inferred speaker.

The original preprocessing used fixed 60-second chunks. Imported scene offsets are explicitly marked as inferred; subtitle intervals remain absolute episode seconds, including boundary overlaps. Final chunk duration can be unknown; Searchy never invents an episode duration. Uploaded video intervals come from probed media and grouped shot boundaries. Short shots are merged into bounded retrieval windows; these are not guaranteed narrative scene boundaries.

The six available clips are in episodes **1x11 (chunks 3,4), 1x14 (2,3), 1x15 (5), and 1x21 (4)**. Missing media produces `playback.available=false`; media endpoints return 404. `/media` serves the available source file with HTTP byte ranges and a scene offset; for uploaded videos the player should seek to `playback.start_offset` and stop at the scene end. It does not claim a full episode exists for imported clips.

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

## Architecture

```text
src/searchy/
  api/         request and response contracts
  core/        validated settings and safe service errors
  ingestion/   processed caption/subtitle/clip import
  processing/  FFprobe, shots, Whisper, frame sampling, extraction caches
  models/      lazy local embeddings and Gemini/Groq vision adapters
  graph/       constrained Neo4j writes and parameterized retrieval
  retrieval/   candidate fusion, evidence filters, deterministic reranking
  storage/     SQLite metadata/jobs and Qdrant vectors
  services/    application dependencies
  main.py      FastAPI application
  worker.py    durable ingestion worker
```

Both ingestion modes produce the same validated `Video`, `Scene`, `Dialogue`, `Observation`, and provenance records. Neo4j observations belong to a scene and optionally a precise evidence interval. Explicit subject links carry clothing/actions; co-occurrence never establishes who spoke or wore something. Reindexing replaces scene facts idempotently. Queries use fixed parameterized Cypher and never change indexed knowledge.

Search fuses semantic, visual and graph candidates with reciprocal-rank fusion, then reranks with observable term coverage and attribution checks. Scores are ranking signals, not calibrated probabilities. Results expose contributing channels, evidence and provenance; unsupported constraints are rejected or marked partial. No LLM writes a synthesized answer, scene, or timestamp during search. Literal outfit/quote checks favor precision and can miss synonyms; this first version has no learned cross-encoder reranker.

SQLite stores queued jobs, leases and progress. A separate heartbeat renews leases during inference; expired jobs can be reclaimed, with three attempts maximum. Only scenes successfully indexed into both external stores are searchable for the current configuration. Failed indexing is repairable by retrying. Writes across SQLite, Neo4j and Qdrant are not a distributed transaction; pending scenes are hidden from search. Run one worker for predictable local GPU/CPU memory and cache access. ASR, shot and VLM outputs are cached using media/model/settings fingerprints.

## Development validation

```powershell
uv lock --check
uv run ruff check src
uv run ruff format --check src
# Local development tests are deliberately ignored, per project policy:
uv run --extra models --extra video pytest .local-tests --basetemp .local-tests/tmp
```

The lock includes base, optional and development dependency groups. PyAV is constrained below 19 for the installed faster-whisper release's audio decoding API. Model weights, media, local tests, caches, generated outputs, database files and `.env` are excluded from Git. A fresh checkout includes no test data or private test scripts. Provider schema/transport tests do not constitute live Gemini/Groq verification; actual API access requires your keys and model availability.
