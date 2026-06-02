from __future__ import annotations

import numpy as np
import pytest

from voice_id.speaker_database import SpeakerDatabase, _cosine


def _emb(seed: int) -> np.ndarray:
    """Unit-norm random embedding, deterministic by seed."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(256).astype(np.float32)
    return v / np.linalg.norm(v)


# ── _cosine ────────────────────────────────────────────────────────────────────

def test_cosine_identical_vectors():
    v = _emb(0)
    assert _cosine(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_zero_vector_returns_zero():
    assert _cosine(np.zeros(256, dtype=np.float32), _emb(0)) == 0.0


# ── SpeakerDatabase ────────────────────────────────────────────────────────────

def test_first_call_registers_new_speaker():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    label = db.identify(_emb(0))
    assert label == "用户1"
    assert db.known_speakers == ["用户1"]


def test_identical_embedding_returns_same_label():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    emb = _emb(0)
    db.identify(emb)
    assert db.identify(emb) == "用户1"


def test_similar_embedding_same_label():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    emb = _emb(0)
    db.identify(emb)
    # Add small noise; similarity stays well above 0.65
    noisy = emb + np.random.default_rng(99).standard_normal(256).astype(np.float32) * 0.05
    noisy /= np.linalg.norm(noisy)
    assert db.identify(noisy) == "用户1"


def test_orthogonal_embedding_new_label():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    db.identify(_emb(0))
    # Seeds 0 and 42 produce nearly-orthogonal random vectors in 256-D
    label = db.identify(_emb(42))
    assert label == "用户2"
    assert db.known_speakers == ["用户1", "用户2"]


def test_incremental_labelling():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    for i in range(5):
        db.identify(_emb(i * 100))
    assert db.known_speakers == ["用户1", "用户2", "用户3", "用户4", "用户5"]


def test_evicts_oldest_when_full():
    db = SpeakerDatabase(threshold=0.65, max_entries=3)
    for i in range(3):
        db.identify(_emb(i * 100))
    assert len(db.known_speakers) == 3
    db.identify(_emb(999))  # fourth distinct speaker → evict 用户1
    assert len(db.known_speakers) == 3
    assert "用户1" not in db.known_speakers


def test_zero_embedding_does_not_crash():
    db = SpeakerDatabase(threshold=0.65, max_entries=20)
    label = db.identify(np.zeros(256, dtype=np.float32))
    assert label == "用户1"
