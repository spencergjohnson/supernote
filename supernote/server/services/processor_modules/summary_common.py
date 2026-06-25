"""Shared schema and helpers for note summary generation.

Used by both the Gemini-backed ``SummaryModule`` and the local-LLM-backed
``LocalSummaryModule`` so the structured output schema, transcript
aggregation and response parsing live in one place.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.summary import METADATA_SEGMENTS
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.utils.note_content import format_page_metadata

logger = logging.getLogger(__name__)

# Metadata key used in the overview Summary 'extra_metadata' field.
METADATA_TOPICS = "topics"
METADATA_TITLE = "title"


@dataclass
class NoteOverview(DataClassJSONMixin):
    title: str = field(
        metadata={
            "description": "A short descriptive title (3-8 words) for the entire note."
        }
    )
    summary: str = field(
        metadata={
            "description": "A 2-4 sentence overarching summary describing what this whole note is about, its purpose, and the kinds of content it holds."
        }
    )
    topics: List[str] = field(
        metadata={
            "description": "3-7 short topic or keyword tags describing the note's main themes."
        }
    )


@dataclass
class SummarySegment(DataClassJSONMixin):
    date_range: str = field(
        metadata={
            "description": "The date range covered by this segment (e.g., '2023-10-27', 'Week of Oct 27')."
        }
    )
    summary: str = field(
        metadata={
            "description": "A concise summary of the events, tasks, and notes for this period."
        }
    )
    extracted_dates: List[str] = field(
        metadata={
            "description": "List of specific dates derived from the content in ISO 8601 format (YYYY-MM-DD)."
        }
    )
    page_refs: List[int] = field(
        metadata={
            "description": "List of 1-indexed page numbers typically found in the text as '--- Page X ---'."
        }
    )


@dataclass
class SummaryResponse(DataClassJSONMixin):
    overview: NoteOverview = field(
        metadata={
            "description": "A single overarching overview of the entire note."
        }
    )
    segments: List[SummarySegment] = field(
        metadata={
            "description": "List of summary segments extracted from the transcript."
        }
    )


@dataclass
class ParsedSummary:
    """Result of parsing the LLM summary response."""

    segments_markdown: str
    segments_metadata: Optional[str]
    overview_content: Optional[str]
    overview_metadata: Optional[str]


def build_transcript_text(
    pages: Sequence[NotePageContentDO], file_do: UserFileDO
) -> str:
    """Aggregate per-page OCR text into a single transcript with page markers."""
    text_parts: List[str] = []
    for p in pages:
        if p.text_content:
            metadata = format_page_metadata(
                page_index=p.page_index,
                page_id=p.page_id or "",
                file_name=file_do.file_name,
                notebook_create_time=file_do.create_time,
                include_section_divider=True,
            )
            text_parts.append(f"{metadata}\n{p.text_content}")
    return "\n\n".join(text_parts)


def _extract_json(text: str) -> str:
    """Strip Markdown code fences and extract the outermost JSON object.

    Handles responses where the model wraps its JSON in ```json ... ``` blocks
    or surrounds it with prose, which causes plain json.loads to fail.
    """
    # Remove ```json ... ``` or ``` ... ``` fences
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line and the closing fence
        lines = stripped.splitlines()
        # Find closing fence
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        stripped = "\n".join(lines[1:end]).strip()

    # Slice from first '{' to last '}' to skip any surrounding prose
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end >= start:
        stripped = stripped[start : end + 1]

    return stripped


def parse_summary_response(text: Optional[str], file_id: int) -> ParsedSummary:
    """Parse the LLM JSON response into markdown + structured metadata.

    Tolerates missing fields, Markdown code fences, and invalid JSON.
    Falls back to a neutral placeholder so raw JSON is never stored as content.
    """
    if not text:
        return ParsedSummary("No summary generated.", None, None, None)

    try:
        data = json.loads(_extract_json(text))
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON summary response for file {file_id}")
        return ParsedSummary("Summary could not be parsed.", None, None, None)

    # --- Segments (preserve existing behaviour) ---
    segments_data = data.get("segments", []) or []
    summary_parts: List[str] = []
    clean_segments: List[dict] = []

    for seg in segments_data:
        date_range = seg.get("date_range", "Unknown Date")
        seg_text = seg.get("summary", "")
        dates = seg.get("extracted_dates", [])
        page_refs = seg.get("page_refs", [])

        header = f"## {date_range}"
        if page_refs:
            pages_str = ", ".join(str(p) for p in page_refs)
            header += f" (Pages {pages_str})"

        summary_parts.append(f"{header}\n{seg_text}")
        clean_segments.append(
            {
                "date_range": date_range,
                "summary": seg_text,
                "extracted_dates": dates,
                "page_refs": page_refs,
            }
        )

    segments_markdown = (
        "\n\n".join(summary_parts) if summary_parts else "No summary generated."
    )
    segments_metadata = (
        json.dumps({METADATA_SEGMENTS: clean_segments}) if clean_segments else None
    )

    # --- Overview (new) ---
    overview_content: Optional[str] = None
    overview_metadata: Optional[str] = None
    overview = data.get("overview") or {}
    if isinstance(overview, dict):
        title = (overview.get("title") or "").strip()
        overview_summary = (overview.get("summary") or "").strip()
        topics = [
            str(t).strip()
            for t in (overview.get("topics") or [])
            if str(t).strip()
        ]
        if overview_summary or title:
            overview_content = (
                f"{title}\n\n{overview_summary}".strip()
                if title
                else overview_summary
            )
            overview_metadata = json.dumps(
                {METADATA_TITLE: title, METADATA_TOPICS: topics}
            )

    return ParsedSummary(
        segments_markdown=segments_markdown,
        segments_metadata=segments_metadata,
        overview_content=overview_content,
        overview_metadata=overview_metadata,
    )
