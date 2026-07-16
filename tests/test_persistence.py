"""Tests for the shared atomic JSON persistence primitive."""

import json
import os
import stat

import pytest

from radsim.persistence import atomic_write_json

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")


def test_atomic_write_round_trips_json_and_leaves_no_temp_file(tmp_path):
    destination = tmp_path / "nested" / "state.json"

    atomic_write_json(destination, {"status": "ready", "count": 3})

    assert json.loads(destination.read_text()) == {"status": "ready", "count": 3}
    assert list(destination.parent.glob(".state.json.*.tmp")) == []


def test_serialization_failure_preserves_existing_file(tmp_path):
    destination = tmp_path / "state.json"
    destination.write_text('{"version": 1}')

    with pytest.raises(TypeError):
        atomic_write_json(destination, {"unsupported": object()})

    assert destination.read_text() == '{"version": 1}'
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_optional_default_serializer_is_explicit(tmp_path):
    destination = tmp_path / "state.json"

    atomic_write_json(destination, {"unsupported": object()}, default=str)

    assert isinstance(json.loads(destination.read_text())["unsupported"], str)


@posix_only
def test_secure_write_restricts_file_and_directory_modes(tmp_path):
    directory = tmp_path / "secure"
    directory.mkdir(mode=0o755)
    destination = directory / "secrets.json"

    atomic_write_json(destination, {"token": "test-only"}, secure=True)

    directory_mode = stat.S_IMODE(directory.stat().st_mode)
    file_mode = stat.S_IMODE(destination.stat().st_mode)
    assert directory_mode == 0o700
    assert file_mode == 0o600
