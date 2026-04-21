import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import Navigation from '../components/Navigation'
import ReportDialog from '../components/ReportDialog'
import { getCurrentUser, getToken } from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import {
  ForumComment,
  ForumThreadDetail,
  createForumComment,
  deleteForumComment,
  deleteForumThread,
  getForumThread,
  reportForumComment,
  reportForumThread,
  uploadForumCommentImages,
  voteForumComment,
  voteForumThread,
} from '../services/forumService'
import '../styles/globals.css'

type ReplyTarget =
  | { key: `comment-${number}`; label: string; parentCommentId: number }

interface LightboxState {
  images: string[]
  index: number
  label: string
}

type ReportTargetState =
  | { type: 'thread'; id: number }
  | { type: 'comment'; id: number }

const formatDateTime = (value: string) => new Date(value).toLocaleString()
const MAX_FORUM_IMAGES = 4
const COMMENTS_PER_PAGE = 10

const sortCommentsRecursively = (
  comments: ForumComment[],
  sortBy: 'recent' | 'popular'
): ForumComment[] => {
  const compareComments = (left: ForumComment, right: ForumComment) => {
    if (sortBy === 'popular') {
      const scoreDelta = right.score - left.score
      if (scoreDelta !== 0) {
        return scoreDelta
      }
      const upvoteDelta = right.upvote_count - left.upvote_count
      if (upvoteDelta !== 0) {
        return upvoteDelta
      }
    }

    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  }

  return [...comments]
    .map((comment) => ({
      ...comment,
      replies: sortCommentsRecursively(comment.replies || [], sortBy),
    }))
    .sort(compareComments)
}

