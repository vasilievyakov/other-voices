"""Speaker diarization WITHIN the system channel (remote participants).

Channel-level ME/OTHER (mic.wav vs system.wav) stays the guaranteed baseline.
This module refines the single system channel into per-speaker labels
SPEAKER_1..SPEAKER_N so multiple remote participants stop collapsing into one
SPEAKER_OTHER.

Approach (simplest thing that works, fully local / offline, no gated downloads):
  1. mlx_whisper already gives us system-channel segments with timestamps.
  2. For each segment we cut its audio slice and compute a 192-d speaker
     embedding with sherpa-onnx (CAM++ ONNX model, downloadable without any
     account/token).
  3. We cluster the embeddings with agglomerative clustering (cosine distance)
     to discover how many distinct voices there are, then relabel segments
     SPEAKER_1..N in order of first appearance.

Design guarantees:
  * Models are lazy-loaded (first diarize() call), so daemon startup stays fast.
  * diarize() NEVER raises. On disabled / missing model / any failure it falls
    back to labelling every system segment "SPEAKER_OTHER" — the pipeline must
    never break because of diarization.
  * Heavy deps (numpy, sklearn, sherpa_onnx) are imported lazily inside
    functions so importing this module is cheap.
"""

import logging
import time
import wave
from pathlib import Path

from .config import (
    DIARIZATION_DISTANCE_THRESHOLD,
    DIARIZATION_ENABLED,
    DIARIZATION_MAX_SPEAKERS,
    DIARIZATION_MIN_EMBED_DURATION,
    DIARIZATION_MODEL_PATH,
    DIARIZATION_MODEL_URL,
    DIARIZATION_NUM_SPEAKERS,
    DIARIZATION_NUM_THREADS,
)

log = logging.getLogger("call-recorder")

# Lazy singleton for the sherpa-onnx speaker embedding extractor.
_extractor = None
_extractor_failed = False


def _get_extractor():
    """Lazily construct the sherpa-onnx speaker embedding extractor.

    Returns the extractor, or None if unavailable (import error / missing model
    / load failure). Caches both success and failure so we try to load at most
    once per process.
    """
    global _extractor, _extractor_failed
    if _extractor is not None:
        return _extractor
    if _extractor_failed:
        return None

    try:
        import sherpa_onnx
    except Exception as e:  # noqa: BLE001 - never let import kill the pipeline
        log.warning(f"Diarization unavailable (sherpa_onnx import failed): {e}")
        _extractor_failed = True
        return None

    model_path = Path(DIARIZATION_MODEL_PATH)
    if not model_path.exists():
        log.warning(
            f"Diarization model not found at {model_path}; "
            "run diarizer.download_model() during setup. Falling back to SPEAKER_OTHER."
        )
        _extractor_failed = True
        return None

    try:
        t0 = time.time()
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path),
            num_threads=DIARIZATION_NUM_THREADS,
            provider="cpu",
        )
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        log.info(
            f"Loaded speaker embedding model ({_extractor.dim}-d) "
            f"in {time.time() - t0:.2f}s"
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"Failed to load speaker embedding model: {e}")
        _extractor_failed = True
        return None

    return _extractor


def _load_wav_mono(wav_path):
    """Read a WAV into a float32 mono numpy array. Returns (samples, sample_rate).

    Returns (None, None) if the format is unsupported or the file is unreadable.
    """
    import numpy as np

    try:
        with wave.open(str(wav_path), "rb") as w:
            sample_rate = w.getframerate()
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            n_frames = w.getnframes()
            raw = w.readframes(n_frames)
    except (wave.Error, OSError, EOFError) as e:
        log.warning(f"Could not read WAV {wav_path}: {e}")
        return None, None

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        log.warning(f"Unsupported WAV sample width {sampwidth} in {wav_path}")
        return None, None

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    return data, sample_rate


def _embed_segments(extractor, samples, sample_rate, segments, min_duration):
    """Compute one speaker embedding per long-enough segment.

    Returns (embeddings, embed_idx):
      embeddings: numpy array (M, dim) of embeddings, M <= len(segments)
      embed_idx:  list of segment indices aligned with `embeddings` rows
    Short/empty/failed segments are skipped (assigned later by nearest neighbour).
    """
    import numpy as np

    embeddings = []
    embed_idx = []
    min_samples = int(min_duration * sample_rate)
    hard_floor = int(0.25 * sample_rate)  # never embed less than 0.25s

    for i, seg in enumerate(segments):
        start = max(0.0, float(seg.get("start", 0.0)))
        end = float(seg.get("end", start))
        if end <= start:
            continue
        a = int(start * sample_rate)
        b = min(len(samples), int(end * sample_rate))
        chunk_len = b - a
        if chunk_len < min_samples or chunk_len < hard_floor:
            continue

        chunk = samples[a:b]
        try:
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sample_rate, waveform=chunk)
            stream.input_finished()
            emb = extractor.compute(stream)
        except Exception as e:  # noqa: BLE001
            log.warning(f"Embedding failed for segment {i}: {e}")
            continue

        emb = np.asarray(emb, dtype=np.float32)
        if emb.size == 0 or not np.all(np.isfinite(emb)):
            continue

        embeddings.append(emb)
        embed_idx.append(i)

    if not embeddings:
        return np.empty((0, 0), dtype=np.float32), []
    return np.vstack(embeddings), embed_idx


def _renumber_by_first_appearance(labels):
    """Relabel arbitrary cluster ids to 0,1,2,... in order of first appearance."""
    import numpy as np

    mapping = {}
    out = []
    nxt = 0
    for label in labels:
        key = int(label)
        if key not in mapping:
            mapping[key] = nxt
            nxt += 1
        out.append(mapping[key])
    return np.asarray(out, dtype=int)


