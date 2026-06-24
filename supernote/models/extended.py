"""Module for server-specific extension models.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

from dataclasses import dataclass, field

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

from supernote.models.base import BaseResponse, ProcessingStatus
from supernote.models.summary import SummaryItem


@dataclass
class WebSummaryListRequestDTO(DataClassJSONMixin):
    """Request DTO for listing summaries by file ID (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The ID of the file to list summaries for."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSummaryListVO(BaseResponse):
    """Response VO for listing summaries (Web Extension).

    Used by: POST /api/extended/file/summary/list
    """

    summary_do_list: list[SummaryItem] = field(
        metadata=field_options(alias="summaryDOList"), default_factory=list
    )
    """List of summary items found for the file."""

    total_records: int = field(metadata=field_options(alias="totalRecords"), default=0)
    """Total count of summaries returned."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskVO(DataClassJSONMixin):
    """VO for a system processing task.

    Used by: GET /api/extended/system/tasks
    """

    id: int
    """The unique ID of the system task."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The ID of the file associated with this task."""

    task_type: str = field(metadata=field_options(alias="taskType"))
    """The type of task (e.g. 'OCR', 'SUMMARY')."""

    key: str
    """The specific key for the task (e.g. 'page_1', 'global')."""

    status: ProcessingStatus
    """The current status (PENDING, PROCESSING, COMPLETED, FAILED)."""

    retry_count: int = field(metadata=field_options(alias="retryCount"))
    """Number of times the task has been retried."""

    update_time: int = field(metadata=field_options(alias="updateTime"))
    """Timestamp of the last update (ms)."""

    last_error: str | None = field(
        metadata=field_options(alias="lastError"), default=None
    )
    """Error message from the last failure, if any."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemTaskListVO(BaseResponse):
    """Response VO for listing system tasks.

    Used by: GET /api/extended/system/tasks
    """

    tasks: list[SystemTaskVO] = field(default_factory=list)
    """List of recent system tasks."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileProcessingStatusDTO(DataClassJSONMixin):
    """Request model for querying processing status of files.

    Used by:
        /api/extended/file/processing/status (POST)
    """

    file_ids: list[int] = field(metadata=field_options(alias="fileIds"))

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class FileProcessingStatusVO(BaseResponse):
    """Response model for file processing status.

    Used by:
        /api/extended/file/processing/status (POST)
    """

    # Map of file_id -> status summary
    # status: PENDING, PROCESSING, COMPLETED, FAILED
    status_map: dict[str, ProcessingStatus] = field(
        metadata=field_options(alias="statusMap"), default_factory=dict
    )


@dataclass
class SearchResultVO(DataClassJSONMixin):
    """VO for a single semantic search result."""

    # Serialized as a string so 64-bit IDs survive JS JSON.parse precision.
    file_id: str = field(metadata=field_options(alias="fileId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    page_index: int = field(metadata=field_options(alias="pageIndex"))
    page_id: str = field(metadata=field_options(alias="pageId"))
    score: float
    text_preview: str = field(metadata=field_options(alias="textPreview"))
    date: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSearchRequestDTO(DataClassJSONMixin):
    """Request DTO for semantic search (Web Extension)."""

    query: str
    top_n: int = field(metadata=field_options(alias="topN"), default=5)
    name_filter: str | None = field(
        metadata=field_options(alias="nameFilter"), default=None
    )
    date_after: str | None = field(
        metadata=field_options(alias="dateAfter"), default=None
    )
    date_before: str | None = field(
        metadata=field_options(alias="dateBefore"), default=None
    )

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebSearchResponseVO(BaseResponse):
    """Response VO for semantic search (Web Extension)."""

    results: list[SearchResultVO] = field(default_factory=list)
    """List of search results."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebTranscriptRequestDTO(DataClassJSONMixin):
    """Request DTO for retrieving a notebook transcript (Web Extension)."""

    file_id: int = field(metadata=field_options(alias="fileId"))
    """The unique ID of the notebook."""

    start_index: int | None = field(
        metadata=field_options(alias="startIndex"), default=None
    )
    """Optional 0-based start page index (inclusive)."""

    end_index: int | None = field(
        metadata=field_options(alias="endIndex"), default=None
    )
    """Optional 0-based end page index (inclusive)."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class WebTranscriptResponseVO(BaseResponse):
    """Response VO for transcript retrieval (Web Extension)."""

    transcript: str | None = None

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TaskTypeProgressVO(DataClassJSONMixin):
    """Progress breakdown for a single processing task type."""

    task_type: str = field(metadata=field_options(alias="taskType"))
    """The task type (e.g. 'OCR', 'EMBED', 'PNG', 'SUMMARY')."""

    total: int = 0
    """Total number of tasks of this type."""

    completed: int = 0
    """Number of completed tasks."""

    processing: int = 0
    """Number of in-progress tasks."""

    pending: int = 0
    """Number of pending tasks."""

    failed: int = 0
    """Number of failed tasks."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class SystemProgressVO(BaseResponse):
    """Aggregate processing/indexing progress across all tasks.

    Used by: GET /api/extended/system/progress
    """

    total: int = 0
    """Total number of tracked tasks."""

    completed: int = 0
    """Tasks in COMPLETED status."""

    processing: int = 0
    """Tasks in PROCESSING status."""

    pending: int = 0
    """Tasks in PENDING status."""

    failed: int = 0
    """Tasks in FAILED status."""

    by_type: list[TaskTypeProgressVO] = field(
        metadata=field_options(alias="byType"), default_factory=list
    )
    """Per-task-type progress breakdown."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class ActivityBucketVO(DataClassJSONMixin):
    """Number of pages attributed to a calendar month (inferred from page IDs)."""

    period: str
    """The month in YYYY-MM form."""

    count: int = 0
    """Number of pages dated within this month."""

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TopNotebookVO(DataClassJSONMixin):
    """A notebook ranked by how many transcribed pages it contains."""

    # Serialized as a string so 64-bit IDs survive JS JSON.parse precision.
    file_id: str = field(metadata=field_options(alias="fileId"))
    file_name: str = field(metadata=field_options(alias="fileName"))
    page_count: int = field(metadata=field_options(alias="pageCount"), default=0)

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class TagCountVO(DataClassJSONMixin):
    """A tag and the number of summaries it appears on."""

    name: str
    count: int = 0

    class Config(BaseConfig):
        serialize_by_alias = True


@dataclass
class DashboardStatsVO(BaseResponse):
    """Aggregated insights about a user's notebook library.

    Used by: GET /api/extended/dashboard
    """

    notebook_count: int = field(
        metadata=field_options(alias="notebookCount"), default=0
    )
    """Number of .note files owned by the user."""

    page_count: int = field(metadata=field_options(alias="pageCount"), default=0)
    """Total number of pages tracked across all notebooks."""

    pages_with_text: int = field(
        metadata=field_options(alias="pagesWithText"), default=0
    )
    """Number of pages that have OCR text."""

    pages_embedded: int = field(
        metadata=field_options(alias="pagesEmbedded"), default=0
    )
    """Number of pages that have a stored embedding vector."""

    summary_count: int = field(metadata=field_options(alias="summaryCount"), default=0)
    """Number of AI summaries generated."""

    activity_by_month: list[ActivityBucketVO] = field(
        metadata=field_options(alias="activityByMonth"), default_factory=list
    )
    """Pages per calendar month, inferred from page IDs (chronological)."""

    top_notebooks: list[TopNotebookVO] = field(
        metadata=field_options(alias="topNotebooks"), default_factory=list
    )
    """Notebooks with the most transcribed pages."""

    top_tags: list[TagCountVO] = field(
        metadata=field_options(alias="topTags"), default_factory=list
    )
    """Most frequent summary tags."""

    class Config(BaseConfig):
        serialize_by_alias = True
