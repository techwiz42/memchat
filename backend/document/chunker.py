"""Split extracted text into embedding-sized chunks."""

import re


def chunk_text(
    text: str, max_chars: int = 2000, overlap: int = 200
) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Splits on paragraph boundaries where possible, falling back to
    sentence boundaries, then to hard character splits.

    Args:
        text: The full extracted text.
        max_chars: Maximum characters per chunk.
        overlap: Number of characters to overlap between chunks.

    Returns:
        List of text chunks.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    # Split into paragraphs first
    paragraphs = re.split(r"\n\s*\n", text)

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If a single paragraph exceeds max_chars, split it by sentences
        if len(para) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            sentence_chunks = _split_long_block(para, max_chars, overlap)
            chunks.extend(sentence_chunks)
            continue

        # If adding this paragraph would exceed the limit, start a new chunk
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            # Start new chunk with overlap from the end of the previous chunk
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:].lstrip() + "\n\n" + para
            else:
                current = para
        else:
            if current:
                current += "\n\n" + para
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _split_long_block(
    text: str, max_chars: int, overlap: int
) -> list[str]:
    """Split a long block of text by sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:].lstrip() + " " + sentence
            else:
                current = sentence
        else:
            if current:
                current += " " + sentence
            else:
                current = sentence

    if current.strip():
        chunks.append(current.strip())

    # Handle case where a single sentence exceeds max_chars
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            # Hard split as last resort
            for i in range(0, len(chunk), max_chars - overlap):
                piece = chunk[i : i + max_chars]
                if piece.strip():
                    final.append(piece.strip())

    return final
