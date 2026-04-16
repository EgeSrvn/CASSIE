import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Navigation from '../components/Navigation'
import { ForumThreadSummary, listForumThreads } from '../services/forumService'
import '../styles/globals.css'

export default function Forum() {
  const navigate = useNavigate()
  const [threads, setThreads] = useState<ForumThreadSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    void loadThreads()
  }, [search])

  const loadThreads = async () => {
    try {
      setLoading(true)
      setError('')
      const response = await listForumThreads(search, 1, 10)
      setThreads(response.items)
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Failed to load forum threads')
      setThreads([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content forum-page">
        <section className="card forum-page-header-card">
          <div className="section-heading forum-page-heading">
            <h2>Forum Discussions</h2>
            <p>The latest 10 discussions appear here. Search uses partial matching across titles and text.</p>
          </div>
          <div className="community-search-row forum-search-row">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="community-search-input"
              placeholder="Search forum discussions"
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
              <button
                key={thread.id}
                type="button"
                className="card forum-thread-card"
                onClick={() => navigate(`/forum/${thread.id}`)}
              >
                <div className="forum-thread-topline">
                  <span className="entry-badge">Discussion</span>
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
                    <span>{thread.comment_count} comment{thread.comment_count === 1 ? '' : 's'}</span>
                    <span>{thread.view_count} view{thread.view_count === 1 ? '' : 's'}</span>
                  </div>
                </div>
              </button>
            ))
          )}
        </section>
      </div>
    </div>
  )
}
