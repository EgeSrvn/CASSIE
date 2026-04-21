from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.api.database.db_init import get_db_connection
from backend.api.models.engagement_model import ReportCreate, ReportTargetType, VoteType
from backend.api.services.user_service import get_user_by_id, set_user_suspension


_VOTE_TABLE_CONFIG = {
    ReportTargetType.PIPELINE: ("pipeline_votes", "pipeline_id"),
    ReportTargetType.FORUM_THREAD: ("forum_thread_votes", "thread_id"),
    ReportTargetType.FORUM_COMMENT: ("forum_comment_votes", "comment_id"),
}

_TARGET_EXISTS_QUERY = {
    ReportTargetType.PIPELINE: "SELECT 1 FROM pipelines WHERE id = %s",
    ReportTargetType.FORUM_THREAD: "SELECT 1 FROM forum_threads WHERE id = %s",
    ReportTargetType.FORUM_COMMENT: "SELECT 1 FROM forum_comments WHERE id = %s",
}


def _normalize_target_type(target_type: str | ReportTargetType) -> ReportTargetType:
    if isinstance(target_type, ReportTargetType):
        return target_type
    return ReportTargetType(str(target_type))


def _vote_table_parts(target_type: str | ReportTargetType) -> tuple[str, str]:
    normalized = _normalize_target_type(target_type)
    return _VOTE_TABLE_CONFIG[normalized]


def _target_exists(cur, target_type: ReportTargetType, target_id: int) -> bool:
    cur.execute(_TARGET_EXISTS_QUERY[target_type], (target_id,))
    return cur.fetchone() is not None


