from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

LOW_SIGNAL_SINGLE_WORD_TERMS = {
    "able",
    "about",
    "after",
    "again",
    "all",
    "almost",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "around",
    "as",
    "at",
    "away",
    "bag",
    "back",
    "be",
    "been",
    "before",
    "being",
    "beautiful",
    "both",
    "boy",
    "brother",
    "but",
    "by",
    "can",
    "chair",
    "child",
    "children",
    "common",
    "do",
    "does",
    "down",
    "each",
    "even",
    "every",
    "face",
    "father",
    "feel",
    "feels",
    "for",
    "from",
    "friendly",
    "gentle",
    "get",
    "girl",
    "go",
    "good",
    "has",
    "have",
    "hand",
    "he",
    "her",
    "here",
    "him",
    "his",
    "how",
    "if",
    "in",
    "inviting",
    "into",
    "is",
    "it",
    "its",
    "just",
    "kind",
    "like",
    "lovely",
    "make",
    "makes",
    "man",
    "many",
    "may",
    "more",
    "most",
    "much",
    "natural",
    "near",
    "of",
    "often",
    "on",
    "one",
    "or",
    "other",
    "our",
    "out",
    "over",
    "park",
    "person",
    "phone",
    "really",
    "right",
    "same",
    "seem",
    "seems",
    "she",
    "shirt",
    "shows",
    "sister",
    "nice",
    "so",
    "some",
    "still",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "table",
    "to",
    "too",
    "tree",
    "under",
    "up",
    "use",
    "used",
    "pleasant",
    "pretty",
    "very",
    "was",
    "way",
    "we",
    "well",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "woman",
    "would",
    "you",
    "your",
    "simple",
    "useful",
}

HIGH_VALUE_MULTIWORD_TERMS = {
    "appears to",
    "creating a sense of",
    "evoking a sense of",
    "giving a sense of",
    "gives the impression",
    "in front of",
    "in the background",
    "in the center",
    "in the distance",
    "in the foreground",
    "looks like",
    "next to",
    "on the side of",
    "seems to",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def slugify_filename(filename: str) -> str:
    stem = Path(filename).stem or "image"
    suffix = Path(filename).suffix.lower() or ".bin"
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "image"
    return f"{safe_stem}{suffix}"


def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if not phone:
        return ""

    prefix = "+"
    if phone.startswith("+"):
        body = phone[1:]
    else:
        prefix = ""
        body = phone

    digits = "".join(ch for ch in body if ch.isdigit())
    if not digits:
        return ""
    return f"{prefix}{digits}"


def normalize_answer(text: str) -> str:
    lowered = text.casefold()
    lowered = re.sub(r"\s+", " ", lowered)
    return re.sub(r"[^a-z0-9 ]+", "", lowered).strip()


def term_surface_score(text: str, *, kind: str = "") -> int:
    normalized = normalize_answer(text)
    if not normalized:
        return 0

    words = normalized.split()
    lowered_kind = kind.strip().casefold()
    if len(words) == 1:
        word = words[0]
        if word in LOW_SIGNAL_SINGLE_WORD_TERMS or len(word) <= 2:
            return 0
        if lowered_kind in {"verb", "noun", "adjective", "adverb"}:
            return 1
        return 1

    if normalized in HIGH_VALUE_MULTIWORD_TERMS:
        return 4
    if lowered_kind in {"expression", "idiom", "sentence pattern"}:
        return 4
    if len(words) >= 3:
        return 3
    return 2


def should_surface_term(text: str, *, kind: str = "") -> bool:
    return term_surface_score(text, kind=kind) > 0


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def extract_json_payload(text: str) -> dict:
    stripped = strip_json_fence(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def _highlight_single_paragraph(text: str, phrases: list[str]) -> str:
    unique_phrases = []
    seen = set()
    for phrase in sorted(
        (phrase.strip() for phrase in phrases if phrase and phrase.strip()),
        key=len,
        reverse=True,
    ):
        lowered = phrase.casefold()
        if lowered not in seen:
            seen.add(lowered)
            unique_phrases.append(phrase)

    lowered_text = text.casefold()
    occupied = [False] * len(text)
    spans: list[tuple[int, int, str]] = []

    for phrase in unique_phrases:
        lowered_phrase = phrase.casefold()
        start = 0
        while True:
            index = lowered_text.find(lowered_phrase, start)
            if index == -1:
                break
            end = index + len(phrase)

            if index > 0 and text[index - 1].isalnum():
                start = index + 1
                continue
            if end < len(text) and text[end].isalnum():
                start = index + 1
                continue
            if any(occupied[pos] for pos in range(index, end)):
                start = index + 1
                continue

            for pos in range(index, end):
                occupied[pos] = True
            spans.append((index, end, phrase))
            start = end

    if not spans:
        return html.escape(text)

    spans.sort(key=lambda item: item[0])
    cursor = 0
    chunks: list[str] = []
    for start, end, phrase in spans:
        if start > cursor:
            chunks.append(html.escape(text[cursor:start]))
        chunks.append(
            "<mark class=\"phrase-highlight\" data-phrase=\"{}\">{}</mark>".format(
                html.escape(phrase),
                html.escape(text[start:end]),
            )
        )
        cursor = end

    if cursor < len(text):
        chunks.append(html.escape(text[cursor:]))

    return "".join(chunks)


def highlight_phrases(text: str, phrases: list[str]) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text.strip())
        if paragraph.strip()
    ]
    if not paragraphs:
        return "<p></p>"

    return "".join(
        f"<p>{_highlight_single_paragraph(paragraph, phrases)}</p>"
        for paragraph in paragraphs
    )
