"""Tests for the universal installer's Windows-specific behavior."""

from types import SimpleNamespace

import install as installer


def test_install_prefers_pipx(monkeypatch):
    """When pipx is available, RadSim installs into an isolated pipx env."""
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        installer.shutil,
        "which",
        lambda name: "/usr/bin/pipx" if name == "pipx" else None,
    )
    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer.install_radsim() is True
    assert calls == [
        ["pipx", "install", "radsimcli"],
        ["pipx", "ensurepath"],
    ]


def test_install_falls_back_to_pip_user(monkeypatch):
    """Without pipx (and no bootstrap), RadSim installs via pip --user."""
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(installer, "find_pipx", lambda: None)
    monkeypatch.setattr(installer, "bootstrap_pipx", lambda: False)
    monkeypatch.setattr(installer.subprocess, "run", fake_run)

    assert installer.install_radsim() is True
    assert calls == [
        [
            installer.sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "--upgrade",
            "radsimcli",
        ]
    ]


def test_find_windows_scripts_directory_prefers_installed_executable(
    tmp_path,
    monkeypatch,
):
    user_scripts = tmp_path / "user-scripts"
    system_scripts = tmp_path / "system-scripts"
    user_scripts.mkdir()
    system_scripts.mkdir()
    (user_scripts / "radsim.exe").touch()

    def fake_get_path(name, scheme=None):
        return str(user_scripts if scheme == "nt_user" else system_scripts)

    monkeypatch.setattr(installer.sysconfig, "get_path", fake_get_path)

    assert installer.find_windows_scripts_directory() == user_scripts


def test_find_windows_scripts_directory_falls_back_to_active_python(
    tmp_path,
    monkeypatch,
):
    user_scripts = tmp_path / "user-scripts"
    system_scripts = tmp_path / "system-scripts"

    def fake_get_path(name, scheme=None):
        return str(user_scripts if scheme == "nt_user" else system_scripts)

    monkeypatch.setattr(installer.sysconfig, "get_path", fake_get_path)

    assert installer.find_windows_scripts_directory() == system_scripts


def test_windows_path_matching_uses_complete_entries():
    path_value = r"C:\Python\Scripts-old;C:\Windows\System32"

    assert installer._path_contains_directory(
        path_value,
        r"C:\Python\Scripts",
    ) is False
    assert installer._path_contains_directory(
        path_value,
        r"c:\windows\system32\\",
    ) is True
