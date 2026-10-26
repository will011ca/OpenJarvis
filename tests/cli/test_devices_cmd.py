from click.testing import CliRunner

from openjarvis.cli.devices_cmd import devices


def test_devices_cli_add_list_remove(tmp_path, monkeypatch):
    path = tmp_path / "devices.toml"
    monkeypatch.setattr("openjarvis.devices.device_config_path", lambda: path)
    runner = CliRunner()

    added = runner.invoke(
        devices,
        [
            "add",
            "desktop",
            "--host",
            "192.168.1.10",
            "--user",
            "home",
            "--os",
            "windows",
        ],
    )
    assert added.exit_code == 0, added.output
    assert path.exists()

    listed = runner.invoke(devices, ["list"])
    assert listed.exit_code == 0, listed.output
    assert "desktop" in listed.output
    assert "192.168.1.10" in listed.output

    removed = runner.invoke(devices, ["remove", "desktop"])
    assert removed.exit_code == 0, removed.output
    assert runner.invoke(devices, ["list"]).exit_code == 0


def test_devices_cli_rejects_public_address(tmp_path, monkeypatch):
    path = tmp_path / "devices.toml"
    monkeypatch.setattr("openjarvis.devices.device_config_path", lambda: path)

    result = CliRunner().invoke(
        devices,
        [
            "add",
            "external",
            "--host",
            "8.8.8.8",
            "--user",
            "home",
            "--os",
            "linux",
        ],
    )

    assert result.exit_code != 0
    assert "private or link-local" in result.output
    assert not path.exists()
