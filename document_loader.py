from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET


WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TEXT_SUFFIXES = {".txt", ".md", ".brd"}


class DocumentLoadError(ValueError):
    """Raised when an uploaded document cannot be converted into BRD text."""


@dataclass(slots=True)
class UploadedDocument:
    name: str
    suffix: str
    text: str


def load_uploaded_document(file_name: str, file_bytes: bytes) -> UploadedDocument:
    suffix = Path(file_name).suffix.lower()

    if suffix in TEXT_SUFFIXES:
        text = file_bytes.decode("utf-8", errors="ignore")
    elif suffix == ".docx":
        text = _extract_docx_text(file_bytes)
    elif suffix == ".pdf":
        text = _extract_pdf_text(file_bytes)
    else:
        raise DocumentLoadError(
            "Unsupported file type. Upload a PDF, DOCX, TXT, MD, or BRD file."
        )

    normalized_text = _normalize_text(text)
    if not normalized_text:
        raise DocumentLoadError("The uploaded document did not contain readable text.")

    return UploadedDocument(name=file_name, suffix=suffix, text=normalized_text)


def _extract_docx_text(file_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise DocumentLoadError("This DOCX file could not be read.") from exc

    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []

    for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
        fragments = [node.text or "" for node in paragraph.findall(".//w:t", WORD_NAMESPACE)]
        paragraph_text = "".join(fragments).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n".join(paragraphs)


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentLoadError(
            "PDF uploads require the `pypdf` package. Install the updated requirements first."
        ) from exc

    reader = PdfReader(BytesIO(file_bytes))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(page for page in pages if page)


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized
