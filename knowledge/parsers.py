"""Format adapters preserve page/section boundaries and exact extracted text."""
from dataclasses import dataclass
from io import BytesIO, StringIO
import csv
import json
import zipfile

SUPPORTED = {"pdf", "docx", "txt", "md", "markdown", "csv", "json", "memory", "profile"}
MAX_TEXT = 4_000_000


@dataclass
class Section:
    text: str
    section: str
    page: int | None = None


def extract(content: bytes, kind: str) -> list[Section]:
    if kind not in SUPPORTED:
        raise ValueError("Unsupported document format")
    result = []
    if kind == "pdf":
        import fitz
        with fitz.open(stream=content, filetype="pdf") as doc:
            if doc.is_encrypted:
                raise ValueError("Unlock this PDF before uploading it")
            for i, page in enumerate(doc):
                text = page.get_text("text", sort=True)
                if not text.strip():
                    raise ValueError(f"Page {i + 1} has no extractable text. OCR this PDF before uploading.")
                result.append(Section(text, f"Page {i + 1}", i + 1))
    elif kind == "docx":
        from docx import Document
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 80_000_000:
                raise ValueError("Expanded DOCX exceeds 80 MB")
        doc = Document(BytesIO(content))
        heading = "Document"
        # iter_inner_content preserves paragraph/table order.
        for item in doc.iter_inner_content():
            if hasattr(item, "text"):
                if item.style and item.style.name.startswith("Heading"):
                    heading = item.text
                if item.text.strip():
                    result.append(Section(item.text, heading))
            else:
                for i, row in enumerate(item.rows):
                    result.append(Section(" | ".join(c.text for c in row.cells), f"{heading} / table row {i + 1}"))
    else:
        text = content.decode("utf-8-sig", errors="strict")
        if kind == "json":
            json.loads(text)  # Validate, but keep the original evidence bytes as text.
            result = [Section(text, "JSON document")]
        elif kind == "csv":
            reader = csv.reader(StringIO(text))
            lines = text.splitlines(keepends=True)
            start = 0
            for i, _ in enumerate(reader):
                end = reader.line_num
                result.append(Section("".join(lines[start:end]), f"CSV row {i + 1}"))
                start = end
        else:
            heading, bits = "Document", []
            for line in text.splitlines(keepends=True):
                if kind in {"md", "markdown", "profile"} and line.startswith("#"):
                    if bits:
                        result.append(Section("".join(bits), heading))
                    heading, bits = line.lstrip("#").strip(), []
                bits.append(line)
            if bits:
                result.append(Section("".join(bits), heading))
    if sum(len(s.text) for s in result) > MAX_TEXT:
        raise ValueError("Extracted text exceeds the 4 million character limit")
    if not any(s.text.strip() for s in result):
        raise ValueError("This document contains no extractable text")
    return result


def chunk(sections: list[Section], size: int = 4800, overlap: int = 350):
    for section in sections:
        offset = 0
        while offset < len(section.text):
            end = min(offset + size, len(section.text))
            if end < len(section.text):
                boundary = section.text.rfind("\n", offset + size // 2, end)
                if boundary > offset:
                    end = boundary + 1
            yield Section(section.text[offset:end], section.section, section.page)
            if end == len(section.text):
                break
            offset = max(offset + 1, end - overlap)
