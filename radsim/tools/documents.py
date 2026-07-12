"""Document and image reading for RadSim tools.

RadSim Principle: One Function, One Purpose.

read_document extracts text from binary document formats (PDF, DOCX, XLSX)
so the model can work with their content. read_image loads an image and
returns it for vision-capable models to interpret. Both follow the same
project-directory path policy as read_file: anything read here is sent to
the model provider, so scope stays deliberately narrow.
"""

import base64
import re
import zipfile
from xml.etree import ElementTree

from .validation import validate_path

# Keep extracted text within a sane context budget.
MAX_EXTRACTED_CHARS = 20000

# Raw image bytes cap: providers reject oversized payloads long before this.
MAX_IMAGE_BYTES = 4 * 1024 * 1024

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_DOCX_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_XLSX_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_document(file_path):
    """Extract text from a document file (PDF, DOCX, XLSX, or plain text).

    Args:
        file_path: Path to the document, inside the project directory.

    Returns:
        dict with success, text, format, and truncated flag.
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}
    if not path.exists() or not path.is_file():
        return {"success": False, "error": f"File not found: {file_path}"}

    readers = {
        ".pdf": _read_pdf_text,
        ".docx": _read_docx_text,
        ".xlsx": _read_xlsx_text,
    }
    reader = readers.get(path.suffix.lower(), _read_plain_text)

    try:
        text = reader(path)
    except Exception as error:
        return {"success": False, "error": f"Could not parse {path.suffix} file: {error}"}

    truncated = len(text) > MAX_EXTRACTED_CHARS
    if truncated:
        text = text[:MAX_EXTRACTED_CHARS] + "\n... [document truncated]"

    return {
        "success": True,
        "text": text,
        "format": path.suffix.lower().lstrip(".") or "text",
        "truncated": truncated,
    }


def _read_pdf_text(path):
    """Extract text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "pypdf is not installed. Install it with pip_install 'pypdf', then retry."
        ) from error

    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, 1):
        page_text = page.extract_text() or ""
        pages.append(f"--- page {number} ---\n{page_text}")
        if sum(len(part) for part in pages) > MAX_EXTRACTED_CHARS:
            break
    return "\n".join(pages)


def _read_docx_text(path):
    """Extract paragraph text from a DOCX file using only the stdlib.

    A .docx is a ZIP archive whose main text lives in word/document.xml.
    """
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    paragraphs = []
    for paragraph in root.iter(f"{_DOCX_NAMESPACE}p"):
        runs = [node.text or "" for node in paragraph.iter(f"{_DOCX_NAMESPACE}t")]
        if runs:
            paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def _read_xlsx_text(path):
    """Extract cell values from every sheet of an XLSX file, stdlib only.

    A .xlsx is a ZIP archive; strings live in xl/sharedStrings.xml and each
    sheet's cells in xl/worksheets/sheetN.xml. Rows render as tab-separated
    lines so tables stay readable.
    """
    with zipfile.ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheet_names = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        sections = []
        for sheet_name in sheet_names:
            rows = _read_sheet_rows(archive.read(sheet_name), shared_strings)
            label = sheet_name.removeprefix("xl/worksheets/").removesuffix(".xml")
            sections.append(f"--- {label} ---\n" + "\n".join(rows))
    return "\n".join(sections)


def _load_shared_strings(archive):
    """Return the shared-string table an XLSX uses for text cells."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.iter(f"{_XLSX_NAMESPACE}si"):
        strings.append("".join(node.text or "" for node in item.iter(f"{_XLSX_NAMESPACE}t")))
    return strings


def _read_sheet_rows(sheet_xml, shared_strings):
    """Render one worksheet's rows as tab-separated lines."""
    root = ElementTree.fromstring(sheet_xml)
    rows = []
    for row in root.iter(f"{_XLSX_NAMESPACE}row"):
        cells = []
        for cell in row.iter(f"{_XLSX_NAMESPACE}c"):
            value_node = cell.find(f"{_XLSX_NAMESPACE}v")
            value = value_node.text if value_node is not None else ""
            if cell.get("t") == "s" and value:
                value = shared_strings[int(value)]
            cells.append(value or "")
        rows.append("\t".join(cells))
    return rows


def _read_plain_text(path):
    """Read a text-based document (csv, md, txt, json, ...)."""
    return path.read_text(encoding="utf-8", errors="replace")


def read_image(file_path):
    """Load an image so a vision-capable model can interpret it.

    The base64 payload travels under the private "_image" key; the agent
    converts it into a proper image message block and keeps it out of the
    plain-text tool result.

    Args:
        file_path: Path to a png/jpg/gif/webp inside the project directory.

    Returns:
        dict with success, media_type, size_bytes, and the _image payload.
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}
    if not path.exists() or not path.is_file():
        return {"success": False, "error": f"File not found: {file_path}"}

    media_type = IMAGE_MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        supported = ", ".join(sorted(IMAGE_MEDIA_TYPES))
        return {"success": False, "error": f"Unsupported image type. Supported: {supported}"}

    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        return {
            "success": False,
            "error": (
                f"Image is {len(data) // 1024} KB; the limit is "
                f"{MAX_IMAGE_BYTES // 1024} KB. Resize it first, e.g. with "
                "'sips -Z 1500 <file>' on macOS."
            ),
        }

    return {
        "success": True,
        "media_type": media_type,
        "size_bytes": len(data),
        "note": (
            "Image attached to the conversation. Interpreting it requires a "
            "vision-capable model."
        ),
        "_image": {
            "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }
