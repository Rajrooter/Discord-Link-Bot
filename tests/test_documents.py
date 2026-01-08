import pytest
import main

@pytest.mark.parametrize(
    "data, expected",
    [
        (b"hello", "hello"),
        ("olá".encode("latin-1"), "olá"),
    ],
)
def test_extract_text_from_bytes_txt(data, expected):
    assert expected in main.extract_text_from_bytes("file.txt", data)

def test_extract_text_from_bytes_pdf_handles_failure(monkeypatch):
    class FakePage:
        def extract_text(self): return "PDFTEXT"
    class FakeReader:
        def __init__(self, bio): self.pages = [FakePage()]
    fake_pdf = bytes(10)
    monkeypatch.setitem(main.__dict__, "PdfReader", FakeReader, raising=False)
    out = main.extract_text_from_bytes("file.pdf", fake_pdf)
    assert "PDFTEXT" in out

def test_extract_text_from_bytes_docx_handles_failure(monkeypatch):
    class FakeParagraph:
        text = "DOCTEXT"
    class FakeDoc:
        paragraphs = [FakeParagraph()]
    class FakeDocx:
        def Document(self, bio): return FakeDoc()
    monkeypatch.setitem(main.__dict__, "docx", FakeDocx(), raising=False)
    out = main.extract_text_from_bytes("file.docx", b"\x00\x01")
    assert "DOCTEXT" in out

@pytest.mark.asyncio
async def test_summarize_document_bytes_extract_fail(monkeypatch):
    monkeypatch.setattr(main, "extract_text_from_bytes", lambda f, d: None)
    out = await main.summarize_document_bytes("file.pdf", b"data")
    assert "Couldn't extract text" in out

@pytest.mark.asyncio
async def test_summarize_document_bytes_happy(monkeypatch):
    monkeypatch.setattr(main, "extract_text_from_bytes", lambda f, d: "hello world")
    async def fake_ai_call(prompt, max_retries=3, timeout=25.0):
        return "summary"
    monkeypatch.setattr(main, "ai_call", fake_ai_call)
    out = await main.summarize_document_bytes("file.pdf", b"data")
    assert "summary" in out
