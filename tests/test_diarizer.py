"""Tests for src.diarizer — speaker diarization within the system channel.

Heavy models are never loaded here: the sherpa-onnx extractor is replaced with a
fake that turns audio level into a separable embedding, and the clustering /
assignment logic is exercised with synthetic embeddings. Numpy/scikit-learn are
required for the clustering tests (skipped if unavailable).
"""

import wave

import pytest

from src import diarizer

# Clustering needs numpy + scikit-learn; skip cleanly if the stack is absent.
np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")


# =============================================================================
# Fake speaker embedding extractor (no ONNX model)
# =============================================================================


class _FakeStream:
    def __init__(self):
        self.buf = None

    def accept_waveform(self, sample_rate, waveform):
        self.buf = np.asarray(waveform, dtype=np.float32)

    def input_finished(self):
        pass


class _FakeExtractor:
    """Maps audio sign to one of two orthogonal embeddings (cosine-separable)."""

    dim = 4

    def create_stream(self):
        return _FakeStream()

    def compute(self, stream):
        m = (
            float(np.mean(stream.buf))
            if stream.buf is not None and stream.buf.size
            else 0.0
        )
        return [1.0, 0.0, 0.0, 0.0] if m >= 0 else [0.0, 1.0, 0.0, 0.0]


def _write_wav(path, samples, sr=16000):
    """Write a float array to a 16-bit mono WAV."""
    data = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype(
        np.int16
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def _two_speaker_wav(path, sr=16000, seg_sec=2.0):
    """4s WAV: first half positive DC (speaker A), second half negative DC (B)."""
    n = int(seg_sec * sr)
    samples = np.concatenate(
        [np.full(n, 0.5, np.float32), np.full(n, -0.5, np.float32)]
    )
    _write_wav(path, samples, sr)
    return sr, seg_sec


# =============================================================================
# _renumber_by_first_appearance
# =============================================================================


class TestRenumber:
    def test_relabels_in_order_of_appearance(self):
        out = diarizer._renumber_by_first_appearance([5, 5, 2, 2, 9])
        assert list(out) == [0, 0, 1, 1, 2]

    def test_single_label(self):
        out = diarizer._renumber_by_first_appearance([7, 7, 7])
        assert list(out) == [0, 0, 0]

    def test_already_ordered(self):
        out = diarizer._renumber_by_first_appearance([0, 1, 2])
        assert list(out) == [0, 1, 2]


# =============================================================================
# _cluster_embeddings
# =============================================================================


def _blob(direction, n, jitter=0.02, seed=0):
    """n embeddings clustered around a unit direction with small noise."""
    rng = np.random.default_rng(seed)
    base = np.zeros(8, np.float32)
    base[direction] = 1.0
    return base + rng.normal(0, jitter, size=(n, 8)).astype(np.float32)


class TestClusterEmbeddings:
    def test_empty(self):
        labels = diarizer._cluster_embeddings(np.empty((0, 8)), 0.55, 8)
        assert len(labels) == 0

    def test_single_embedding(self):
        labels = diarizer._cluster_embeddings(_blob(0, 1), 0.55, 8)
        assert list(labels) == [0]

    def test_two_well_separated_clusters(self):
        emb = np.vstack([_blob(0, 4, seed=1), _blob(3, 4, seed=2)])
        labels = diarizer._cluster_embeddings(emb, 0.55, 8)
        assert len(set(labels.tolist())) == 2
        # first 4 share a label, last 4 share the other
        assert len(set(labels[:4].tolist())) == 1
        assert len(set(labels[4:].tolist())) == 1
        assert labels[0] != labels[4]

    def test_three_clusters(self):
        emb = np.vstack([_blob(0, 3, seed=1), _blob(2, 3, seed=2), _blob(5, 3, seed=3)])
        labels = diarizer._cluster_embeddings(emb, 0.55, 8)
        assert len(set(labels.tolist())) == 3

    def test_single_speaker_stays_one_cluster(self):
        emb = _blob(0, 6, seed=7)
        labels = diarizer._cluster_embeddings(emb, 0.55, 8)
        assert len(set(labels.tolist())) == 1

    def test_num_speakers_forces_count(self):
        # Two natural clusters, but force exactly 1.
        emb = np.vstack([_blob(0, 4, seed=1), _blob(3, 4, seed=2)])
        labels = diarizer._cluster_embeddings(emb, 0.55, 8, num_speakers=1)
        assert len(set(labels.tolist())) == 1

    def test_max_speakers_caps_count(self):
        # Three natural clusters, capped to 2.
        emb = np.vstack([_blob(0, 3, seed=1), _blob(2, 3, seed=2), _blob(5, 3, seed=3)])
        labels = diarizer._cluster_embeddings(emb, 0.55, max_speakers=2)
        assert len(set(labels.tolist())) == 2


# =============================================================================
# _assign_speakers
# =============================================================================


class TestAssignSpeakers:
    def test_maps_labels_one_indexed(self):
        segs = [
            {"start": 0.0, "end": 1.0},
            {"start": 1.0, "end": 2.0},
        ]
        speakers = diarizer._assign_speakers(segs, [0, 1], np.array([0, 1]))
        assert speakers == ["SPEAKER_1", "SPEAKER_2"]

    def test_short_segment_inherits_nearest(self):
        # seg 1 (index 1) was not embedded; it sits closest in time to seg 2.
        segs = [
            {"start": 0.0, "end": 3.0},  # embedded -> cluster 0
            {"start": 9.5, "end": 9.6},  # short, unembedded -> nearest = seg 2
            {"start": 10.0, "end": 13.0},  # embedded -> cluster 1
        ]
        speakers = diarizer._assign_speakers(segs, [0, 2], np.array([0, 1]))
        assert speakers[0] == "SPEAKER_1"
        assert speakers[2] == "SPEAKER_2"
        assert speakers[1] == "SPEAKER_2"  # inherited from temporally nearest


# =============================================================================
# _load_wav_mono
# =============================================================================


class TestLoadWav:
    def test_reads_mono_16bit(self, tmp_path):
        p = tmp_path / "a.wav"
        _write_wav(p, np.full(16000, 0.5, np.float32), sr=16000)
        samples, sr = diarizer._load_wav_mono(str(p))
        assert sr == 16000
        assert len(samples) == 16000
        assert abs(float(samples.mean()) - 0.5) < 0.01

    def test_unreadable_returns_none(self, tmp_path):
        p = tmp_path / "not_a.wav"
        p.write_bytes(b"garbage")
        samples, sr = diarizer._load_wav_mono(str(p))
        assert samples is None and sr is None


# =============================================================================
# diarize — happy path (fake extractor) and fallbacks
# =============================================================================


class TestDiarize:
    def test_two_speakers_end_to_end(self, tmp_path, monkeypatch):
        monkeypatch.setattr(diarizer, "_get_extractor", lambda: _FakeExtractor())
        wav = tmp_path / "system.wav"
        sr, seg = _two_speaker_wav(wav)
        segments = [
            {"start": 0.0, "end": 1.0, "text": "a1"},
            {"start": 1.0, "end": 2.0, "text": "a2"},
            {"start": 2.0, "end": 3.0, "text": "b1"},
            {"start": 3.0, "end": 4.0, "text": "b2"},
        ]
        out = diarizer.diarize(str(wav), segments)
        speakers = [s["speaker"] for s in out]
        assert speakers[0] == speakers[1]  # both in speaker A
        assert speakers[2] == speakers[3]  # both in speaker B
        assert speakers[0] != speakers[2]  # A != B
        assert set(speakers) == {"SPEAKER_1", "SPEAKER_2"}

    def test_does_not_mutate_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr(diarizer, "_get_extractor", lambda: _FakeExtractor())
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        segments = [{"start": 0.0, "end": 2.0, "text": "x"}]
        diarizer.diarize(str(wav), segments)
        assert "speaker" not in segments[0]  # caller's dict untouched

    def test_disabled_falls_back_to_other(self, tmp_path):
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        segments = [{"start": 0.0, "end": 2.0, "text": "x"}]
        out = diarizer.diarize(str(wav), segments, enabled=False)
        assert all(s["speaker"] == "SPEAKER_OTHER" for s in out)

    def test_empty_segments(self, tmp_path):
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        assert diarizer.diarize(str(wav), []) == []

    def test_model_unavailable_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(diarizer, "_get_extractor", lambda: None)
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        segments = [{"start": 0.0, "end": 2.0, "text": "x"}]
        out = diarizer.diarize(str(wav), segments)
        assert all(s["speaker"] == "SPEAKER_OTHER" for s in out)

    def test_missing_wav_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(diarizer, "_get_extractor", lambda: _FakeExtractor())
        segments = [{"start": 0.0, "end": 2.0, "text": "x"}]
        out = diarizer.diarize(str(tmp_path / "nope.wav"), segments)
        assert all(s["speaker"] == "SPEAKER_OTHER" for s in out)

    def test_all_segments_too_short_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(diarizer, "_get_extractor", lambda: _FakeExtractor())
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        # every segment shorter than DIARIZATION_MIN_EMBED_DURATION -> nothing embeds
        segments = [{"start": 0.0, "end": 0.1, "text": "x"}]
        out = diarizer.diarize(str(wav), segments)
        assert all(s["speaker"] == "SPEAKER_OTHER" for s in out)

    def test_extractor_raising_never_propagates(self, tmp_path, monkeypatch):
        class _Boom:
            dim = 4

            def create_stream(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(diarizer, "_get_extractor", lambda: _Boom())
        wav = tmp_path / "system.wav"
        _two_speaker_wav(wav)
        segments = [{"start": 0.0, "end": 2.0, "text": "x"}]
        # embedding raises per-segment -> no embeddings -> fallback, but never raises
        out = diarizer.diarize(str(wav), segments)
        assert all(s["speaker"] == "SPEAKER_OTHER" for s in out)


# =============================================================================
# download_model
# =============================================================================


class TestDownloadModel:
    def test_skips_when_present(self, tmp_path):
        existing = tmp_path / "model.onnx"
        existing.write_bytes(b"x" * 100)
        assert diarizer.download_model(dest_path=existing) is True