export default function ForumThread() {
  const navigate = useNavigate()
  const { threadId } = useParams()
  const numericThreadId = Number(threadId)
  const isAuthenticated = !!getToken()
  const [thread, setThread] = useState<ForumThreadDetail | null>(null)
  const [currentUserId, setCurrentUserId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [replyBody, setReplyBody] = useState('')
  const [commentImages, setCommentImages] = useState<File[]>([])
  const [replyImages, setReplyImages] = useState<File[]>([])
  const [replyTarget, setReplyTarget] = useState<ReplyTarget | null>(null)
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(null)
  const [submittingComment, setSubmittingComment] = useState(false)
  const [submittingReply, setSubmittingReply] = useState(false)
  const [currentCommentPage, setCurrentCommentPage] = useState(1)
  const [commentSortBy, setCommentSortBy] = useState<'recent' | 'popular'>('recent')
  const [lightbox, setLightbox] = useState<LightboxState | null>(null)
  const [reportTarget, setReportTarget] = useState<ReportTargetState | null>(null)
  const [submittingReport, setSubmittingReport] = useState(false)

  const commentImagePreviews = useMemo(
    () => commentImages.map((file) => ({ file, url: URL.createObjectURL(file) })),
    [commentImages]
  )

  const replyImagePreviews = useMemo(
    () => replyImages.map((file) => ({ file, url: URL.createObjectURL(file) })),
    [replyImages]
  )

  useEffect(() => {
    return () => {
      commentImagePreviews.forEach(({ url }) => URL.revokeObjectURL(url))
      replyImagePreviews.forEach(({ url }) => URL.revokeObjectURL(url))
    }
  }, [commentImagePreviews, replyImagePreviews])

  useEffect(() => {
    if (!lightbox) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setLightbox(null)
        return
      }
      if (event.key === 'ArrowLeft') {
        setLightbox((current) =>
          current
            ? {
                ...current,
                index: (current.index - 1 + current.images.length) % current.images.length,
              }
            : current
        )
      }
      if (event.key === 'ArrowRight') {
        setLightbox((current) =>
          current
            ? {
                ...current,
                index: (current.index + 1) % current.images.length,
              }
            : current
        )
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [lightbox])

  useEffect(() => {
    if (!Number.isFinite(numericThreadId)) {
      setError('Forum thread not found')
      setLoading(false)
      return
    }

    void loadThread()

    if (isAuthenticated) {
      void getCurrentUser()
        .then((user) => setCurrentUserId(user.id))
        .catch(() => setCurrentUserId(null))
    }
  }, [numericThreadId, isAuthenticated])

  useEffect(() => {
    setCurrentCommentPage(1)
  }, [commentSortBy, thread?.thread_comments.length])

  const loadThread = async () => {
    try {
      setLoading(true)
      setError('')
      const data = await getForumThread(numericThreadId)
      setThread(data)
      setCurrentCommentPage(1)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to load forum thread'))
      setThread(null)
    } finally {
      setLoading(false)
    }
  }

  const closeReplyComposer = () => {
    setReplyTarget(null)
    setReplyBody('')
    setReplyImages([])
  }

  const beginReply = (target: ReplyTarget) => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    setReplyTarget(target)
    setReplyBody('')
    setReplyImages([])
    setOpenMenuKey(null)
  }

  const handleImageSelection = (files: FileList | null, setFiles: (files: File[]) => void) => {
    const nextFiles = Array.from(files || [])
    if (nextFiles.length > MAX_FORUM_IMAGES) {
      setError(`You can attach up to ${MAX_FORUM_IMAGES} images per post.`)
      return
    }
    setError('')
    setFiles(nextFiles)
  }

  const appendReplyToTree = (comments: ForumComment[], newComment: ForumComment): ForumComment[] =>
    comments.map((comment) => {
      if (comment.id === newComment.parent_comment_id) {
        return { ...comment, replies: [...(comment.replies || []), newComment] }
      }

      if (comment.replies && comment.replies.length > 0) {
        return { ...comment, replies: appendReplyToTree(comment.replies, newComment) }
      }

      return comment
    })

  const removeCommentFromTree = (comments: ForumComment[], commentId: number): ForumComment[] =>
    comments
      .filter((comment) => comment.id !== commentId)
      .map((comment) => ({
        ...comment,
        replies: removeCommentFromTree(comment.replies || [], commentId),
      }))

  const countCommentTreeSize = (comment: ForumComment): number =>
    1 + (comment.replies || []).reduce((sum, reply) => sum + countCommentTreeSize(reply), 0)

  const findDeletedCommentSize = (comments: ForumComment[], commentId: number): number => {
    for (const comment of comments) {
      if (comment.id === commentId) {
        return countCommentTreeSize(comment)
      }
      const nestedCount = findDeletedCommentSize(comment.replies || [], commentId)
      if (nestedCount > 0) {
        return nestedCount
      }
    }
    return 0
  }

  const uploadImagesForComment = async (comment: ForumComment, files: File[]): Promise<ForumComment> => {
    if (files.length === 0) {
      return comment
    }
    const updatedComment = await uploadForumCommentImages(comment.id, files)
    return updatedComment || comment
  }

  const openLightbox = (images: string[], index: number, label: string) => {
    if (images.length === 0) {
      return
    }
    setLightbox({ images, index, label })
  }

  const moveLightbox = (direction: -1 | 1) => {
    setLightbox((current) =>
      current
        ? {
            ...current,
            index: (current.index + direction + current.images.length) % current.images.length,
          }
        : current
    )
  }

  const handlePostTopLevelComment = async (e: FormEvent) => {
    e.preventDefault()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    try {
      setSubmittingComment(true)
      const createdComment = await createForumComment(numericThreadId, { body: commentBody })
      let newComment = createdComment
      try {
        newComment = await uploadImagesForComment(createdComment, commentImages)
      } catch (err: any) {
        setError(extractApiErrorMessage(err, 'Comment posted, but image upload failed.'))
      }
      setCommentBody('')
      setCommentImages([])
      setThread((current) =>
        current
          ? {
              ...current,
              comment_count: current.comment_count + 1,
              thread_comments: [...current.thread_comments, newComment],
            }
          : current
      )
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to post comment'))
    } finally {
      setSubmittingComment(false)
    }
  }

  const handlePostReply = async (e: FormEvent) => {
    e.preventDefault()
    if (!replyTarget) {
      return
    }
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    try {
      setSubmittingReply(true)
      const createdComment = await createForumComment(numericThreadId, {
        body: replyBody,
        parent_comment_id: replyTarget.parentCommentId,
      })
      let newComment = createdComment
      try {
        newComment = await uploadImagesForComment(createdComment, replyImages)
      } catch (err: any) {
        setError(extractApiErrorMessage(err, 'Reply posted, but image upload failed.'))
      }

      setThread((current) =>
        current
          ? {
              ...current,
              comment_count: current.comment_count + 1,
              thread_comments: replyTarget.parentCommentId
                ? appendReplyToTree(current.thread_comments, newComment)
                : [...current.thread_comments, newComment],
            }
          : current
      )

      closeReplyComposer()
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to post reply'))
    } finally {
      setSubmittingReply(false)
    }
  }

  const handleDeleteThread = async () => {
    if (!thread) return

    try {
      await deleteForumThread(thread.id)
      navigate('/forum')
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to delete discussion'))
    }
  }

  const handleDeleteComment = async (commentId: number) => {
    try {
      await deleteForumComment(commentId)
      const deletedCount = thread ? findDeletedCommentSize(thread.thread_comments, commentId) || 1 : 1
      setThread((current) =>
        current
          ? {
              ...current,
              thread_comments: removeCommentFromTree(current.thread_comments, commentId),
              comment_count: Math.max(0, current.comment_count - deletedCount),
            }
          : current
      )
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to delete comment'))
    }
  }

  const updateCommentTree = (
    comments: ForumComment[],
    commentId: number,
    updater: (comment: ForumComment) => ForumComment
  ): ForumComment[] =>
    comments.map((comment) => {
      if (comment.id === commentId) {
        return updater(comment)
      }
      if (comment.replies && comment.replies.length > 0) {
        return {
          ...comment,
          replies: updateCommentTree(comment.replies, commentId, updater),
        }
      }
      return comment
    })

  const handleVoteThread = async (voteType: 'upvote' | 'downvote') => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    if (!thread) {
      return
    }
    try {
      const summary = await voteForumThread(thread.id, voteType)
      setThread((current) => current ? { ...current, ...summary } : current)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to vote on forum post'))
    }
  }

  const handleVoteComment = async (commentId: number, voteType: 'upvote' | 'downvote') => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    try {
      const summary = await voteForumComment(commentId, voteType)
      setThread((current) =>
        current
          ? {
              ...current,
              thread_comments: updateCommentTree(current.thread_comments, commentId, (comment) => ({
                ...comment,
                ...summary,
              })),
            }
          : current
      )
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to vote on forum comment'))
    }
  }

  const openReportThread = () => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    if (!thread) {
      return
    }
    setReportTarget({ type: 'thread', id: thread.id })
  }

  const openReportComment = (commentId: number) => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    setReportTarget({ type: 'comment', id: commentId })
  }

  const handleSubmitReport = async (payload: { reason: string; details?: string }) => {
    if (!reportTarget) {
      return
    }
    try {
      setSubmittingReport(true)
      if (reportTarget.type === 'thread') {
        await reportForumThread(reportTarget.id, payload)
      } else {
        await reportForumComment(reportTarget.id, payload)
      }
      setReportTarget(null)
      alert('Report sent to the admin team.')
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to submit report'))
    } finally {
      setSubmittingReport(false)
    }
  }

  const renderAuthorCard = (author: ForumThreadDetail['author']) => (
    <button
      type="button"
      className="community-publisher-card forum-author-card"
      onClick={() => navigate(`/profile/${author.id}`)}
    >
      {author.avatar_url ? (
        <img className="community-publisher-avatar" src={author.avatar_url} alt={author.username} />
      ) : (
        <span className="community-publisher-avatar community-publisher-avatar-fallback">
          {(author.display_name || author.username).slice(0, 1).toUpperCase()}
        </span>
      )}
      <span className="community-publisher-text">
        <strong>{author.display_name || author.username}</strong>
        <small>@{author.username}</small>
      </span>
    </button>
  )

  const renderVoteSymbols = (
    userVote: 'upvote' | 'downvote' | null | undefined,
    onVote: (voteType: 'upvote' | 'downvote') => void,
    targetLabel: string,
    counts: { upvotes: number; downvotes: number },
  ) => (
    <div className="engagement-vote-cluster engagement-vote-cluster-compact">
      <button
        type="button"
        className={`engagement-symbol-button engagement-vote-button engagement-symbol-upvote ${userVote === 'upvote' ? 'active' : ''}`}
        onClick={() => onVote('upvote')}
        aria-label={`Upvote ${targetLabel}`}
        title={userVote === 'upvote' ? 'Take back upvote' : 'Upvote'}
      >
        <span className="engagement-vote-icon" aria-hidden="true">▲</span>
        <span className="engagement-vote-label">Upvote</span>
        <span className="engagement-vote-count">{counts.upvotes}</span>
      </button>
      <button
        type="button"
        className={`engagement-symbol-button engagement-vote-button engagement-symbol-downvote ${userVote === 'downvote' ? 'active' : ''}`}
        onClick={() => onVote('downvote')}
        aria-label={`Downvote ${targetLabel}`}
        title={userVote === 'downvote' ? 'Take back downvote' : 'Downvote'}
      >
        <span className="engagement-vote-icon" aria-hidden="true">▼</span>
        <span className="engagement-vote-label">Downvote</span>
        <span className="engagement-vote-count">{counts.downvotes}</span>
      </button>
    </div>
  )

  const renderActionMenu = (
    menuKey: string,
    items: Array<{ label: string; onClick: () => void; danger?: boolean }>
  ) => {
    if (items.length === 0) {
      return null
    }

    return (
      <div className="forum-post-menu-shell">
      <button
        type="button"
        className="forum-post-menu-trigger"
        aria-label="Post actions"
        onClick={() => setOpenMenuKey((current) => (current === menuKey ? null : menuKey))}
      >
        {'\u22ee'}
      </button>
      {openMenuKey === menuKey && (
        <div className="forum-post-menu">
          {items.map((item) => (
            <button
              key={`${menuKey}-${item.label}`}
              type="button"
              className={`forum-post-menu-item ${item.danger ? 'forum-post-menu-item-danger' : ''}`}
              onClick={item.onClick}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      </div>
    )
  }

  const renderReplyComposer = (targetKey: string) =>
    replyTarget?.key === targetKey ? (
      <form className="forum-inline-form forum-reply-composer" onSubmit={handlePostReply}>
        <div className="forum-reply-composer-header">
          <strong>Replying to {replyTarget.label}</strong>
          <button type="button" className="btn-secondary btn-small" onClick={closeReplyComposer}>
            Close
          </button>
        </div>
        <textarea
          rows={4}
          value={replyBody}
          onChange={(e) => setReplyBody(e.target.value)}
          placeholder="Write your reply"
        />
        <input
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
          multiple
          onChange={(e) => handleImageSelection(e.target.files, setReplyImages)}
        />
        {replyImagePreviews.length > 0 && (
          <div className="forum-image-preview-grid forum-inline-image-grid">
            {replyImagePreviews.map(({ file, url }) => (
              <div key={`${file.name}-${file.size}`} className="forum-image-preview-card">
                <img src={url} alt={file.name} className="forum-image-preview" />
                <span>{file.name}</span>
              </div>
            ))}
          </div>
        )}
        <div className="button-row">
          <button type="submit" className="btn-primary btn-small" disabled={submittingReply}>
            {submittingReply ? 'Posting...' : 'Post Reply'}
          </button>
        </div>
      </form>
    ) : null

  const renderComment = (comment: ForumComment) => {
    const commentKey = `comment-${comment.id}` as const

    return (
      <div key={comment.id} className="forum-comment-stack">
        <article className="card forum-comment-card">
          <div className="forum-post-header">
            <div className="forum-post-author-block">
              {renderAuthorCard(comment.author)}
              <div className="forum-thread-stats forum-engagement-stats">
                <span>{formatDateTime(comment.created_at)}</span>
                {renderVoteSymbols(
                  comment.user_vote,
                  (voteType) => handleVoteComment(comment.id, voteType),
                  'comment',
                  { upvotes: comment.upvote_count, downvotes: comment.downvote_count }
                )}
              </div>
            </div>
            <div className="forum-post-header-actions">
              <button
                type="button"
                className="engagement-symbol-button engagement-symbol-report"
                onClick={() => openReportComment(comment.id)}
                aria-label="Report comment"
                title="Report"
              >
                ⚑
              </button>
              {renderActionMenu(commentKey, [
                {
                  label: 'Reply',
                  onClick: () => beginReply({
                    key: commentKey,
                    parentCommentId: comment.id,
                    label: comment.author.display_name || comment.author.username,
                  }),
                },
                ...(comment.user_id === currentUserId
                  ? [{ label: 'Delete', onClick: () => void handleDeleteComment(comment.id), danger: true }]
                  : []),
              ])}
            </div>
          </div>
          {comment.parent_comment_preview && (
            <div className="forum-quote-preview">
              <strong>{comment.parent_comment_preview.author_name} said:</strong>
              <span>{comment.parent_comment_preview.body}</span>
            </div>
          )}
          <div className="forum-post-body">
            <p>{comment.body}</p>
          </div>
          {comment.image_urls.length > 0 && (
            <div className="forum-post-image-grid">
              {comment.image_urls.map((imageUrl, index) => (
                <button
                  key={`${comment.id}-image-${index}`}
                  type="button"
                  className="forum-post-image-button"
                  onClick={() =>
                    openLightbox(comment.image_urls, index, comment.author.display_name || comment.author.username)
                  }
                >
                  <img
                    src={imageUrl}
                    alt={`Comment image ${index + 1}`}
                    className="forum-post-image"
                  />
                </button>
              ))}
            </div>
          )}
          {renderReplyComposer(commentKey)}
        </article>
        {comment.replies && comment.replies.length > 0 && (
          <div className="forum-comment-children">
            {comment.replies.map((reply) => renderComment(reply))}
          </div>
        )}
      </div>
    )
  }

  const sortedThreadComments = useMemo(
    () => sortCommentsRecursively(thread?.thread_comments || [], commentSortBy),
    [thread?.thread_comments, commentSortBy]
  )

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <div className="loading-state">Loading forum thread...</div>
        </div>
      </div>
    )
  }

  if (!thread) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <div className="error-message">{error || 'Forum thread not found.'}</div>
        </div>
      </div>
    )
  }
  const totalCommentPages = Math.max(1, Math.ceil(sortedThreadComments.length / COMMENTS_PER_PAGE))
  const visibleComments = sortedThreadComments.slice(
    (currentCommentPage - 1) * COMMENTS_PER_PAGE,
    currentCommentPage * COMMENTS_PER_PAGE
  )
  const buildVisibleCommentPages = () => {
    const pages = new Set<number>([1, 2, 3, currentCommentPage, currentCommentPage + 1, totalCommentPages])
    return Array.from(pages)
      .filter((value) => value >= 1 && value <= totalCommentPages)
      .sort((a, b) => a - b)
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content forum-thread-page">
        {error && <div className="error-message">{error}</div>}

        <section className="forum-thread-layout">
          <article className="card forum-thread-main-card forum-post-card">
            <div className="forum-thread-main-topline">
              <span className="forum-meta-inline">{formatDateTime(thread.created_at)}</span>
            </div>
            <h1 className="forum-thread-title">{thread.title}</h1>
            <div className="forum-post-header">
              <div className="forum-post-author-block">
                {renderAuthorCard(thread.author)}
                <div className="forum-thread-stats">
                  {renderVoteSymbols(
                    thread.user_vote,
                    (voteType) => void handleVoteThread(voteType),
                    'forum post',
                    { upvotes: thread.upvote_count, downvotes: thread.downvote_count }
                  )}
                  <span>{thread.comment_count} comment{thread.comment_count === 1 ? '' : 's'}</span>
                  <span>{thread.view_count} view{thread.view_count === 1 ? '' : 's'}</span>
                </div>
              </div>
              <div className="forum-post-header-actions">
                <button
                  type="button"
                  className="engagement-symbol-button engagement-symbol-report"
                  onClick={openReportThread}
                  aria-label="Report forum post"
                  title="Report"
                >
                  ⚑
                </button>
                {renderActionMenu('thread-main', [
                  ...(thread.user_id === currentUserId
                    ? [{ label: 'Delete', onClick: () => void handleDeleteThread(), danger: true }]
                    : []),
                ])}
              </div>
            </div>
            {thread.image_urls.length > 0 && (
              <div className="forum-post-image-grid">
                {thread.image_urls.map((imageUrl, index) => (
                  <button
                    key={`${thread.id}-image-${index}`}
                    type="button"
                    className="forum-post-image-button"
                    onClick={() => openLightbox(thread.image_urls, index, thread.title)}
                  >
                    <img
                      src={imageUrl}
                      alt={`${thread.title} ${index + 1}`}
                      className="forum-post-image"
                    />
                  </button>
                ))}
              </div>
            )}
            <div className="forum-thread-body forum-post-body">
              {thread.body.split('\n').map((paragraph, index) => (
                <p key={`${thread.id}-body-${index}`}>{paragraph}</p>
              ))}
            </div>
          </article>

          <section className="card forum-section-card forum-answer-composer-card">
            <div className="section-heading">
              <h2>Add a Comment</h2>
              <p>Comments and replies all appear as standalone forum posts below.</p>
            </div>
            <form className="forum-inline-form forum-answer-form" onSubmit={handlePostTopLevelComment}>
              <textarea
                rows={5}
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                placeholder="Write your comment"
              />
              <input
                type="file"
                accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
                multiple
                onChange={(e) => handleImageSelection(e.target.files, setCommentImages)}
              />
              {commentImagePreviews.length > 0 && (
                <div className="forum-image-preview-grid forum-inline-image-grid">
                  {commentImagePreviews.map(({ file, url }) => (
                    <div key={`${file.name}-${file.size}`} className="forum-image-preview-card">
                      <img src={url} alt={file.name} className="forum-image-preview" />
                      <span>{file.name}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="button-row">
                <button type="submit" className="btn-primary" disabled={submittingComment}>
                  {submittingComment ? 'Posting...' : 'Post Comment'}
                </button>
              </div>
            </form>
          </section>

          <section className="forum-answer-list">
            <div className="section-heading forum-comment-list-heading">
              <h2>Discussion</h2>
              <div className="community-sort-controls">
                <label htmlFor="thread-comment-sort">Sort comments</label>
                <select
                  id="thread-comment-sort"
                  className="community-sort-select"
                  value={commentSortBy}
                  onChange={(e) => setCommentSortBy(e.target.value as 'recent' | 'popular')}
                >
                  <option value="recent">Most Recent</option>
                  <option value="popular">Most Popular</option>
                </select>
              </div>
            </div>
            {sortedThreadComments.length === 0 ? (
              <div className="empty-state compact-empty">
                <p>No comments yet. You can be the first person to join this discussion.</p>
              </div>
            ) : (
              <>
                {visibleComments.map((comment) => renderComment(comment))}
                {totalCommentPages > 1 && (
                  <div className="forum-pagination forum-list-pagination">
                    <button
                      type="button"
                      className="btn-secondary btn-small forum-page-arrow"
                      disabled={currentCommentPage === 1}
                      onClick={() => setCurrentCommentPage((page) => Math.max(1, page - 1))}
                      aria-label="Previous comments page"
                    >
                      ←
                    </button>
                    {buildVisibleCommentPages().map((pageNumber, index, pages) => (
                      <span key={`thread-comment-page-${pageNumber}`} className="forum-pagination-cluster">
                        {index > 0 && pageNumber - pages[index - 1] > 1 ? <span className="forum-page-ellipsis">…</span> : null}
                        <button
                          type="button"
                          className={`btn-secondary btn-small forum-page-chip ${currentCommentPage === pageNumber ? 'active' : ''}`}
                          onClick={() => setCurrentCommentPage(pageNumber)}
                        >
                          {pageNumber}
                        </button>
                      </span>
                    ))}
                    <button
                      type="button"
                      className="btn-secondary btn-small forum-page-arrow"
                      disabled={currentCommentPage === totalCommentPages}
                      onClick={() => setCurrentCommentPage((page) => Math.min(totalCommentPages, page + 1))}
                      aria-label="Next comments page"
                    >
                      →
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </section>
      </div>
      {lightbox && (
        <div className="forum-lightbox" onClick={() => setLightbox(null)} role="presentation">
          <button
            type="button"
            className="forum-lightbox-close"
            onClick={() => setLightbox(null)}
            aria-label="Close image viewer"
          >
            ×
          </button>
          {lightbox.images.length > 1 && (
            <button
              type="button"
              className="forum-lightbox-nav forum-lightbox-nav-left"
              onClick={(e) => {
                e.stopPropagation()
                moveLightbox(-1)
              }}
              aria-label="Previous image"
            >
              ‹
            </button>
          )}
          <div className="forum-lightbox-content" onClick={(e) => e.stopPropagation()} role="presentation">
            <img
              src={lightbox.images[lightbox.index]}
              alt={`${lightbox.label} image ${lightbox.index + 1}`}
              className="forum-lightbox-image"
            />
            <div className="forum-lightbox-caption">
              <strong>{lightbox.label}</strong>
              <span>
                Image {lightbox.index + 1} of {lightbox.images.length}
              </span>
            </div>
          </div>
          {lightbox.images.length > 1 && (
            <button
              type="button"
              className="forum-lightbox-nav forum-lightbox-nav-right"
              onClick={(e) => {
                e.stopPropagation()
                moveLightbox(1)
              }}
              aria-label="Next image"
            >
              ›
            </button>
          )}
        </div>
      )}
      <ReportDialog
        isOpen={Boolean(reportTarget)}
        title={reportTarget?.type === 'comment' ? 'Report Comment' : 'Report Forum Post'}
        targetLabel={reportTarget?.type === 'comment' ? 'comment' : 'forum post'}
        submitting={submittingReport}
        onClose={() => {
          if (!submittingReport) {
            setReportTarget(null)
          }
        }}
        onSubmit={handleSubmitReport}
      />
    </div>
  )
}
