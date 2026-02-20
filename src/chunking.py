"""Call Recorder — transcript chunking for long calls."""


def chunk_transcript(
    text: str,
    max_chars: int = 25000,
    overlap: int = 2000,
) -> list[str]:
    """Split a transcript into overlapping chunks at line boundaries.

    Args:
        text: Full transcript text (plain or with timestamps).
        max_chars: Maximum characters per chunk. Default 25K fits
                   comfortably within 32K token context with prompt overhead.
        overlap: Characters of overlap between consecutive chunks to
                 avoid losing context at boundaries.

    Returns:
        List of chunk strings. Single-element list if text fits in one chunk.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + max_chars

        if end >= text_len:
            # Last chunk — take everything remaining
            chunks.append(text[start:])
            break

        # Find last newline before the cut point to avoid splitting mid-line
        last_nl = text.rfind("\n", start, end)
        if last_nl > start:
            end = last_nl + 1

        chunks.append(text[start:end])

        # Move start back by overlap to preserve context at boundaries
        start = end - overlap

    return chunks
