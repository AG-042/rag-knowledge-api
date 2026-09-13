from app.services import cache_key, chunk_text


def test_chunk_text_preserves_content_order(monkeypatch):
    from app import services

    monkeypatch.setattr(services.settings, "chunk_size", 20)
    monkeypatch.setattr(services.settings, "chunk_overlap", 5)
    chunks = chunk_text("abcdefghijklmnopqrstuvwxyz")

    assert chunks[0] == "abcdefghijklmnopqrst"
    assert chunks[1].startswith("pqrst")
    assert chunks[-1].endswith("z")


def test_cache_key_is_stable_and_sensitive_to_top_k():
    assert cache_key("What is Redis?", 5) == cache_key(" what is redis? ", 5)
    assert cache_key("What is Redis?", 5) != cache_key("What is Redis?", 3)
