"""Scene-aware document splitting for large documents.

Splits FDX screenplays on scene heading boundaries and large text documents
into manageable sections for chunked LLM editing.  Oversized scenes are
sub-split on Character paragraph boundaries so every section stays under
MAX_SECTION_CHARS.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from typing import List

MAX_SECTION_CHARS = 4000


@dataclass
class DocumentSection:
    """One section of a split document."""
    index: int
    heading: str
    content: str
    xml_para_start: int  # index of first <Paragraph> in this section
    xml_para_end: int    # index past last <Paragraph> in this section


def split_fdx_into_scenes(fdx_bytes: bytes) -> List[dict]:
    """Parse FDX XML and split on Scene Heading boundaries.

    If any scene exceeds MAX_SECTION_CHARS, it is sub-split on Character
    paragraph boundaries so each chunk stays manageable for the LLM.

    Returns a list of section dicts (JSON-serializable).
    """
    root = ET.fromstring(fdx_bytes)
    content_el = root.find("Content")
    if content_el is None:
        return []

    paragraphs = list(content_el.findall("Paragraph"))
    if not paragraphs:
        return []

    # --- Phase 1: split on Scene Heading boundaries ---
    raw_scenes: list[dict] = []  # {heading, para_start, para_end}
    current_heading = "UNTITLED"
    section_start = 0

    for i, para in enumerate(paragraphs):
        ptype = para.get("Type", "")
        if ptype == "Scene Heading":
            if i > 0:
                raw_scenes.append({
                    "heading": current_heading,
                    "para_start": section_start,
                    "para_end": i,
                })
            line = _para_text(para)
            current_heading = line.upper() if line else f"SCENE {len(raw_scenes) + 1}"
            section_start = i

    # Close final scene
    raw_scenes.append({
        "heading": current_heading,
        "para_start": section_start,
        "para_end": len(paragraphs),
    })

    # --- Phase 2: sub-split oversized scenes ---
    final_sections: list[DocumentSection] = []

    for scene in raw_scenes:
        ps = scene["para_start"]
        pe = scene["para_end"]
        scene_paras = paragraphs[ps:pe]
        scene_text = _render_paras(scene_paras)

        if len(scene_text) <= MAX_SECTION_CHARS:
            # Small enough — keep as-is
            final_sections.append(DocumentSection(
                index=len(final_sections),
                heading=scene["heading"],
                content=scene_text,
                xml_para_start=ps,
                xml_para_end=pe,
            ))
        else:
            # Sub-split on Character paragraph boundaries
            _subsplit_scene(
                final_sections, paragraphs, scene["heading"],
                ps, pe,
            )

    # Re-number indices
    for i, s in enumerate(final_sections):
        s.index = i

    return [asdict(s) for s in final_sections]


def _subsplit_scene(
    out: list,
    all_paras: list,
    base_heading: str,
    para_start: int,
    para_end: int,
) -> None:
    """Sub-split an oversized scene on Character paragraph boundaries.

    Each sub-section starts at a Character paragraph (a natural dialogue
    beat boundary) and accumulates paragraphs until hitting MAX_SECTION_CHARS.
    """
    chunk_start = para_start
    chunk_lines: list[str] = []
    chunk_chars = 0
    sub_idx = 0
    first_char_name = ""

    for i in range(para_start, para_end):
        para = all_paras[i]
        ptype = para.get("Type", "")
        line = _render_one_para(para)

        # Split point: Character paragraph and chunk is already large enough
        if ptype == "Character" and chunk_chars > MAX_SECTION_CHARS and chunk_lines:
            heading = f"{base_heading} (part {sub_idx + 1})"
            if first_char_name:
                heading += f" — {first_char_name}..."
            out.append(DocumentSection(
                index=0,  # re-numbered later
                heading=heading,
                content="\n".join(chunk_lines).strip(),
                xml_para_start=chunk_start,
                xml_para_end=i,
            ))
            chunk_start = i
            chunk_lines = []
            chunk_chars = 0
            sub_idx += 1
            first_char_name = ""

        if ptype == "Character" and not first_char_name:
            first_char_name = _para_text(para).upper()

        chunk_lines.append(line)
        chunk_chars += len(line) + 1

    # Close final sub-chunk
    if chunk_lines:
        heading = f"{base_heading} (part {sub_idx + 1})"
        if first_char_name and sub_idx > 0:
            heading += f" — {first_char_name}..."
        out.append(DocumentSection(
            index=0,
            heading=heading,
            content="\n".join(chunk_lines).strip(),
            xml_para_start=chunk_start,
            xml_para_end=para_end,
        ))


def split_large_text(text: str, max_section_chars: int = MAX_SECTION_CHARS) -> List[dict]:
    """Generic fallback splitter for non-FDX large documents.

    Splits on double-newline paragraph boundaries, grouping paragraphs into
    sections that don't exceed max_section_chars.
    """
    paragraphs = text.split("\n\n")
    sections: List[dict] = []
    current_lines: list[str] = []
    current_chars = 0
    para_start = 0
    para_cursor = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            para_cursor += 1
            continue

        if current_chars + len(para) > max_section_chars and current_lines:
            heading = _extract_heading(current_lines[0])
            sections.append({
                "index": len(sections),
                "heading": heading,
                "content": "\n\n".join(current_lines),
                "xml_para_start": para_start,
                "xml_para_end": para_cursor,
            })
            current_lines = []
            current_chars = 0
            para_start = para_cursor

        current_lines.append(para)
        current_chars += len(para)
        para_cursor += 1

    if current_lines:
        heading = _extract_heading(current_lines[0])
        sections.append({
            "index": len(sections),
            "heading": heading,
            "content": "\n\n".join(current_lines),
            "xml_para_start": para_start,
            "xml_para_end": para_cursor,
        })

    return sections


def build_table_of_contents(sections: List[dict]) -> str:
    """Build a compact TOC string from sections list."""
    lines = []
    for s in sections:
        char_count = len(s.get("content", ""))
        lines.append(f"  [{s['index']}] {s['heading']}  ({char_count} chars)")
    return "TABLE OF CONTENTS:\n" + "\n".join(lines)


def _para_text(para: ET.Element) -> str:
    """Extract plain text from an FDX <Paragraph> element."""
    texts = []
    for text_el in para.iter("Text"):
        if text_el.text:
            texts.append(text_el.text)
    return "".join(texts).strip()


def _render_one_para(para: ET.Element) -> str:
    """Render a single FDX paragraph to screenplay text."""
    ptype = para.get("Type", "")
    line = _para_text(para)
    if not line:
        return ""
    if ptype == "Scene Heading":
        return line.upper()
    if ptype == "Character":
        return f"  {line.upper()}"
    if ptype == "Parenthetical":
        return f"  {line}"
    if ptype == "Dialogue":
        return f"  {line}"
    if ptype == "Transition":
        return line.upper()
    return line


def _render_paras(paras: list) -> str:
    """Render a list of FDX paragraphs to screenplay text."""
    lines = [_render_one_para(p) for p in paras]
    return "\n".join(lines).strip()


def _extract_heading(first_line: str) -> str:
    """Extract a short heading from the first line of a section."""
    line = first_line.strip()[:80]
    return line if line else "SECTION"
