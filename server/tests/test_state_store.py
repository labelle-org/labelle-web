"""Tests for the shared JSON state store backing LABELLE_STATE_FILE.

state_store is the single owner of the on-disk state file. Both the USB
power feature (hub/port cache) and per-printer settings persistence write
through it, so its read-modify-write must preserve keys it doesn't know
about and be safe under concurrent callers.
"""

import json
import threading

import state_store


class TestReadAll:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        assert state_store.read_all(tmp_path / "absent.json") == {}

    def test_returns_parsed_dict_when_valid(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps({"hub": "1-1", "port": 3}))
        assert state_store.read_all(p) == {"hub": "1-1", "port": 3}

    def test_returns_empty_dict_when_corrupt(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{not json")
        assert state_store.read_all(p) == {}

    def test_returns_empty_dict_when_top_level_not_object(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(json.dumps([1, 2, 3]))
        assert state_store.read_all(p) == {}

    def test_returns_empty_dict_on_non_utf8_bytes(self, tmp_path):
        # Non-UTF8 bytes raise UnicodeDecodeError (a ValueError, not OSError).
        p = tmp_path / "state.json"
        p.write_bytes(b"\xff\xfe\x00garbage")
        assert state_store.read_all(p) == {}

    def test_non_ascii_value_round_trips_as_utf8(self, tmp_path):
        # The file is written and read as UTF-8 explicitly (not the process
        # locale), so non-ASCII values survive regardless of environment.
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.update(printers={"virtual:Büro": {}}), p)
        assert p.read_text(encoding="utf-8")  # readable as UTF-8
        assert state_store.read_all(p)["printers"] == {"virtual:Büro": {}}


class TestUpdate:
    def test_persists_mutation(self, tmp_path):
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.update(hub="2-4", port=7), p)
        assert state_store.read_all(p) == {"hub": "2-4", "port": 7}

    def test_preserves_unrelated_keys(self, tmp_path):
        """A writer touching one key must not drop another writer's keys."""
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.update(hub="1-1", port=3), p)
        state_store.update(
            lambda d: d.setdefault("printers", {}).__setitem__("p1", {"tapeSizeMm": 12}),
            p,
        )
        data = state_store.read_all(p)
        assert data["hub"] == "1-1"
        assert data["port"] == 3
        assert data["printers"]["p1"] == {"tapeSizeMm": 12}

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "nested" / "dir" / "state.json"
        state_store.update(lambda d: d.update(hub="1-1", port=3), p)
        assert p.exists()

    def test_swallows_write_errors(self, tmp_path):
        # Parent is a file, so mkdir/replace fail; update must not raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        bad_path = blocker / "state.json"
        state_store.update(lambda d: d.update(hub="1-1", port=3), bad_path)

    def test_swallows_serialization_errors(self, tmp_path):
        # A non-JSON-serializable value must not crash the caller, and must
        # leave any prior on-disk state intact (the bad write never lands).
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.update(hub="1-1", port=3), p)
        state_store.update(lambda d: d.update(bad={1, 2, 3}), p)  # set → TypeError
        assert state_store.read_all(p) == {"hub": "1-1", "port": 3}

    def test_returns_resulting_data(self, tmp_path):
        p = tmp_path / "state.json"
        result = state_store.update(lambda d: d.update(hub="1-1", port=3), p)
        assert result == {"hub": "1-1", "port": 3}

    def test_concurrent_updates_do_not_lose_writes(self, tmp_path):
        """Read-modify-write under the lock must not drop interleaved writes."""
        p = tmp_path / "state.json"
        state_store.update(lambda d: d.setdefault("printers", {}), p)

        def writer(key):
            state_store.update(
                lambda d: d["printers"].__setitem__(key, {"tapeSizeMm": 12}), p
            )

        threads = [threading.Thread(target=writer, args=(f"p{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        printers = state_store.read_all(p)["printers"]
        assert set(printers) == {f"p{i}" for i in range(20)}
