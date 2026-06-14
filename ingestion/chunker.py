import re
import PyPDF2

# Rough approximation: 1 token ≈ 4 characters (standard for English prose/code).
# Used when a tokeniser library is unavailable.
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def chunk_pdf(filepath: str, tokens_per_chunk: int = 500, overlap_tokens: int = 50) -> list[str]:
    """Split PDF into overlapping token-sized chunks."""
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        full_text = " ".join(page.extract_text() or "" for page in reader.pages)
    return chunk_text(full_text, tokens_per_chunk=tokens_per_chunk, overlap_tokens=overlap_tokens)


def chunk_text(text: str, tokens_per_chunk: int = 500, overlap_tokens: int = 50) -> list[str]:
    """
    Split text into chunks of approximately `tokens_per_chunk` tokens with
    `overlap_tokens` of overlap between consecutive chunks.

    Splitting prefers sentence boundaries so that a chunk never cuts mid-sentence.
    Falls back to hard character splitting when no boundary is found.
    """
    chunk_chars = tokens_per_chunk * _CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN

    # Normalise whitespace but preserve paragraph breaks as sentence boundaries.
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    if not text:
        return []

    chunks: list[str] = []
    start = 0
    step = chunk_chars - overlap_chars

    while start < len(text):
        end = start + chunk_chars
        segment = text[start:end]

        # If this isn't the last chunk, trim to the last sentence boundary.
        if end < len(text):
            # Look for a sentence-ending punctuation followed by whitespace/newline.
            boundary = _last_sentence_boundary(segment)
            if boundary and boundary > chunk_chars // 2:
                segment = segment[:boundary]

        chunk = segment.strip()
        if chunk:
            chunks.append(chunk)

        # Advance by the length of the actual segment taken (minus overlap).
        advance = max(len(segment) - overlap_chars, step)
        start += advance

    return chunks


def _last_sentence_boundary(text: str) -> int | None:
    """Return the index just after the last sentence-ending boundary in `text`."""
    # Match '. ', '! ', '? ', or end of a paragraph ('\n\n').
    for match in reversed(list(re.finditer(r"(?<=[.!?])\s+|(?<=\n)\n", text))):
        return match.end()
    return None