def _cluster_embeddings(
    embeddings,
    distance_threshold,
    max_speakers,
    num_speakers=None,
):
    """Cluster speaker embeddings by cosine distance.

    Returns a numpy int array of cluster labels (0-indexed, renumbered by first
    appearance), one per embedding row.

    * num_speakers > 0: force exactly that many clusters (capped at n).
    * otherwise: auto-detect via `distance_threshold`, then cap at `max_speakers`.
    """
    import numpy as np

    n = len(embeddings)
    if n == 0:
        return np.empty((0,), dtype=int)
    if n == 1:
        return np.zeros((1,), dtype=int)

    from sklearn.cluster import AgglomerativeClustering

    if num_speakers and num_speakers > 0:
        k = min(int(num_speakers), n)
        raw = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average"
        ).fit_predict(embeddings)
        return _renumber_by_first_appearance(raw)

    raw = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=float(distance_threshold),
        metric="cosine",
        linkage="average",
    ).fit_predict(embeddings)

    n_found = len(set(raw.tolist()))
    if max_speakers and n_found > max_speakers:
        raw = AgglomerativeClustering(
            n_clusters=int(max_speakers), metric="cosine", linkage="average"
        ).fit_predict(embeddings)

    return _renumber_by_first_appearance(raw)


def _assign_speakers(segments, embed_idx, labels):
    """Map cluster labels onto every segment, returning a list of speaker strings.

    Embedded segments get their cluster's label. Short/skipped segments inherit
    the label of the temporally nearest embedded segment (by midpoint).
    Cluster ids are 1-indexed in the output: SPEAKER_1..SPEAKER_N.
    """
    n = len(segments)
    cluster_of = [None] * n
    for pos, seg_i in enumerate(embed_idx):
        cluster_of[seg_i] = int(labels[pos])

    embedded_mid = [
        (float(segments[i].get("start", 0.0)) + float(segments[i].get("end", 0.0)))
        / 2.0
        for i in embed_idx
    ]

    for i in range(n):
        if cluster_of[i] is not None:
            continue
        mid = (
            float(segments[i].get("start", 0.0)) + float(segments[i].get("end", 0.0))
        ) / 2.0
        best_pos = min(range(len(embed_idx)), key=lambda p: abs(embedded_mid[p] - mid))
        cluster_of[i] = int(labels[best_pos])

    return [f"SPEAKER_{c + 1}" for c in cluster_of]


def diarize(wav_path, segments, *, enabled=None):
    """Assign per-speaker labels to system-channel whisper segments.

    Args:
        wav_path: path to the single-channel system WAV.
        segments: list of {"start", "end", "text", ...} dicts (from whisper).
        enabled: override DIARIZATION_ENABLED (mainly for tests).

    Returns:
        A NEW list of segment dicts (copies) each with a "speaker" key set to
        "SPEAKER_1".."SPEAKER_N" on success, or "SPEAKER_OTHER" on fallback.
        Never raises.
    """
    segs = [dict(s) for s in segments]
    if not segs:
        return segs

    use = DIARIZATION_ENABLED if enabled is None else enabled
    if not use:
        for s in segs:
            s["speaker"] = "SPEAKER_OTHER"
        return segs

    try:
        extractor = _get_extractor()
        if extractor is None:
            raise RuntimeError("speaker embedding extractor unavailable")

        if not Path(wav_path).exists():
            raise FileNotFoundError(str(wav_path))

        t0 = time.time()
        samples, sample_rate = _load_wav_mono(wav_path)
        if samples is None or len(samples) == 0:
            raise RuntimeError("could not load audio")

        embeddings, embed_idx = _embed_segments(
            extractor, samples, sample_rate, segs, DIARIZATION_MIN_EMBED_DURATION
        )
        if len(embed_idx) == 0:
            raise RuntimeError("no embeddable segments (all too short)")

        labels = _cluster_embeddings(
            embeddings,
            distance_threshold=DIARIZATION_DISTANCE_THRESHOLD,
            max_speakers=DIARIZATION_MAX_SPEAKERS,
            num_speakers=DIARIZATION_NUM_SPEAKERS or None,
        )
        speakers = _assign_speakers(segs, embed_idx, labels)
        for s, spk in zip(segs, speakers):
            s["speaker"] = spk

        n_speakers = len(set(speakers))
        log.info(
            f"Diarization: {len(segs)} segments, {len(embed_idx)} embedded, "
            f"{n_speakers} speaker(s) in {time.time() - t0:.2f}s"
        )
        return segs
    except Exception as e:  # noqa: BLE001 - diarization must never break the pipeline
        log.warning(f"Diarization failed ({e}); falling back to SPEAKER_OTHER")
        for s in segs:
            s["speaker"] = "SPEAKER_OTHER"
        return segs


def download_model(dest_path=None, url=None) -> bool:
    """Download the speaker embedding model to the configured cache path.

    Reproducible-setup helper (not called on the hot path). Returns True on
    success or if the model already exists. Offline-safe: logs and returns False
    on failure instead of raising.
    """
    import urllib.error
    import urllib.request

    dest = Path(dest_path) if dest_path else Path(DIARIZATION_MODEL_PATH)
    src = url or DIARIZATION_MODEL_URL

    if dest.exists() and dest.stat().st_size > 0:
        log.info(f"Diarization model already present at {dest}")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading diarization model from {src} -> {dest}")
    try:
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(src, timeout=120) as resp, open(tmp, "wb") as f:
            f.write(resp.read())
        tmp.replace(dest)
        log.info(f"Downloaded diarization model ({dest.stat().st_size} bytes)")
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        log.warning(f"Failed to download diarization model: {e}")
        return False
