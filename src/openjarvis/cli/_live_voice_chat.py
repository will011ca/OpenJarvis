"""Low-latency streamed responses and barge-in for live voice chat."""

from __future__ import annotations

import asyncio
import queue
import re
import threading
from typing import Any

from openjarvis.cli._voice_chat import VoiceSession, _terminal_safe_text, speak
from openjarvis.speech.live_input import LiveVoiceInput

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_EXIT_NORMALIZER = re.compile(r"[^\w\s/]", re.UNICODE)
_EXIT_PHRASES = {"/quit", "/exit", "jarvis sair", "jarvis encerrar"}


def transcribe_phrase(audio: bytes, session: VoiceSession, console: Any) -> str | None:
    """Transcribe a completed microphone phrase using the configured backend."""
    backend = session.get_stt_backend()
    if backend is None:
        raise RuntimeError("No healthy speech-to-text backend is available")
    result = backend.transcribe(
        audio, format="wav", language=session.get_stt_language()
    )
    text = result.text.strip()
    if text:
        console.print(f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}")
        return text
    console.print("[dim]Nothing heard — keep listening.[/dim]")
    return None


def is_voice_exit(text: str) -> bool:
    """Recognize explicit spoken commands for ending the live session."""
    normalized = _EXIT_NORMALIZER.sub("", text.casefold())
    return " ".join(normalized.split()) in _EXIT_PHRASES


def stop_voice_playback() -> None:
    """Stop sounddevice playback when the user interrupts spoken output."""
    import sounddevice as sd

    sd.stop()


async def _run_live_generation(
    engine: Any,
    messages: list[Any],
    *,
    model: str,
    engine_kwargs: dict[str, Any],
    listener: LiveVoiceInput,
    session: VoiceSession,
    console: Any,
) -> tuple[str, str | None]:
    audio_queue: queue.Queue[str | None] = queue.Queue()
    cancelled = threading.Event()
    speaker_done = threading.Event()

    def speak_queued_audio() -> None:
        try:
            while (sentence := audio_queue.get()) is not None:
                if not cancelled.is_set():
                    speak(sentence, console, session, cancel_event=cancelled)
        finally:
            speaker_done.set()

    speaker = threading.Thread(
        target=speak_queued_audio,
        name="openjarvis-live-voice-output",
        daemon=True,
    )
    speaker.start()

    response: list[str] = []
    pending_text = ""
    generation = engine.stream(messages, model=model, **engine_kwargs).__aiter__()
    next_token = asyncio.create_task(generation.__anext__())
    interrupted: str | None = None

    def queue_sentences(text: str, *, flush: bool = False) -> str:
        parts = _SENTENCE_END.split(text)
        remainder = "" if flush else parts.pop()
        ready = parts + ([remainder] if flush else [])
        if not flush and len(remainder) > 180:
            split_at = remainder.rfind(" ", 0, 180)
            if split_at > 0:
                ready.append(remainder[:split_at])
                remainder = remainder[split_at + 1 :]
        for part in ready:
            sentence = part.strip()
            if sentence:
                audio_queue.put(sentence)
        return remainder

    try:
        while True:
            done, _ = await asyncio.wait({next_token}, timeout=0.08)
            phrase = listener.take_nowait()
            if phrase is not None:
                cancelled.set()
                audio_queue.put(None)
                stop_voice_playback()
                next_token.cancel()
                try:
                    await next_token
                except asyncio.CancelledError:
                    pass
                interrupted = await asyncio.to_thread(
                    transcribe_phrase, phrase, session, console
                )
                if interrupted is None:
                    interrupted = ""
                break

            if not done:
                continue

            try:
                token = next_token.result()
            except StopAsyncIteration:
                break

            response.append(token)
            pending_text += token
            pending_text = queue_sentences(pending_text)
            next_token = asyncio.create_task(generation.__anext__())

        if interrupted is None:
            pending_text = queue_sentences(pending_text, flush=True)
            audio_queue.put(None)

        while not speaker_done.is_set():
            phrase = listener.take_nowait()
            if phrase is not None:
                cancelled.set()
                stop_voice_playback()
                interrupted = await asyncio.to_thread(
                    transcribe_phrase, phrase, session, console
                )
                if interrupted is None:
                    interrupted = ""
                break
            await asyncio.sleep(0.08)

        if interrupted is not None:
            cancelled.set()
            stop_voice_playback()
        await asyncio.to_thread(speaker.join, 2.0)
        return "".join(response).strip(), interrupted
    finally:
        if not next_token.done():
            next_token.cancel()
            try:
                await next_token
            except asyncio.CancelledError:
                pass
        close = getattr(generation, "aclose", None)
        if close is not None:
            await close()
        if not speaker_done.is_set():
            cancelled.set()
            audio_queue.put(None)
            stop_voice_playback()
            await asyncio.to_thread(speaker.join, 2.0)


def run_live_generation(
    engine: Any,
    messages: list[Any],
    *,
    model: str,
    engine_kwargs: dict[str, Any],
    listener: LiveVoiceInput,
    session: VoiceSession,
    console: Any,
) -> tuple[str, str | None]:
    """Stream a response, speaking sentence chunks and accepting barge-in."""
    return asyncio.run(
        _run_live_generation(
            engine,
            messages,
            model=model,
            engine_kwargs=engine_kwargs,
            listener=listener,
            session=session,
            console=console,
        )
    )


__all__ = ["is_voice_exit", "run_live_generation", "transcribe_phrase"]
