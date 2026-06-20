import json

import pytest

from agent.ops.state import PersistentState, StateError


def test_persistent_state_load_save_update(tmp_path):
    path = tmp_path / "state.json"
    state = PersistentState(str(path))

    assert state.load()["mode"] == "paper"
    state.update(nav=100.5, positions={"WBNB": 1.25}, receipt_seq=2)

    reloaded = PersistentState(str(path))
    data = reloaded.load()
    assert data["nav"] == 100.5
    assert data["positions"] == {"WBNB": 1.25}
    assert data["receipt_seq"] == 2


def test_persistent_state_ignores_partial_temp_write(tmp_path):
    path = tmp_path / "state.json"
    state = PersistentState(str(path))
    state.update(nav=42.0)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text('{"nav":', encoding="utf-8")

    reloaded = PersistentState(str(path))

    assert reloaded.load()["nav"] == 42.0


def test_persistent_state_rejects_corrupt_committed_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(StateError):
        PersistentState(str(path)).load()


def test_persistent_state_rejects_unknown_update_field(tmp_path):
    state = PersistentState(str(tmp_path / "state.json"))

    with pytest.raises(StateError):
        state.update(unknown=True)

