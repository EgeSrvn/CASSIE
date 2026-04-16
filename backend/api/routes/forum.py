import os
import tempfile
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse

from backend.api.models.forum_model import ForumCommentCreate, ForumThreadCreate
from backend.api.models.user_model import UserResponse
from backend.api.routes.auth import get_current_user
from backend.api.services.forum_service import (
    append_thread_image_keys,
    create_forum_comment,
    create_forum_thread,
    delete_forum_comment,
    delete_forum_thread,
    get_forum_thread,
    get_forum_thread_owner,
    list_forum_threads,
)
from backend.api.services.minio_client import MinIOClient
from backend.api.utils.logger import get_logger
from backend.api.utils.response_builder import ErrorCode, error_response, not_found_response, success_response

logger = get_logger(__name__)

router = APIRouter(prefix="/forum", tags=["forum"])


@router.get("")
async def list_threads(
    q: Optional[str] = Query(None, description="Search threads by title/body with LIKE matching"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
):
    try:
        result = list_forum_threads(search_query=q, page=page, per_page=per_page)
        return success_response(data=result.model_dump(), message="Forum threads retrieved successfully")
    except Exception as e:
        logger.error(f"Failed to list forum threads: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to load forum threads",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ForumThreadCreate,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        thread = create_forum_thread(current_user.id, payload)
        return success_response(
            data=thread.model_dump(),
            message="Forum thread created successfully",
            status_code=status.HTTP_201_CREATED,
        )
    except ValueError as e:
        logger.info(f"Rejected forum thread for user {current_user.id}: {e}")
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Failed to create forum thread: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to create forum thread",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/media/{owner_user_id}")
async def get_forum_media(owner_user_id: int, key: str = Query(...)):
    try:
        minio_client = MinIOClient()
        url = minio_client.generate_presigned_url(user_id=owner_user_id, s3_key=key, expiration=3600)
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    except Exception as e:
        logger.error(f"Failed to resolve forum media: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forum media not found")


@router.get("/{thread_id}")
async def get_thread(thread_id: int):
    try:
        thread = get_forum_thread(thread_id)
        if thread is None:
            return JSONResponse(content=not_found_response("Forum thread", thread_id), status_code=status.HTTP_404_NOT_FOUND)
        return success_response(data=thread.model_dump(), message="Forum thread retrieved successfully")
    except Exception as e:
        logger.error(f"Failed to load forum thread {thread_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to load forum thread",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/{thread_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_thread_comment(
    thread_id: int,
    payload: ForumCommentCreate,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        comment = create_forum_comment(current_user.id, thread_id, payload)
        if comment is None:
            return JSONResponse(content=not_found_response("Forum thread", thread_id), status_code=status.HTTP_404_NOT_FOUND)
        return success_response(
            data=comment.model_dump(),
            message="Comment posted successfully",
            status_code=status.HTTP_201_CREATED,
        )
    except ValueError as e:
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Failed to post comment on thread {thread_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to post comment",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/{thread_id}/images", status_code=status.HTTP_201_CREATED)
async def upload_thread_images(
    thread_id: int,
    files: list[UploadFile] = File(...),
    current_user: UserResponse = Depends(get_current_user),
):
    owner_id = get_forum_thread_owner(thread_id)
    if owner_id != current_user.id:
        return JSONResponse(content=not_found_response("Forum thread", thread_id), status_code=status.HTTP_404_NOT_FOUND)

    temp_paths: list[str] = []
    uploaded_keys: list[str] = []
    minio_client = MinIOClient()

    try:
        for upload in files:
            content_type = (upload.content_type or "").lower()
            if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}:
                return JSONResponse(
                    content=error_response(
                        error_code=ErrorCode.VALIDATION_ERROR,
                        message="Forum images must be PNG, JPEG, WEBP, or GIF",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            suffix = Path(upload.filename or "").suffix.lower() or {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/jpg": ".jpg",
                "image/webp": ".webp",
                "image/gif": ".gif",
            }[content_type]

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_path = temp_file.name
                temp_paths.append(temp_path)
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)

            key = f"forum/threads/{thread_id}/{uuid4().hex}{suffix}"
            minio_client.upload_file(
                user_id=current_user.id,
                username=current_user.username,
                local_path=temp_path,
                s3_key=key,
                metadata={"purpose": "forum-thread-image", "thread_id": str(thread_id)},
            )
            uploaded_keys.append(key)
            await upload.close()

        updated_thread = append_thread_image_keys(thread_id, current_user.id, uploaded_keys)
        return success_response(
            data=updated_thread.model_dump() if updated_thread else None,
            message="Forum images uploaded successfully",
            status_code=status.HTTP_201_CREATED,
        )
    except Exception as e:
        logger.error(f"Failed to upload forum images for thread {thread_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to upload forum images",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


@router.delete("/{thread_id}")
async def remove_thread(
    thread_id: int,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        deleted = delete_forum_thread(thread_id, current_user.id)
        if not deleted:
            return JSONResponse(content=not_found_response("Forum thread", thread_id), status_code=status.HTTP_404_NOT_FOUND)
        return success_response(data=None, message="Forum thread deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete forum thread {thread_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to delete forum thread",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.delete("/comments/{comment_id}")
async def remove_comment(
    comment_id: int,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        deleted = delete_forum_comment(comment_id, current_user.id)
        if not deleted:
            return JSONResponse(content=not_found_response("Forum comment", comment_id), status_code=status.HTTP_404_NOT_FOUND)
        return success_response(data=None, message="Forum comment deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete forum comment {comment_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to delete forum comment",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
