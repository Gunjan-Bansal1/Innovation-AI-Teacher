"""
Document parser — extracts real text from PDF, DOCX, PPTX, TXT.

Rules:
- NEVER fabricates page numbers, chapter names, sections, or citations.
- Only populates metadata fields if actually detected in the document.
- Returns None for undetected metadata fields.
"""
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedPage:
    """A single page or slide from a document."""
    page_number: Optional[int]          # Real page number or None
    text: str                           # Actual extracted text
    heading: Optional[str] = None       # Detected heading/title or None
    section: Optional[str] = None       # Detected section or None


@dataclass
class ParsedDocument:
    """Full parsed document with real metadata only."""
    filename: str
    file_type: str                          # pdf, docx, pptx, txt
    total_pages: Optional[int]
    pages: list[ParsedPage] = field(default_factory=list)
    detected_chapters: list[str] = field(default_factory=list)
    detected_sections: list[str] = field(default_factory=list)
    word_count: int = 0


class DocumentParser:
    """Parse documents to extract real text and metadata."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}

    def parse(self, file_path: str | Path, filename: str) -> ParsedDocument:
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        if ext == ".pdf":
            return self._parse_pdf(path, filename)
        elif ext == ".docx":
            return self._parse_docx(path, filename)
        elif ext == ".pptx":
            return self._parse_pptx(path, filename)
        elif ext == ".txt":
            return self._parse_txt(path, filename)

    def _parse_pdf(self, path: Path, filename: str) -> ParsedDocument:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF not installed. Run: pip install PyMuPDF")

        doc_obj = fitz.open(str(path))
        pages: list[ParsedPage] = []
        chapters = []
        sections = []

        for page_idx in range(len(doc_obj)):
            page = doc_obj[page_idx]
            text = page.get_text("text")  # type: ignore[attr-defined]

            if not text.strip():
                continue

            # Real page number from PDF (1-indexed)
            page_number = page_idx + 1

            # Detect headings from font size analysis
            heading = self._detect_pdf_heading(page)
            section = self._detect_section(text)

            if heading and heading not in chapters:
                chapters.append(heading)
            if section and section not in sections:
                sections.append(section)

            pages.append(ParsedPage(
                page_number=page_number,
                text=text.strip(),
                heading=heading,
                section=section,
            ))

        doc_obj.close()
        word_count = sum(len(p.text.split()) for p in pages)

        return ParsedDocument(
            filename=filename,
            file_type="pdf",
            total_pages=len(pages),
            pages=pages,
            detected_chapters=chapters[:20],   # cap at 20
            detected_sections=sections[:50],
            word_count=word_count,
        )

    def _detect_pdf_heading(self, page) -> Optional[str]:
        """Detect the main heading of a PDF page from font size."""
        try:
            blocks = page.get_text("dict")["blocks"]
            largest_font = 0
            heading_text = None

            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font_size = span.get("size", 0)
                        text = span.get("text", "").strip()
                        if font_size > largest_font and len(text) > 3:
                            largest_font = font_size
                            heading_text = text

            # Only return if font is noticeably larger (heading-like)
            return heading_text if largest_font > 14 else None
        except Exception:
            return None

    def _parse_docx(self, path: Path, filename: str) -> ParsedDocument:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx not installed. Run: pip install python-docx")

        doc_obj = Document(str(path))
        pages: list[ParsedPage] = []
        chapters = []
        sections = []
        current_heading = None
        current_section = None
        buffer_texts = []
        page_num = 1

        for para in doc_obj.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name if para.style else ""

            if "Heading 1" in style_name or "Title" in style_name:
                # Save previous buffer as a page
                if buffer_texts:
                    pages.append(ParsedPage(
                        page_number=page_num,
                        text="\n".join(buffer_texts),
                        heading=current_heading,
                        section=current_section,
                    ))
                    page_num += 1
                    buffer_texts = []
                current_heading = text
                if text not in chapters:
                    chapters.append(text)

            elif "Heading 2" in style_name:
                current_section = text
                if text not in sections:
                    sections.append(text)
                buffer_texts.append(text)

            else:
                buffer_texts.append(text)

        # Flush remaining
        if buffer_texts:
            pages.append(ParsedPage(
                page_number=page_num,
                text="\n".join(buffer_texts),
                heading=current_heading,
                section=current_section,
            ))

        word_count = sum(len(p.text.split()) for p in pages)
        return ParsedDocument(
            filename=filename,
            file_type="docx",
            total_pages=len(pages),
            pages=pages,
            detected_chapters=chapters[:20],
            detected_sections=sections[:50],
            word_count=word_count,
        )

    def _parse_pptx(self, path: Path, filename: str) -> ParsedDocument:
        try:
            from pptx import Presentation
        except ImportError:
            raise ImportError("python-pptx not installed. Run: pip install python-pptx")

        prs = Presentation(str(path))
        pages: list[ParsedPage] = []
        chapters = []

        for slide_idx, slide in enumerate(prs.slides):
            slide_title = None
            texts = []

            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                shape_text = shape.text_frame.text.strip()
                if not shape_text:
                    continue

                # First text in title placeholder = slide title
                if shape.shape_type == 13 or (hasattr(shape, "placeholder_format") and
                                               shape.placeholder_format and
                                               shape.placeholder_format.idx == 0):
                    slide_title = shape_text
                    if slide_title not in chapters:
                        chapters.append(slide_title)
                else:
                    texts.append(shape_text)

            full_text = "\n".join([slide_title] + texts if slide_title else texts)
            if full_text.strip():
                pages.append(ParsedPage(
                    page_number=slide_idx + 1,
                    text=full_text.strip(),
                    heading=slide_title,
                    section=None,
                ))

        word_count = sum(len(p.text.split()) for p in pages)
        return ParsedDocument(
            filename=filename,
            file_type="pptx",
            total_pages=len(pages),
            pages=pages,
            detected_chapters=chapters[:20],
            detected_sections=[],
            word_count=word_count,
        )

    def _parse_txt(self, path: Path, filename: str) -> ParsedDocument:
        for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = path.read_bytes().decode("utf-8", errors="replace")

        # Split into logical pages by double newlines or ~500 words
        paragraphs = re.split(r"\n{2,}", text.strip())
        pages: list[ParsedPage] = []
        sections = []

        # Group paragraphs into ~500-word "pages"
        buffer = []
        buffer_words = 0
        page_num = 1

        for para in paragraphs:
            if not para.strip():
                continue
            words = len(para.split())
            buffer.append(para.strip())
            buffer_words += words

            if buffer_words >= 400:
                combined = "\n\n".join(buffer)
                section = self._detect_section(combined)
                if section and section not in sections:
                    sections.append(section)
                pages.append(ParsedPage(
                    page_number=page_num,
                    text=combined,
                    heading=None,
                    section=section,
                ))
                page_num += 1
                buffer = []
                buffer_words = 0

        if buffer:
            combined = "\n\n".join(buffer)
            pages.append(ParsedPage(
                page_number=page_num,
                text=combined,
                heading=None,
                section=None,
            ))

        word_count = sum(len(p.text.split()) for p in pages)
        return ParsedDocument(
            filename=filename,
            file_type="txt",
            total_pages=len(pages),
            pages=pages,
            detected_chapters=[],
            detected_sections=sections[:50],
            word_count=word_count,
        )

    def _detect_section(self, text: str) -> Optional[str]:
        """Detect a section header from text patterns. Returns None if not found."""
        lines = text.strip().split("\n")
        for line in lines[:5]:  # check first 5 lines
            stripped = line.strip()
            # All caps line that's not too long = likely a section header
            if stripped.isupper() and 3 < len(stripped) < 80:
                return stripped
            # Numbered heading pattern: "1. Introduction" or "1.2 Resistance"
            if re.match(r"^\d+(\.\d+)?\s+[A-Z][a-zA-Z\s]{3,60}$", stripped):
                return stripped
        return None


document_parser = DocumentParser()
