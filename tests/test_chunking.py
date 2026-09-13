from app.services import chunk_text


def test_chunk_text_splits_with_overlap():
    text = "abcdefghij"
    chunks = chunk_text(text, size=6, overlap=2)
    assert chunks == ["abcdef", "efghij"]


def test_chunk_overlap_must_be_smaller_than_size():
    try:
        chunk_text("hello world", size=5, overlap=5)
    except ValueError as exc:
        assert "smaller" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
