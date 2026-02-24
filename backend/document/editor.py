"""Format-preserving document editor.

Given original file bytes and new text content from the LLM, applies text-level
changes to the original document while preserving its structure and formatting.
"""

import io
import logging
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

import pdfplumber
from docx import Document as DocxDocument
from pdf2docx import Converter

logger = logging.getLogger(__name__)


def edit_preserving_format(
    original_bytes: bytes,
    original_filename: str,
    new_text: str,
) -> bytes | None:
    """Apply text edits to the original file, preserving formatting.

    Returns edited file bytes, or None if format-preserving edit is not
    supported for this file type (caller should fall back to generate_document).
    """
    ext = _get_extension(original_filename)
    if ext == ".fdx":
        return _edit_fdx(original_bytes, new_text)
    if ext == ".docx":
        return _edit_docx(original_bytes, new_text)
    if ext == ".pdf":
        return _edit_pdf(original_bytes, new_text)
    return None


# ---------------------------------------------------------------------------
# PDF editing via PDF → DOCX → edit → PDF pipeline
# ---------------------------------------------------------------------------

def _edit_pdf(original_bytes: bytes, new_text: str) -> bytes | None:
    """Edit a PDF by converting to DOCX, applying edits, converting back.

    The LLM sees pdfplumber-extracted text, but the intermediate DOCX comes from
    pdf2docx which produces different paragraph structure.  We bridge the gap by:
    1. Re-extracting text with pdfplumber (matching what the LLM saw)
    2. Diffing that against the LLM's new text to find specific changes
    3. Applying those changes as find-and-replace on the DOCX paragraphs
    """
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "original.pdf")
        docx_path = os.path.join(tmp, "converted.docx")
        out_pdf_path = os.path.join(tmp, "edited.pdf")

        # 1. Write original PDF
        with open(pdf_path, "wb") as f:
            f.write(original_bytes)

        # 2. Re-extract text with pdfplumber (same method used at upload time)
        original_extracted = _extract_pdf_text(original_bytes)

        # 3. Compute specific text changes between extraction and LLM's output
        replacements = _compute_text_replacements(original_extracted, new_text)
        if not replacements:
            logger.info("No text changes detected for PDF edit")
            return None

        logger.info("PDF edit: found %d text replacement(s)", len(replacements))

        # 4. PDF → DOCX
        try:
            cv = Converter(pdf_path)
            cv.convert(docx_path)
            cv.close()
        except Exception as e:
            logger.warning("pdf2docx conversion failed: %s", e)
            return None

        # 5. Apply replacements to the DOCX
        with open(docx_path, "rb") as f:
            docx_bytes = f.read()

        edited_docx = _apply_replacements_to_docx(docx_bytes, replacements)
        if edited_docx is None:
            return None

        edited_docx_path = os.path.join(tmp, "edited.docx")
        with open(edited_docx_path, "wb") as f:
            f.write(edited_docx)

        # 6. DOCX → PDF via LibreOffice
        try:
            subprocess.run(
                [
                    "libreoffice", "--headless", "--norestore",
                    "--convert-to", "pdf",
                    "--outdir", tmp,
                    edited_docx_path,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("LibreOffice PDF conversion failed: %s", e)
            return None

        if not os.path.exists(out_pdf_path):
            # LibreOffice names output after the input file
            alt_path = os.path.join(tmp, "edited.pdf")
            if not os.path.exists(alt_path):
                logger.warning("LibreOffice did not produce output PDF")
                return None
            out_pdf_path = alt_path

        with open(out_pdf_path, "rb") as f:
            return f.read()


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber (same method as parser.py)."""
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)


def _compute_text_replacements(
    original: str, new: str,
) -> list[tuple[str, str]]:
    """Diff original vs new text at the word level, returning (old, new) phrase pairs."""
    orig_words = original.split()
    new_words = new.split()

    matcher = SequenceMatcher(
        None, [w.lower() for w in orig_words], [w.lower() for w in new_words],
    )

    replacements: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_phrase = " ".join(orig_words[i1:i2])
        new_phrase = " ".join(new_words[j1:j2])
        if old_phrase != new_phrase:
            replacements.append((old_phrase, new_phrase))
            logger.info("PDF edit change: %r -> %r", old_phrase[:80], new_phrase[:80])

    return replacements


def _apply_replacements_to_docx(
    docx_bytes: bytes, replacements: list[tuple[str, str]],
) -> bytes | None:
    """Apply find-and-replace text changes to a DOCX, preserving formatting."""
    try:
        doc = DocxDocument(io.BytesIO(docx_bytes))
    except Exception:
        logger.warning("Failed to parse DOCX for replacement")
        return None

    _WS = re.compile(r"\s+")
    applied_count = 0

    def _apply_to_paragraph(para):
        """Apply replacements to a single paragraph, return True if changed."""
        text = para.text
        if not text.strip():
            return False

        new_text_val = text
        for old_phrase, new_phrase in replacements:
            if not old_phrase:
                continue
            # Normalize whitespace for matching (pdf2docx may use different spacing)
            pattern = _WS.sub(r"\\s+", re.escape(old_phrase))
            match = re.search(pattern, new_text_val)
            if match:
                logger.info("MATCH: %r -> %r", old_phrase[:60], new_phrase[:60])
                new_text_val = new_text_val[:match.start()] + new_phrase + new_text_val[match.end():]

        if new_text_val != text:
            if para.runs:
                para.runs[0].text = new_text_val
                for run in para.runs[1:]:
                    run.text = ""
            else:
                para.text = new_text_val
            return True
        return False

    # Apply to body paragraphs
    for para in doc.paragraphs:
        if _apply_to_paragraph(para):
            applied_count += 1

    # Apply to table cells (pdf2docx often puts structured data in tables)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    if _apply_to_paragraph(para):
                        applied_count += 1

    logger.info("Applied replacements to %d paragraph(s)", applied_count)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# FDX editing (Final Draft screenplay XML)
# ---------------------------------------------------------------------------

def _edit_fdx(original_bytes: bytes, new_text: str) -> bytes | None:
    """Edit an FDX screenplay XML, replacing text while preserving structure."""
    try:
        root = ET.fromstring(original_bytes)
    except ET.ParseError:
        logger.warning("Failed to parse original FDX XML")
        return None

    # Collect original paragraph elements and their plain text
    content_el = root.find("Content")
    if content_el is None:
        return None

    orig_paragraphs: list[tuple[ET.Element, str]] = []
    for para in content_el.findall("Paragraph"):
        texts = []
        for text_el in para.iter("Text"):
            if text_el.text:
                texts.append(text_el.text)
        line = "".join(texts).strip()
        if line:
            orig_paragraphs.append((para, line))

    # Parse new text into lines (strip screenplay indentation from extraction)
    new_lines = [
        line.strip() for line in new_text.splitlines() if line.strip()
    ]

    # Build case-insensitive versions for matching
    orig_texts = [t.lower() for _, t in orig_paragraphs]
    new_lower = [t.lower() for t in new_lines]

    # Use SequenceMatcher to align original paragraphs with new text
    matcher = SequenceMatcher(None, orig_texts, new_lower)
    opcodes = matcher.get_opcodes()

    # Build a new Content element preserving structure
    new_content = ET.Element("Content")

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            # Keep original elements unchanged (they match)
            for idx in range(i1, i2):
                new_content.append(orig_paragraphs[idx][0])
        elif tag == "replace":
            # Map new text onto original elements where possible
            orig_slice = list(range(i1, i2))
            new_slice = list(range(j1, j2))
            for k, j_idx in enumerate(new_slice):
                if k < len(orig_slice):
                    # Update text in existing element (preserves Type attribute)
                    para_el = orig_paragraphs[orig_slice[k]][0]
                    _set_paragraph_text(para_el, new_lines[j_idx])
                    new_content.append(para_el)
                else:
                    # Extra new lines — create Action paragraphs
                    new_content.append(_make_paragraph("Action", new_lines[j_idx]))
            # Original paragraphs beyond the new slice are dropped (deleted)
        elif tag == "insert":
            # New lines with no original counterpart
            for j_idx in range(j1, j2):
                new_content.append(_make_paragraph("Action", new_lines[j_idx]))
        elif tag == "delete":
            # Original lines removed in the edit — skip them
            pass

    # Replace Content element in the tree
    root.remove(content_el)
    root.append(new_content)

    buf = io.BytesIO()
    tree = ET.ElementTree(root)
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _set_paragraph_text(para: ET.Element, new_text: str) -> None:
    """Replace all Text element content in a Paragraph with new text."""
    text_els = list(para.iter("Text"))
    if text_els:
        # Put all text in the first Text element, clear the rest
        text_els[0].text = new_text
        for extra in text_els[1:]:
            extra.text = ""
    else:
        text_el = ET.SubElement(para, "Text")
        text_el.text = new_text


def _make_paragraph(ptype: str, text: str) -> ET.Element:
    """Create a new FDX Paragraph element."""
    para = ET.Element("Paragraph", Type=ptype)
    text_el = ET.SubElement(para, "Text")
    text_el.text = text
    return para


# ---------------------------------------------------------------------------
# DOCX editing
# ---------------------------------------------------------------------------

def _edit_docx(original_bytes: bytes, new_text: str) -> bytes | None:
    """Edit a DOCX file, replacing paragraph text while preserving styles."""
    try:
        doc = DocxDocument(io.BytesIO(original_bytes))
    except Exception:
        logger.warning("Failed to parse original DOCX")
        return None

    # Extract original paragraph texts (non-empty only)
    orig_paras_with_idx: list[tuple[int, str]] = []
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            orig_paras_with_idx.append((i, para.text.strip()))

    new_lines = [line.strip() for line in new_text.splitlines() if line.strip()]

    orig_texts = [t.lower() for _, t in orig_paras_with_idx]
    new_lower = [t.lower() for t in new_lines]

    matcher = SequenceMatcher(None, orig_texts, new_lower)
    opcodes = matcher.get_opcodes()

    # Track which original paragraphs to update
    updates: dict[int, str] = {}  # doc paragraph index -> new text

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            pass
        elif tag == "replace":
            orig_slice = list(range(i1, i2))
            new_slice = list(range(j1, j2))
            for k, j_idx in enumerate(new_slice):
                if k < len(orig_slice):
                    doc_idx = orig_paras_with_idx[orig_slice[k]][0]
                    updates[doc_idx] = new_lines[j_idx]

    # Apply updates: replace text while preserving the first run's formatting
    for doc_idx, new_text_val in updates.items():
        para = doc.paragraphs[doc_idx]
        if para.runs:
            para.runs[0].text = new_text_val
            for run in para.runs[1:]:
                run.text = ""
        else:
            para.text = new_text_val

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extension(filename: str) -> str:
    dot = filename.rfind(".")
    if dot == -1:
        return ""
    return filename[dot:].lower()
