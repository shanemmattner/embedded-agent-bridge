from eab.data_stream import DataStreamWriter
from eab.implementations import RealClock, RealFileSystem


def test_data_stream_append_and_truncate(tmp_path):
    data_path = tmp_path / "data.bin"
    writer = DataStreamWriter(
        filesystem=RealFileSystem(),
        clock=RealClock(),
        data_path=str(data_path),
    )

    meta1 = writer.append(b"abc")
    assert meta1["offset"] == 0
    assert meta1["length"] == 3

    meta2 = writer.append(b"defg")
    assert meta2["offset"] == 3
    assert meta2["length"] == 4
    assert data_path.read_bytes() == b"abcdefg"

    writer.truncate()
    assert data_path.read_bytes() == b""
    assert writer.current_offset() == 0
