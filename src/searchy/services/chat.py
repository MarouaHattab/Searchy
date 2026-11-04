import json
import re

import httpx

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.retrieval.understanding import understand
from searchy.services.answers import AnswerService

_HEADINGS = (
    "SCENE SETTING",
    "CHARACTERS PRESENT",
    "ACTIONS AND INTERACTIONS",
    "OBJECTS AND PROPS",
    "DIALOGUE CONTEXT",
    "TEMPORAL NOTES",
)
_MARKUP = re.compile("|".join([r"[#*_`>]+"] + [re.escape(h) + ":?" for h in _HEADINGS]), re.I)

SYSTEM = """You are Searchy, answering questions about an indexed video collection.
Every numbered source below comes from that collection. Use only those sources.
If they do not contain the answer, say so plainly instead of guessing.
Cite the source numbers you used, like [1] or [2], at the end of a sentence.
Never invent a timestamp, an episode, a character or a quote.

Counting questions:
- A counted list in the sources is authoritative. Report its figure as the answer.
- Do not add up rows yourself if a total is already given.
- Do not count mentions inside prose; count the entries the sources list.

Grounding:
- Subtitles describe what is said; captions describe what is seen. Do not treat
  one as proof of the other, and do not assume a name in a caption is correct.
- If the sources disagree, say so rather than picking one.
- If a source only partly answers the question, say what is missing.

Style:
- Answer in the language the question was asked in.
- Lead with the direct answer, then the supporting detail. No preamble.
- Keep it to a few sentences unless the question needs more. Do not restate
  the question and do not describe the interface.
"""


_WHERE_CUES = re.compile(r"(where|which place|what place|located|live|work|stay|sit)", re.I)

_STOP = {
    "the", "and", "was", "were", "what", "where", "when", "who", "how", "does",
    "did", "have", "has", "had", "is", "are", "in", "on", "at", "to", "of",
    "for", "with", "that", "this", "there", "about", "any", "from", "into",
}


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9']+", text.lower())
        if word not in _STOP and len(word) > 2
    }


