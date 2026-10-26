"""Confirmed, read-only SSH diagnostics for manually registered LAN computers."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.devices import load_devices
from openjarvis.tools._stubs import BaseTool, ToolSpec

_ACTIONS = {
    "system_info": "Show the remote computer's hostname and operating system.",
    "disk_usage": "Show filesystem disk usage.",
    "process_summary": "List a short summary of running processes.",
}
_REMOTE_COMMANDS = {
    "windows": {
        "system_info": (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command '
            '"Get-CimInstance Win32_OperatingSystem | '
            "Select-Object CSName,Caption,Version | Format-List\""
        ),
        "disk_usage": (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command '
            '"Get-PSDrive -PSProvider FileSystem | '
            "Select-Object Name,Used,Free | Format-Table -AutoSize\""
        ),
        "process_summary": (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command '
            '"Get-Process | Sort-Object CPU -Descending | '
            "Select-Object -First 15 ProcessName,Id,CPU | Format-Table -AutoSize\""
        ),
    },
    "linux": {
        "system_info": "hostname && uname -sr",
        "disk_usage": "df -h",
        "process_summary": "ps -eo pid,comm --sort=-%cpu | head -n 15",
    },
    "macos": {
        "system_info": "hostname && uname -sr",
        "disk_usage": "df -h",
        "process_summary": "ps -A -o pid,comm | head -n 15",
    },
}
_MAX_OUTPUT = 12_000
_SSH_ENV_KEYS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "APPDATA",
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "LANG",
)


@ToolRegistry.register("lan_computer")
class LanComputerTool(BaseTool):
    """Run a fixed set of read-only diagnostics on registered LAN computers."""

    tool_id = "lan_computer"

    @property
    def spec(self) -> ToolSpec:
        try:
            devices = load_devices()
            device_ids = [device.id for device in devices]
            device_hint = (
                ", ".join(device_ids)
                if device_ids
                else "none registered; use `jarvis devices add` first"
            )
        except ValueError as exc:
            device_hint = f"configuration error: {exc}"
        return ToolSpec(
            name="lan_computer",
            description=(
                "Run one fixed, read-only diagnostic on a manually registered "
                "computer over SSH. Registered devices: "
                f"{device_hint}. Never accepts arbitrary shell commands. "
                "Each call requires user confirmation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The id of a registered LAN computer.",
                    },
                    "action": {
                        "type": "string",
                        "enum": list(_ACTIONS),
                        "description": "The fixed read-only diagnostic to run.",
                    },
                },
                "required": ["device_id", "action"],
                "additionalProperties": False,
            },
            category="system",
            requires_confirmation=True,
            timeout_seconds=30.0,
            required_capabilities=["network:fetch", "code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        device_id = params.get("device_id")
        action = params.get("action")
        if not isinstance(device_id, str) or not isinstance(action, str):
            return self._failure("A device id and action are required.")
        if action not in _ACTIONS:
            return self._failure("Unsupported action. No command was run.")

        try:
            devices = load_devices()
        except ValueError as exc:
            return self._failure(str(exc))
        device = next((item for item in devices if item.id == device_id), None)
        if device is None:
            return self._failure(
                f"Device {device_id!r} is not registered. "
                "Add it with `jarvis devices add`."
            )

        ssh = shutil.which("ssh") or shutil.which("ssh.exe")
        if not ssh:
            return self._failure(
                "OpenSSH client was not found. Install/enable the OpenSSH Client "
                "and reopen the terminal."
            )

        destination = f"{device.user}@{device.host}"
        command = [
            ssh,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "RemoteCommand=none",
            "-p",
            str(device.port),
        ]
        if device.identity_file:
            command.extend(["-o", "IdentitiesOnly=yes", "-i", device.identity_file])
        command.extend(["--", destination, _REMOTE_COMMANDS[device.os][action]])
        env = {key: os.environ[key] for key in _SSH_ENV_KEYS if key in os.environ}

        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._failure(f"SSH timed out while querying {device.id!r}.")
        except OSError as exc:
            return self._failure(f"Could not start OpenSSH: {exc}")

        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + "\n... (output truncated)"
        return ToolResult(
            tool_name=self.spec.name,
            content=output or "(no output)",
            success=result.returncode == 0,
            metadata={
                "returncode": result.returncode,
                "device_id": device.id,
                "action": action,
            },
        )

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(tool_name="lan_computer", content=message, success=False)


__all__ = ["LanComputerTool"]