def get_vote_summaries(
    target_type: str | ReportTargetType,
    target_ids: list[int],
    *,
    user_id: Optional[int] = None,
) -> dict[int, dict[str, Any]]:
    normalized = _normalize_target_type(target_type)
    table_name, id_column = _vote_table_parts(normalized)
    unique_ids = sorted({int(item_id) for item_id in target_ids if item_id is not None})
    if not unique_ids:
        return {}

    summaries = {
        item_id: {
            "upvote_count": 0,
            "downvote_count": 0,
            "score": 0,
            "user_vote": None,
        }
        for item_id in unique_ids
    }

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                SELECT
                    {id_column},
                    COUNT(*) FILTER (WHERE vote_type = 'upvote') AS upvote_count,
                    COUNT(*) FILTER (WHERE vote_type = 'downvote') AS downvote_count
                FROM {table_name}
                WHERE {id_column} = ANY(%s)
                GROUP BY {id_column}
                """,
                (unique_ids,),
            )
            for row in cur.fetchall():
                item_id = int(row[0])
                upvote_count = int(row[1] or 0)
                downvote_count = int(row[2] or 0)
                summaries[item_id] = {
                    "upvote_count": upvote_count,
                    "downvote_count": downvote_count,
                    "score": upvote_count - downvote_count,
                    "user_vote": None,
                }

            if user_id is not None:
                cur.execute(
                    f"""
                    SELECT {id_column}, vote_type
                    FROM {table_name}
                    WHERE user_id = %s AND {id_column} = ANY(%s)
                    """,
                    (user_id, unique_ids),
                )
                for row in cur.fetchall():
                    item_id = int(row[0])
                    vote_type = str(row[1] or "").strip().lower()
                    if vote_type in {VoteType.UPVOTE.value, VoteType.DOWNVOTE.value}:
                        summaries[item_id]["user_vote"] = vote_type
        finally:
            cur.close()

    return summaries


def set_vote(
    *,
    target_type: str | ReportTargetType,
    target_id: int,
    user_id: int,
    vote_type: VoteType,
) -> dict[str, Any]:
    normalized = _normalize_target_type(target_type)
    table_name, id_column = _vote_table_parts(normalized)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            if not _target_exists(cur, normalized, target_id):
                raise ValueError(f"{normalized.value.replace('_', ' ').title()} {target_id} not found")

            cur.execute(
                f"""
                SELECT vote_type
                FROM {table_name}
                WHERE {id_column} = %s AND user_id = %s
                """,
                (target_id, user_id),
            )
            existing_row = cur.fetchone()
            existing_vote = str(existing_row[0]).strip().lower() if existing_row and existing_row[0] else None

            if existing_vote == vote_type.value:
                cur.execute(
                    f"DELETE FROM {table_name} WHERE {id_column} = %s AND user_id = %s",
                    (target_id, user_id),
                )
                conn.commit()
                return get_vote_summaries(normalized, [target_id], user_id=user_id).get(
                    target_id,
                    {"upvote_count": 0, "downvote_count": 0, "score": 0, "user_vote": None},
                )

            cur.execute(
                f"""
                INSERT INTO {table_name} ({id_column}, user_id, vote_type)
                VALUES (%s, %s, %s)
                ON CONFLICT ({id_column}, user_id)
                DO UPDATE SET vote_type = EXCLUDED.vote_type, updated_at = NOW()
                """,
                (target_id, user_id, vote_type.value),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    return get_vote_summaries(normalized, [target_id], user_id=user_id).get(
        target_id,
        {"upvote_count": 0, "downvote_count": 0, "score": 0, "user_vote": vote_type.value},
    )


def create_report(
    *,
    target_type: str | ReportTargetType,
    target_id: int,
    reporter_user_id: int,
    payload: ReportCreate,
) -> dict[str, Any]:
    normalized = _normalize_target_type(target_type)
    reason = payload.reason.strip()
    details = payload.details.strip() if payload.details else None

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            if not _target_exists(cur, normalized, target_id):
                raise ValueError(f"{normalized.value.replace('_', ' ').title()} {target_id} not found")

            cur.execute(
                """
                INSERT INTO moderation_reports (reporter_user_id, target_type, target_id, reason, details)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (reporter_user_id, target_type, target_id)
                DO UPDATE SET reason = EXCLUDED.reason, details = EXCLUDED.details, status = 'open', updated_at = NOW()
                RETURNING id, reporter_user_id, target_type, target_id, reason, details, status, created_at, updated_at
                """,
                (reporter_user_id, normalized.value, target_id, reason, details),
            )
            row = cur.fetchone()
            conn.commit()
            return {
                "id": int(row[0]),
                "reporter_user_id": int(row[1]),
                "target_type": str(row[2]),
                "target_id": int(row[3]),
                "reason": str(row[4]),
                "details": row[5],
                "status": str(row[6]),
                "created_at": row[7],
                "updated_at": row[8],
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def list_reports_for_admin() -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                    r.id,
                    r.reporter_user_id,
                    r.target_type,
                    r.target_id,
                    r.reason,
                    r.details,
                    r.status,
                    r.created_at,
                    u.username,
                    p.user_id,
                    p.name,
                    ft.user_id,
                    ft.title,
                    fc.user_id,
                    fc.body
                FROM moderation_reports r
                JOIN users u ON u.id = r.reporter_user_id
                LEFT JOIN pipelines p ON r.target_type = 'pipeline' AND p.id = r.target_id
                LEFT JOIN forum_threads ft ON r.target_type = 'forum_thread' AND ft.id = r.target_id
                LEFT JOIN forum_comments fc ON r.target_type = 'forum_comment' AND fc.id = r.target_id
                WHERE r.status <> 'dismissed'
                ORDER BY
                    CASE WHEN r.status = 'open' THEN 0 ELSE 1 END,
                    r.created_at DESC
                """
            )

            rows: list[dict[str, Any]] = []
            for row in cur.fetchall():
                reporter_user = get_user_by_id(int(row[1]))
                target_type = str(row[2])
                target_label = "-"
                preview = "-"
                owner_user_id = None
                if target_type == ReportTargetType.PIPELINE.value:
                    target_label = f"Pipeline #{row[3]}"
                    owner_user_id = int(row[9]) if row[9] is not None else None
                    preview = str(row[10] or "-")
                elif target_type == ReportTargetType.FORUM_THREAD.value:
                    target_label = f"Forum Thread #{row[3]}"
                    owner_user_id = int(row[11]) if row[11] is not None else None
                    preview = str(row[12] or "-")
                elif target_type == ReportTargetType.FORUM_COMMENT.value:
                    target_label = f"Forum Comment #{row[3]}"
                    owner_user_id = int(row[13]) if row[13] is not None else None
                    preview = str(row[14] or "-")

                owner_user = get_user_by_id(owner_user_id) if owner_user_id is not None else None

                rows.append(
                    {
                        "id": int(row[0]),
                        "reporter_user_id": int(row[1]),
                        "reporter_username": str(row[8]),
                        "reporter_display_name": getattr(reporter_user, "display_name", None),
                        "target_type": target_type,
                        "target_id": int(row[3]),
                        "target_label": target_label,
                        "reason": str(row[4]),
                        "details": row[5],
                        "status": str(row[6]),
                        "created_at": row[7],
                        "preview": preview,
                        "target_owner_user_id": owner_user_id,
                        "target_owner_username": getattr(owner_user, "username", None),
                        "target_owner_display_name": getattr(owner_user, "display_name", None),
                    }
                )
            return rows
        finally:
            cur.close()