def _matching_passage(caption: str, query: str, width: int = 240) -> str:
    """The part of a caption that overlaps the question.

    A scene caption covers a whole minute: six people, their clothing, the
    props, and a dialogue summary. Handing all of it to a small model lets the
    irrelevant half answer instead of the relevant half, so the window with the
    most query terms is used.
    """
    if not caption:
        return ""
    wanted = _terms(query)
    if not wanted:
        return caption[:width]
    words = caption.split()
    step = max(1, width // 3)
    best, best_score = 0, -1
    for start in range(0, max(1, len(words) - width + step), step):
        window = " ".join(words[start : start + width])
        score = len(wanted & _terms(window))
        if score > best_score:
            best, best_score = start, score
    if best_score <= 0:
        return caption[:width]
    return " ".join(words[best : best + width])


def _matching_dialogue(scene, query: str, limit: int = 3) -> str:
    """The dialogue lines that share terms with the question."""
    wanted = _terms(query)
    scored = []
    for line in scene.dialogue:
        hits = len(wanted & _terms(line.text))
        if hits:
            scored.append((hits, line))
    if not scored:
        joined = " ".join(line.text for line in scene.dialogue)
        return joined[:220]
    scored.sort(key=lambda item: -item[0])
    return " ".join(line.text for _, line in scored[:limit])[:320]


_PRONOUN = re.compile(r"\b(he|she|him|her|his|hers|they|them|their)\b", re.I)
# Plurals and possessives cannot be mapped to one person without guessing.
_SINGULAR = {"he", "she", "him", "her", "his", "hers"}


def resolve_pronouns(question: str, history: list[dict], known: list[str]) -> str:
    """Replace a leading pronoun with the character the conversation was about.

    Chat does not rewrite follow-ups, so "how many times did he appear" reaches
    retrieval with no subject and counts the verb instead of the person. The
    most recent user turn that named a character supplies the antecedent.
    """
    match = _PRONOUN.search(question)
    if not match or not known:
        return question
    if match.group(1).lower() not in _SINGULAR:
        return question
    subject = None
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        text = (turn.get("content") or "").casefold()
        hits = [name for name in known if name.casefold() in text]
        # Exactly one name in the earlier turn is a safe antecedent. Two names
        # make the pronoun ambiguous, and guessing would answer a different
        # question than the one asked.
        if len(hits) == 1:
            subject = hits[0]
            break
        if len(hits) > 1:
            return question
    if not subject:
        return question
    # Only the first pronoun is replaced: a later "his" usually refers to
    # someone inside the answer, not to the topic of the conversation.
    return _PRONOUN.sub(subject, question, count=1)


class ChatService:
    """Retrieval-augmented chat over the scene index.

    Search picks the scenes, the model writes the reply from those scenes only,
    and every reply ships with the sources it may have used so the interface can
    show timestamps and jump into playback.
    """

    def __init__(self, settings: Settings, metadata, search, chat, graph=None):
        self.settings = settings
        self.metadata = metadata
        self.search = search
        self.chat = chat
        self.graph = graph
        self.answers = AnswerService(settings, metadata, search, graph=graph)

    def _sources(self, query: str, collection_id: str | None, limit: int) -> tuple[list, list]:
        result = self.search.search(query, limit=limit, collection_id=collection_id)
        scenes = []
        for match in result.get("results", []):
            scene = self.metadata.get_scene(match["scene_id"])
            if scene is None:
                continue
            scenes.append((scene, match))
        return scenes, result.get("warnings", [])

    def _context(self, scenes, query: str = "") -> tuple[str, list[dict]]:
        blocks = []
        sources = []
        for number, (scene, _match) in enumerate(scenes, 1):
            lines = [f"[{number}] {scene.episode_id or scene.video_id}"]
            if scene.start is not None and scene.end is not None:
                lines.append(f"    time: {scene.start:.1f}s to {scene.end:.1f}s")
            # A scene is one 60s chunk whose caption averages 400+ words, split
            # into several vector windows. Passing the whole caption lets an
            # unrelated clause become "evidence", so only the passage that
            # actually matched is shown, plus the structured fields this
            # question is about.
            caption = " ".join(_MARKUP.sub(" ", scene.description or "").split())
            passage = _matching_passage(caption, query)
            if passage:
                lines.append(f"    seen: {passage}")
            spoken = _matching_dialogue(scene, query)
            if spoken:
                lines.append(f"    said: {spoken}")
            for item in self.answers._select_evidence(scene, query, None)[:3]:
                if item["kind"] not in {"description", "dialogue"}:
                    lines.append(f"    {item['kind']}: {item['text'][:120]}")
            blocks.append("\n".join(lines))
            sources.append(
                {
                    "number": number,
                    "scene_id": scene.scene_id,
                    "label": f"{scene.episode_id or scene.video_id}",
                    "start": scene.start,
                    "end": scene.end,
                    "timestamp_basis": scene.timestamp_basis,
                    "available": bool(scene.media and scene.media.path),
                    "snippet": (caption or spoken)[:180],
                }
            )
        return "\n\n".join(blocks), sources

    def _messages(self, question: str, history: list[dict], context: str) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM}]
        for turn in history[-6:]:
            if turn["role"] in {"user", "assistant"} and turn["content"]:
                messages.append({"role": turn["role"], "content": turn["content"][:1200]})
        messages.append(
            {
                "role": "user",
                "content": f"Sources:\n{context or '(no matching scenes)'}\n\nQuestion: {question}",
            }
        )
        return messages

    def _endpoint(self) -> tuple[str, str]:
        base = self.settings.vllm_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        if not base:
            raise SearchyError(
                "Chat needs a local model. Set VLLM_BASE_URL to an Ollama server, "
                "for example http://127.0.0.1:11434/v1"
            )
        return base, self.settings.chat_model or "gemma3:1b"

    def stream(
        self,
        question: str,
        conversation_id: str | None,
        collection_id: str | None = None,
        character_ids: list[str] | None = None,
    ):
        question = question.strip()
        if not question:
            raise InvalidInput("Ask a question first")
        base, model = self._endpoint()
        # A follow-up like "how many times did he appear" carries no subject.
        # Retrieval needs the name, so the pronoun is resolved against the
        # conversation before anything else runs.
        history = self.chat.history(conversation_id) if conversation_id else []
        known = self.search.requested_characters(" ".join(t["content"] for t in history), collection_id)
        known = known or list(self.metadata.characters(collection_id))
        resolved = resolve_pronouns(question, history, known)

        plan = understand(resolved, self.search.requested_characters(resolved, collection_id))

        # The API sends the opening frame; the service starts at retrieval.
        scenes, warnings = self._sources(resolved, collection_id, self.settings.chat_source_limit)
        context, sources = self._context(scenes, resolved)
        # "Where does Monica work?" asks for a relation between a person and a
        # place. Ranking scenes by whether they mention Monica returns every
        # scene she is in, so the character's locations are fetched from the
        # graph and stated directly.
        if self.graph is not None and plan.characters and _WHERE_CUES.search(question):
            try:
                places = self.graph.where_is(plan.characters[0], 6)
            except SearchyError:
                places = []
            if places:
                listed = "; ".join(
                    f"{row['location']} ({row['scenes']} scenes)" for row in places
                )
                context = (
                    f"RELATION: locations of {plan.characters[0]}, most frequent first: "
                    f"{listed}\n\n{context}"
                )
                warnings.append(
                    f"Location for {plan.characters[0]} comes from where their scenes take place."
                )

        if plan.shape in {"count", "superlative", "list"} and self.graph is not None:
            try:
                aggregate = self.graph.aggregate(plan.shape, plan.shape_target)
            except SearchyError:
                aggregate = None
            if aggregate and aggregate.get("rows"):
                summary = "; ".join(
                    f"{row.get('label')}: {row.get('total')} scene(s)"
                    for row in aggregate["rows"][:8]
                    if row.get("label")
                )
                # A "count" row carries only the total, so it has no label and
                # produces no summary. The figure is the answer in that case.
                if not summary and aggregate["shape"] == "count":
                    summary = f"{aggregate['total']} scene(s) match"
                if summary:
                    # The counts are the answer to a shape question, so they head
                    # the list as their own numbered source. Otherwise the model
                    # cites [1]..[n] against graph rows the user cannot see.
                    sources.insert(
                        0,
                        {
                            "number": 1,
                            "scene_id": "",
                            "label": f"Graph counts for “{aggregate['term']}”",
                            "start": None,
                            "end": None,
                            "timestamp_basis": "aggregate",
                            "available": False,
                            "snippet": summary,
                        },
                    )
                    for offset, source in enumerate(sources[1:], 2):
                        source["number"] = offset
                    # State the figure plainly: a 2B model asked to count rows in
                    # prose gets it wrong, but it will repeat a number given to it.
                    answer_line = {
                        "count": f"COUNTED TOTAL: {aggregate['total']}",
                        "list": f"LISTED EPISODES: {len(aggregate['rows'])}",
                        "superlative": "RANKING (highest first)",
                    }.get(aggregate["shape"], "")
                    context = (
                        f"[1] Graph query for '{aggregate['term']}' "
                        f"({aggregate['shape']}). {answer_line}. "
                        f"Rows: {summary}\n\n{context}"
                    )

        yield "sources", {"sources": sources, "warnings": warnings}
        messages = self._messages(resolved, history, context)
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {
                "num_ctx": self.settings.chat_context,
                "temperature": self.settings.chat_temperature,
                "num_predict": self.settings.chat_max_tokens,
            },
        }

        answer = []
        try:
            with httpx.Client(timeout=max(self.settings.provider_timeout_seconds * 8, 600)) as client:
                with client.stream("POST", f"{base}/api/chat", json=payload) as response:
                    if not response.is_success:
                        raise SearchyError(f"Chat model returned HTTP {response.status_code}")
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue
                        piece = (data.get("message") or {}).get("content") or ""
                        if piece:
                            answer.append(piece)
                            yield "delta", {"text": piece}
                        if data.get("done"):
                            break
        except httpx.RequestError:
            raise SearchyError(f"Chat model at {base} is unreachable") from None

        text = "".join(answer).strip()
        if not text:
            text = "The model returned no answer. Try rephrasing the question."
            yield "delta", {"text": text}

        # The ranked-scene answer path verifies every claim before showing it;
        # chat used to show the model's text unchecked. A citation that points
        # past the supplied sources is the cheapest reliable signal that the
        # model invented its support, so it is checked here before display.
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        available = {source["number"] for source in sources}
        invalid = sorted(cited - available)
        if invalid:
            note = (
                "The model cited sources that were not provided, so this answer is "
                "unverified. Treat it as a lead and check the scenes below."
            )
            warnings.append(note)
            text = f"{text}\n\n_{note}_"
            yield "delta", {"text": f"\n\n{note}"}

        # A generator's return value is invisible to a `for` loop, so the
        # finished answer travels as an event instead.
        yield "answer", {
            "conversation_id": conversation_id,
            "answer": text,
            "sources": sources,
            "warnings": warnings,
            "model": model,
        }

    def respond(
        self,
        question: str,
        conversation_id: str | None,
        collection_id: str | None = None,
        character_ids: list[str] | None = None,
    ) -> dict:
        conversation = self.chat.ensure(conversation_id, title=question[:120])
        self.chat.append(conversation, "user", question)
        final: dict = {}
        for _event, payload in self.stream(question, conversation, collection_id, character_ids):
            if isinstance(payload, dict) and "answer" in payload:
                final = payload
        if not final:
            raise SearchyError("The chat model produced no answer")
        self.chat.append(
            conversation,
            "assistant",
            final["answer"],
            {"sources": final["sources"], "model": final["model"]},
        )
        return {**final, "conversation_id": conversation}
