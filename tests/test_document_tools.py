"""Document creation and reading: binary safety, parsing, and image plumbing."""

import base64
import zipfile

import pytest

from radsim.agent_api import extract_image_block
from radsim.api_client import OpenAIClient, _block_to_openai_part
from radsim.tools import execute_tool
from radsim.tools.advanced import database_query
from radsim.tools.documents import read_document, read_image
from radsim.tools.file_ops import write_file

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    """Run every test inside an isolated project directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_docx(path, paragraphs):
    """Build a minimal valid .docx with the given paragraph texts."""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = f'<?xml version="1.0"?><w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def make_xlsx(path, rows):
    """Build a minimal valid .xlsx with one sheet of string cells."""
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    strings = [cell for row in rows for cell in row]
    shared = f'<?xml version="1.0"?><sst xmlns="{namespace}">' + "".join(
        f"<si><t>{value}</t></si>" for value in strings
    ) + "</sst>"

    cells_xml = []
    index = 0
    for row_number, row in enumerate(rows, 1):
        cells = ""
        for _ in row:
            cells += f'<c t="s"><v>{index}</v></c>'
            index += 1
        cells_xml.append(f'<row r="{row_number}">{cells}</row>')
    sheet = (
        f'<?xml version="1.0"?><worksheet xmlns="{namespace}"><sheetData>'
        + "".join(cells_xml)
        + "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class TestWriteFileRejectsBinary:
    """Binary content must fail loudly, never corrupt silently."""

    def test_pdf_bytes_are_rejected_with_script_guidance(self):
        result = write_file("out.pdf", "%PDF-1.4 fake content")
        assert result["success"] is False
        assert "run_shell_command" in result["error"]
        assert "fpdf2" in result["error"]

    def test_png_bytes_are_rejected(self):
        result = write_file("img.png", "\x89PNG\r\n fake")
        assert result["success"] is False

    def test_zip_based_formats_are_rejected(self):
        result = write_file("doc.docx", "PK\x03\x04 fake")
        assert result["success"] is False
        assert "docx" in result["error"]

    def test_null_bytes_are_rejected(self):
        result = write_file("data.bin", "abc\x00def")
        assert result["success"] is False

    def test_ordinary_text_still_writes(self):
        result = write_file("notes.csv", "name,score\nalice,90\n")
        assert result["success"] is True


class TestDatabaseQueryGuardMessages:
    """Blocked queries must explain the working alternative accurately."""

    def test_drop_table_is_blocked_with_accurate_message(self):
        result = database_query("DROP TABLE users", "app.db", read_only=False)
        assert result["success"] is False
        assert "WHERE" not in result["error"]
        assert "sqlite3" in result["error"]

    def test_mass_delete_requires_where_clause(self):
        result = database_query("DELETE FROM users", "app.db", read_only=False)
        assert result["success"] is False
        assert "WHERE" in result["error"]

    def test_targeted_delete_is_allowed(self):
        database_query("CREATE TABLE t (id INTEGER)", "app.db", read_only=False)
        result = database_query("DELETE FROM t WHERE id = 1", "app.db", read_only=False)
        assert result["success"] is True


class TestReadDocument:
    """Text extraction from each supported format."""

    def test_plain_text_and_csv(self, workspace):
        (workspace / "data.csv").write_text("name,score\nalice,90\n")
        result = read_document("data.csv")
        assert result["success"] is True
        assert "alice,90" in result["text"]
        assert result["format"] == "csv"

    def test_docx_paragraphs_are_extracted(self, workspace):
        make_docx(workspace / "report.docx", ["Quarterly Report", "Revenue grew 12%."])
        result = read_document("report.docx")
        assert result["success"] is True
        assert "Quarterly Report" in result["text"]
        assert "Revenue grew 12%." in result["text"]

    def test_xlsx_rows_are_extracted(self, workspace):
        make_xlsx(workspace / "sheet.xlsx", [["name", "score"], ["alice", "90"]])
        result = read_document("sheet.xlsx")
        assert result["success"] is True
        assert "name\tscore" in result["text"]
        assert "alice\t90" in result["text"]

    def test_pdf_extraction_via_pypdf(self, workspace):
        pypdf = pytest.importorskip("pypdf")
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(workspace / "blank.pdf", "wb") as handle:
            writer.write(handle)

        result = read_document("blank.pdf")
        assert result["success"] is True
        assert result["format"] == "pdf"
        assert "page 1" in result["text"]

    def test_missing_file_fails_closed(self):
        result = read_document("nope.pdf")
        assert result["success"] is False

    def test_corrupt_docx_reports_parse_error(self, workspace):
        (workspace / "bad.docx").write_bytes(b"not a zip at all")
        result = read_document("bad.docx")
        assert result["success"] is False
        assert "parse" in result["error"].lower()


class TestReadImage:
    """Images load as private payloads bound for message blocks."""

    def test_png_loads_with_payload(self, workspace):
        (workspace / "pixel.png").write_bytes(ONE_PIXEL_PNG)
        result = read_image("pixel.png")
        assert result["success"] is True
        assert result["media_type"] == "image/png"
        assert base64.b64decode(result["_image"]["data"]) == ONE_PIXEL_PNG

    def test_unsupported_extension_is_rejected(self, workspace):
        (workspace / "vector.svg").write_text("<svg/>")
        result = read_image("vector.svg")
        assert result["success"] is False
        assert "Supported" in result["error"]

    def test_oversized_image_is_rejected(self, workspace, monkeypatch):
        import radsim.tools.documents as documents

        monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", 10)
        (workspace / "big.png").write_bytes(ONE_PIXEL_PNG)
        result = documents.read_image("big.png")
        assert result["success"] is False
        assert "Resize" in result["error"]

    def test_execute_tool_path_is_wired(self, workspace):
        (workspace / "pixel.png").write_bytes(ONE_PIXEL_PNG)
        result = execute_tool("read_image", {"file_path": "pixel.png"})
        assert result["success"] is True
        assert "_image" in result


class TestImageMessagePlumbing:
    """The payload must become a real image block and leave the text result."""

    def test_extract_image_block_pops_payload(self):
        result = {"success": True, "_image": {"media_type": "image/png", "data": "QUJD"}}
        block = extract_image_block(result)
        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/png"
        assert "_image" not in result

    def test_failed_results_produce_no_block(self):
        result = {"success": False, "_image": {"media_type": "image/png", "data": "QUJD"}}
        assert extract_image_block(result) is None

    def test_plain_results_pass_through(self):
        assert extract_image_block({"success": True, "stdout": "ok"}) is None


class TestOpenAIImageConversion:
    """Anthropic-style image blocks must survive conversion to OpenAI format."""

    def make_client(self):
        return OpenAIClient(api_key="test-key-not-real")

    def test_image_block_becomes_data_uri_part(self):
        part = _block_to_openai_part(
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
        )
        assert part["type"] == "image_url"
        assert part["image_url"]["url"] == "data:image/png;base64,QUJD"

    def test_tool_results_with_image_gain_user_message(self):
        client = self.make_client()
        message = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"success": true}'},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
            ],
        }
        formatted = client._format_message(message)
        assert formatted[0]["role"] == "tool"
        assert formatted[1]["role"] == "user"
        assert formatted[1]["content"][0]["type"] == "image_url"

    def test_plain_tool_results_unchanged(self):
        client = self.make_client()
        message = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
            ],
        }
        formatted = client._format_message(message)
        assert formatted == [{"role": "tool", "tool_call_id": "t1", "content": "ok"}]