def update_report_status(report_id: int, status_value: str) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE moderation_reports
                SET status = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (status_value, report_id),
            )
            updated = cur.rowcount > 0
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def moderate_report_target(report_id: int) -> dict[str, Any]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT target_type, target_id
                FROM moderation_reports
                WHERE id = %s
                """,
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Report {report_id} not found")

            target_type = ReportTargetType(str(row[0]))
            target_id = int(row[1])

            if target_type == ReportTargetType.PIPELINE:
                cur.execute(
                    """
                    UPDATE pipelines
                    SET is_shared = FALSE, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (target_id,),
                )
                action_label = "Pipeline removed from community sharing"
            elif target_type == ReportTargetType.FORUM_THREAD:
                cur.execute("DELETE FROM forum_threads WHERE id = %s", (target_id,))
                action_label = "Forum thread deleted"
            elif target_type == ReportTargetType.FORUM_COMMENT:
                cur.execute("DELETE FROM forum_comments WHERE id = %s", (target_id,))
                action_label = "Forum comment deleted"
            else:
                raise ValueError(f"Unsupported target type: {target_type.value}")

            if cur.rowcount <= 0:
                raise ValueError(f"Reported target {target_type.value} #{target_id} was not found")

            cur.execute(
                """
                UPDATE moderation_reports
                SET status = 'resolved_removed', updated_at = NOW()
                WHERE target_type = %s AND target_id = %s
                """,
                (target_type.value, target_id),
            )
            conn.commit()
            return {"target_type": target_type.value, "target_id": target_id, "message": action_label}
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def suspend_report_target_owner(report_id: int, *, duration_value: int, duration_unit: str) -> dict[str, Any]:
    if duration_value <= 0:
        raise ValueError("Suspension duration must be at least 1")
    normalized_unit = str(duration_unit or "").strip().lower()
    if normalized_unit not in {"hours", "days", "weeks"}:
        raise ValueError("Suspension unit must be hours, days, or weeks")

    reports = {report["id"]: report for report in list_reports_for_admin()}
    report = reports.get(report_id)
    if not report:
        raise ValueError(f"Report {report_id} not found")

    owner_user_id = report.get("target_owner_user_id")
    if owner_user_id is None:
        raise ValueError("The reported item no longer has an owning user")

    if normalized_unit == "hours":
        delta = timedelta(hours=duration_value)
    elif normalized_unit == "days":
        delta = timedelta(days=duration_value)
    else:
        delta = timedelta(weeks=duration_value)

    suspended_until = datetime.now(timezone.utc) + delta
    reason = f"Admin moderation action from report #{report_id}: {report.get('reason', 'policy violation')}"
    updated_user = set_user_suspension(int(owner_user_id), suspended_until, reason)
    if updated_user is None:
        raise ValueError(f"User {owner_user_id} not found")

    update_report_status(report_id, "resolved_suspended")
    return {
        "user_id": int(owner_user_id),
        "username": updated_user.username,
        "suspended_until": suspended_until,
    }
