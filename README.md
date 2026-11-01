<p align="center">
  <img src="searchy.png" width="280" alt="Searchy">
</p>

<h1 align="center">Searchy</h1>

<p align="center">
  Multimodal video search with a scene-scoped knowledge graph, hybrid GraphRAG retrieval,
  and answers that can only say what the indexed evidence supports.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19">
  <img src="https://img.shields.io/badge/Neo4j-5.26-008CC1?logo=neo4j&logoColor=white" alt="Neo4j 5.26">
  <img src="https://img.shields.io/badge/Qdrant-1.20-DC244C?logo=qdrant&logoColor=white" alt="Qdrant 1.20">
</p>

---

Searchy is a video analysis and retrieval system. It turns recordings — or an existing set of
processed scene chunks — into **evidence records you can point at**: every description, line of
dialogue, and visual observation keeps its source, its method, its model, its confidence, and
the time interval it belongs to. Search runs across those records, and the answer step may
publish a sentence only after the server can match it back to a stored record.

The constraint that drives the rest of the design is that a video index should not become a
plausible-sounding fiction engine. A scene description produced by a vision model is not the
same thing as a verified fact, and Searchy keeps that distinction visible all the way to the
interface instead of collapsing it at the prompt boundary.

## How it differs from plain RAG-over-video

- **Evidence is scoped, not global.** A clothing observation proves what was visible in *that*
  scene. It does not prove who owns the garment across a series, and it never silently upgrades
  to an identity claim.
- **Retrieval is deterministic before it is generative.** Query understanding is lexical and
  explainable, so the same query yields the same plan twice. No LLM decides what matched.
- **The answer is checked, not trusted.** Each generated claim must cite an evidence id that
  exists, whose scene matches, and whose quote appears verbatim in that record. A second model
  pass then judges entailment. Claims failing either gate are dropped with a warning.
- **Missing media stays missing.** A metadata-only scene is reported as metadata-only. Searchy
  does not synthesize a clip, invent a timestamp, or borrow a neighbouring scene's interval.

## Key Features

**Multimodal video understanding.** Each scene carries a description, word-timed dialogue, and
typed visual observations. Uploaded videos go through FFprobe validation, shot detection, frame
sampling and Whisper; existing processed chunks are imported as they are. Both paths yield the
same validated records.

**Computer vision and visual analysis.** A vision model receives a small set of representative
frames per scene and returns structured JSON: a description plus observations with `kind`,
`value`, optional `subject`, the underlying `evidence`, a `frame_index` and a `confidence`. It is
instructed not to infer motion between sparse frames and not to identify anyone from world
knowledge.

**Audio understanding and transcription.** faster-whisper produces word-level transcripts with
VAD filtering when the file has audio. Words are clipped to scene boundaries and merged across
short gaps. Non-speech audio events are not a current capability.

**Structured knowledge extraction.** Captions are parsed along their fixed headings into typed
observations; garments are attributed only where the caption itself puts them on a person.
Imported subtitles become `Dialogue` records with interval and provenance.

**Knowledge graph construction.** Ten node labels and nine relationship types in Neo4j, with
uniqueness constraints and idempotent upserts. Observations and dialogue stay scoped to the scene
that owns them; entities are shared, but the evidence mentioning them is not.

**Vector-based semantic retrieval.** Local `sentence-transformers` embeddings in named Qdrant
vectors, plus optional CLIP frame vectors. Named vectors encode the provider and model, so a
model change cannot silently mix vector spaces.

**Hybrid GraphRAG.** Qdrant semantic search, Neo4j graph search, optional visual search and exact
dialogue matching run as parallel channels. Reciprocal-rank fusion combines them, then
deterministic checks verify characters, clothing ownership, speaker attribution, quoted lines and
timing.

**Evidence-grounded LLM answers.** Generated claims must cite existing evidence ids, matching
scenes and verbatim quotes; a second model pass judges entailment. Unsupported statements are
dropped with a visible warning, and an answer with no surviving claim returns
`insufficient_evidence` rather than text.

**Graph evidence exploration.** A bounded, read-only subgraph of the retrieved scenes renders in
React Flow, with an inspector that shows each edge's supporting records and a jump straight to
the source scene at its timestamp.

**Character references with human review.** Reference images can be encoded with OpenCV
YuNet + SFace. Candidate matches remain `pending` until a reviewer accepts them, and only
accepted matches become verified observations.

