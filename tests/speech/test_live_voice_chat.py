from __future__ import annotations

import asyncio
import struct
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openjarvis.cli._live_voice_chat import is_voice_exit, run_live_generation
from openjarvis.speech.live_input import LiveVoiceInput


class _Listener:
    def __init__(self, phrase_after: int | None = None) -> None:
        self.calls = 0
        self.phrase_after = phrase_after

    def take_nowait(self) -> bytes | None:
        self.calls += 1
        if self.phrase_after is not None and self.calls >= self.phrase_after:
            self.phrase_after = None
            return b"interruption audio"
        return None


class _Engine:
    def __init__(self, tokens: list[str], *, wait_after_first: bool = False) -> None:
        self.tokens = tokens
        self.wait_after_first = wait_after_first

    async def stream(self, messages, *, model, **kwargs):
        for index, token in enumerate(self.tokens):
            if index == 1 and self.wait_after_first:
                await asyncio.sleep(1)
            yield token


class _FiniteInputStream:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = iter(frames)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def read(self, chunk: int):
        return next(self.frames), False


def test_is_voice_exit_requires_explicit_phrase() -> None:
    assert is_voice_exit("  Jarvis   sair ")
    assert is_voice_exit("Jarvis, encerrar.")
    assert is_voice_exit("/QUIT")
    assert not is_voice_exit("quero sair mais tarde")


def test_live_input_emits_phrase_after_silence(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_MIC", raising=False)
    speech = struct.pack("1024h", *([1000] * 1024))
    silence = bytes(1024 * 2)
    stream = _FiniteInputStream([speech, *([silence] * 10)])
    fake_sd = SimpleNamespace(
        query_devices=lambda: [],
        RawInputStream=lambda **kwargs: stream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    listener = LiveVoiceInput()

    listener._capture()

    phrase = listener.next_phrase()
    assert phrase.startswith(b"RIFF")
    try:
        listener.next_phrase()
    except RuntimeError as exc:
        assert "Microphone capture failed" in str(exc)
    else:
        raise AssertionError("Microphone stream failure must be surfaced")


def test_live_generation_streams_sentences_to_speech_queue() -> None:
    spoken: list[str] = []
    with patch(
        "openjarvis.cli._live_voice_chat.speak",
        side_effect=lambda text, *args, **kwargs: spoken.append(text),
    ):
        response, interrupted = run_live_generation(
            _Engine(["Olá. ", "Como posso ajudar?"]),
            [],
            model="test-model",
            engine_kwargs={},
            listener=_Listener(),
            session=MagicMock(),
            console=MagicMock(),
        )

    assert response == "Olá. Como posso ajudar?"
    assert interrupted is None
    assert spoken == ["Olá.", "Como posso ajudar?"]


def test_live_generation_cancels_when_user_speaks() -> None:
    with (
        patch(
            "openjarvis.cli._live_voice_chat.transcribe_phrase",
            return_value="Pare, quero falar",
        ),
        patch("openjarvis.cli._live_voice_chat.stop_voice_playback"),
        patch("openjarvis.cli._live_voice_chat.speak"),
    ):
        response, interrupted = run_live_generation(
            _Engine(["Resposta parcial. ", "Ainda gerando"], wait_after_first=True),
            [],
            model="test-model",
            engine_kwargs={},
            listener=_Listener(phrase_after=2),
            session=MagicMock(),
            console=MagicMock(),
        )

    assert response == "Resposta parcial."
    assert interrupted == "Pare, quero falar"
