"""
rag/chunker.py  —  Phase 15: Sentence-aware chunking

Previous version: dumb character-level slicing at 500 chars.
Problems:
  - Chunks cut mid-sentence → embeddings represent incomplete thoughts
  - Overlap of 100 chars often started mid-word
  - No minimum chunk length → tiny fragments wasted embedding slots

New version:
  - Split on sentence boundaries first (period/newline)
  - Build chunks by accumulating sentences until target size
  - Overlap carries the LAST sentence of the previous chunk (meaningful)
  - Filter out chunks shorter than MIN_CHUNK_CHARS (noise)
  - Larger default chunk size (800) captures more context per embedding
"""

import re

CHUNK_SIZE    = 800    # target characters per chunk
CHUNK_OVERLAP = 200   # overlap in characters (carried as whole sentences)
MIN_CHUNK     = 80    # discard chunks shorter than this


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation and newlines."""
    # Normalise whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Split on: end of sentence punctuation OR double newline (paragraph break)
    parts = re.split(r"(?<=[.!?])\s+|(?:\n\s*\n)", text)
    sentences = []
    for p in parts:
        p = p.strip()
        if p:
            sentences.append(p)
    return sentences


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Build overlapping chunks from sentence-split text.
    Each chunk is roughly `chunk_size` chars, with the last sentence(s)
    of the previous chunk prepended for context continuity.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence) + 1  # +1 for space

        # If adding this sentence would exceed limit and we have content, flush
        if current_len + sentence_len > chunk_size and current_sentences:
            chunk = " ".join(current_sentences).strip()
            if len(chunk) >= MIN_CHUNK:
                chunks.append(chunk)

            # Carry overlap: keep sentences from the end that fit in `overlap`
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current_sentences):
                if overlap_len + len(s) + 1 <= overlap:
                    overlap_sentences.insert(0, s)
                    overlap_len += len(s) + 1
                else:
                    break

            current_sentences = overlap_sentences
            current_len = overlap_len

        current_sentences.append(sentence)
        current_len += sentence_len

    # Flush remaining
    if current_sentences:
        chunk = " ".join(current_sentences).strip()
        if len(chunk) >= MIN_CHUNK:
            chunks.append(chunk)

    return chunks
