"""Security regression tests for bounded document parsing (R-07).

read_document is read-only and unconfirmed, but DOCX/XLSX handlers read and
parse ZIP members before the 20k text cap applied. A zip bomb or an XML
entity bomb could exhaust memory/CPU. These tests prove archive limits, a
file-size cap, and DTD rejection all fire on hostile documents while ordinary
documents still parse.
"""

import zipfile

import pytest

from radsim.tools import documents
from radsim.tools.documents import UnsafeDocument, _reject_dtd, read_document
from radsim.tools.validation import clear_path_validation_cache


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside tmp_path so validate_path accepts the fixture documents."""
    monkeypatch.chdir(tmp_path)
    clear_path_validation_cache()
    return tmp_path


DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
GOOD_DOCX_XML = (
    '<?xml version="1.0"?>'
    f'<w:document xmlns:w="{DOCX_NS}">'
    "<w:body><w:p><w:r><w:t>Hello World</w:t></w:r></w:p></w:body>"
    "</w:document>"
)


def _make_docx(path, document_xml=GOOD_DOCX_XML, compress=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compress) as archive:
        archive.writestr("word/document.xml", document_xml)
    return path


class TestDtdRejection:
    def test_reject_doctype(self):
        with pytest.raises(UnsafeDocument):
            _reject_dtd(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><root/>')

    def test_reject_entity(self):
        with pytest.raises(UnsafeDocument):
            _reject_dtd(b"<!ENTITY lol 'lol'>")

    def test_plain_xml_passes(self):
        assert _reject_dtd(b"<root>ok</root>") == b"<root>ok</root>"

    def test_billion_laughs_docx_blocked(self, project):
        bomb = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
            f'<w:document xmlns:w="{DOCX_NS}"><w:body><w:p><w:r><w:t>&lol2;</w:t>'
            "</w:r></w:p></w:body></w:document>"
        )
        path = _make_docx(project / "bomb.docx", bomb)
        result = read_document(str(path))
        assert result["success"] is False


class TestArchiveLimits:
    def test_high_compression_ratio_blocked(self, project):
        # 2 MB of one repeated byte compresses to a few KB -> ratio >> 200.
        payload = (
            '<?xml version="1.0"?>'
            f'<w:document xmlns:w="{DOCX_NS}"><w:body><w:p><w:r><w:t>'
            + ("A" * 2_000_000)
            + "</w:t></w:r></w:p></w:body></w:document>"
        )
        path = _make_docx(project / "ratio.docx", payload)
        result = read_document(str(path))
        assert result["success"] is False

    def test_total_uncompressed_limit_enforced(self, project, monkeypatch):
        monkeypatch.setattr(documents, "MAX_ZIP_TOTAL_BYTES", 500)
        monkeypatch.setattr(documents, "MAX_COMPRESSION_RATIO", 10_000)
        path = _make_docx(project / "big.docx", GOOD_DOCX_XML.replace("Hello World", "X" * 5000))
        result = read_document(str(path))
        assert result["success"] is False

    def test_member_count_limit_enforced(self, project, monkeypatch):
        monkeypatch.setattr(documents, "MAX_ZIP_MEMBERS", 3)
        path = project / "many.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", GOOD_DOCX_XML)
            for i in range(5):
                archive.writestr(f"extra{i}.bin", "x")
        result = read_document(str(path))
        assert result["success"] is False


class TestFileSizeCap:
    def test_oversized_document_rejected(self, project, monkeypatch):
        monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 100)
        path = project / "big.txt"
        path.write_text("x" * 500)
        result = read_document(str(path))
        assert result["success"] is False
        assert "too large" in result["error"].lower()


class TestLegitimateDocumentsStillParse:
    def test_valid_docx_extracts_text(self, project):
        path = _make_docx(project / "ok.docx")
        result = read_document(str(path))
        assert result["success"] is True
        assert "Hello World" in result["text"]

    def test_plain_text_still_reads(self, project):
        path = project / "notes.md"
        path.write_text("# Title\nbody")
        result = read_document(str(path))
        assert result["success"] is True
        assert "Title" in result["text"]
