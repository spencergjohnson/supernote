"""Module for server-specific extension routes.

These are for APIs that are not part of the standard API offering, specific
to our new server.
"""

import logging
from collections import Counter

import aiohttp
from aiohttp import web
from sqlalchemy import func, select

from supernote.models.base import ProcessingStatus
from supernote.models.extended import (
    ActivityBucketVO,
    ChatRequestDTO,
    ChatResponseVO,
    ChatSourceVO,
    DashboardStatsVO,
    FileProcessingStatusDTO,
    FileProcessingStatusVO,
    ModelInfoVO,
    SearchResultVO,
    SetSystemConfigDTO,
    SystemConfigVO,
    SystemInfoVO,
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
from supernote.server.services.chat import ChatMessage, ChatService
from supernote.server.services.search import SearchService
from supernote.server.services.settings import SettingsService
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
                file_id=str(r.file_id),
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
            file_id=str(file_id),
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


@routes.post("/api/extended/chat")
async def handle_chat(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/chat
    # Purpose: RAG-based conversational Q&A over the user's notebooks.
    user_email = request["user"]

    try:
        data = await request.json()
        req_dto = ChatRequestDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid Request: {e}"}, status=400)

    user_service: UserService = request.app["user_service"]
    chat_service: ChatService = request.app["chat_service"]

    user_id = await user_service.get_user_id(user_email)
    if not user_id:
        return web.json_response({"error": "User not found"}, status=404)

    messages = [ChatMessage(role=m.role, content=m.content) for m in req_dto.messages]

    try:
        result = await chat_service.answer(
            user_id=user_id,
            query=req_dto.query,
            messages=messages,
            scope=req_dto.scope,
            top_k=req_dto.top_k,
        )
    except Exception as err:
        logger.exception("Error in chat handler")
        return SupernoteError.uncaught(err).to_response()

    sources = [
        ChatSourceVO(
            file_id=str(s.file_id),
            file_name=s.file_name,
            page_index=s.page_index,
            text_preview=s.text_preview,
            date=s.date,
        )
        for s in result.sources
    ]
    return web.json_response(
        ChatResponseVO(answer=result.answer, sources=sources).to_dict()
    )


@routes.get("/api/extended/system/info")
async def handle_system_info(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/info
    # Purpose: Return localMode + isAdmin so the frontend can gate admin UI.
    user_email = request["user"]
    user_service: UserService = request.app["user_service"]
    config = request.app["config"]

    user = await user_service.get_user_by_email(user_email)
    is_admin = bool(user and getattr(user, "is_admin", False))
    local_mode = bool(config.local_mode)

    return web.json_response(
        SystemInfoVO(local_mode=local_mode, is_admin=is_admin).to_dict()
    )


async def _check_admin(request: web.Request) -> bool:
    user_email = request.get("user", "")
    user_service: UserService = request.app["user_service"]
    user = await user_service.get_user_by_email(user_email)
    return bool(user and getattr(user, "is_admin", False))


def _classify_model(entry: dict) -> ModelInfoVO:
    """Normalize a llama-swap /v1/models entry into ModelInfoVO."""
    model_id = entry.get("id", "")
    caps_list: list[str] = []

    # llama-swap v225+ shape
    meta = entry.get("metadata") or {}
    caps = meta.get("capabilities") or []
    if isinstance(caps, list):
        caps_list = [str(c).lower() for c in caps]

    # Older / pass-through shape (architecture.input_modalities)
    arch = entry.get("architecture") or {}
    modalities = arch.get("input_modalities") or []
    if "image" in modalities:
        caps_list.append("vision")

    # Fallback: infer embedding from model id when capabilities metadata is
    # absent (e.g. older llama-swap versions or minimal configs).
    if "embedding" not in caps_list and "embed" in model_id.lower():
        caps_list.append("embedding")

    vision = "vision" in caps_list
    embedding = "embedding" in caps_list
    text = not embedding  # embedding models aren't chat/text models

    return ModelInfoVO(id=model_id, vision=vision, embedding=embedding, text=text)


@routes.get("/api/extended/system/models")
async def handle_system_models(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/models  (admin only)
    # Purpose: Proxy llama-swap /v1/models and normalize for the UI.
    if not await _check_admin(request):
        return web.json_response({"error": "Forbidden"}, status=403)

    config = request.app["config"]
    if not config.local_mode:
        return web.json_response({"error": "Not in local mode"}, status=400)

    url = config.local_llm_url.rstrip("/") + "/v1/models"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if not resp.ok:
                    return web.json_response(
                        {"error": f"llama-swap returned {resp.status}"}, status=502
                    )
                data = await resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch llama-swap models: {e}")
        return web.json_response({"error": f"Could not reach llama-swap: {e}"}, status=502)

    raw_models = data.get("data") or []
    models = [_classify_model(m) for m in raw_models]
    # Sort: vision first, then text, then embedding
    models.sort(key=lambda m: (not m.vision, m.embedding))

    return web.json_response({"models": [m.to_dict() for m in models]})


@routes.get("/api/extended/system/config")
async def handle_system_config_get(request: web.Request) -> web.Response:
    # Endpoint: GET /api/extended/system/config  (admin only)
    # Purpose: Return current model selection for each role.
    # ``vision``/``summary``/``chat``/``embedding`` are the *raw* stored
    # overrides (empty = inherit).  ``summaryEffective``/``chatEffective``
    # are the fully-resolved values in use right now.
    if not await _check_admin(request):
        return web.json_response({"error": "Forbidden"}, status=403)

    config = request.app["config"]
    return web.json_response(
        SystemConfigVO(
            vision=config.local_llm_model,
            summary=config.local_summary_model,
            chat=config.local_chat_model,
            embedding=config.local_embedding_model,
            summary_effective=config.summary_model,
            chat_effective=config.chat_model,
            local_mode=config.local_mode,
            llm_url=config.local_llm_url if config.local_mode else "",
        ).to_dict()
    )


@routes.post("/api/extended/system/config")
async def handle_system_config_set(request: web.Request) -> web.Response:
    # Endpoint: POST /api/extended/system/config  (admin only)
    # Purpose: Persist model role selections and apply to running config.
    if not await _check_admin(request):
        return web.json_response({"error": "Forbidden"}, status=403)

    config = request.app["config"]
    if not config.local_mode:
        return web.json_response({"error": "Model selection only available in local mode"}, status=400)

    try:
        data = await request.json()
        dto = SetSystemConfigDTO.from_dict(data)
    except Exception as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)

    settings_service: SettingsService = request.app["settings_service"]

    # vision / embedding: only update when explicitly provided (non-None).
    if dto.vision is not None:
        await settings_service.set_role_model("vision", dto.vision)
        config.local_llm_model = dto.vision

    # summary / chat: empty string is a valid value meaning "inherit from
    # fallback chain"; only skip when the field is absent (None).
    if dto.summary is not None:
        await settings_service.set_role_model("summary", dto.summary)
        config.local_summary_model = dto.summary

    if dto.chat is not None:
        await settings_service.set_role_model("chat", dto.chat)
        config.local_chat_model = dto.chat

    if dto.embedding is not None:
        await settings_service.set_role_model("embedding", dto.embedding)
        config.local_embedding_model = dto.embedding

    return web.json_response(
        SystemConfigVO(
            vision=config.local_llm_model,
            summary=config.local_summary_model,
            chat=config.local_chat_model,
            embedding=config.local_embedding_model,
            summary_effective=config.summary_model,
            chat_effective=config.chat_model,
            local_mode=config.local_mode,
            llm_url=config.local_llm_url,
        ).to_dict()
    )
