"""Module for server-specific extension routes.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

import logging
from collections import Counter

from aiohttp import web
from sqlalchemy import func, select

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    ActivityBucketVO,
    DashboardStatsVO,
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    SearchResultVO,
    SystemProgressVO,
    SystemTaskListVO,
    SystemTaskVO,
    TagCountVO,
    TaskTypeProgressVO,
    TopNotebookVO,
    WebSearchRequestDTO,
    WebSearchResponseVO,
    WebSummaryListRequestDTO,
    WebSummaryListVO,
    WebTranscriptRequestDTO,
    WebTranscriptResponseVO,
)
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.exceptions import SupernoteError
from supernote.server.services.search import SearchService
from supernote.server.services.summary import SummaryService
from supernote.server.services.user import UserService
from supernote.server.utils.note_content import infer_page_date

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()


@routes.post("/api/extended/file/summary/list")
async def handle_extended_file_summary_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/summary/list
    # Purpose: Extended API to list summaries for a file.
    user_email = request["user"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        req_dto = WebSummaryListRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    summary_service: SummaryService = request.app["summary_service"]

    try:
        summaries = await summary_service.list_summaries_for_file_internal(
            user_email, req_dto.file_id
        )
        return web.json_response(
            WebSummaryListVO(
                summary_do_list=summaries, total_records=len(summaries)
            ).to_dict()
        )
    except SupernoteError as err:
        return err.to_response()
    except Exception as err:
        logger.exception("Error fetching summaries")
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/extended/system/tasks")
async def handle_list_system_tasks(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/tasks
    # Purpose: Extended API to list system tasks for the control panel.

    processor_service = request.app["processor_service"]

    try:
        tasks = await processor_service.list_system_tasks()
    except Exception as err:
        logger.exception("Error listing system tasks")
        return SupernoteError.uncaught(err).to_response()

    task_vos = [
        SystemTaskVO(
            id=t.id,
            file_id=t.file_id,
            task_type=t.task_type,
            key=t.key,
            status=ProcessingStatus(t.status),
            retry_count=t.retry_count,
            last_error=t.last_error,
            update_time=t.update_time,
        )
        for t in tasks
    ]

    return web.json_response(SystemTaskListVO(tasks=task_vos).to_dict())


@routes.get("/api/extended/system/progress")
async def handle_system_progress(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/progress
    # Purpose: Aggregate sync/indexing progress across every processing task.
    session_manager = request.app["session_manager"]

    try:
        async with session_manager.session() as session:
            stmt = select(
                SystemTaskDO.task_type,
                SystemTaskDO.status,
                func.count().label("count"),
            ).group_by(SystemTaskDO.task_type, SystemTaskDO.status)
            result = await session.execute(stmt)
            rows = result.all()
    except Exception as err:
        logger.exception("Error aggregating system progress")
        return SupernoteError.uncaught(err).to_response()

    by_type: dict[str, TaskTypeProgressVO] = {}
    totals = {"completed": 0, "processing": 0, "pending": 0, "failed": 0, "total": 0}

    for task_type, status, count in rows:
        bucket = by_type.setdefault(task_type, TaskTypeProgressVO(task_type=task_type))
        bucket.total += count
        totals["total"] += count
        if status == ProcessingStatus.COMPLETED:
            bucket.completed += count
            totals["completed"] += count
        elif status == ProcessingStatus.PROCESSING:
            bucket.processing += count
            totals["processing"] += count
        elif status == ProcessingStatus.FAILED:
            bucket.failed += count
            totals["failed"] += count
        else:
            bucket.pending += count
            totals["pending"] += count

    return web.json_response(
        SystemProgressVO(
            total=totals["total"],
            completed=totals["completed"],
            processing=totals["processing"],
            pending=totals["pending"],
            failed=totals["failed"],
            by_type=sorted(by_type.values(), key=lambda b: b.task_type),
        ).to_dict()
    )


@routes.post("/api/extended/file/processing/status")
async def handle_file_processing_status(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/file/processing/status
    # Purpose: Get aggregated processing status for a list of files.

    try:
        data = await request.json()
        req_dto = FileProcessingStatusDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    session_manager = request.app["session_manager"]

    try:
        status_map = {}
        async with session_manager.session() as session:
            for file_id in req_dto.file_ids:
                # Aggregate tasks for this file
                stmt = select(SystemTaskDO).where(SystemTaskDO.file_id == file_id)
                result = await session.execute(stmt)
                tasks = result.scalars().all()

                if not tasks:
                    status_map[str(file_id)] = ProcessingStatus.NONE
                    continue

                # Logic:
                # If any FAILED -> FAILED
                # If any PROCESSING -> PROCESSING
                # If all COMPLETED -> COMPLETED
                # Else -> PENDING

                if any(t.status == ProcessingStatus.FAILED for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.FAILED
                elif any(t.status == ProcessingStatus.PROCESSING for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.PROCESSING
                elif all(t.status == ProcessingStatus.COMPLETED for t in tasks):
                    status_map[str(file_id)] = ProcessingStatus.COMPLETED
                else:
                    status_map[str(file_id)] = ProcessingStatus.PENDING

        return web.json_response(
            FileProcessingStatusVO(status_map=status_map).to_dict()
        )
    except Exception as err:
        logger.exception("Error fetching processing status")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/search")
async def handle_extended_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/search
    # Purpose: Semantic search across notebook content.
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebSearchRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    search_service: SearchService = request.app["search_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        results = await search_service.search_chunks(
            user_id=user_id,
            query=req_dto.query,
            top_n=req_dto.top_n,
            name_filter=req_dto.name_filter,
            date_after=req_dto.date_after,
            date_before=req_dto.date_before,
        )

        vo_results = [
            SearchResultVO(
                file_id=r.file_id,
                file_name=r.file_name,
                page_index=r.page_index,
                page_id=r.page_id,
                score=float(r.score),
                text_preview=r.text_preview,
                date=r.date,
            )
            for r in results
        ]

        return web.json_response(WebSearchResponseVO(results=vo_results).to_dict())
    except Exception as err:
        logger.exception("Error performing semantic search")
        return SupernoteError.uncaught(err).to_response()


@routes.post("/api/extended/transcript")
async def handle_extended_transcript(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/transcript
    # Purpose: Retrieve notebook transcript.
    user_email = request["user"]
    try:
        data = await request.json()
        req_dto = WebTranscriptRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    search_service: SearchService = request.app["search_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        transcript = await search_service.get_transcript(
            user_id=user_id,
            file_id=req_dto.file_id,
            start_index=req_dto.start_index,
            end_index=req_dto.end_index,
        )

        if transcript is None:
            return web.json_response(
                {"error": f"No transcript found for notebook {req_dto.file_id}"},
                status=404,
            )

        return web.json_response(
            WebTranscriptResponseVO(transcript=transcript).to_dict()
        )
    except Exception as err:
        logger.exception("Error fetching notebook transcript")
        return SupernoteError.uncaught(err).to_response()


@routes.get("/api/extended/dashboard")
async def handle_dashboard(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/dashboard
    # Purpose: Aggregated insights/visualization data for the current user.
    user_email = request["user"]
    user_service: UserService = request.app["user_service"]
    session_manager = request.app["session_manager"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    try:
        async with session_manager.session() as session:
            # Active .note notebooks owned by the user.
            notebook_count = (
                await session.execute(
                    select(func.count())
                    .select_from(UserFileDO)
                    .where(UserFileDO.user_id == user_id)
                    .where(UserFileDO.is_active == "Y")
                    .where(UserFileDO.is_folder == "N")
                    .where(UserFileDO.file_name.ilike("%.note"))
                )
            ).scalar_one()

            # Page-level coverage stats (scoped to the user's files via join).
            page_join = NotePageContentDO.__table__.join(
                UserFileDO.__table__, UserFileDO.id == NotePageContentDO.file_id
            )
            base_where = UserFileDO.user_id == user_id

            page_count = (
                await session.execute(
                    select(func.count()).select_from(page_join).where(base_where)
                )
            ).scalar_one()
            pages_with_text = (
                await session.execute(
                    select(func.count())
                    .select_from(page_join)
                    .where(base_where)
                    .where(NotePageContentDO.text_content.isnot(None))
                )
            ).scalar_one()
            pages_embedded = (
                await session.execute(
                    select(func.count())
                    .select_from(page_join)
                    .where(base_where)
                    .where(NotePageContentDO.embedding.isnot(None))
                )
            ).scalar_one()

            summary_count = (
                await session.execute(
                    select(func.count())
                    .select_from(SummaryDO)
                    .where(SummaryDO.user_id == user_id)
                    .where(SummaryDO.is_summary_group.is_(False))
                    .where(SummaryDO.is_deleted.is_(False))
                )
            ).scalar_one()

            # Pull page IDs + owning notebook for activity-over-time and ranking.
            rows = (
                await session.execute(
                    select(
                        NotePageContentDO.page_id,
                        NotePageContentDO.file_id,
                        UserFileDO.file_name,
                    )
                    .select_from(page_join)
                    .where(base_where)
                )
            ).all()

            # Tags across the user's summaries.
            tag_rows = (
                await session.execute(
                    select(SummaryDO.tags)
                    .where(SummaryDO.user_id == user_id)
                    .where(SummaryDO.is_deleted.is_(False))
                    .where(SummaryDO.tags.isnot(None))
                )
            ).all()
    except Exception as err:
        logger.exception("Error building dashboard stats")
        return SupernoteError.uncaught(err).to_response()

    # Bucket pages by inferred month + rank notebooks by page count.
    month_counter: Counter[str] = Counter()
    notebook_counter: Counter[int] = Counter()
    notebook_names: dict[int, str] = {}
    for page_id, file_id, file_name in rows:
        notebook_counter[file_id] += 1
        notebook_names[file_id] = file_name
        page_date = infer_page_date(page_id)
        if page_date:
            month_counter[page_date.strftime("%Y-%m")] += 1

    activity_by_month = [
        ActivityBucketVO(period=period, count=count)
        for period, count in sorted(month_counter.items())
    ]
    top_notebooks = [
        TopNotebookVO(
            file_id=file_id,
            file_name=notebook_names.get(file_id, str(file_id)),
            page_count=count,
        )
        for file_id, count in notebook_counter.most_common(8)
    ]

    tag_counter: Counter[str] = Counter()
    for (tags,) in tag_rows:
        if not tags:
            continue
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                tag_counter[tag] += 1
    top_tags = [
        TagCountVO(name=name, count=count) for name, count in tag_counter.most_common(12)
    ]

    return web.json_response(
        DashboardStatsVO(
            notebook_count=notebook_count,
            page_count=page_count,
            pages_with_text=pages_with_text,
            pages_embedded=pages_embedded,
            summary_count=summary_count,
            activity_by_month=activity_by_month,
            top_notebooks=top_notebooks,
            top_tags=top_tags,
        ).to_dict()
    )
