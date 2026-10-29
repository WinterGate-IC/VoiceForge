"""Long-form text handling.

A voice service will not swallow an entire chapter in one request, and even
where it would, one bad request loses everything. So a script is split at
natural boundaries and rendered in pieces, then glued back together with a
short pause between them.

The splitter never drops words: joining the chunks reproduces the input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_LIMIT = 1800  # characters per request - comfortably inside every limit

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")


@dataclass(frozen=True)
class Plan:
    characters: int
    words: int
    chunks: int
    limit: int

    def describe(self) -> str:
        parts = f"{self.chunks} part" + ("s" if self.chunks != 1 else "")
        return (f"{self.characters:,} characters · {self.words:,} words · {parts} "
                f"(max {self.limit:,} per part)")


def normalise(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing spaces/tabs per line without a backtracking regex: a
    # pattern like r"[ \t]+\n" is quadratic on a long run of tabs (CWE-1333).
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return text.strip()


def _hard_split(block: str, limit: int) -> list[str]:
    """Split a block that is longer than the limit, preferring word gaps."""
    out: list[str] = []
    current = ""
    for word in block.split():
        if len(word) > limit:  # a single unbroken token: slice it
            if current:
                out.append(current)
                current = ""
            out.extend(word[i:i + limit] for i in range(0, len(word), limit))
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return [c for c in out if c]


def _pack(pieces: list[str], limit: int) -> list[str]:
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                out.append(current)
            current = piece
    if current:
        out.append(current)
    return [c for c in out if c]


def _split_sentences(block: str, limit: int) -> list[str]:
    pieces: list[str] = []
    for sentence in _SENTENCE.split(block):
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        for clause in _CLAUSE.split(sentence):
            if len(clause) <= limit:
                pieces.append(clause)
            else:
                pieces.extend(_hard_split(clause, limit))
    return _pack(pieces, limit)


def split_for_speech(text: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Return chunks <= limit, in order, losing nothing."""
    text = normalise(text)
    if not text:
        return []
    limit = max(200, int(limit))

    chunks: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(buffer.strip())
        buffer = ""

    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > limit:
            flush()
            chunks.extend(_split_sentences(paragraph, limit))
            continue
        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= limit:
            buffer = candidate
        else:
            flush()
            buffer = paragraph
    flush()
    return chunks


def plan(text: str, limit: int = DEFAULT_LIMIT) -> Plan:
    text = normalise(text)
    return Plan(
        characters=len(text),
        words=len(text.split()),
        chunks=max(1, len(split_for_speech(text, limit))) if text else 0,
        limit=max(200, int(limit)),
    )
