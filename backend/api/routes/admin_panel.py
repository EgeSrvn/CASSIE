"""
Secret admin panel routes for CASSIE.

This panel is intentionally server-rendered and mounted outside the normal API
prefix so it can live behind a non-obvious path.
"""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, status, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.api.database.db_init import check_database_health, get_db_connection
from backend.api.models.job_model import ExecutionStatus, JobExecutionUpdate, JobStatus, JobUpdate
from backend.api.services.auth_service import (
    create_scoped_token,
    decode_access_token,
    verify_password,
)
from backend.api.services.engagement_service import (
    list_reports_for_admin,
    moderate_report_target,
    suspend_report_target_owner,
    update_report_status,
)
from backend.api.services.job_execution_service import get_executions_by_job, update_job_execution
from backend.api.services.job_service import get_job_by_id, update_job
from backend.api.services.invitation_code_service import create_invitation_code, list_invitation_codes
from backend.api.services.kubernetes_manager import (
    get_kubernetes_pipeline_runner,
    kubernetes_is_available,
)
from backend.api.services.runtime_estimator_service import APP_CONFIG_PATH
from backend.api.services.user_service import ensure_admin_user, get_user_by_id, get_user_by_username, set_user_admin, update_user_password
from backend.api.services import demo_service as _demo_svc
from backend.api.utils.config_loader import get_config
from backend.api.services.workflow_service import get_workflow_by_id
from tool_registry import get_tool_registry

config = get_config()
router = APIRouter(include_in_schema=False)


