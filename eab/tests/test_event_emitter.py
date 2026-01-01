import json

from eab.event_emitter import EventEmitter
from eab.implementations import RealClock, RealFileSystem


def test_event_emitter_sequences_and_persists(tmp_path):
    events_path = tmp_path / "events.jsonl"
    emitter = EventEmitter(
        filesystem=RealFileSystem(),
        clock=RealClock(),
        events_path=str(events_path),
    )

    first = emitter.emit("test_event", {"key": "value"})
    second = emitter.emit("another_event", {})

    lines = events_path.read_text().splitlines()
    assert len(lines) == 2
    parsed_first = json.loads(lines[0])
    parsed_second = json.loads(lines[1])

    assert parsed_first["sequence"] == 1
    assert parsed_first["type"] == "test_event"
    assert parsed_first["data"]["key"] == "value"
    assert parsed_second["sequence"] == 2
    assert parsed_second["type"] == "another_event"

    # New emitter should continue sequence from file.
    emitter2 = EventEmitter(
        filesystem=RealFileSystem(),
        clock=RealClock(),
        events_path=str(events_path),
    )
    third = emitter2.emit("third_event", {})
    assert third["sequence"] == 3
