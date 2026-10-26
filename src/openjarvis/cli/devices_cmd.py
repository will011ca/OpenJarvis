"""Manage explicitly registered computers reachable over the private LAN."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from openjarvis.devices import (
    LanDevice,
    device_config_path,
    load_devices,
    remove_device,
    save_device,
)


@click.group("devices")
def devices() -> None:
    """Manage manually registered LAN computers."""


@devices.command("list")
def list_devices() -> None:
    """List registered devices without contacting them."""
    console = Console()
    try:
        configured = load_devices()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not configured:
        console.print(
            f"No computers registered. Add one with `jarvis devices add`.\n"
            f"Configuration: {device_config_path()}"
        )
        return
    table = Table(title="Registered LAN Computers")
    for column in ("ID", "Host", "User", "OS", "Port"):
        table.add_column(column)
    for device in configured:
        table.add_row(
            device.id,
            device.host,
            device.user,
            device.os,
            str(device.port),
        )
    console.print(table)


@devices.command("add")
@click.argument("device_id")
@click.option("--host", required=True, help="Private LAN IP or local hostname.")
@click.option("--user", required=True, help="SSH user account on the device.")
@click.option(
    "--os",
    "os_name",
    required=True,
    type=click.Choice(["windows", "linux", "macos"], case_sensitive=False),
    help="Remote operating system.",
)
@click.option("--port", default=22, show_default=True, type=click.IntRange(1, 65535))
@click.option(
    "--identity-file",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Optional SSH private key file; only its path is saved.",
)
def add_device(
    device_id: str,
    host: str,
    user: str,
    os_name: str,
    port: int,
    identity_file: Path | None,
) -> None:
    """Register one computer by explicit address; no network scan is performed."""
    key_path = str(identity_file.expanduser().resolve()) if identity_file else ""
    try:
        path = save_device(
            LanDevice(
                id=device_id,
                host=host,
                user=user,
                os=os_name.casefold(),
                port=port,
                identity_file=key_path,
            )
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    Console().print(f"Registered [cyan]{device_id}[/cyan] in {path}.")


@devices.command("remove")
@click.argument("device_id")
def remove_registered_device(device_id: str) -> None:
    """Remove a device from the local allowlist; does not affect the device."""
    try:
        removed = remove_device(device_id)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not removed:
        raise click.ClickException(f"Device {device_id!r} is not registered.")
    Console().print(f"Removed [cyan]{device_id}[/cyan] from the local registry.")


__all__ = ["devices"]
