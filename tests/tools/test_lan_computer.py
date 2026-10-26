from __future__ import annotations

import subprocess

from openjarvis.devices import LanDevice, load_devices, remove_device, save_device
from openjarvis.tools.lan_computer import LanComputerTool


def test_device_registry_round_trip_and_rejects_public_ip(tmp_path, monkeypatch):
    path = tmp_path / "devices.toml"
    monkeypatch.setattr("openjarvis.devices.device_config_path", lambda: path)

    saved = save_device(
        LanDevice(
            id="office_pc",
            host="192.168.1.20",
            user="user",
            os="windows",
        )
    )

    assert saved == path
    assert load_devices() == [
        LanDevice(
            id="office_pc",
            host="192.168.1.20",
            user="user",
            os="windows",
        )
    ]
    assert path.exists()

    try:
        save_device(
            LanDevice(
                id="public",
                host="8.8.8.8",
                user="user",
                os="linux",
            )
        )
    except ValueError as exc:
        assert "private or link-local" in str(exc)
    else:
        raise AssertionError("public IP addresses must not be accepted")

    assert remove_device("office_pc")
    assert load_devices() == []


def test_lan_tool_requires_confirmation_and_only_runs_fixed_actions(
    tmp_path, monkeypatch
):
    path = tmp_path / "devices.toml"
    monkeypatch.setattr("openjarvis.devices.device_config_path", lambda: path)
    save_device(
        LanDevice(
            id="linux_box",
            host="192.168.1.30",
            user="user",
            os="linux",
        )
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "Linux box\n", "")

    monkeypatch.setattr("openjarvis.tools.lan_computer.shutil.which", lambda _: "ssh")
    monkeypatch.setattr("openjarvis.tools.lan_computer.subprocess.run", fake_run)

    tool = LanComputerTool()
    assert tool.spec.requires_confirmation is True
    assert tool.spec.required_capabilities == ["network:fetch", "code:execute"]

    result = tool.execute(device_id="linux_box", action="system_info")
    assert result.success
    command, kwargs = calls[0]
    assert "StrictHostKeyChecking=yes" in command
    assert command[-1] == "hostname && uname -sr"
    assert kwargs["stdin"] == subprocess.DEVNULL

    rejected = tool.execute(
        device_id="linux_box",
        action="run_arbitrary_shell_command",
        command="whoami",
    )
    assert not rejected.success
    assert len(calls) == 1
