import { FormEvent, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import Navigation from '../components/Navigation'
import { getCurrentUser, getToken } from '../services/authService'
import {
  ForumComment,
  ForumThreadDetail,
  createForumComment,
  deleteForumComment,
  deleteForumThread,
  getForumThread,
} from '../services/forumService'
import '../styles/globals.css'

type ReplyTarget =
  | { key: 'thread-main'; label: string; parentCommentId?: undefined }
  | { key: `comment-${number}`; label: string; parentCommentId: number }

const formatDateTime = (value: string) => new Date(value).toLocaleString()

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
  const [replyTarget, setReplyTarget] = useState<ReplyTarget | null>(null)
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(null)
  const [submittingComment, setSubmittingComment] = useState(false)
  const [submittingReply, setSubmittingReply] = useState(false)

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

  const loadThread = async () => {
    try {
      setLoading(true)
      setError('')
      const data = await getForumThread(numericThreadId)
      setThread(data)
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Failed to load forum thread')
      setThread(null)
    } finally {
      setLoading(false)
    }
  }

  const closeReplyComposer = () => {
    setReplyTarget(null)
    setReplyBody('')
  }

  const beginReply = (target: ReplyTarget) => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    setReplyTarget(target)
    setReplyBody('')
    setOpenMenuKey(null)
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

  const handlePostTopLevelComment = async (e: FormEvent) => {
    e.preventDefault()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    try {
      setSubmittingComment(true)
      const newComment = await createForumComment(numericThreadId, { body: commentBody })
      setCommentBody('')
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
      setError(err.response?.data?.message || err.message || 'Failed to post comment')
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
      const newComment = await createForumComment(numericThreadId, {
        body: replyBody,
        parent_comment_id: replyTarget.parentCommentId,
      })

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
      setError(err.response?.data?.message || err.message || 'Failed to post reply')
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
      setError(err.response?.data?.message || err.message || 'Failed to delete discussion')
    }
  }

  const handleDeleteComment = async (commentId: number) => {
    try {
      await deleteForumComment(commentId)
      setThread((current) =>
        current
          ? {
              ...current,
              thread_comments: removeCommentFromTree(current.thread_comments, commentId),
              comment_count: Math.max(0, current.comment_count - 1),
            }
          : current
      )
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Failed to delete comment')
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

  const renderActionMenu = (menuKey: string, onReply: () => void, onDelete?: () => void) => (
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
          <button type="button" className="forum-post-menu-item" onClick={onReply}>
            Reply
          </button>
          {onDelete && (
            <button
              type="button"
              className="forum-post-menu-item forum-post-menu-item-danger"
              onClick={onDelete}
            >
              Delete
            </button>
          )}
        </div>
      )}
    </div>
  )

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
              <span className="forum-meta-inline">{formatDateTime(comment.created_at)}</span>
            </div>
            {renderActionMenu(
              commentKey,
              () =>
                beginReply({
                  key: commentKey,
                  parentCommentId: comment.id,
                  label: comment.author.display_name || comment.author.username,
                }),
              comment.user_id === currentUserId ? () => handleDeleteComment(comment.id) : undefined
            )}
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

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content forum-thread-page">
        {error && <div className="error-message">{error}</div>}

        <section className="forum-thread-layout">
          <article className="card forum-thread-main-card forum-post-card">
            <div className="forum-thread-main-topline">
              <span className="entry-badge">Main Question</span>
              <span className="forum-meta-inline">{formatDateTime(thread.created_at)}</span>
            </div>
            <h1 className="forum-thread-title">{thread.title}</h1>
            <div className="forum-post-header">
              <div className="forum-post-author-block">
                {renderAuthorCard(thread.author)}
                <div className="forum-thread-stats">
                  <span>{thread.comment_count} comment{thread.comment_count === 1 ? '' : 's'}</span>
                  <span>{thread.view_count} view{thread.view_count === 1 ? '' : 's'}</span>
                </div>
              </div>
              {renderActionMenu(
                'thread-main',
                () => beginReply({ key: 'thread-main', label: 'the main question' }),
                thread.user_id === currentUserId ? handleDeleteThread : undefined
              )}
            </div>
            {thread.image_urls.length > 0 && (
              <div className="forum-post-image-grid">
                {thread.image_urls.map((imageUrl, index) => (
                  <img
                    key={`${thread.id}-image-${index}`}
                    src={imageUrl}
                    alt={`${thread.title} ${index + 1}`}
                    className="forum-post-image"
                  />
                ))}
              </div>
            )}
            <div className="forum-thread-body forum-post-body">
              {thread.body.split('\n').map((paragraph, index) => (
                <p key={`${thread.id}-body-${index}`}>{paragraph}</p>
              ))}
            </div>
            {renderReplyComposer('thread-main')}
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
              <div className="button-row">
                <button type="submit" className="btn-primary" disabled={submittingComment}>
                  {submittingComment ? 'Posting...' : 'Post Comment'}
                </button>
              </div>
            </form>
          </section>

          <section className="forum-answer-list">
            {thread.thread_comments.length === 0 ? (
              <div className="empty-state compact-empty">
                <p>No comments yet. You can be the first person to join this discussion.</p>
              </div>
            ) : (
              thread.thread_comments.map((comment) => renderComment(comment))
            )}
          </section>
        </section>
      </div>
    </div>
  )
}
