"""Continuous microphone capture with voice-activity based phrase boundaries."""

from __future__ import annotations

import queue
import threading
from collections import deque

from openjarvis.speech.voice_io import (
    _CHUNK,
    _MAX_RECORD_SECONDS,
    _SAMPLE_RATE,
    _SILENCE_THRESHOLD,
    _frames_to_wav,
    _rms,
    resolve_input_device,
)


class LiveVoiceInput:
    """Capture complete speech phrases continuously on a background thread."""

    def __init__(
        self,
        *,
        sample_rate: int = _SAMPLE_RATE,
        silence_threshold: int = _SILENCE_THRESHOLD,
        silence_seconds: float = 0.55,
        max_phrase_seconds: float = _MAX_RECORD_SECONDS,
    ) -> None:
        if sample_rate <= 0 or silence_threshold < 0:
            raise ValueError("Invalid live voice input audio settings")
        if silence_seconds <= 0 or max_phrase_seconds <= 0:
            raise ValueError("Voice timing settings must be positive")
        self._sample_rate = sample_rate
        self._silence_threshold = silence_threshold
        self._silence_seconds = silence_seconds
        self._max_phrase_seconds = max_phrase_seconds
        self._phrases: queue.Queue[bytes | Exception] = queue.Queue()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._startup_error: Exception | None = None
        self._thread: threading.Thread | None = None

    def start(self, *, timeout: float = 10.0) -> None:
        """Start capture and wait for the microphone stream to open."""
        if self._thread is not None:
            raise RuntimeError("Live microphone capture has already been started")
        self._thread = threading.Thread(
            target=self._capture,
            name="openjarvis-live-microphone",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise RuntimeError("Timed out while opening the microphone")
        error = self._startup_error
        if error is not None:
            self.close()
            raise RuntimeError(
                f"Could not start microphone capture: {error}"
            ) from error

    def next_phrase(self, timeout: float | None = None) -> bytes:
        """Wait for a phrase; raise ``queue.Empty`` if the timeout expires."""
        item = self._phrases.get(timeout=timeout)
        if isinstance(item, Exception):
            raise RuntimeError(f"Microphone capture failed: {item}") from item
        return item

    def take_nowait(self) -> bytes | None:
        """Return a completed phrase immediately, if one is available."""
        try:
            item = self._phrases.get_nowait()
        except queue.Empty:
            return None
        if isinstance(item, Exception):
            raise RuntimeError(f"Microphone capture failed: {item}") from item
        return item

    def close(self) -> None:
        """Stop capture and join the microphone thread."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                raise RuntimeError("Microphone capture did not stop")
            self._thread = None

    def _capture(self) -> None:
        try:
            import sounddevice as sd

            silence_chunks = max(
                1, int(self._silence_seconds * self._sample_rate / _CHUNK)
            )
            max_chunks = max(
                1, int(self._max_phrase_seconds * self._sample_rate / _CHUNK)
            )
            device = resolve_input_device(sd)
            pre_roll: deque[bytes] = deque(maxlen=4)
            frames: list[bytes] = []
            silence_count = 0
            speaking = False

            with sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=_CHUNK,
                device=device,
            ) as stream:
                self._ready.set()
                while not self._stopping.is_set():
                    raw, _ = stream.read(_CHUNK)
                    data = bytes(raw)
                    amplitude = _rms(data)

                    if amplitude > self._silence_threshold:
                        if not speaking:
                            frames = list(pre_roll)
                            speaking = True
                        frames.append(data)
                        silence_count = 0
                    elif speaking:
                        frames.append(data)
                        silence_count += 1
                    else:
                        pre_roll.append(data)

                    if speaking and (
                        silence_count >= silence_chunks or len(frames) >= max_chunks
                    ):
                        self._phrases.put(_frames_to_wav(frames, self._sample_rate))
                        frames = []
                        pre_roll.clear()
                        silence_count = 0
                        speaking = False
        except Exception as exc:
            self._startup_error = exc
            self._phrases.put(exc)
            self._ready.set()


__all__ = ["LiveVoiceInput"]
