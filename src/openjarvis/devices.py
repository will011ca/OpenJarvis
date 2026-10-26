"""Configuration for explicitly registered computers on a private LAN."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_USER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_OS_NAMES = {"windows", "linux", "macos"}


@dataclass(frozen=True, slots=True)
class LanDevice:
    id: str
    host: str
    user: str
    os: str
    port: int = 22
    identity_file: str = ""


def device_config_path() -> Path:
    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / "devices.toml"


def validate_device(device: LanDevice) -> LanDevice:
    if not _DEVICE_ID.fullmatch(device.id):
        raise ValueError("Device id must use 1-32 letters, numbers, '_' or '-'.")
    if not _USER.fullmatch(device.user):
        raise ValueError("SSH user must use only letters, numbers, '.', '_' or '-'.")
    if device.os not in _OS_NAMES:
        raise ValueError("OS must be one of: windows, linux, macos.")
    if not isinstance(device.port, int) or not 1 <= device.port <= 65535:
        raise ValueError("SSH port must be an integer from 1 to 65535.")

    host = device.host.strip()
    if not host or any(char in host for char in "/\\@"):
        raise ValueError("Host must be a private IP address or a LAN hostname.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.rstrip(".").split(".")
        suffix = ".".join(labels[1:]).casefold()
        valid_suffix = suffix in {"local", "lan", "home.arpa"}
        if not (
            all(
                1 <= len(label) <= 63
                and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                for label in labels
            )
            and (len(labels) == 1 or valid_suffix)
        ):
            raise ValueError(
                "LAN hostnames must be a single label or end in .local, .lan, "
                "or .home.arpa."
            )
    else:
        if (
            address.is_loopback
            or address.is_multicast
            or address.is_unspecified
            or not (
                address.is_link_local
                or address in ipaddress.ip_network("10.0.0.0/8")
                or address in ipaddress.ip_network("172.16.0.0/12")
                or address in ipaddress.ip_network("192.168.0.0/16")
                or address in ipaddress.ip_network("fc00::/7")
            )
        ):
            raise ValueError("IP address must be on a private or link-local network.")

    identity_file = device.identity_file.strip()
    if identity_file:
        key_path = Path(identity_file).expanduser()
        if not key_path.is_absolute() or not key_path.is_file():
            raise ValueError("Identity file must be an existing absolute file path.")

    return LanDevice(
        id=device.id,
        host=host,
        user=device.user,
        os=device.os,
        port=device.port,
        identity_file=identity_file,
    )


def load_devices() -> list[LanDevice]:
    path = device_config_path()
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Could not read device configuration {path}: {exc}") from exc

    entries = data.get("device", [])
    if not isinstance(entries, list):
        raise ValueError(f"Expected [[device]] entries in {path}.")

    devices: list[LanDevice] = []
    ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Device entry {index + 1} in {path} must be a table.")
        try:
            device = validate_device(
                LanDevice(
                    id=entry["id"],
                    host=entry["host"],
                    user=entry["user"],
                    os=entry["os"],
                    port=entry.get("port", 22),
                    identity_file=entry.get("identity_file", ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid device entry {index + 1} in {path}: {exc}"
            ) from exc
        if device.id in ids:
            raise ValueError(f"Duplicate device id {device.id!r} in {path}.")
        ids.add(device.id)
        devices.append(device)
    return devices


def save_device(device: LanDevice) -> Path:
    import tomlkit
    from tomlkit.items import AoT

    device = validate_device(device)
    path = device_config_path()
    if path.exists():
        try:
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
        except (OSError, tomlkit.exceptions.ParseError) as exc:
            raise ValueError(
                f"Could not read device configuration {path}: {exc}"
            ) from exc
    else:
        document = tomlkit.document()

    existing = load_devices()
    if any(item.id == device.id for item in existing):
        raise ValueError(f"Device id {device.id!r} is already registered.")

    entries = document.get("device")
    if entries is None:
        entries = tomlkit.aot()
        document.add("device", entries)
    elif not isinstance(entries, AoT):
        raise ValueError(f"Expected [[device]] entries in {path}.")

    table: Any = tomlkit.table()
    table.add("id", device.id)
    table.add("host", device.host)
    table.add("user", device.user)
    table.add("os", device.os)
    table.add("port", device.port)
    if device.identity_file:
        table.add("identity_file", device.identity_file)
    entries.append(table)

    from openjarvis.security.file_utils import secure_write_text

    secure_write_text(path, tomlkit.dumps(document), mode=0o600, encoding="utf-8")
    return path


def remove_device(device_id: str) -> bool:
    import tomlkit
    from tomlkit.items import AoT

    path = device_config_path()
    if not path.exists():
        return False
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.ParseError) as exc:
        raise ValueError(
            f"Could not read device configuration {path}: {exc}"
        ) from exc
    entries = document.get("device")
    if not isinstance(entries, AoT):
        return False
    retained = [entry for entry in entries if entry.get("id") != device_id]
    if len(retained) == len(entries):
        return False
    document["device"] = tomlkit.aot()
    for entry in retained:
        document["device"].append(entry)
    from openjarvis.security.file_utils import secure_write_text

    secure_write_text(path, tomlkit.dumps(document), mode=0o600, encoding="utf-8")
    return True


__all__ = [
    "LanDevice",
    "device_config_path",
    "load_devices",
    "remove_device",
    "save_device",
    "validate_device",
]
