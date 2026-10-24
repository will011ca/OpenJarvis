from __future__ import annotations

import argparse
import ctypes
import math
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
WEB_URL = "http://127.0.0.1:8000/"
HEALTH_URL = "http://127.0.0.1:8000/health"
CLAP_PAIR_SECONDS = 1.25
CLAP_MIN_INTERVAL_SECONDS = 0.18


def _prepare_path() -> None:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    candidates = (
        Path.home() / ".local" / "bin",
        local_app_data / "Programs" / "Ollama",
    )
    current = os.environ.get("PATH", "").split(os.pathsep)
    for candidate in candidates:
        if candidate.is_dir() and not any(
            str(candidate).casefold() == entry.rstrip("\\").casefold()
            for entry in current
        ):
            current.insert(0, str(candidate))
    os.environ["PATH"] = os.pathsep.join(current)


def _uv_executable() -> str:
    uv = shutil.which("uv")
    if uv:
        return uv
    candidate = Path.home() / ".local" / "bin" / "uv.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("uv não foi encontrado; instale-o antes de executar.")


def _threshold() -> float:
    value = os.environ.get("JARVIS_CLAP_THRESH", "0.65")
    try:
        threshold = float(value)
    except ValueError as exc:
        raise ValueError(
            "JARVIS_CLAP_THRESH precisa ser um número entre 0 e 1."
        ) from exc
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("JARVIS_CLAP_THRESH precisa estar no intervalo (0, 1].")
    return threshold


def _list_microphones() -> int:
    import sounddevice as sd

    devices = sd.query_devices()
    microphones = [
        (index, device)
        for index, device in enumerate(devices)
        if int(device.get("max_input_channels", 0)) > 0
    ]
    if not microphones:
        print("Nenhum microfone de entrada foi detectado.")
        return 1
    for index, device in microphones:
        print(f"{index}: {device['name']}")
    return 0


def _listen_for_double_clap(sd, np, device: int | None, threshold: float) -> None:
    print(
        f"Escutando palmas no microfone {device if device is not None else 'padrão'} "
        f"(limiar {threshold:.2f}); dê duas palmas em até "
        f"{CLAP_PAIR_SECONDS:.2f} s. Ctrl+C cancela."
    )
    previous_block_was_loud = False
    first_clap_at: float | None = None

    with sd.InputStream(
        device=device,
        channels=1,
        samplerate=16000,
        blocksize=512,
        dtype="float32",
    ) as stream:
        while True:
            audio, _overflowed = stream.read(512)
            is_loud = float(np.max(np.abs(audio))) >= threshold
            if is_loud and not previous_block_was_loud:
                now = time.monotonic()
                if first_clap_at is not None:
                    interval = now - first_clap_at
                    if CLAP_MIN_INTERVAL_SECONDS <= interval <= CLAP_PAIR_SECONDS:
                        print("Duas palmas detectadas.")
                        return
                if first_clap_at is None or now - first_clap_at > CLAP_PAIR_SECONDS:
                    print("Primeira palma detectada.")
                    first_clap_at = now
            previous_block_was_loud = is_loud


def _mci(command: str) -> None:
    winmm = ctypes.WinDLL("winmm")
    send = winmm.mciSendStringW
    send.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    send.restype = ctypes.c_uint
    error = send(command, None, 0, None)
    if error:
        message = ctypes.create_unicode_buffer(256)
        get_error = winmm.mciGetErrorStringW
        get_error.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        get_error.restype = ctypes.c_int
        get_error(error, message, len(message))
        raise OSError(f"Falha ao reproduzir jingle: {message.value or error}")


def _play_jingle_if_present() -> None:
    jingle = ROOT / "voice" / "assets" / "jingle.mp3"
    if not jingle.is_file():
        print(f"Jingle não encontrado; seguindo sem ele ({jingle}).")
        return

    _mci(f'open "{jingle}" type mpegvideo alias jarvis_jingle')
    try:
        _mci("play jarvis_jingle wait")
    finally:
        _mci("close jarvis_jingle")


def _url_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=1) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def _open_web_ui(uv: str) -> None:
    if not _url_is_ready(HEALTH_URL):
        result = subprocess.run(
            [uv, "run", "jarvis", "start", "--port", "8000"],
            cwd=ROOT,
            env=os.environ.copy(),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"jarvis start terminou com código {result.returncode}."
            )

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not _url_is_ready(HEALTH_URL):
            time.sleep(0.5)
        if not _url_is_ready(HEALTH_URL):
            raise RuntimeError("A API não respondeu na porta 8000 em 90 segundos.")

    if not _url_is_ready(WEB_URL):
        raise RuntimeError(f"A interface web não respondeu em {WEB_URL}.")
    if not webbrowser.open(WEB_URL):
        raise RuntimeError(f"Não foi possível abrir o navegador em {WEB_URL}.")
    print(f"Interface web aberta em {WEB_URL}.")


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Este acionador foi configurado para Windows.")

    parser = argparse.ArgumentParser(description="Ativa o OpenJarvis com duas palmas.")
    parser.add_argument(
        "--list-mics",
        action="store_true",
        help="Lista os microfones disponíveis e encerra.",
    )
    args = parser.parse_args()
    if args.list_mics:
        return _list_microphones()

    _prepare_path()
    import numpy as np
    import sounddevice as sd

    from openjarvis.speech.voice_io import resolve_input_device

    threshold = _threshold()
    device = resolve_input_device(sd)
    uv = _uv_executable()
    _listen_for_double_clap(sd, np, device, threshold)
    _play_jingle_if_present()
    _open_web_ui(uv)
    return subprocess.run(
        [uv, "run", "jarvis", "chat", "--voice"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    ).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAcionador interrompido.", file=sys.stderr)
        raise SystemExit(130)
