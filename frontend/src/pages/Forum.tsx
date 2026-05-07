import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Navigation from '../components/Navigation'
import ReportDialog from '../components/ReportDialog'
import SortDropdown from '../components/SortDropdown'
import {
  ForumThreadSummary,
  listForumThreads,
  reportForumThread,
  voteForumThread,
} from '../services/forumService'
import { getStoredUser, getToken } from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import '../styles/globals.css'

export default function Forum() {
  const navigate = useNavigate()
  const isAuthenticated = !!getToken()
  const [threads, setThreads] = useState<ForumThreadSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'recent' | 'popular'>('recent')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [reportingThread, setReportingThread] = useState<ForumThreadSummary | null>(null)
  const [submittingReport, setSubmittingReport] = useState(false)
  const currentUserId = getStoredUser()?.id ?? null

  useEffect(() => {
    void loadThreads()
  }, [search, page, sortBy])

  const buildVisiblePages = () => {
    const pages = new Set<number>([1, 2, 3, page, page + 1, totalPages])
    return Array.from(pages)
      .filter((value) => value >= 1 && value <= totalPages)
      .sort((a, b) => a - b)
  }

  const loadThreads = async () => {
    try {
      setLoading(true)
      setError('')
      const response = await listForumThreads(search, page, 10, sortBy)
      const nextTotalPages = Math.max(1, Math.ceil(response.total / response.per_page))
      if (page > nextTotalPages) {
        setPage(nextTotalPages)
        return
      }
      setThreads(response.items)
      setTotalPages(nextTotalPages)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to load forum threads'))
      setThreads([])
    } finally {
      setLoading(false)
    }
  }

  const applyThreadEngagement = (threadId: number, summary: { upvote_count: number; downvote_count: number; score: number; user_vote?: 'upvote' | 'downvote' | null }) => {
    setThreads((current) =>
      current.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              ...summary,
            }
          : thread
      )
    )
  }

  const handleVoteThread = async (threadId: number, voteType: 'upvote' | 'downvote', event: React.MouseEvent) => {
    event.stopPropagation()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    try {
      const summary = await voteForumThread(threadId, voteType)
      applyThreadEngagement(threadId, summary)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to vote on forum post'))
    }
  }

  const openReportThread = async (thread: ForumThreadSummary, event: React.MouseEvent) => {
    event.stopPropagation()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    if (thread.author.id === currentUserId) {
      return
    }
    setReportingThread(thread)
  }

  const handleReportThread = async (payload: { reason: string; details?: string }) => {
    if (!reportingThread) {
      return
    }
    try {
      setSubmittingReport(true)
      await reportForumThread(reportingThread.id, payload)
      setReportingThread(null)
      alert('Forum post reported to the admin team.')
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to report forum post'))
    } finally {
      setSubmittingReport(false)
    }
  }

  const renderVoteButton = (
    thread: ForumThreadSummary,
    voteType: 'upvote' | 'downvote',
    count: number
  ) => {
    const isActive = thread.user_vote === voteType
    const label = voteType === 'upvote' ? 'Upvote' : 'Downvote'
    const icon = voteType === 'upvote' ? '▲' : '▼'

    return (
      <button
        type="button"
        className={`engagement-symbol-button engagement-vote-button engagement-symbol-${voteType} ${isActive ? 'active' : ''}`}
        onClick={(event) => handleVoteThread(thread.id, voteType, event)}
        aria-label={`${label} thread ${thread.title}`}
        title={isActive ? `Take back ${label.toLowerCase()}` : label}
      >
        <span className="engagement-vote-icon" aria-hidden="true">{icon}</span>
        <span className="engagement-vote-count">{count}</span>
      </button>
    )
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content forum-page">
        <section className="card forum-page-header-card">
          <div className="section-heading forum-page-heading">
            <h2>Forum Discussions</h2>
          </div>
          <div className="community-search-row forum-search-row">
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              className="community-search-input"
              placeholder="Search forum discussions"
            />
            <SortDropdown
              id="forum-sort"
              label="Sort by"
              value={sortBy}
              options={[
                { value: 'recent', label: 'Most Recent' },
                { value: 'popular', label: 'Most Popular' },
              ]}
              onChange={(value) => {
                setSortBy(value as 'recent' | 'popular')
                setPage(1)
              }}
            />
            <button type="button" className="btn-primary" onClick={() => navigate('/forum/new')}>
              New Discussion
            </button>
          </div>
        </section>

        {error && <div className="error-message">{error}</div>}

        <section className="forum-thread-list">
          {loading ? (
            <div className="loading-state">Loading forum discussions...</div>
          ) : threads.length === 0 ? (
            <div className="empty-state">
              <p>No forum discussions matched your search.</p>
            </div>
          ) : (
            threads.map((thread) => (
              <article
                key={thread.id}
                className="card forum-thread-card"
                onClick={() => navigate(`/forum/${thread.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    navigate(`/forum/${thread.id}`)
                  }
                }}
              >
                {thread.author.id !== currentUserId && (
                  <button
                    type="button"
                    className="engagement-symbol-button engagement-symbol-report forum-report-corner-button"
                    onClick={(event) => void openReportThread(thread, event)}
                    aria-label={`Report thread ${thread.title}`}
                    title="Report"
                  >
                    !
                  </button>
                )}
                <div className="forum-thread-topline">
                  <span>{new Date(thread.last_activity_at).toLocaleString()}</span>
                </div>
                <h3>{thread.title}</h3>
                <p>{thread.body}</p>
                <div className="forum-thread-meta">
                  <button
                    type="button"
                    className="community-publisher-card forum-author-card"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/profile/${thread.author.id}`)
                    }}
                  >
                    {thread.author.avatar_url ? (
                      <img className="community-publisher-avatar" src={thread.author.avatar_url} alt={thread.author.username} />
                    ) : (
                      <span className="community-publisher-avatar community-publisher-avatar-fallback">
                        {(thread.author.display_name || thread.author.username).slice(0, 1).toUpperCase()}
                      </span>
                    )}
                    <span className="community-publisher-text">
                      <strong>{thread.author.display_name || thread.author.username}</strong>
                      <small>@{thread.author.username}</small>
                    </span>
                  </button>
                  <div className="forum-thread-stats">
                    <div className="forum-thread-engagement-stack">
                      <div className="engagement-vote-cluster engagement-vote-cluster-compact">
                        {renderVoteButton(thread, 'upvote', thread.upvote_count)}
                        {renderVoteButton(thread, 'downvote', thread.downvote_count)}
                      </div>
                      <span className="forum-comment-count-under-votes">
                        {thread.comment_count} comment{thread.comment_count === 1 ? '' : 's'}
                      </span>
                    </div>
                  </div>
                </div>
              </article>
            ))
          )}
        </section>
        {totalPages > 1 && (
          <nav className="forum-pagination forum-list-pagination" aria-label="Forum pages">
            <button
              type="button"
              className="btn-secondary btn-small forum-page-arrow"
              disabled={page === 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              aria-label="Previous page"
            >
              ←
            </button>
            {buildVisiblePages().map((pageNumber, index, pages) => (
              <span key={`forum-page-${pageNumber}`} className="forum-pagination-cluster">
                {index > 0 && pageNumber - pages[index - 1] > 1 ? <span className="forum-page-ellipsis">…</span> : null}
                <button
                  type="button"
                  className={`btn-secondary btn-small forum-page-chip ${page === pageNumber ? 'active' : ''}`}
                  onClick={() => setPage(pageNumber)}
                >
                  {pageNumber}
                </button>
              </span>
            ))}
            <button
              type="button"
              className="btn-secondary btn-small forum-page-arrow"
              disabled={page === totalPages}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              aria-label="Next page"
            >
              →
            </button>
          </nav>
        )}
        <ReportDialog
          isOpen={Boolean(reportingThread)}
          title="Report Forum Post"
          targetLabel="forum post"
          submitting={submittingReport}
          onClose={() => {
            if (!submittingReport) {
              setReportingThread(null)
            }
          }}
          onSubmit={handleReportThread}
        />
      </div>
    </div>
  )
}
