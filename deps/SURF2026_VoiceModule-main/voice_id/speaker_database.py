from __future__ import annotations

import threading

import numpy as np

from config.voice_config import CONFIG


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerDatabase:
    """Rolling speaker registry using cosine similarity of voice embeddings.

    Each identify() call:
    - Compares the embedding against all stored entries.
    - If the best match >= threshold, returns that speaker's label and refreshes
      their stored embedding.
    - Otherwise registers a new label ("用户1", "用户2", …) and stores the entry.
    - History is capped at max_entries; the oldest entry is evicted first.
    """

    def __init__(
        self,
        threshold: float = CONFIG.speaker_sim_threshold,
        max_entries: int = CONFIG.speaker_max_history,
    ) -> None:
        self._threshold = threshold
        self._max_entries = max_entries
        self._entries: list[tuple[str, np.ndarray]] = []
        self._next_id = 1
        self._lock = threading.Lock()

    def identify_with_score(self, embedding: np.ndarray) -> tuple[str, float]:
        with self._lock:
            if self._entries:
                sims = [_cosine(embedding, e) for _, e in self._entries]
                best = int(np.argmax(sims))
                if sims[best] >= self._threshold:
                    label = self._entries[best][0]
                    self._entries[best] = (label, embedding)
                    return label, round(float(sims[best]), 4)
            label = f"用户{self._next_id}"
            self._next_id += 1
            if len(self._entries) >= self._max_entries:
                self._entries.pop(0)
            self._entries.append((label, embedding))
            return label, 0.0

    def identify(self, embedding: np.ndarray) -> str:
        label, _ = self.identify_with_score(embedding)
        return label

    @property
    def known_speakers(self) -> list[str]:
        with self._lock:
            return [lbl for lbl, _ in self._entries]
