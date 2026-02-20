"""Tests for src.chunking — transcript splitting utility."""

from src.chunking import chunk_transcript


class TestChunkTranscript:
    def test_short_text_single_chunk(self):
        """Text under max_chars returns a single chunk."""
        text = "Hello world"
        chunks = chunk_transcript(text, max_chars=100)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_exact_max_chars(self):
        """Text exactly at max_chars is a single chunk."""
        text = "a" * 100
        chunks = chunk_transcript(text, max_chars=100)
        assert len(chunks) == 1

    def test_splits_long_text(self):
        """Text exceeding max_chars is split into multiple chunks."""
        text = "line\n" * 100  # 500 chars
        chunks = chunk_transcript(text, max_chars=200, overlap=50)
        assert len(chunks) > 1

    def test_all_text_covered(self):
        """Every character from the original text appears in at least one chunk."""
        text = "".join(f"line {i}\n" for i in range(200))
        chunks = chunk_transcript(text, max_chars=500, overlap=100)
        # Reconstruct: first chunk full, subsequent chunks skip overlap
        combined = chunks[0]
        for chunk in chunks[1:]:
            # Each subsequent chunk starts with overlap from previous
            combined += chunk[100:]  # skip overlap region
        # All original content should be present
        for i in range(200):
            assert f"line {i}" in "".join(chunks)

    def test_splits_at_newlines(self):
        """Chunks should break at newline boundaries, not mid-line."""
        lines = [f"Speaker: This is line number {i}\n" for i in range(50)]
        text = "".join(lines)
        chunks = chunk_transcript(text, max_chars=500, overlap=100)
        for chunk in chunks:
            # Each chunk should end with a newline (except possibly the last)
            if chunk != chunks[-1]:
                assert chunk.endswith("\n")

    def test_overlap_preserves_context(self):
        """Consecutive chunks share overlapping content."""
        text = "".join(f"line {i}\n" for i in range(100))
        chunks = chunk_transcript(text, max_chars=300, overlap=100)
        if len(chunks) >= 2:
            # End of chunk 0 should appear in start of chunk 1
            tail = chunks[0][-100:]
            assert tail in chunks[1]

    def test_empty_text(self):
        """Empty text returns single empty chunk."""
        chunks = chunk_transcript("", max_chars=100)
        assert len(chunks) == 1
        assert chunks[0] == ""

    def test_no_overlap(self):
        """Overlap of 0 produces non-overlapping chunks."""
        text = "a" * 300
        chunks = chunk_transcript(text, max_chars=100, overlap=0)
        assert len(chunks) == 3
        total_len = sum(len(c) for c in chunks)
        assert total_len == 300

    def test_default_params(self):
        """Default parameters (25K chars, 2K overlap) work correctly."""
        short = "x" * 1000
        assert len(chunk_transcript(short)) == 1

        long = "x\n" * 20000  # 40K chars
        chunks = chunk_transcript(long)
        assert len(chunks) >= 2
