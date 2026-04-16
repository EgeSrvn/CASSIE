from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Optional, Any

from backend.api.database.db_init import get_db_connection
from backend.api.models.forum_model import (
    ForumAnswerCreate,
    ForumAnswerResponse,
    ForumAuthorResponse,
    ForumCommentCreate,
    ForumCommentResponse,
    ForumThreadCreate,
    ForumThreadDetailResponse,
    ForumThreadListResponse,
    ForumThreadSummaryResponse,
)
from backend.api.services.forum_moderation import validate_forum_text
from backend.api.services.minio_client import MinIOClient
from backend.api.services.user_service import get_user_by_id
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def _resolved_avatar_url(user) -> Optional[str]:
    stored_avatar = getattr(user, "avatar_url", None)
    if not stored_avatar:
        return None

    normalized = str(stored_avatar).strip()
    if not normalized:
        return None

    if normalized.startswith(("http://", "https://", "data:", "/api/auth/profile/avatar/")):
        return normalized

    return f"/api/auth/profile/avatar/{user.id}"


def _build_author(user_id: int) -> ForumAuthorResponse:
    user = get_user_by_id(user_id)
    if user is None:
        return ForumAuthorResponse(
            id=user_id,
            username="unknown",
            display_name="Unknown user",
            affiliation=None,
            avatar_url=None,
        )

    return ForumAuthorResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        affiliation=user.affiliation,
        avatar_url=_resolved_avatar_url(user),
    )


@dataclass
class _ThreadRow:
    id: int
    user_id: int
    title: str
    body: str
    image_keys: list[str]
    view_count: int
    answer_count: int
    comment_count: int
    created_at: object
    updated_at: object
    last_activity_at: object


def _parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


def _build_forum_media_url(user_id: int, key: str) -> str:
    from urllib.parse import quote_plus

    return f"/api/forum/media/{user_id}?key={quote_plus(key)}"


def _thread_row_to_summary(row) -> ForumThreadSummaryResponse:
    thread = _ThreadRow(
        id=row[0],
        user_id=row[1],
        title=row[2],
        body=row[3],
        image_keys=_parse_json_list(row[4]),
        view_count=row[5],
        answer_count=row[6],
        comment_count=row[7],
        created_at=row[8],
        updated_at=row[9],
        last_activity_at=row[10],
    )
    return ForumThreadSummaryResponse(
        id=thread.id,
        user_id=thread.user_id,
        title=thread.title,
        body=thread.body,
        image_urls=[_build_forum_media_url(thread.user_id, key) for key in thread.image_keys],
        view_count=thread.view_count,
        answer_count=thread.answer_count,
        comment_count=thread.comment_count,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        last_activity_at=thread.last_activity_at,
        author=_build_author(thread.user_id),
    )


def _comment_row_to_response(row) -> ForumCommentResponse:
    return ForumCommentResponse(
        id=row[0],
        thread_id=row[1],
        answer_id=row[2],
        parent_comment_id=row[3],
        user_id=row[4],
        body=row[5],
        created_at=row[6],
        updated_at=row[7],
        author=_build_author(row[4]),
    )


def _answer_row_to_response(row) -> ForumAnswerResponse:
    return ForumAnswerResponse(
        id=row[0],
        thread_id=row[1],
        user_id=row[2],
        body=row[3],
        created_at=row[4],
        updated_at=row[5],
        author=_build_author(row[2]),
        comments=[],
    )


def list_forum_threads(search_query: Optional[str] = None, page: int = 1, per_page: int = 20) -> ForumThreadListResponse:
    safe_page = max(page, 1)
    safe_per_page = min(max(per_page, 1), 50)
    offset = (safe_page - 1) * safe_per_page

    where_clause = ""
    params: list[object] = []
    count_params: list[object] = []
    if search_query and search_query.strip():
        like_query = f"%{search_query.strip()}%"
        where_clause = "WHERE t.title ILIKE %s OR t.body ILIKE %s"
        params.extend([like_query, like_query])
        count_params.extend([like_query, like_query])

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM forum_threads t
                {where_clause}
                """,
                count_params,
            )
            total = int(cur.fetchone()[0])

            params.extend([safe_per_page, offset])
            cur.execute(
                f"""
                SELECT
                    t.id,
                    t.user_id,
                    t.title,
                    t.body,
                    t.image_keys,
                    t.view_count,
                    COALESCE(answer_stats.answer_count, 0) AS answer_count,
                    COALESCE(comment_stats.comment_count, 0) AS comment_count,
                    t.created_at,
                    t.updated_at,
                    GREATEST(
                        t.created_at,
                        COALESCE(answer_stats.latest_answer_at, t.created_at),
                        COALESCE(comment_stats.latest_comment_at, t.created_at)
                    ) AS last_activity_at
                FROM forum_threads t
                LEFT JOIN (
                    SELECT
                        thread_id,
                        COUNT(*) AS answer_count,
                        MAX(updated_at) AS latest_answer_at
                    FROM forum_answers
                    GROUP BY thread_id
                ) AS answer_stats ON answer_stats.thread_id = t.id
                LEFT JOIN (
                    SELECT
                        thread_id,
                        COUNT(*) AS comment_count,
                        MAX(updated_at) AS latest_comment_at
                    FROM forum_comments
                    GROUP BY thread_id
                ) AS comment_stats ON comment_stats.thread_id = t.id
                {where_clause}
                ORDER BY last_activity_at DESC, t.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )

            items = [_thread_row_to_summary(row) for row in cur.fetchall()]
            return ForumThreadListResponse(
                items=items,
                total=total,
                page=safe_page,
                per_page=safe_per_page,
            )
        finally:
            cur.close()


