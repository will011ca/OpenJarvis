from __future__ import annotations

from types import SimpleNamespace

import jarvis_show
import numpy as np


class _FakeInputStream:
    def __init__(self, blocks: list[np.ndarray]) -> None:
        self.blocks = iter(blocks)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def read(self, _chunk: int):
        return next(self.blocks), False


def test_double_clap_is_detected_above_threshold(monkeypatch, capsys) -> None:
    stream = _FakeInputStream(
        [
            np.array([0.0], dtype=np.float32),
            np.array([0.8], dtype=np.float32),
            np.array([0.0], dtype=np.float32),
            np.array([0.8], dtype=np.float32),
        ]
    )
    times = iter([10.0, 10.4])
    monkeypatch.setattr(jarvis_show.time, "monotonic", lambda: next(times))
    fake_sd = SimpleNamespace(InputStream=lambda **_kwargs: stream)

    jarvis_show._listen_for_double_clap(fake_sd, np, None, 0.65)

    assert "Duas palmas detectadas." in capsys.readouterr().out
