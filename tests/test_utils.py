import main

def test_is_media_url_by_extension():
    assert main.is_media_url("https://x.com/file.jpg")
    assert not main.is_media_url("https://example.com/file.pdf")

def test_is_media_url_by_domain():
    assert main.is_media_url("https://media.discordapp.net/some/file")

def test_load_rules_default(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RULES_FILE", tmp_path / "missing.txt")
    content = main.load_rules()
    assert "Server Rules" in content
