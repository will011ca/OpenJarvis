"""Timing behavior for microphone silence detection."""

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace

from openjarvis.speech.voice_io import record_until_silence, resolve_input_device


class _FakeStream:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = iter(frames)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def read(self, chunk: int):
        self.reads += 1
        return next(self.frames), False


def _install_audio(monkeypatch, stream: _FakeStream) -> None:
    fake_sd = SimpleNamespace(RawInputStream=lambda **kwargs: stream)
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)


def test_initial_silence_stops_at_startup_timeout(monkeypatch) -> None:
    silence = bytes(1024 * 2)
    stream = _FakeStream([silence] * 30)
    _install_audio(monkeypatch, stream)

    record_until_silence(
        sample_rate=1024,
        startup_silence_seconds=2,
        max_seconds=30,
    )

    assert stream.reads == 2


def test_post_speech_uses_normal_silence_window(monkeypatch) -> None:
    speech = struct.pack("1024h", *([1000] * 1024))
    silence = bytes(1024 * 2)
    stream = _FakeStream([speech, silence, silence, silence])
    _install_audio(monkeypatch, stream)

    record_until_silence(
        sample_rate=1024,
        silence_seconds=2,
        startup_silence_seconds=1,
        max_seconds=30,
    )

    assert stream.reads == 3


def test_resolve_input_device_defaults_to_system_device(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_MIC", raising=False)
    fake_sd = SimpleNamespace()

    assert resolve_input_device(fake_sd) is None


def test_resolve_input_device_accepts_index_or_name(monkeypatch) -> None:
    devices = [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Microphone", "max_input_channels": 1},
    ]
    fake_sd = SimpleNamespace(query_devices=lambda: devices)

    monkeypatch.setenv("JARVIS_MIC", "1")
    assert resolve_input_device(fake_sd) == 1
    monkeypatch.setenv("JARVIS_MIC", "usb mic")
    assert resolve_input_device(fake_sd) == 1


def test_resolve_input_device_rejects_ambiguous_name(monkeypatch) -> None:
    devices = [
        {"name": "USB Microphone 1", "max_input_channels": 1},
        {"name": "USB Microphone 2", "max_input_channels": 1},
    ]
    fake_sd = SimpleNamespace(query_devices=lambda: devices)
    monkeypatch.setenv("JARVIS_MIC", "USB Microphone")

    try:
        resolve_input_device(fake_sd)
    except RuntimeError as exc:
        assert "matches multiple input devices" in str(exc)
    else:
        raise AssertionError("Ambiguous microphone names must be rejected.")


def test_recording_uses_selected_input_device(monkeypatch) -> None:
    stream = _FakeStream([bytes(1024 * 2)] * 2)
    options = {}
    devices = [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Microphone", "max_input_channels": 1},
    ]
    fake_sd = SimpleNamespace(
        query_devices=lambda: devices,
        RawInputStream=lambda **kwargs: (options.update(kwargs) or stream),
    )
    monkeypatch.setenv("JARVIS_MIC", "1")
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    record_until_silence(
        sample_rate=1024,
        startup_silence_seconds=2,
        max_seconds=30,
    )

    assert options["device"] == 1