def create_forum_thread(user_id: int, payload: ForumThreadCreate) -> ForumThreadSummaryResponse:
    validate_forum_text(payload.title, payload.body)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO forum_threads (user_id, title, body, view_count)
                VALUES (%s, %s, %s, 0)
                RETURNING
                    id,
                    user_id,
                    title,
                    body,
                    image_keys,
                    view_count,
                    0 AS answer_count,
                    0 AS comment_count,
                    created_at,
                    updated_at,
                    created_at AS last_activity_at
                """,
                (user_id, payload.title.strip(), payload.body.strip()),
            )
            row = cur.fetchone()
            conn.commit()
            return _thread_row_to_summary(row)
        except Exception:
            conn.rollback()
            logger.exception("Failed to create forum thread")
            raise
        finally:
            cur.close()


def get_forum_thread(thread_id: int, increment_view_count: bool = True) -> Optional[ForumThreadDetailResponse]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            if increment_view_count:
                cur.execute(
                    """
                    UPDATE forum_threads
                    SET view_count = view_count + 1, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (thread_id,),
                )
                conn.commit()

            cur.execute(
                """
                SELECT
                    t.id,
                    t.user_id,
                    t.title,
                    t.body,
                    t.image_keys,
                    t.view_count,
                    COALESCE(answer_stats.answer_count, 0) AS answer_count,
                    COALESCE(comment_stats.comment_count, 0) AS comment_count,
                    t.created_at,
                    t.updated_at,
                    GREATEST(
                        t.created_at,
                        COALESCE(answer_stats.latest_answer_at, t.created_at),
                        COALESCE(comment_stats.latest_comment_at, t.created_at)
                    ) AS last_activity_at
                FROM forum_threads t
                LEFT JOIN (
                    SELECT
                        thread_id,
                        COUNT(*) AS answer_count,
                        MAX(updated_at) AS latest_answer_at
                    FROM forum_answers
                    GROUP BY thread_id
                ) AS answer_stats ON answer_stats.thread_id = t.id
                LEFT JOIN (
                    SELECT
                        thread_id,
                        COUNT(*) AS comment_count,
                        MAX(updated_at) AS latest_comment_at
                    FROM forum_comments
                    GROUP BY thread_id
                ) AS comment_stats ON comment_stats.thread_id = t.id
                WHERE t.id = %s
                """,
                (thread_id,),
            )
            thread_row = cur.fetchone()
            if not thread_row:
                return None

            cur.execute(
                """
                SELECT id, thread_id, user_id, body, created_at, updated_at
                FROM forum_answers
                WHERE thread_id = %s
                ORDER BY created_at ASC
                """,
                (thread_id,),
            )
            answers = [_answer_row_to_response(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, thread_id, answer_id, parent_comment_id, user_id, body, created_at, updated_at
                FROM forum_comments
                WHERE thread_id = %s
                ORDER BY created_at ASC
                """,
                (thread_id,),
            )
            comments = [_comment_row_to_response(row) for row in cur.fetchall()]
        finally:
            cur.close()

    comment_map = {comment.id: comment for comment in comments}
    comments_by_answer: dict[int, list[ForumCommentResponse]] = defaultdict(list)
    comments_by_parent: dict[int, list[ForumCommentResponse]] = defaultdict(list)
    thread_comments: list[ForumCommentResponse] = []
    for comment in comments:
        if comment.parent_comment_id is not None:
            comments_by_parent[comment.parent_comment_id].append(comment)
        elif comment.answer_id is None:
            thread_comments.append(comment)
        else:
            comments_by_answer[comment.answer_id].append(comment)

    def attach_replies(comment: ForumCommentResponse) -> ForumCommentResponse:
        if comment.parent_comment_id is not None:
            parent_comment = comment_map.get(comment.parent_comment_id)
            if parent_comment is not None:
                comment.parent_comment_preview = {
                    "id": parent_comment.id,
                    "author_name": parent_comment.author.display_name or parent_comment.author.username,
                    "body": parent_comment.body,
                }
        comment.replies = [attach_replies(reply) for reply in comments_by_parent.get(comment.id, [])]
        return comment

    thread_comments = [attach_replies(comment) for comment in thread_comments]

    for answer in answers:
        answer.comments = [attach_replies(comment) for comment in comments_by_answer.get(answer.id, [])]

    summary = _thread_row_to_summary(thread_row)
    return ForumThreadDetailResponse(
        **summary.model_dump(),
        thread_comments=thread_comments,
        answers=answers,
    )


def create_forum_answer(user_id: int, thread_id: int, payload: ForumAnswerCreate) -> Optional[ForumAnswerResponse]:
    validate_forum_text(payload.body)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM forum_threads WHERE id = %s", (thread_id,))
            if cur.fetchone() is None:
                return None

            cur.execute(
                """
                INSERT INTO forum_answers (thread_id, user_id, body)
                VALUES (%s, %s, %s)
                RETURNING id, thread_id, user_id, body, created_at, updated_at
                """,
                (thread_id, user_id, payload.body.strip()),
            )
            row = cur.fetchone()
            conn.commit()
            return _answer_row_to_response(row)
        except Exception:
            conn.rollback()
            logger.exception("Failed to create forum answer")
            raise
        finally:
            cur.close()


def create_forum_comment(
    user_id: int,
    thread_id: int,
    payload: ForumCommentCreate,
    answer_id: Optional[int] = None,
) -> Optional[ForumCommentResponse]:
    validate_forum_text(payload.body)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM forum_threads WHERE id = %s", (thread_id,))
            if cur.fetchone() is None:
                return None

            if answer_id is not None:
                cur.execute(
                    "SELECT 1 FROM forum_answers WHERE id = %s AND thread_id = %s",
                    (answer_id, thread_id),
                )
                if cur.fetchone() is None:
                    return None

            parent_comment_id = payload.parent_comment_id
            if parent_comment_id is not None:
                cur.execute(
                    """
                    SELECT answer_id
                    FROM forum_comments
                    WHERE id = %s AND thread_id = %s
                    """,
                    (parent_comment_id, thread_id),
                )
                parent_comment_row = cur.fetchone()
                if parent_comment_row is None:
                    return None

                parent_answer_id = parent_comment_row[0]
                if answer_id is None and parent_answer_id is not None:
                    return None
                if answer_id is not None and parent_answer_id != answer_id:
                    return None

            cur.execute(
                """
                INSERT INTO forum_comments (thread_id, answer_id, parent_comment_id, user_id, body)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, thread_id, answer_id, parent_comment_id, user_id, body, created_at, updated_at
                """,
                (thread_id, answer_id, parent_comment_id, user_id, payload.body.strip()),
            )
            row = cur.fetchone()
            conn.commit()
            return _comment_row_to_response(row)
        except Exception:
            conn.rollback()
            logger.exception("Failed to create forum comment")
            raise
        finally:
            cur.close()


def get_forum_thread_summary(thread_id: int) -> Optional[ForumThreadSummaryResponse]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                    t.id,
                    t.user_id,
                    t.title,
                    t.body,
                    t.image_keys,
                    t.view_count,
                    COALESCE(answer_stats.answer_count, 0) AS answer_count,
                    COALESCE(comment_stats.comment_count, 0) AS comment_count,
                    t.created_at,
                    t.updated_at,
                    GREATEST(
                        t.created_at,
                        COALESCE(answer_stats.latest_answer_at, t.created_at),
                        COALESCE(comment_stats.latest_comment_at, t.created_at)
                    ) AS last_activity_at
                FROM forum_threads t
                LEFT JOIN (
                    SELECT thread_id, COUNT(*) AS answer_count, MAX(updated_at) AS latest_answer_at
                    FROM forum_answers
                    GROUP BY thread_id
                ) AS answer_stats ON answer_stats.thread_id = t.id
                LEFT JOIN (
                    SELECT thread_id, COUNT(*) AS comment_count, MAX(updated_at) AS latest_comment_at
                    FROM forum_comments
                    GROUP BY thread_id
                ) AS comment_stats ON comment_stats.thread_id = t.id
                WHERE t.id = %s
                """,
                (thread_id,),
            )
            row = cur.fetchone()
            return _thread_row_to_summary(row) if row else None
        finally:
            cur.close()


def append_thread_image_keys(thread_id: int, user_id: int, image_keys: list[str]) -> Optional[ForumThreadSummaryResponse]:
    if not image_keys:
        return get_forum_thread_summary(thread_id)

    image_keys_json = json.dumps(image_keys)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE forum_threads
                SET image_keys = COALESCE(image_keys, '[]'::jsonb) || %s::jsonb
                WHERE id = %s AND user_id = %s
                """,
                (image_keys_json, thread_id, user_id),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
            return get_forum_thread_summary(thread_id)
        except Exception:
            conn.rollback()
            logger.exception("Failed to append forum thread image keys")
            raise
        finally:
            cur.close()


def get_forum_thread_owner(thread_id: int) -> Optional[int]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM forum_threads WHERE id = %s", (thread_id,))
            row = cur.fetchone()
            return int(row[0]) if row else None
        finally:
            cur.close()


def delete_forum_thread(thread_id: int, user_id: int) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM forum_threads WHERE id = %s AND user_id = %s", (thread_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            logger.exception("Failed to delete forum thread")
            raise
        finally:
            cur.close()


def delete_forum_comment(comment_id: int, user_id: int) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM forum_comments WHERE id = %s AND user_id = %s", (comment_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            logger.exception("Failed to delete forum comment")
            raise
        finally:
            cur.close()