def _render_page(*, title: str, body: str, script: str = "") -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #efe6da;
        --bg-2: #f8f4ec;
        --panel: #fffdf8;
        --ink: #1f1a16;
        --muted: #6b5f54;
        --line: #d8c8b6;
        --accent: #9a3412;
        --accent-2: #0f766e;
        --accent-ink: #fffaf5;
        --danger: #b42318;
        --warn: #b54708;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        background:
          radial-gradient(circle at top left, #f4dac0 0, transparent 28%),
          radial-gradient(circle at top right, #dcefe9 0, transparent 25%),
          linear-gradient(180deg, var(--bg-2) 0%, var(--bg) 100%);
        color: var(--ink);
        min-height: 100vh;
      }}
      .wrap {{
        width: min(1320px, calc(100vw - 2rem));
        margin: 2rem auto 4rem;
      }}
      .panel {{
        background: rgba(255, 253, 248, 0.92);
        border: 1px solid var(--line);
        border-radius: 24px;
        padding: 1.5rem;
        box-shadow: 0 22px 60px rgba(71, 49, 24, 0.10);
        backdrop-filter: blur(6px);
      }}
      h1, h2, h3 {{ margin-top: 0; }}
      h1 {{ font-size: clamp(2rem, 4vw, 3rem); margin-bottom: 0.5rem; }}
      h2 {{ font-size: 1.4rem; margin-bottom: 0.6rem; }}
      h3 {{ font-size: 1rem; margin-bottom: 0.5rem; }}
      p {{ color: var(--muted); line-height: 1.55; }}
      label {{
        display: block;
        margin-bottom: 0.35rem;
        font-weight: 600;
      }}
      input, select {{
        width: 100%;
        padding: 0.8rem 0.9rem;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: white;
        margin-bottom: 1rem;
        font: inherit;
      }}
      button, .button-link {{
        display: inline-block;
        border: 0;
        border-radius: 999px;
        padding: 0.75rem 1.15rem;
        background: var(--accent);
        color: var(--accent-ink);
        cursor: pointer;
        text-decoration: none;
        font: inherit;
      }}
      .secondary {{
        background: transparent;
        color: var(--ink);
        border: 1px solid var(--line);
      }}
      .danger {{
        background: var(--danger);
        color: white;
      }}
      .small-button {{
        padding: 0.45rem 0.8rem;
        font-size: 0.88rem;
      }}
      .row {{
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        align-items: center;
      }}
      .tab-nav {{
        display: flex;
        gap: 0.65rem;
        flex-wrap: wrap;
        margin: 1.25rem 0 1.5rem;
      }}
      .tab-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 0.65rem 0.95rem;
        text-decoration: none;
        color: var(--ink);
        background: rgba(255, 255, 255, 0.72);
      }}
      .tab-link.active {{
        background: var(--accent);
        color: var(--accent-ink);
        border-color: var(--accent);
      }}
      .grid {{
        display: grid;
        gap: 1rem;
      }}
      .grid.cols-2 {{
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      }}
      .grid.cols-3 {{
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      }}
      .job-layout {{
        display: grid;
        gap: 1rem;
        grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
        align-items: start;
      }}
      .job-layout > * {{
        min-width: 0;
      }}
      .sticky {{
        position: sticky;
        top: 1rem;
      }}
      .section {{
        margin-top: 1.5rem;
        padding-top: 1.25rem;
        border-top: 1px solid var(--line);
      }}
      .notice {{
        border-radius: 12px;
        padding: 0.85rem 1rem;
        margin-bottom: 1rem;
        border: 1px solid var(--line);
        background: #f6fbfa;
      }}
      .notice.error {{
        border-color: #efc2bb;
        background: #fff3f1;
        color: var(--danger);
      }}
      .cards {{
        display: grid;
        gap: 0.9rem;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        margin-top: 1rem;
      }}
      .card {{
        padding: 1rem;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(249,245,238,0.9));
      }}
      .card strong {{
        display: block;
        font-size: 1.6rem;
        margin-bottom: 0.25rem;
      }}
      .meta {{
        display: grid;
        gap: 0.75rem;
        margin: 1rem 0 1.5rem;
      }}
      .kv {{
        display: grid;
        gap: 0.45rem;
        grid-template-columns: minmax(9rem, 12rem) minmax(0, 1fr);
        margin: 1rem 0;
      }}
      .kv div {{
        padding: 0.25rem 0;
        border-bottom: 1px dashed #eadfd1;
      }}
      .meta strong {{
        display: inline-block;
        min-width: 10rem;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 0.6rem;
        font-size: 0.95rem;
      }}
      th, td {{
        text-align: left;
        padding: 0.65rem 0.55rem;
        border-bottom: 1px solid #eadfd1;
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }}
      pre {{
        margin: 0;
        padding: 1rem;
        border-radius: 16px;
        background: #f7f0e6;
        border: 1px solid #eadfd1;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: "SFMono-Regular", Menlo, Consolas, monospace;
        font-size: 0.86rem;
        line-height: 1.45;
      }}
      code {{
        padding: 0.1rem 0.35rem;
        border-radius: 6px;
        background: #f2ece3;
      }}
      details {{
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(255,255,255,0.6);
        padding: 0.9rem 1rem;
        min-width: 0;
        overflow: hidden;
      }}
      details + details {{
        margin-top: 0.85rem;
      }}
      summary {{
        cursor: pointer;
        font-weight: 700;
      }}
      .inline-form {{
        display: inline-flex;
        margin: 0;
        align-items: center;
        gap: 0.45rem;
      }}
      .inline-form.wrap {{
        flex-wrap: wrap;
      }}
      .inline-form input[type="hidden"] {{
        display: none;
      }}
      .inline-form input,
      .inline-form select {{
        width: auto;
        margin-bottom: 0;
      }}
      .input-compact {{
        min-width: 5rem;
        padding: 0.45rem 0.65rem;
        font-size: 0.88rem;
      }}
      .pill {{
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        background: #f2ece3;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
        font-size: 0.82rem;
      }}
      .status-running {{ color: var(--accent-2); font-weight: 700; }}
      .status-failed {{ color: var(--danger); font-weight: 700; }}
      .status-pending {{ color: var(--warn); font-weight: 700; }}
      .status-completed {{ color: #166534; font-weight: 700; }}
      .status-cancelled {{ color: var(--danger); font-weight: 700; }}
      .status-reviewed,
      .status-resolved_removed,
      .status-resolved_suspended {{ color: #166534; font-weight: 700; }}
      .status-dismissed {{ color: var(--muted); font-weight: 700; }}
      .mono {{ font-family: "SFMono-Regular", Menlo, Consolas, monospace; }}
      .stack {{
        display: grid;
        gap: 0.85rem;
        min-width: 0;
      }}
      .subpanel {{
        padding: 1rem;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(255,255,255,0.72);
        min-width: 0;
        overflow: hidden;
      }}
      .muted {{
        color: var(--muted);
      }}
      .button-row {{
        display: flex;
        gap: 0.6rem;
        flex-wrap: wrap;
        align-items: center;
      }}
      a.secret-link {{ color: var(--accent); text-decoration: none; }}
      @media (max-width: 768px) {{
        .wrap {{ width: min(100vw - 1rem, 1320px); margin-top: 1rem; }}
        .panel {{ padding: 1rem; border-radius: 18px; }}
        .job-layout {{ grid-template-columns: 1fr; }}
        .sticky {{ position: static; }}
        .kv {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="panel">
        {body}
      </div>
    </div>
    {script}
  </body>
</html>"""
    return HTMLResponse(content=html)


def _notice(message: str | None, *, error: bool = False) -> str:
    if not message:
        return ""
    css_class = "notice error" if error else "notice"
    return f'<div class="{css_class}">{escape(message)}</div>'


def _admin_session_cookie(token: str) -> dict:
    forwarded_proto = os.getenv("FORWARDED_PROTO", "").lower()
    secure_cookie = (
        os.getenv("ADMIN_PANEL_SECURE_COOKIE", "").lower() in {"1", "true", "yes"}
        or forwarded_proto == "https"
    )
    return {
        "key": config.admin_panel.session_cookie_name,
        "value": token,
        "httponly": True,
        "max_age": config.admin_panel.session_duration_minutes * 60,
        "samesite": "lax",
        "secure": secure_cookie,
        "path": config.admin_panel.path,
    }


def _get_authenticated_admin(request: Request):
    token = request.cookies.get(config.admin_panel.session_cookie_name)
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None
    if payload.get("token_type") != "admin_panel":
        return None
    user_id = payload.get("user_id")
    if not user_id:
        return None

    try:
        user = get_user_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    if not user or not user.is_admin or not user.is_active:
        return None
    return user


def _mask_value(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    sensitive_tokens = ("password", "secret", "token", "key", "cookie")
    if any(token in key.lower() for token in sensitive_tokens):
        if len(value) <= 8:
            return "***"
        return f"{value[:3]}***{value[-2:]}"
    return value


def _load_app_config_file() -> dict[str, Any]:
    try:
        payload = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _runtime_prediction_mode(app_config: dict[str, Any]) -> str:
    runtime_config = app_config.get("runtime_prediction", {})
    mode = str(runtime_config.get("mode") if isinstance(runtime_config, dict) else "").strip().lower()
    if not mode:
        gemini_config = app_config.get("gemini_prediction", {})
        if isinstance(gemini_config, dict) and gemini_config.get("use_gemini_for_runtime_predictions"):
            mode = "gemini"
    return mode if mode in {"deterministic", "gemini", "openai"} else "deterministic"


def _write_runtime_prediction_mode(mode: str) -> None:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"deterministic", "gemini", "openai"}:
        raise ValueError("Unknown prediction mode")

    app_config = _load_app_config_file()
    runtime_config = app_config.get("runtime_prediction")
    if not isinstance(runtime_config, dict):
        runtime_config = {}
    runtime_config["mode"] = normalized_mode
    app_config["runtime_prediction"] = runtime_config

    gemini_config = app_config.get("gemini_prediction")
    if isinstance(gemini_config, dict):
        gemini_config["use_gemini_for_runtime_predictions"] = normalized_mode == "gemini"
        app_config["gemini_prediction"] = gemini_config

    temp_path = APP_CONFIG_PATH.with_suffix(f"{APP_CONFIG_PATH.suffix}.tmp")
    temp_path.write_text(json.dumps(app_config, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(APP_CONFIG_PATH)


def _format_datetime(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)


def _format_duration(started_at: Any) -> str:
    if not started_at:
        return "-"
    if isinstance(started_at, str):
        try:
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return started_at
    if not isinstance(started_at, datetime):
        return str(started_at)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)
    total_seconds = max(int(delta.total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _status_class(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"running", "failed", "pending", "completed", "cancelled", "reviewed", "dismissed", "resolved_removed", "resolved_suspended"}:
        return f"status-{normalized}"
    return ""


def _safe_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _html_table(columns: list[tuple[str, str]], rows: Iterable[dict[str, Any]]) -> str:
    rows = list(rows)
    if not rows:
        return "<p>No data available.</p>"

    header = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{row.get(key, '-')}</td>" for key, _ in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _admin_url(*, message: str | None = None, error: bool = False, job_id: int | None = None, tab: str | None = None) -> str:
    params: dict[str, str] = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = "1"
    if job_id is not None:
        params["job_id"] = str(job_id)
    if tab:
        params["tab"] = tab
    query = urlencode(params)
    return f"{config.admin_panel.path}{f'?{query}' if query else ''}"


def _admin_redirect(*, message: str, error: bool = False, job_id: int | None = None, tab: str | None = None) -> RedirectResponse:
    return RedirectResponse(
        url=_admin_url(message=message, error=error, job_id=job_id, tab=tab),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _moderation_action_form(action: str, label: str, report_id: int, *, css_class: str = "secondary", extra_fields: str = "") -> str:
    return (
        f'<form method="post" action="{escape(config.admin_panel.path)}/moderation-action" class="inline-form">'
        f'<input type="hidden" name="report_id" value="{report_id}">'
        f'<input type="hidden" name="action" value="{escape(action)}">'
        f"{extra_fields}"
        f'<button type="submit" class="{escape(css_class)} small-button">{escape(label)}</button>'
        f"</form>"
    )


def _format_json_blob(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return escape(_safe_json(value))


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def _format_bytes(value: Any) -> str:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size_float = float(size)
    for unit in units:
        if size_float < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size_float)} {unit}"
            return f"{size_float:.1f} {unit}"
        size_float /= 1024
    return f"{size} B"


def _truncate_text(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _status_badge(value: Any) -> str:
    text = str(value or "-")
    return f'<span class="{_status_class(text)}">{escape(text)}</span>'


def _job_link(job_id: int, label: str | None = None, *, tab: str | None = None) -> str:
    return f'<a class="secret-link" href="{escape(_admin_url(job_id=job_id, tab=tab))}">{escape(label or f"#{job_id}")}</a>'


def _terminate_button(job_id: int) -> str:
    return (
        f'<form class="inline-form" method="post" action="{escape(config.admin_panel.path)}/terminate-job">'
        f'<input type="hidden" name="job_id" value="{job_id}">'
        f'<button type="submit" class="danger small-button">End Job</button>'
        f"</form>"
    )

def _render_tool_registry() -> str:
    blocks = []
    for tool in get_tool_registry():
        requirements = "".join(
            f'<span class="pill">{escape(req.get("label", req.get("type", "input")))}: {escape(", ".join(req.get("formats", [])))}</span>'
            for req in tool.get("input_requirements", [])
        ) or "<span class=\"pill\">No explicit inputs</span>"
        produces = "".join(
            f'<span class="pill">{escape(str(item))}</span>'
            for item in tool.get("produces", [])
        ) or "<span class=\"pill\">No declared outputs</span>"
        docker_image = escape(str(tool.get("docker", {}).get("image", "unknown")))
        blocks.append(
            f"""
            <details>
              <summary>{escape(tool.get("name", tool.get("id", "Tool")))} <span class="mono">({escape(tool.get("id", ""))})</span></summary>
              <p>{escape(tool.get("description", ""))}</p>
              <div><strong>Type:</strong> {escape(tool.get("type", "unknown"))}</div>
              <div><strong>Image:</strong> <code>{docker_image}</code></div>
              <div style="margin-top:0.6rem;"><strong>Inputs</strong><br>{requirements}</div>
              <div style="margin-top:0.6rem;"><strong>Produces</strong><br>{produces}</div>
            </details>
            """
        )
    return "".join(blocks)


def _collect_recent_job_ids(limit: int = 200) -> list[int]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id
                FROM jobs
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [int(row[0]) for row in cur.fetchall()]
        finally:
            cur.close()


def _extract_stage_log_history(
    selected_job: dict[str, Any],
    *,
    include_live_runtime: bool = True,
) -> list[dict[str, Any]]:
    job = selected_job["job"]
    entries: list[dict[str, Any]] = []
    for execution in selected_job["executions"]:
        for stage_entry in execution["stages"]:
            recorded = stage_entry["recorded"]
            runtime = stage_entry["runtime"] or {}
            log_sections: list[tuple[str, str]] = []
            for title, content in (
                ("Persisted Init Logs", recorded.get("init_logs_full")),
                ("Persisted Tool Logs", recorded.get("tool_logs_full")),
                ("Persisted Log Preview", recorded.get("logs_preview")),
                ("Recorded Error", recorded.get("error")),
            ):
                if content:
                    log_sections.append((title, str(content)))
            if include_live_runtime:
                for title, content in (
                    ("Live Init Logs", runtime.get("live_init_logs")),
                    ("Live Tool Logs", runtime.get("live_tool_logs")),
                ):
                    if content:
                        log_sections.append((title, str(content)))

            entries.append(
                {
                    "log_key": f'exec-{execution["id"]}-stage-{recorded.get("stage_number") or "na"}',
                    "job_id": job["id"],
                    "job_name": job["name"],
                    "username": job["username"],
                    "execution_id": execution["id"],
                    "execution_number": execution["execution_number"],
                    "execution_status": execution["status"],
                    "stage_number": recorded.get("stage_number"),
                    "tool_id": recorded.get("tool_id"),
                    "tool_name": recorded.get("tool_name"),
                    "stage_status": recorded.get("status"),
                    "kubernetes_job_name": runtime.get("kubernetes_job_name") or recorded.get("kubernetes_job_name"),
                    "pod_name": runtime.get("pod_name") or recorded.get("pod_name"),
                    "started_at": recorded.get("started_at") or execution["started_at"],
                    "completed_at": recorded.get("completed_at") or execution["completed_at"],
                    "log_sections": log_sections,
                }
            )
    return entries


def _render_job_logs_content(selected_job: dict[str, Any]) -> str:
    log_entries = _extract_stage_log_history(selected_job)
    log_entries.sort(
        key=lambda item: (
            _format_datetime(item.get("started_at")),
            item.get("execution_number") or 0,
            item.get("stage_number") or 0,
        ),
        reverse=True,
    )

    blocks = []
    for item in log_entries:
        log_sections = []
        for title, content in item["log_sections"]:
            section_key = _slugify(title)
            log_sections.append(
                f"""
                <div class="log-section" data-section-key="{escape(section_key)}">
                  <h3>{escape(title)}</h3>
                  <pre data-log-text="1">{escape(content)}</pre>
                </div>
                """
            )
        logs_html = "".join(log_sections) or "<p class='muted'>No persisted or live logs are available for this stage.</p>"
        blocks.append(
            f"""
            <details data-log-key="{escape(item['log_key'])}">
              <summary>
                <span data-field="summary-execution">Exec #{escape(str(item["execution_number"]))}</span>
                | <span data-field="summary-stage">Stage {escape(str(item["stage_number"] or "-"))}</span>
                | <span data-field="summary-tool">{escape(str(item["tool_name"] or item["tool_id"] or "-"))}</span>
                | <span data-field="summary-stage-status">{_status_badge(item["stage_status"])}</span>
              </summary>
              <div class="kv">
                <div><strong>Execution Status</strong></div><div data-field="execution-status">{_status_badge(item["execution_status"])}</div>
                <div><strong>Kubernetes Job</strong></div><div data-field="kubernetes-job"><code>{escape(str(item["kubernetes_job_name"] or "-"))}</code></div>
                <div><strong>Pod</strong></div><div data-field="pod-name"><code>{escape(str(item["pod_name"] or "-"))}</code></div>
                <div><strong>Started</strong></div><div data-field="started-at">{escape(_format_datetime(item["started_at"]))}</div>
                <div><strong>Completed</strong></div><div data-field="completed-at">{escape(_format_datetime(item["completed_at"]))}</div>
              </div>
              {logs_html}
            </details>
            """
        )

    return (
        f"<p class='muted'>Full Kubernetes stage logs for this job. Live pod logs refresh automatically while the job is running.</p>"
        f"{''.join(blocks) if blocks else '<p class=\"muted\" data-empty-terminal=\"1\">No Kubernetes stage log history is available yet.</p>'}"
    )


def _job_logs_payload(selected_job: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _extract_stage_log_history(selected_job)
    entries.sort(
        key=lambda item: (
            _format_datetime(item.get("started_at")),
            item.get("execution_number") or 0,
            item.get("stage_number") or 0,
        ),
        reverse=True,
    )
    payload = []
    for item in entries:
        payload.append(
            {
                "log_key": item["log_key"],
                "execution_number": item["execution_number"],
                "stage_number": item["stage_number"],
                "tool_name": item["tool_name"],
                "tool_id": item["tool_id"],
                "stage_status": item["stage_status"],
                "stage_status_badge_html": _status_badge(item["stage_status"]),
                "execution_status": item["execution_status"],
                "execution_status_badge_html": _status_badge(item["execution_status"]),
                "kubernetes_job_name": item["kubernetes_job_name"],
                "pod_name": item["pod_name"],
                "started_at_text": _format_datetime(item["started_at"]),
                "completed_at_text": _format_datetime(item["completed_at"]),
                "log_sections": [
                    {
                        "title": title,
                        "section_key": _slugify(title),
                        "content": content,
                    }
                    for title, content in item["log_sections"]
                ],
            }
        )
    return payload


def _job_logs_live_script(job_id: int) -> str:
    endpoint = f"{config.admin_panel.path}/job-logs-fragment?job_id={job_id}"
    return f"""
<script>
(() => {{
  const container = document.getElementById('job-live-logs');
  if (!container) return;
  const endpoint = {json.dumps(endpoint)};
  let inflight = false;

  function createSection(section) {{
    const wrapper = document.createElement('div');
    wrapper.className = 'log-section';
    wrapper.dataset.sectionKey = section.section_key;
    const heading = document.createElement('h3');
    heading.textContent = section.title;
    const pre = document.createElement('pre');
    pre.dataset.logText = '1';
    pre.textContent = section.content;
    wrapper.appendChild(heading);
    wrapper.appendChild(pre);
    return wrapper;
  }}

  function createDetails(entry) {{
    const details = document.createElement('details');
    details.dataset.logKey = entry.log_key;

    const summary = document.createElement('summary');
    summary.innerHTML =
      '<span data-field="summary-execution"></span>' +
      ' | <span data-field="summary-stage"></span>' +
      ' | <span data-field="summary-tool"></span>' +
      ' | <span data-field="summary-stage-status"></span>';
    details.appendChild(summary);

    const kv = document.createElement('div');
    kv.className = 'kv';
    kv.innerHTML =
      '<div><strong>Execution Status</strong></div><div data-field="execution-status"></div>' +
      '<div><strong>Kubernetes Job</strong></div><div data-field="kubernetes-job"></div>' +
      '<div><strong>Pod</strong></div><div data-field="pod-name"></div>' +
      '<div><strong>Started</strong></div><div data-field="started-at"></div>' +
      '<div><strong>Completed</strong></div><div data-field="completed-at"></div>';
    details.appendChild(kv);

    if (!entry.log_sections.length) {{
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.dataset.emptyLogs = '1';
      empty.textContent = 'No persisted or live logs are available for this stage.';
      details.appendChild(empty);
    }} else {{
      for (const section of entry.log_sections) {{
        details.appendChild(createSection(section));
      }}
    }}

    return details;
  }}

  function setHTML(node, value) {{
    if (node) node.innerHTML = value;
  }}

  function setText(node, value) {{
    if (node) node.textContent = value;
  }}

  function updateDetails(details, entry) {{
    setText(details.querySelector('[data-field="summary-execution"]'), `Exec #${{entry.execution_number}}`);
    setText(details.querySelector('[data-field="summary-stage"]'), `Stage ${{entry.stage_number ?? '-'}}`);
    setText(details.querySelector('[data-field="summary-tool"]'), entry.tool_name || entry.tool_id || '-');
    setHTML(details.querySelector('[data-field="summary-stage-status"]'), entry.stage_status_badge_html);
    setHTML(details.querySelector('[data-field="execution-status"]'), entry.execution_status_badge_html);
    setHTML(details.querySelector('[data-field="kubernetes-job"]'), `<code>${{entry.kubernetes_job_name || '-'}}</code>`);
    setHTML(details.querySelector('[data-field="pod-name"]'), `<code>${{entry.pod_name || '-'}}</code>`);
    setText(details.querySelector('[data-field="started-at"]'), entry.started_at_text);
    setText(details.querySelector('[data-field="completed-at"]'), entry.completed_at_text);

    const existingSections = new Map(
      Array.from(details.querySelectorAll('.log-section')).map((node) => [node.dataset.sectionKey, node])
    );
    const emptyMessage = details.querySelector('[data-empty-logs]');
    if (entry.log_sections.length) {{
      if (emptyMessage) emptyMessage.remove();
      for (const section of entry.log_sections) {{
        const existing = existingSections.get(section.section_key);
        if (existing) {{
          const pre = existing.querySelector('[data-log-text]');
          if (pre) pre.textContent = section.content;
        }} else {{
          details.appendChild(createSection(section));
        }}
      }}
    }} else if (!emptyMessage && !details.querySelector('.log-section')) {{
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.dataset.emptyLogs = '1';
      empty.textContent = 'No persisted or live logs are available for this stage.';
      details.appendChild(empty);
    }}
  }}

  async function refreshLogs() {{
    if (inflight) return;
    inflight = true;
    try {{
      const response = await fetch(endpoint, {{
        credentials: 'same-origin',
        headers: {{ 'X-Requested-With': 'fetch' }}
      }});
      if (!response.ok) return;
      const payload = await response.json();
      const existingDetails = new Map(
        Array.from(container.querySelectorAll('details[data-log-key]')).map((node) => [node.dataset.logKey, node])
      );
      const seen = new Set();
      for (const entry of payload.entries || []) {{
        seen.add(entry.log_key);
        const existing = existingDetails.get(entry.log_key);
        if (existing) {{
          updateDetails(existing, entry);
        }} else {{
          container.appendChild(createDetails(entry));
          updateDetails(container.querySelector(`details[data-log-key="${{entry.log_key}}"]`), entry);
        }}
      }}
      for (const [key, node] of existingDetails.entries()) {{
        if (!seen.has(key)) {{
          node.remove();
        }}
      }}
      if ((!payload.entries || !payload.entries.length) && !container.querySelector('[data-empty-terminal]')) {{
        container.innerHTML = '<p class="muted" data-empty-terminal="1">No Kubernetes stage log history is available yet.</p>';
      }} else if (payload.entries && payload.entries.length) {{
        const empty = container.querySelector('[data-empty-terminal]');
        if (empty) empty.remove();
      }}
      const stamp = document.getElementById('job-live-logs-status');
      if (stamp) {{
        stamp.textContent = 'Last refreshed: ' + new Date().toLocaleTimeString();
      }}
    }} catch (_error) {{
    }} finally {{
      inflight = false;
    }}
  }}

  refreshLogs();
  window.setInterval(refreshLogs, 5000);
}})();
</script>
"""


def _collect_job_details(job_id: int) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                    j.id,
                    j.user_id,
                    u.username,
                    u.email,
                    j.name,
                    j.status,
                    j.workflow_id,
                    w.name,
                    j.pipeline_config_id,
                    j.pipeline_id,
                    j.assembler,
                    j.data_types,
                    j.cloud_provider,
                    j.vm_name,
                    j.created_at,
                    j.updated_at
                FROM jobs j
                JOIN users u ON u.id = j.user_id
                LEFT JOIN workflows w ON w.id = j.workflow_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            cur.execute(
                """
                SELECT id, filename, file_type, file_format, size_bytes, s3_key, uploaded_at, created_at
                FROM files
                WHERE job_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (job_id,),
            )
            file_rows = cur.fetchall()
        finally:
            cur.close()

    executions = get_executions_by_job(job_id)
    workflow = get_workflow_by_id(row[6]) if row[6] else None
    runtime_details = {
        "namespace": get_config().kubernetes.namespace,
        "stages": [],
        "errors": [],
    }
    if kubernetes_is_available():
        try:
            runtime_details = get_kubernetes_pipeline_runner().get_job_runtime_details(job_id, executions)
        except Exception as exc:
            runtime_details["errors"].append(str(exc))
    else:
        runtime_details["errors"].append("Kubernetes backend is not available from this backend instance.")

    runtime_by_execution_stage = {
        (str(item.get("execution_id")), str(item.get("stage_number"))): item
        for item in runtime_details.get("stages", [])
    }

    execution_payload = []
    for execution in executions:
        parameters_used = execution.parameters_used if isinstance(execution.parameters_used, dict) else {}
        stages = parameters_used.get("stages") if isinstance(parameters_used.get("stages"), list) else []
        stage_payload = []
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            runtime = runtime_by_execution_stage.get((str(execution.id), str(stage.get("stage_number"))), {})
            stage_payload.append(
                {
                    "recorded": stage,
                    "runtime": runtime,
                }
            )

        execution_payload.append(
            {
                "id": execution.id,
                "execution_number": execution.execution_number,
                "status": execution.status.value,
                "nextflow_run_id": execution.nextflow_run_id,
                "work_dir": execution.work_dir,
                "output_dir": execution.output_dir,
                "process_id": execution.process_id,
                "tool_versions": execution.tool_versions,
                "parameters_used": parameters_used,
                "error_message": execution.error_message,
                "started_at": execution.started_at,
                "completed_at": execution.completed_at,
                "created_at": execution.created_at,
                "stages": stage_payload,
            }
        )

    return {
        "job": {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "email": row[3],
            "name": row[4],
            "status": row[5],
            "workflow_id": row[6],
            "workflow_name": row[7],
            "pipeline_config_id": row[8],
            "pipeline_id": row[9],
            "assembler": row[10],
            "data_types": row[11],
            "cloud_provider": row[12],
            "vm_name": row[13],
            "created_at": row[14],
            "updated_at": row[15],
        },
        "workflow": workflow,
        "files": [
            {
                "id": file_row[0],
                "filename": file_row[1],
                "file_type": file_row[2],
                "file_format": file_row[3],
                "size_bytes": file_row[4],
                "s3_key": file_row[5],
                "uploaded_at": file_row[6],
                "created_at": file_row[7],
            }
            for file_row in file_rows
        ],
        "executions": execution_payload,
        "runtime": runtime_details,
    }


def _render_job_detail(selected_job: dict[str, Any]) -> str:
    job = selected_job["job"]
    workflow = selected_job.get("workflow") or {}
    files = selected_job["files"]
    executions = selected_job["executions"]
    runtime = selected_job["runtime"]
    input_files = [file_item for file_item in files if str(file_item.get("file_type") or "").lower() == "input"]
    workflow_steps = workflow.get("workflow_steps") if isinstance(workflow.get("workflow_steps"), list) else []
    selected_tools = workflow.get("tools_used") if isinstance(workflow.get("tools_used"), list) else []

    file_rows = [
        {
            "id": str(file_item["id"]),
            "filename": escape(file_item["filename"]),
            "type": escape(str(file_item["file_type"] or "-")),
            "format": escape(str(file_item["file_format"] or "-")),
            "size": escape(_format_bytes(file_item["size_bytes"])),
            "uploaded": escape(_format_datetime(file_item["uploaded_at"] or file_item["created_at"])),
            "path": f'<code>{escape(str(file_item["s3_key"]))}</code>',
        }
        for file_item in files
    ]

    execution_blocks = []
    for execution in executions:
        stage_blocks = []
        for stage_entry in execution["stages"]:
            stage = stage_entry["recorded"]
            runtime_entry = stage_entry["runtime"] or {}
            recorded_logs = stage.get("logs_preview")
            live_tool_logs = runtime_entry.get("live_tool_logs")
            live_init_logs = runtime_entry.get("live_init_logs")
            runtime_meta = {
                "Kubernetes Job": runtime_entry.get("kubernetes_job_name") or stage.get("kubernetes_job_name") or "-",
                "Pod": runtime_entry.get("pod_name") or stage.get("pod_name") or "-",
                "Recorded Status": stage.get("status") or "-",
                "Live Job Status": runtime_entry.get("job_status") or "-",
                "Pod Phase": runtime_entry.get("pod_phase") or "-",
                "Started": _format_datetime(stage.get("started_at")),
                "Completed": _format_datetime(stage.get("completed_at")),
            }
            runtime_meta_html = "".join(
                f"<div><strong>{escape(key)}</strong></div><div>{_status_badge(value) if 'Status' in key or key == 'Pod Phase' else escape(str(value))}</div>"
                for key, value in runtime_meta.items()
            )
            stage_logs = []
            if recorded_logs:
                stage_logs.append(f"<h3>Recorded Log Preview</h3><pre>{escape(str(recorded_logs))}</pre>")
            if live_init_logs:
                stage_logs.append(f"<h3>Live Init Container Logs</h3><pre>{escape(str(live_init_logs))}</pre>")
            if live_tool_logs:
                stage_logs.append(f"<h3>Live Tool Logs</h3><pre>{escape(str(live_tool_logs))}</pre>")
            if stage.get("error"):
                stage_logs.append(f"<h3>Recorded Error</h3><pre>{escape(str(stage.get('error')))}</pre>")
            if runtime_entry.get("raw_job_status"):
                stage_logs.append(f"<h3>Kubernetes Status Snapshot</h3><pre>{_format_json_blob(runtime_entry.get('raw_job_status'))}</pre>")
            if runtime_entry.get("raw_pod_status"):
                stage_logs.append(f"<h3>Pod Snapshot</h3><pre>{_format_json_blob(runtime_entry.get('raw_pod_status'))}</pre>")

            stage_blocks.append(
                f"""
                <details>
                  <summary>
                    Stage {escape(str(stage.get("stage_number") or "-"))}: {escape(str(stage.get("tool_name") or stage.get("tool_id") or "-"))}
                    {_status_badge(stage.get("status"))}
                  </summary>
                  <div class="kv">{runtime_meta_html}</div>
                  {' '.join(stage_logs) if stage_logs else '<p class="muted">No stage log content is currently available.</p>'}
                </details>
                """
            )

        execution_blocks.append(
            f"""
            <details>
              <summary>
                Execution #{escape(str(execution["execution_number"]))} {_status_badge(execution["status"])}
                <span class="muted">Started {escape(_format_datetime(execution["started_at"]))}</span>
              </summary>
              <div class="kv">
                <div><strong>Execution ID</strong></div><div><code>{escape(str(execution["id"]))}</code></div>
                <div><strong>Nextflow Run ID</strong></div><div>{escape(str(execution["nextflow_run_id"] or "-"))}</div>
                <div><strong>Process ID</strong></div><div>{escape(str(execution["process_id"] or "-"))}</div>
                <div><strong>Started</strong></div><div>{escape(_format_datetime(execution["started_at"]))}</div>
                <div><strong>Completed</strong></div><div>{escape(_format_datetime(execution["completed_at"]))}</div>
                <div><strong>Work Dir</strong></div><div><code>{escape(str(execution["work_dir"] or "-"))}</code></div>
                <div><strong>Output Dir</strong></div><div><code>{escape(str(execution["output_dir"] or "-"))}</code></div>
              </div>
              {f'<h3>Error</h3><pre>{escape(str(execution["error_message"]))}</pre>' if execution.get("error_message") else ''}
              {f'<h3>Tool Versions</h3><pre>{_format_json_blob(execution["tool_versions"])}</pre>' if execution.get("tool_versions") else ''}
              {''.join(stage_blocks) if stage_blocks else '<p class="muted">No per-stage metadata was recorded for this execution.</p>'}
              <details>
                <summary>Raw Parameters Used</summary>
                <pre>{_format_json_blob(execution["parameters_used"])}</pre>
              </details>
            </details>
            """
        )

    runtime_errors = runtime.get("errors") or []
    runtime_notes = "".join(f"<div class='notice error'>{escape(str(item))}</div>" for item in runtime_errors)
    live_logs_html = _render_job_logs_content(selected_job)

    return f"""
      <div class="section">
        <div class="row" style="justify-content: space-between; align-items: flex-start;">
          <div>
            <h2>Job Detail: {escape(job["name"])}</h2>
            <p>
              {_job_link(job["id"], f'Job #{job["id"]}')} owned by <strong>{escape(job["username"])}</strong>.
              Live Kubernetes logs appear while pods still exist; once Kubernetes garbage collection removes a pod, the panel falls back to the recorded stage previews stored in execution metadata.
            </p>
          </div>
          <div class="button-row">
            {_terminate_button(job["id"]) if str(job["status"]).lower() in {"running", "pending"} else ""}
            <a class="button-link secondary" href="{escape(config.admin_panel.path)}">Clear Selection</a>
          </div>
        </div>
        {runtime_notes}
        <div class="job-layout">
          <div class="stack sticky">
            <div class="subpanel">
              <h3>Overview</h3>
              <div class="kv">
                <div><strong>Status</strong></div><div>{_status_badge(job["status"])}</div>
                <div><strong>User</strong></div><div>{escape(job["username"])} ({escape(job["email"] or "-")})</div>
                <div><strong>Workflow</strong></div><div>{escape(str(job["workflow_name"] or "-"))}</div>
                <div><strong>Workflow ID</strong></div><div>{escape(str(job["workflow_id"] or "-"))}</div>
                <div><strong>Pipeline Config</strong></div><div>{escape(str(job["pipeline_config_id"] or "-"))}</div>
                <div><strong>Pipeline</strong></div><div>{escape(str(job["pipeline_id"] or "-"))}</div>
                <div><strong>VM</strong></div><div>{escape(str(job["vm_name"] or "-"))}</div>
                <div><strong>Assembler</strong></div><div>{escape(str(job["assembler"] or "-"))}</div>
                <div><strong>Cloud</strong></div><div>{escape(str(job["cloud_provider"] or "-"))}</div>
                <div><strong>Data Types</strong></div><div>{escape(", ".join(job["data_types"] or []) or "-")}</div>
                <div><strong>Created</strong></div><div>{escape(_format_datetime(job["created_at"]))}</div>
                <div><strong>Updated</strong></div><div>{escape(_format_datetime(job["updated_at"]))}</div>
                <div><strong>Kubernetes Namespace</strong></div><div><code>{escape(str(runtime.get("namespace") or "-"))}</code></div>
              </div>
            </div>
            <div class="subpanel">
              <h3>Selected Tools</h3>
              <p>{", ".join(selected_tools) if selected_tools else "No workflow tool list is available for this job."}</p>
              {''.join(
                f'<span class="pill">Step {escape(str(step.get("step") or "-"))}: {escape(str(step.get("name") or step.get("tool") or "-"))}</span>'
                for step in workflow_steps
              ) or '<p class="muted">No workflow steps recorded.</p>'}
            </div>
            <div class="subpanel">
              <h3>Input Files</h3>
              <p>{", ".join(file_item["filename"] for file_item in input_files) if input_files else "No input files were recorded for this job."}</p>
            </div>
          </div>
          <div class="stack">
            <div class="subpanel">
              <h3>Files</h3>
              <p>{len(files)} files linked to this job.</p>
              {_html_table(
                [
                  ("id", "ID"),
                  ("filename", "Filename"),
                  ("type", "Type"),
                  ("format", "Format"),
                  ("size", "Size"),
                  ("uploaded", "Uploaded"),
                  ("path", "S3 Key"),
                ],
                file_rows,
              )}
            </div>
            <div class="subpanel">
              <h3>Execution History</h3>
              <p>Every execution record, including runtime fields, stage-level status, and Kubernetes log snippets.</p>
              {''.join(execution_blocks) if execution_blocks else '<p>No executions recorded for this job yet.</p>'}
            </div>
            <div class="subpanel">
              <div class="row" style="justify-content: space-between; align-items: center;">
                <h3 style="margin-bottom:0;">Kubernetes Logs</h3>
                <div id="job-live-logs-status" class="muted">Waiting for first refresh...</div>
              </div>
              <div id="job-live-logs">
                {live_logs_html}
              </div>
            </div>
          </div>
        </div>
      </div>
    """


def _collect_dashboard_data(selected_job_id: int | None = None) -> dict[str, Any]:
    db_health = check_database_health()
    config_dict = config.to_dict()
    app_config = _load_app_config_file()
    masked_env = {
        key: _mask_value(key, value)
        for key, value in sorted(os.environ.items())
    }

    demo_files_rows = []
    demo_data_root = Path(os.getenv("DEMO_DATA_ROOT", "mock/data"))
    if demo_data_root.exists() and demo_data_root.is_dir():
        for f in demo_data_root.iterdir():
            if f.is_file():
                try:
                    stat = f.stat()
                    demo_files_rows.append({
                        "filename": f.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    })
                except Exception:
                    pass
    demo_files_rows.sort(key=lambda x: x["filename"])

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM users")
            total_users = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM jobs")
            total_jobs = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'")
            running_jobs_count = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM workflows")
            total_workflows = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM files")
            total_files = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT
                    j.id,
                    j.name,
                    u.username,
                    j.status,
                    j.vm_name,
                    w.name,
                    je.execution_number,
                    je.status,
                    je.started_at,
                    je.completed_at,
                    je.error_message,
                    j.updated_at
                FROM jobs j
                JOIN users u ON u.id = j.user_id
                LEFT JOIN workflows w ON w.id = j.workflow_id
                LEFT JOIN LATERAL (
                    SELECT execution_number, status, started_at, completed_at, error_message
                    FROM job_executions
                    WHERE job_id = j.id
                    ORDER BY execution_number DESC
                    LIMIT 1
                ) je ON TRUE
                ORDER BY j.updated_at DESC, j.id DESC
                LIMIT 200
                """
            )
            all_job_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                    j.id,
                    j.name,
                    j.status,
                    j.vm_name,
                    j.created_at,
                    j.updated_at,
                    u.username,
                    w.name,
                    je.id,
                    je.execution_number,
                    je.status,
                    je.started_at,
                    je.completed_at,
                    je.parameters_used,
                    je.error_message
                FROM jobs j
                JOIN users u ON u.id = j.user_id
                LEFT JOIN workflows w ON w.id = j.workflow_id
                LEFT JOIN LATERAL (
                    SELECT id, execution_number, status, started_at, completed_at, parameters_used, error_message
                    FROM job_executions
                    WHERE job_id = j.id
                    ORDER BY execution_number DESC
                    LIMIT 1
                ) je ON TRUE
                WHERE j.status = 'running' OR (je.status = 'running')
                ORDER BY COALESCE(je.started_at, j.updated_at, j.created_at) DESC
                """
            )
            running_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                    u.id,
                    u.username,
                    u.email,
                    u.created_at,
                    u.suspended_until,
                    u.is_admin,
                    COUNT(j.id) AS job_count,
                    COUNT(*) FILTER (WHERE j.status = 'running') AS running_job_count
                FROM users u
                LEFT JOIN jobs j ON j.user_id = u.id
                GROUP BY u.id, u.username, u.email, u.created_at, u.suspended_until, u.is_admin
                ORDER BY u.created_at DESC
                """
            )
            user_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                    j.id,
                    j.name,
                    u.username,
                    j.status,
                    je.execution_number,
                    je.status,
                    je.started_at,
                    je.completed_at,
                    je.error_message
                FROM jobs j
                JOIN users u ON u.id = j.user_id
                LEFT JOIN LATERAL (
                    SELECT execution_number, status, started_at, completed_at, error_message
                    FROM job_executions
                    WHERE job_id = j.id
                    ORDER BY execution_number DESC
                    LIMIT 1
                ) je ON TRUE
                ORDER BY j.updated_at DESC
                LIMIT 20
                """
            )
            recent_rows = cur.fetchall()
        finally:
            cur.close()

    running_jobs = []
    for row in running_rows:
        parameters_used = row[13] or {}
        if isinstance(parameters_used, str):
            try:
                parameters_used = json.loads(parameters_used)
            except json.JSONDecodeError:
                parameters_used = {}
        stages = parameters_used.get("stages") or []
        current_stage = next(
            (stage for stage in stages if str(stage.get("status", "")).lower() == "running"),
            None,
        ) or next(
            (stage for stage in stages if str(stage.get("status", "")).lower() in {"waiting_for_resources", "waiting_for_dependencies", "pending"}),
            None,
        )
        running_jobs.append(
            {
                "job_id": row[0],
                "job_name": row[1],
                "job_status": row[2],
                "vm_name": row[3] or "-",
                "job_created_at": row[4],
                "job_updated_at": row[5],
                "username": row[6],
                "workflow_name": row[7] or "-",
                "execution_id": row[8],
                "execution_number": row[9],
                "execution_status": row[10] or "-",
                "started_at": row[11],
                "completed_at": row[12],
                "parameters_used": parameters_used,
                "error_message": row[14] or "",
                "current_stage": current_stage,
            }
        )

    users = [
        {
            "user_id": row[0],
            "username": row[1],
            "email": row[2] or "-",
            "created_at": row[3],
            "suspended_until": row[4],
            "is_admin": bool(row[5]),
            "job_count": int(row[6] or 0),
            "running_job_count": int(row[7] or 0),
        }
        for row in user_rows
    ]

    recent_jobs = [
        {
            "job_id": row[0],
            "job_name": row[1],
            "username": row[2],
            "job_status": row[3],
            "execution_number": row[4],
            "execution_status": row[5] or "-",
            "started_at": row[6],
            "completed_at": row[7],
            "error_message": row[8] or "",
        }
        for row in recent_rows
    ]

    all_jobs = [
        {
            "job_id": row[0],
            "job_name": row[1],
            "username": row[2],
            "job_status": row[3],
            "vm_name": row[4],
            "workflow_name": row[5] or "-",
            "execution_number": row[6],
            "execution_status": row[7] or "-",
            "started_at": row[8],
            "completed_at": row[9],
            "error_message": row[10] or "",
            "updated_at": row[11],
        }
        for row in all_job_rows
    ]

    return {
        "db_health": db_health,
        "config_dict": config_dict,
        "app_config": app_config,
        "runtime_prediction_mode": _runtime_prediction_mode(app_config),
        "masked_env": masked_env,
        "demo_files": demo_files_rows,
        "tool_registry_count": len(get_tool_registry()),
        "totals": {
            "users": total_users,
            "jobs": total_jobs,
            "running_jobs": running_jobs_count,
            "workflows": total_workflows,
            "files": total_files,
        },
        "running_jobs": running_jobs,
        "users": users,
        "recent_jobs": recent_jobs,
        "all_jobs": all_jobs,
        "invitation_codes": list_invitation_codes(),
        "reports": list_reports_for_admin(),
        "selected_job": _collect_job_details(selected_job_id) if selected_job_id is not None else None,
    }


def _render_demo_codes_section(message: str | None, *, error: bool) -> str:
    generated_codes_html = ""
    display_message = message
    if message and message.startswith("DEMO_CODES:"):
        codes_raw = message[len("DEMO_CODES:"):]
        codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
        generated_codes_html = (
            '<div class="notice">'
            '<strong>Generated codes — copy now, shown once only:</strong><br><br>'
            + "".join(f'<code style="display:block;margin-bottom:0.4rem;font-size:1.05rem">{escape(c)}</code>' for c in codes)
            + "</div>"
        )
        display_message = None

    try:
        codes_list = _demo_svc.get_demo_codes()
    except Exception:
        codes_list = []

    code_rows = [
        {
            "masked": f'<code>{escape(str(c.get("masked_code") or c.get("code_prefix_masked") or "-"))}</code>',
            "created": escape(_format_datetime(c.get("created_at"))),
            "expires": escape(_format_datetime(c.get("expires_at"))) if c.get("expires_at") else "Never",
            "status": (
                f'<span class="{_status_class("completed")}">used</span>'
                if c.get("used_at") or c.get("status") == "used"
                else (
                    f'<span class="{_status_class("cancelled")}">deactivated</span>'
                    if c.get("status") == "deactivated" or not c.get("is_active")
                    else (
                        f'<span class="{_status_class("failed")}">expired</span>'
                        if c.get("status") == "expired"
                        else f'<span class="{_status_class("pending")}">available</span>'
                    )
                )
            ),
            "used_at": escape(_format_datetime(c.get("used_at"))) if c.get("used_at") else "-",
            "actions": (
                f'<form class="inline-form" method="post" action="{escape(config.admin_panel.path)}/demo-codes/deactivate">'
                f'<input type="hidden" name="code_id" value="{escape(str(c.get("id")))}">'
                f'<button class="small-button danger" type="submit">Deactivate</button>'
                f'</form>'
                if c.get("id") is not None and c.get("is_active") and not c.get("used_at") and c.get("status") not in {"used", "deactivated", "expired"}
                else "-"
            ),
        }
        for c in codes_list
    ]

    return f"""
      <div class="section">
        <h2>Generate Demo Codes</h2>
        <p>Codes are bcrypt-hashed and stored. Plaintext is shown once only after generation.</p>
        {_notice(display_message, error=error)}
        {generated_codes_html}
        <form method="post" action="{escape(config.admin_panel.path)}/demo-codes">
          <label for="demo_count">Number of codes</label>
          <input id="demo_count" name="count" type="number" min="1" max="50" value="1" style="max-width:8rem">
          <label for="demo_expires">Expires at (optional, UTC)</label>
          <input id="demo_expires" name="expires_at" type="datetime-local">
          <div class="row">
            <button type="submit">Generate Demo Codes</button>
          </div>
        </form>
      </div>
      <div class="section">
        <h2>Existing Codes</h2>
        {_html_table(
          [
            ("masked", "Code (masked)"),
            ("created", "Created"),
            ("expires", "Expires"),
            ("status", "Status"),
            ("used_at", "Used At"),
            ("actions", "Actions"),
          ],
          code_rows,
        )}
      </div>
    """


def _login_form(message: str | None = None, *, error: bool = False) -> HTMLResponse:
    body = f"""
      <h1>CASSIE Admin Console</h1>
      <p>This console is intentionally hidden behind a secret backend route.</p>
      {_notice(message, error=error)}
      <form method="post" action="{escape(config.admin_panel.path)}/login">
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" required>
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Sign In</button>
      </form>
    """
    return _render_page(title="CASSIE Admin Panel", body=body)


def _dashboard_page(
    message: str | None = None,
    *,
    error: bool = False,
    selected_job_id: int | None = None,
    active_tab: str = "overview",
) -> HTMLResponse:
    data = _collect_dashboard_data(selected_job_id)
    allowed_tabs = {"overview", "jobs", "users", "moderation", "system", "demo"}
    if active_tab not in allowed_tabs:
        active_tab = "overview"
    if active_tab == "demo" and not config.demo.enabled:
        active_tab = "overview"
    db_status = "healthy" if data["db_health"].get("healthy") else "degraded"
    running_rows = []
    for item in data["running_jobs"]:
        current_stage = item.get("current_stage") or {}
        stage_label = "-"
        if current_stage:
            stage_label = f'{escape(str(current_stage.get("tool_name") or current_stage.get("tool_id") or "-"))} <span class="{_status_class(current_stage.get("status"))}">{escape(str(current_stage.get("status") or "-"))}</span>'
        running_rows.append(
            {
                "job": f'{_job_link(item["job_id"], tab="jobs")} <strong>{escape(item["job_name"])}</strong>',
                "user": escape(item["username"]),
                "workflow": escape(item["workflow_name"]),
                "status": f'<span class="{_status_class(item["job_status"])}">{escape(str(item["job_status"]))}</span> / '
                          f'<span class="{_status_class(item["execution_status"])}">{escape(str(item["execution_status"]))}</span>',
                "stage": stage_label,
                "timing": f'Started: {escape(_format_datetime(item["started_at"]))}<br>Elapsed: {escape(_format_duration(item["started_at"]))}',
                "details": (
                    f'VM: {escape(str(item["vm_name"]))}<br>'
                    f'Execution: {escape(str(item["execution_number"] or "-"))}<br>'
                    f'Run ID: <span class="mono">{escape(str((item["parameters_used"] or {}).get("workflow_id") or "-"))}</span><br>'
                    f'{_terminate_button(item["job_id"])}'
                ),
            }
        )

    user_rows = [
        {
            "username": escape(user["username"]),
            "email": escape(user["email"]),
            "role": f'<span class="{_status_class("completed" if user["is_admin"] else "pending")}">{"Admin" if user["is_admin"] else "User"}</span>',
            "joined": escape(_format_datetime(user["created_at"])),
            "suspension": escape(_format_datetime(user["suspended_until"])) if user.get("suspended_until") else "-",
            "jobs": str(user["job_count"]),
            "running": str(user["running_job_count"]),
            "actions": (
                f'<form class="inline-form" method="post" action="{escape(config.admin_panel.path)}/users/admin-status">'
                f'<input type="hidden" name="user_id" value="{user["user_id"]}">'
                f'<input type="hidden" name="is_admin" value="{"false" if user["is_admin"] else "true"}">'
                f'<button class="small-button {"danger" if user["is_admin"] else "secondary"}" type="submit">'
                f'{"Revoke Admin" if user["is_admin"] else "Make Admin"}'
                f'</button>'
                f'</form>'
            ),
        }
        for user in data["users"]
    ]
    usernames_by_id = {user["user_id"]: user["username"] for user in data["users"]}

    invitation_rows = [
        {
            "code": f'<code>{escape(invitation.code)}</code>',
            "note": escape(invitation.note or "-"),
            "created": escape(_format_datetime(invitation.created_at)),
            "created_by": escape(usernames_by_id.get(invitation.created_by_user_id, "-")),
            "status": (
                f'<span class="{_status_class("completed")}">used</span>'
                if invitation.used_at
                else f'<span class="{_status_class("pending")}">available</span>'
            ),
            "used_by": escape(usernames_by_id.get(invitation.used_by_user_id, "-")),
            "used_at": escape(_format_datetime(invitation.used_at)),
        }
        for invitation in data["invitation_codes"]
    ]

    recent_rows = [
        {
            "job": f'{_job_link(job["job_id"], tab="jobs")} <strong>{escape(job["job_name"])}</strong>',
            "user": escape(job["username"]),
            "status": f'<span class="{_status_class(job["job_status"])}">{escape(str(job["job_status"]))}</span> / '
                      f'<span class="{_status_class(job["execution_status"])}">{escape(str(job["execution_status"]))}</span>',
            "timing": f'Started: {escape(_format_datetime(job["started_at"]))}<br>Completed: {escape(_format_datetime(job["completed_at"]))}',
            "error": escape(job["error_message"][:180] + ("..." if len(job["error_message"]) > 180 else "")) if job["error_message"] else "-",
        }
        for job in data["recent_jobs"]
    ]

    all_job_rows = [
        {
            "job": f'{_job_link(job["job_id"], tab="jobs")} <strong>{escape(job["job_name"])}</strong>',
            "user": escape(job["username"]),
            "workflow": escape(str(job["workflow_name"] or "-")),
            "status": f'{_status_badge(job["job_status"])} / {_status_badge(job["execution_status"])}',
            "timing": (
                f'Updated: {escape(_format_datetime(job["updated_at"]))}<br>'
                f'Started: {escape(_format_datetime(job["started_at"]))}'
            ),
            "ops": (
                f'<a class="button-link secondary small-button" href="{escape(_admin_url(job_id=job["job_id"], tab="jobs"))}">Inspect</a> '
                + (_terminate_button(job["job_id"]) if str(job["job_status"]).lower() in {"running", "pending"} else "")
            ),
        }
        for job in data["all_jobs"]
    ]

    report_rows = [
        {
            "target": f'{escape(report["target_label"])} <span class="muted">#{report["target_id"]}</span>',
            "owner": escape(report["target_owner_display_name"] or report["target_owner_username"] or "-"),
            "reporter": escape(report["reporter_display_name"] or report["reporter_username"]),
            "reason": escape(report["reason"]),
            "details": escape(str(report["details"] or "-")),
            "status": f'<span class="{_status_class(report["status"])}">{escape(report["status"])}</span>',
            "created": escape(_format_datetime(report["created_at"])),
            "preview": escape(str(report["preview"])[:180] + ("..." if len(str(report["preview"])) > 180 else "")),
            "actions": (
                '<div class="button-row">'
                + _moderation_action_form("remove", "Remove", report["id"], css_class="danger")
                + _moderation_action_form(
                    "suspend",
                    "Block User",
                    report["id"],
                    css_class="secondary",
                    extra_fields=(
                        '<input class="input-compact" type="number" name="duration_value" min="1" max="365" value="7" required>'
                        '<select class="input-compact" name="duration_unit" required>'
                        '<option value="days">days</option>'
                        '<option value="hours">hours</option>'
                        '<option value="weeks">weeks</option>'
                        '</select>'
                    ),
                )
                + _moderation_action_form("dismiss", "Dismiss", report["id"], css_class="secondary")
                + "</div>"
            ),
        }
        for report in data["reports"]
    ]

    demo_files_rendered = [
        {
            "filename": f'<code>{escape(f["filename"])}</code>',
            "size": escape(_format_bytes(f["size"])),
            "modified": escape(_format_datetime(f["modified"])),
            "ops": (
                f'<form class="inline-form" method="post" action="{escape(config.admin_panel.path)}/demo-files/delete">'
                f'<input type="hidden" name="filename" value="{escape(f["filename"])}">'
                f'<button type="submit" class="danger small-button">Delete</button>'
                f'</form>'
            ),
        }
        for f in data.get("demo_files", [])
    ]

    report_total = len(data["reports"])
    open_reports = sum(1 for report in data["reports"] if str(report["status"]).lower() == "open")
    pipeline_reports = sum(1 for report in data["reports"] if report["target_type"] == "pipeline")
    forum_reports = sum(1 for report in data["reports"] if report["target_type"] in {"forum_thread", "forum_comment"})

    selected_job_html = _render_job_detail(data["selected_job"]) if data.get("selected_job") and active_tab == "jobs" else ""
    page_script = _job_logs_live_script(selected_job_id) if data.get("selected_job") and selected_job_id is not None and active_tab == "jobs" else ""

    tabs = [
        ("overview", "Overview"),
        ("jobs", "Jobs"),
        ("users", "Users"),
        ("moderation", "Moderation"),
        ("system", "System"),
    ]
    if config.demo.enabled:
        tabs.append(("demo", "Demo Codes"))
    tab_nav = "".join(
        f'<a class="tab-link{" active" if active_tab == tab_key else ""}" href="{escape(_admin_url(tab=tab_key, job_id=selected_job_id if tab_key == "jobs" else None))}">{escape(tab_label)}</a>'
        for tab_key, tab_label in tabs
    )

    overview_section = f"""
      <div class="section">
        <h2>Running Jobs</h2>
        <p>Active jobs with user, workflow, execution timing, stage information, and direct kill controls.</p>
        {_html_table(
          [
            ("job", "Job"),
            ("user", "User"),
            ("workflow", "Workflow"),
            ("status", "Status"),
            ("stage", "Current Stage"),
            ("timing", "Timing"),
            ("details", "Details"),
          ],
          running_rows,
        )}
      </div>

      <div class="section grid cols-2">
        <div>
          <h2>Recent Jobs</h2>
          <p>Latest job and execution summaries across the system.</p>
          {_html_table(
            [
              ("job", "Job"),
              ("user", "User"),
              ("status", "Status"),
              ("timing", "Timing"),
              ("error", "Last Error"),
            ],
            recent_rows,
          )}
        </div>
        <div>
          <h2>Users Snapshot</h2>
          <p>Recent account activity and running job counts.</p>
          {_html_table(
            [
              ("username", "Username"),
              ("email", "Email"),
              ("role", "Role"),
              ("joined", "Joined"),
              ("suspension", "Blocked Until"),
              ("jobs", "Jobs"),
              ("running", "Running"),
            ],
            user_rows[:12],
          )}
        </div>
      </div>
    """

    jobs_section = f"""
      <div class="section">
        <h2>Jobs</h2>
        <p>System-wide job index. Use Inspect for a full execution and Kubernetes drill-down.</p>
        {_html_table(
          [
            ("job", "Job"),
            ("user", "User"),
            ("workflow", "Workflow"),
            ("status", "Status"),
            ("timing", "Timing"),
            ("ops", "Ops"),
          ],
          all_job_rows,
        )}
      </div>
      {selected_job_html}
    """

    users_section = f"""
      <div class="section">
        <h2>Users</h2>
        <p>Current user accounts and their job counts.</p>
        {_html_table(
          [
            ("username", "Username"),
            ("email", "Email"),
            ("role", "Role"),
            ("joined", "Joined"),
            ("suspension", "Blocked Until"),
            ("jobs", "Jobs"),
            ("running", "Running"),
            ("actions", "Actions"),
          ],
          user_rows,
        )}
      </div>
      <div class="section">
        <h2>Invitation Codes</h2>
        <p>Registration is locked to one-time invitation codes generated here.</p>
        <form method="post" action="{escape(config.admin_panel.path)}/invitation-codes">
          <label for="invitation_note">Note</label>
          <input id="invitation_note" name="note" maxlength="255" placeholder="Optional recipient or campaign note">
          <div class="row">
            <button type="submit">Generate Invitation Code</button>
          </div>
        </form>
        {_html_table(
          [
            ("code", "Code"),
            ("note", "Note"),
            ("created", "Created"),
            ("created_by", "Created By"),
            ("status", "Status"),
            ("used_by", "Used By"),
            ("used_at", "Used At"),
          ],
          invitation_rows,
        )}
      </div>
    """

    moderation_section = f"""
      <div class="section">
        <h2>Moderation</h2>
        <p>All reported pipelines, forum posts, and forum comments appear here for admin review.</p>
        <div class="cards">
          <div class="card"><strong>{open_reports}</strong><span>Open Reports</span></div>
          <div class="card"><strong>{report_total}</strong><span>Total Reports</span></div>
          <div class="card"><strong>{pipeline_reports}</strong><span>Pipeline Reports</span></div>
          <div class="card"><strong>{forum_reports}</strong><span>Forum Reports</span></div>
        </div>
        {_html_table(
          [
            ("target", "Target"),
            ("owner", "Owner"),
            ("reporter", "Reporter"),
            ("reason", "Reason"),
            ("details", "Details"),
            ("status", "Status"),
            ("created", "Created"),
            ("preview", "Preview"),
            ("actions", "Actions"),
          ],
          report_rows,
        )}
      </div>
    """

    system_section = f"""
      <div class="section grid cols-2">
        <div>
          <h2>App Config</h2>
          <p>Loaded application configuration with sensitive values masked.</p>
          <pre>{escape(_safe_json(data["config_dict"]))}</pre>
        </div>
        <div>
          <h2>Prediction Mode</h2>
          <p>Runtime prediction provider used by cost estimates.</p>
          <form method="post" action="{escape(config.admin_panel.path)}/runtime-prediction-mode">
            <label for="prediction_mode">Provider</label>
            <select id="prediction_mode" name="prediction_mode">
              <option value="deterministic"{" selected" if data["runtime_prediction_mode"] == "deterministic" else ""}>Deterministic</option>
              <option value="gemini"{" selected" if data["runtime_prediction_mode"] == "gemini" else ""}>Gemini</option>
              <option value="openai"{" selected" if data["runtime_prediction_mode"] == "openai" else ""}>OpenAI</option>
            </select>
            <div class="row">
              <button type="submit">Save Mode</button>
            </div>
          </form>
          <pre>{escape(_safe_json(data["app_config"]))}</pre>
        </div>
      </div>

      <div class="section">
          <h2>Environment Variables</h2>
          <p>Runtime environment visible to the backend container, including tool and cluster settings.</p>
          <pre>{escape(_safe_json(data["masked_env"]))}</pre>
      </div>

      <div class="section">
        <h2>Tool Registry</h2>
        <p>Tool definitions, input requirements, outputs, and configured images.</p>
        {_render_tool_registry()}
      </div>

      <div class="section">
        <h2>Change Admin Password</h2>
        <p>The new password takes effect immediately and persists across restarts.</p>
        <form method="post" action="{escape(config.admin_panel.path)}/password">
          <label for="current_password">Current Password</label>
          <input id="current_password" name="current_password" type="password" autocomplete="current-password" required>
          <label for="new_password">New Password</label>
          <input id="new_password" name="new_password" type="password" autocomplete="new-password" required>
          <label for="confirm_password">Confirm New Password</label>
          <input id="confirm_password" name="confirm_password" type="password" autocomplete="new-password" required>
          <div class="row">
            <button type="submit">Update Password</button>
          </div>
        </form>
      </div>

      <div class="section">
        <h2>Demo Files (Mock Data)</h2>
        <p>Upload and list physical demo files stored in the <code>DEMO_DATA_ROOT</code> (default: <code>mock/data/</code>). Upload a new <code>manifest.json</code> to update dataset definitions.</p>
        <form method="post" action="{escape(config.admin_panel.path)}/demo-files/upload" enctype="multipart/form-data">
          <label for="demo_file">Select File</label>
          <input id="demo_file" name="file" type="file" required style="margin-bottom:0.5rem">
          <div class="row">
            <button type="submit">Upload Demo File</button>
          </div>
        </form>
        {_html_table(
          [
            ("filename", "Filename"),
            ("size", "Size"),
            ("modified", "Last Modified"),
            ("ops", "Actions"),
          ],
          demo_files_rendered,
        )}
      </div>
    """

    demo_section = _render_demo_codes_section(message if active_tab == "demo" else None, error=error if active_tab == "demo" else False) if config.demo.enabled else ""
    tab_sections = {
        "overview": overview_section,
        "jobs": jobs_section,
        "users": users_section,
        "moderation": moderation_section,
        "system": system_section,
        "demo": demo_section,
    }

    body = f"""
      <div class="row" style="justify-content: space-between; align-items: flex-start;">
        <div>
          <h1>CASSIE Admin Console</h1>
          <p>
            Secret route:
            <a class="secret-link" href="{escape(config.admin_panel.path)}"><code>{escape(config.admin_panel.path)}</code></a>
          </p>
        </div>
        <form method="post" action="{escape(config.admin_panel.path)}/logout">
          <button type="submit" class="secondary">Log Out</button>
        </form>
      </div>
      {_notice(message if active_tab != "demo" else None, error=error)}
      <div class="meta">
        <div><strong>Bootstrap Admin Username</strong> <code>{escape(config.admin_panel.username)}</code></div>
        <div><strong>Cookie Scope</strong> <code>{escape(config.admin_panel.path)}</code></div>
        <div><strong>Database Status</strong> <span class="{_status_class(db_status)}">{escape(db_status)}</span></div>
      </div>

      <div class="cards">
        <div class="card"><strong>{data["totals"]["running_jobs"]}</strong><span>Running Jobs</span></div>
        <div class="card"><strong>{data["totals"]["jobs"]}</strong><span>Total Jobs</span></div>
        <div class="card"><strong>{data["totals"]["users"]}</strong><span>Total Users</span></div>
        <div class="card"><strong>{data["totals"]["workflows"]}</strong><span>Workflows</span></div>
        <div class="card"><strong>{data["totals"]["files"]}</strong><span>Tracked Files</span></div>
        <div class="card"><strong>{data["tool_registry_count"]}</strong><span>Registered Tools</span></div>
      </div>
      <div class="tab-nav">{tab_nav}</div>
      {tab_sections[active_tab]}
    """
    return _render_page(title="CASSIE Admin Panel", body=body, script=page_script)


@router.get(config.admin_panel.path, response_class=HTMLResponse)
async def admin_panel_home(request: Request):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        message = request.query_params.get("message")
        error = request.query_params.get("error") == "1"
        return _login_form(message=message, error=error)

    message = request.query_params.get("message")
    error = request.query_params.get("error") == "1"
    active_tab = request.query_params.get("tab") or "overview"
    selected_job_id = None
    raw_job_id = request.query_params.get("job_id")
    if raw_job_id:
        try:
            selected_job_id = int(raw_job_id)
        except ValueError:
            selected_job_id = None
    return _dashboard_page(message=message, error=error, selected_job_id=selected_job_id, active_tab=active_tab)


@router.get(f"{config.admin_panel.path}/job-logs-fragment")
async def admin_panel_job_logs_fragment(request: Request, job_id: int):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return JSONResponse(
            {"entries": [], "error": "Authentication expired. Refresh the page and sign in again."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    selected_job = _collect_job_details(job_id)
    if not selected_job:
        return JSONResponse({"entries": [], "error": "Job not found."}, status_code=status.HTTP_404_NOT_FOUND)

    return JSONResponse({"entries": _job_logs_payload(selected_job)})


@router.post(f"{config.admin_panel.path}/login")
async def admin_panel_login(
    username: str = Form(...),
    password: str = Form(...),
):
    ensure_admin_user()
    admin_user = get_user_by_username(username)

    if not admin_user or not admin_user.is_admin or not admin_user.is_active or not verify_password(password, admin_user.password_hash):
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=Invalid+credentials&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    token = create_scoped_token(
        {"username": admin_user.username, "user_id": admin_user.id},
        token_type="admin_panel",
        expires_delta=timedelta(minutes=config.admin_panel.session_duration_minutes),
    )
    response = RedirectResponse(url=config.admin_panel.path, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(**_admin_session_cookie(token))
    return response


@router.post(f"{config.admin_panel.path}/password")
async def admin_panel_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=Please+sign+in+again&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not verify_password(current_password, admin_user.password_hash):
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=Current+password+is+incorrect&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if len(new_password) < 12:
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=New+password+must+be+at+least+12+characters&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if new_password != confirm_password:
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=New+passwords+do+not+match&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    update_user_password(admin_user.id, new_password)

    refreshed_admin = get_user_by_id(admin_user.id)
    if not refreshed_admin:
        return RedirectResponse(
            url=f"{config.admin_panel.path}?message=Please+sign+in+again&error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    token = create_scoped_token(
        {"username": refreshed_admin.username, "user_id": refreshed_admin.id},
        token_type="admin_panel",
        expires_delta=timedelta(minutes=config.admin_panel.session_duration_minutes),
    )
    response = RedirectResponse(
        url=f"{config.admin_panel.path}?message=Admin+password+updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.set_cookie(**_admin_session_cookie(token))
    return response


@router.post(f"{config.admin_panel.path}/runtime-prediction-mode")
async def admin_panel_runtime_prediction_mode(
    request: Request,
    prediction_mode: str = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="system")

    try:
        _write_runtime_prediction_mode(prediction_mode)
    except ValueError as exc:
        return _admin_redirect(message=str(exc), error=True, tab="system")
    except Exception:
        return _admin_redirect(message="Failed to update runtime prediction mode", error=True, tab="system")

    return _admin_redirect(message=f"Runtime prediction mode set to {prediction_mode}", tab="system")


@router.post(f"{config.admin_panel.path}/users/admin-status")
async def admin_panel_update_user_admin_status(
    request: Request,
    user_id: int = Form(...),
    is_admin: bool = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="users")

    if admin_user.id == user_id and not is_admin:
        return _admin_redirect(message="You cannot revoke admin from the signed-in admin account", error=True, tab="users")

    updated_user = set_user_admin(user_id, is_admin)
    if not updated_user:
        return _admin_redirect(message=f"User {user_id} was not found", error=True, tab="users")

    role_label = "admin" if updated_user.is_admin else "regular user"
    return _admin_redirect(message=f"{updated_user.username} is now a {role_label}", tab="users")


@router.post(f"{config.admin_panel.path}/invitation-codes")
async def admin_panel_create_invitation_code(
    request: Request,
    note: str = Form(""),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="users")

    try:
        invitation = create_invitation_code(created_by_user_id=admin_user.id, note=note)
    except Exception:
        return _admin_redirect(message="Failed to generate invitation code", error=True, tab="users")

    return _admin_redirect(message=f"Invitation code generated: {invitation.code}", tab="users")


@router.post(f"{config.admin_panel.path}/terminate-job")
async def admin_panel_terminate_job(
    request: Request,
    job_id: int = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, job_id=job_id)

    job = get_job_by_id(job_id)
    if not job:
        return _admin_redirect(message=f"Job {job_id} was not found", error=True)

    executions = get_executions_by_job(job_id)
    cleanup_summary = {"deleted_stage_jobs": [], "errors": []}
    if kubernetes_is_available():
        try:
            cleanup_summary = get_kubernetes_pipeline_runner().terminate_job_stages(job_id, executions)
        except Exception as exc:
            cleanup_summary["errors"].append(str(exc))

    active_execution_statuses = {
        ExecutionStatus.RUNNING,
        ExecutionStatus.PENDING,
    }
    now = datetime.now(timezone.utc)
    for execution in executions:
        if execution.status not in active_execution_statuses:
            continue
        parameters_used = deepcopy(execution.parameters_used) if isinstance(execution.parameters_used, dict) else {}
        stages = parameters_used.get("stages")
        if isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                if str(stage.get("status") or "").lower() in {
                    "pending",
                    "running",
                    "waiting_for_dependencies",
                    "waiting_for_resources",
                }:
                    stage["status"] = "cancelled"
                    stage["completed_at"] = now.isoformat()
                    stage["error"] = "Cancelled from admin panel"
        update_job_execution(
            execution.id,
            JobExecutionUpdate(
                status=ExecutionStatus.CANCELLED,
                completed_at=now,
                error_message="Cancelled from admin panel",
                parameters_used=parameters_used,
            ),
        )

    update_job(job_id, job.user_id, JobUpdate(status=JobStatus.CANCELLED))

    deleted_jobs_count = len(cleanup_summary.get("deleted_stage_jobs") or [])
    error_count = len(cleanup_summary.get("errors") or [])
    message = f"Job {job_id} cancelled. Deleted {deleted_jobs_count} Kubernetes stage jobs."
    if error_count:
        message += f" {error_count} cleanup errors were recorded."
    return _admin_redirect(message=message, error=bool(error_count), job_id=job_id)


@router.post(f"{config.admin_panel.path}/moderation-action")
async def admin_panel_moderation_action(
    request: Request,
    report_id: int = Form(...),
    action: str = Form(...),
    duration_value: int | None = Form(None),
    duration_unit: str | None = Form(None),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="moderation")

    try:
        if action == "remove":
            result = moderate_report_target(report_id)
            return _admin_redirect(message=result["message"], tab="moderation")
        if action == "dismiss":
            if not update_report_status(report_id, "dismissed"):
                return _admin_redirect(message=f"Report {report_id} was not found", error=True, tab="moderation")
            return _admin_redirect(message=f"Report {report_id} dismissed", tab="moderation")
        if action == "suspend":
            if duration_value is None or duration_unit is None:
                return _admin_redirect(message="Suspension duration is required", error=True, tab="moderation")
            result = suspend_report_target_owner(
                report_id,
                duration_value=duration_value,
                duration_unit=duration_unit,
            )
            return _admin_redirect(
                message=f'User {result["username"]} blocked until {_format_datetime(result["suspended_until"])}',
                tab="moderation",
            )
        return _admin_redirect(message=f"Unknown moderation action: {action}", error=True, tab="moderation")
    except Exception as exc:
        return _admin_redirect(message=str(exc), error=True, tab="moderation")


@router.post(f"{config.admin_panel.path}/demo-codes")
async def admin_panel_generate_demo_codes(
    request: Request,
    count: int = Form(1),
    expires_at: str = Form(""),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="demo")

    if not config.demo.enabled:
        return _admin_redirect(message="Demo mode is not enabled", error=True, tab="demo")

    count = max(1, min(count, 50))
    parsed_expires: datetime | None = None
    if expires_at.strip():
        try:
            parsed_expires = datetime.fromisoformat(expires_at.strip()).replace(tzinfo=timezone.utc)
        except ValueError:
            return _admin_redirect(message="Invalid expiry date format", error=True, tab="demo")

    try:
        plaintext_codes = _demo_svc.generate_demo_codes(
            admin_user_id=admin_user.id,
            count=count,
            expires_at=parsed_expires,
        )
    except Exception as exc:
        return _admin_redirect(message=f"Failed to generate codes: {exc}", error=True, tab="demo")

    codes_param = ",".join(plaintext_codes)
    from urllib.parse import quote
    return RedirectResponse(
        url=f"{config.admin_panel.path}?tab=demo&message={quote('DEMO_CODES:' + codes_param)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(f"{config.admin_panel.path}/demo-codes/deactivate")
async def admin_panel_deactivate_demo_code(
    request: Request,
    code_id: int = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="demo")

    if not config.demo.enabled:
        return _admin_redirect(message="Demo mode is not enabled", error=True, tab="demo")

    try:
        _demo_svc.deactivate_demo_code(code_id)
    except Exception as exc:
        return _admin_redirect(message=f"Failed to deactivate code: {exc}", error=True, tab="demo")

    return _admin_redirect(message=f"Demo code {code_id} deactivated", tab="demo")


@router.post(f"{config.admin_panel.path}/logout")
async def admin_panel_logout():
    response = RedirectResponse(
        url=f"{config.admin_panel.path}?message=Signed+out",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(
        key=config.admin_panel.session_cookie_name,
        path=config.admin_panel.path,
    )
    return response


@router.post(f"{config.admin_panel.path}/demo-files/upload")
async def admin_panel_upload_demo_file(
    request: Request,
    file: UploadFile = File(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="system")

    if not file.filename:
        return _admin_redirect(message="No file selected", error=True, tab="system")

    demo_data_root = Path(os.getenv("DEMO_DATA_ROOT", "mock/data"))
    try:
        demo_data_root.mkdir(parents=True, exist_ok=True)
        filename = Path(file.filename).name
        if not filename:
            return _admin_redirect(message="Invalid filename", error=True, tab="system")
        file_path = demo_data_root / filename
        
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        return _admin_redirect(message=f"Failed to upload file: {exc}", error=True, tab="system")

    return _admin_redirect(message=f"Uploaded {filename} to demo data", tab="system")


@router.post(f"{config.admin_panel.path}/demo-files/delete")
async def admin_panel_delete_demo_file(
    request: Request,
    filename: str = Form(...),
):
    ensure_admin_user()
    admin_user = _get_authenticated_admin(request)
    if not admin_user:
        return _admin_redirect(message="Please sign in again", error=True, tab="system")

    demo_data_root = Path(os.getenv("DEMO_DATA_ROOT", "mock/data"))
    try:
        clean_filename = Path(filename).name
        if not clean_filename:
            return _admin_redirect(message="Invalid filename", error=True, tab="system")
        file_path = demo_data_root / clean_filename
            
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except Exception as exc:
        return _admin_redirect(message=f"Failed to delete file: {exc}", error=True, tab="system")

    return _admin_redirect(message=f"Deleted {clean_filename}", tab="system")
