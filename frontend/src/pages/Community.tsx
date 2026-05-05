import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createPipeline,
  getPipeline,
  getSharedPipelines,
  Pipeline,
  PipelineCreate,
  reportPipeline,
  votePipeline,
} from '../services/pipelineService'
import { getToken } from '../services/authService'
import { getAvailableTools } from '../services/toolService'
import Navigation from '../components/Navigation'
import ReportDialog from '../components/ReportDialog'
import SortDropdown from '../components/SortDropdown'
import '../styles/globals.css'

interface ToolFilterOption {
  key: string
  name: string
  type: string
}

const formatToolTypeLabel = (toolType: string): string => {
  const normalized = String(toolType || '').trim().toLowerCase()
  if (!normalized) return 'Unknown'
  if (normalized === 'qc') return 'Quality Control'
  if (normalized === 'transform') return 'Assembly'
  return normalized
    .split(/[_\s-]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export default function Community() {
  const ITEMS_PER_PAGE = 10
  const navigate = useNavigate()
  const [allPipelines, setAllPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [sortBy, setSortBy] = useState<'recent' | 'popular'>('recent')
  const [error, setError] = useState<string>('')
  const [savingPipelineId, setSavingPipelineId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [toolFilterOpen, setToolFilterOpen] = useState(false)
  const [toolCatalog, setToolCatalog] = useState<ToolFilterOption[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [reportingPipeline, setReportingPipeline] = useState<Pipeline | null>(null)
  const [submittingReport, setSubmittingReport] = useState(false)
  const isAuthenticated = !!getToken()

  useEffect(() => {
    void loadPipelines()
  }, [sortBy])

  useEffect(() => {
    void loadToolCatalog()
  }, [])

  const loadPipelines = async () => {
    try {
      setLoading(true)
      setError('')
      const data = await getSharedPipelines(undefined, sortBy)
      setAllPipelines(data)
    } catch (err: any) {
      console.error('Failed to load shared pipelines:', err)
      const errorMessage = err.response?.data?.message || err.message || 'Failed to load community pipelines'
      setError(errorMessage)
      setAllPipelines([])
    } finally {
      setLoading(false)
    }
  }

  const loadToolCatalog = async () => {
    try {
      const tools = await getAvailableTools()
      setToolCatalog(
        tools
          .filter((tool) => tool.enabled)
          .map((tool) => ({
            key: `${tool.id}-${tool.name.toLowerCase()}`,
            name: tool.name,
            type: tool.type || 'unknown',
          }))
          .sort((a, b) => a.name.localeCompare(b.name))
      )
    } catch (err) {
      console.warn('Failed to load tool catalog for community filters', err)
      setToolCatalog([])
    }
  }

  const toolCatalogByName = useMemo(() => {
    const lookup = new Map<string, ToolFilterOption>()
    toolCatalog.forEach((tool) => {
      lookup.set(tool.name.trim().toLowerCase(), tool)
    })
    return lookup
  }, [toolCatalog])

  const availableTools = useMemo<ToolFilterOption[]>(() => {
    const labels = new Map<string, ToolFilterOption>()
    toolCatalog.forEach((tool) => labels.set(tool.key, tool))
    allPipelines.forEach((pipeline) => {
      ;(pipeline.tool_labels || []).forEach((toolLabel) => {
        const normalizedLabel = toolLabel.trim().toLowerCase()
        if (!normalizedLabel) return
        const matchedTool = Array.from(toolCatalogByName.values()).find((tool) => normalizedLabel.includes(tool.name.trim().toLowerCase()))
        const option = matchedTool || {
          key: `pipeline-${normalizedLabel}`,
          name: toolLabel,
          type: 'unknown',
        }
        labels.set(option.key, option)
      })
    })
    return Array.from(labels.values()).sort((a, b) => {
      const typeComparison = formatToolTypeLabel(a.type).localeCompare(formatToolTypeLabel(b.type))
      return typeComparison !== 0 ? typeComparison : a.name.localeCompare(b.name)
    })
  }, [allPipelines, toolCatalog, toolCatalogByName])

  const pipelines = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()

    const filtered = allPipelines.filter((pipeline) => {
      const normalizedPipelineToolLabels = (pipeline.tool_labels || []).map((toolLabel) => toolLabel.toLowerCase())
      const matchesSearch =
        !normalizedSearch ||
        pipeline.name.toLowerCase().includes(normalizedSearch) ||
        (pipeline.description || '').toLowerCase().includes(normalizedSearch) ||
        normalizedPipelineToolLabels.some((toolLabel) => toolLabel.includes(normalizedSearch))

      const matchesTool =
        selectedTools.length === 0 ||
        selectedTools.some((selectedToolKey) => {
          const selectedTool = availableTools.find((tool) => tool.key === selectedToolKey)
          if (!selectedTool) return false

          const normalizedSelectedName = selectedTool.name.toLowerCase()
          const normalizedSelectedType = selectedTool.type.toLowerCase()
          return normalizedPipelineToolLabels.some((toolLabel) => {
            if (
              toolLabel === normalizedSelectedName ||
              toolLabel.includes(normalizedSelectedName) ||
              normalizedSelectedName.includes(toolLabel)
            ) {
              return true
            }

            const matchedCatalogEntry = Array.from(toolCatalogByName.values()).find((tool) =>
              toolLabel.includes(tool.name.trim().toLowerCase())
            )
            return Boolean(
              matchedCatalogEntry &&
              matchedCatalogEntry.type.toLowerCase() === normalizedSelectedType &&
              matchedCatalogEntry.name.toLowerCase() === normalizedSelectedName
            )
          })
        })

      return matchesSearch && matchesTool
    })

    return filtered
  }, [allPipelines, availableTools, search, selectedTools, sortBy, toolCatalogByName])

  useEffect(() => {
    setCurrentPage(1)
  }, [search, selectedTools, sortBy])

  const totalPages = Math.max(1, Math.ceil(pipelines.length / ITEMS_PER_PAGE))
  const currentPageSafe = Math.min(currentPage, totalPages)

  const paginatedPipelines = useMemo(() => {
    const startIndex = (currentPageSafe - 1) * ITEMS_PER_PAGE
    return pipelines.slice(startIndex, startIndex + ITEMS_PER_PAGE)
  }, [currentPageSafe, pipelines])

  const communityPageButtons = useMemo(() => {
    if (totalPages <= 1) {
      return [1]
    }

    const pages = new Set<number>([1, totalPages, currentPageSafe, currentPageSafe - 1, currentPageSafe + 1])
    return Array.from(pages)
      .filter((page) => page >= 1 && page <= totalPages)
      .sort((a, b) => a - b)
  }, [currentPageSafe, totalPages])

  const toggleToolFilter = (toolKey: string) => {
    setSelectedTools((current) =>
      current.includes(toolKey)
        ? current.filter((item) => item !== toolKey)
        : [...current, toolKey]
    )
  }

  const handleViewPipeline = (pipelineId: number) => {
    navigate(`/pipelines/builder/${pipelineId}`)
  }

  const applyPipelineEngagement = (pipelineId: number, summary: { upvote_count: number; downvote_count: number; score: number; user_vote?: 'upvote' | 'downvote' | null }) => {
    setAllPipelines((current) =>
      current.map((pipeline) =>
        pipeline.id === pipelineId
          ? {
              ...pipeline,
              ...summary,
            }
          : pipeline
      )
    )
  }

  const handleSavePipeline = async (pipelineId: number, e: React.MouseEvent) => {
    e.stopPropagation()

    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    try {
      setSavingPipelineId(pipelineId)

      const sharedPipeline = await getPipeline(pipelineId)
      const pipelineData: PipelineCreate = {
        name: `${sharedPipeline.name} (Copy)`,
        description: sharedPipeline.description
          ? `${sharedPipeline.description} (Copied from community)`
          : 'Copied from community',
        nodes: sharedPipeline.nodes,
        edges: sharedPipeline.edges,
      }

      const newPipeline = await createPipeline(pipelineData)
      alert(`Pipeline "${newPipeline.name}" has been saved to your pipelines!`)
      navigate('/pipelines')
    } catch (err: any) {
      console.error('Failed to save pipeline:', err)
      const errorMessage = err.response?.data?.message || err.message || 'Failed to save pipeline'
      alert(`Error: ${errorMessage}`)
    } finally {
      setSavingPipelineId(null)
    }
  }

  const handleVotePipeline = async (pipelineId: number, voteType: 'upvote' | 'downvote', e: React.MouseEvent) => {
    e.stopPropagation()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }

    try {
      const summary = await votePipeline(pipelineId, voteType)
      applyPipelineEngagement(pipelineId, summary)
    } catch (err: any) {
      alert(err.message || 'Failed to vote on pipeline')
    }
  }

  const openReportPipeline = (pipeline: Pipeline, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    setReportingPipeline(pipeline)
  }

  const handleReportPipeline = async (payload: { reason: string; details?: string }) => {
    if (!reportingPipeline) {
      return
    }
    try {
      setSubmittingReport(true)
      await reportPipeline(reportingPipeline.id, payload)
      setReportingPipeline(null)
      alert('Pipeline reported to the admin team.')
    } catch (err: any) {
      alert(err.message || 'Failed to report pipeline')
    } finally {
      setSubmittingReport(false)
    }
  }

  const renderVoteButton = (
    pipeline: Pipeline,
    voteType: 'upvote' | 'downvote',
    count: number
  ) => {
    const isActive = pipeline.user_vote === voteType
    const label = voteType === 'upvote' ? 'Upvote' : 'Downvote'
    const icon = voteType === 'upvote' ? '▲' : '▼'

    return (
      <button
        type="button"
        onClick={(e) => handleVotePipeline(pipeline.id, voteType, e)}
        className={`engagement-symbol-button engagement-vote-button engagement-symbol-${voteType} ${isActive ? 'active' : ''}`}
        aria-label={`${label} pipeline ${pipeline.name}`}
        title={isActive ? `Take back ${label.toLowerCase()}` : label}
      >
        <span className="engagement-vote-icon" aria-hidden="true">{icon}</span>
        <span className="engagement-vote-label">{label}</span>
        <span className="engagement-vote-count">{count}</span>
      </button>
    )
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <section className="card profile-community-card profile-community-main">
          <div className="section-heading">
            <h2>Search Community Pipelines</h2>
          </div>
          <div className="community-search-row">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="community-search-input"
              placeholder="Search pipeline name or tool, for example: spades, quast, fastqc"
            />
            <SortDropdown
              id="community-sort"
              label="Sort by"
              value={sortBy}
              options={[
                { value: 'recent', label: 'Most Recent' },
                { value: 'popular', label: 'Most Popular' },
              ]}
              onChange={(value) => setSortBy(value as 'recent' | 'popular')}
            />
            <div className="community-tool-dropdown">
              <button
                type="button"
                className="community-tool-dropdown-trigger"
                onClick={() => setToolFilterOpen((current) => !current)}
              >
                {selectedTools.length > 0 ? `Tools (${selectedTools.length})` : 'Filter Tools'}
              </button>
              {toolFilterOpen && availableTools.length > 0 && (
                <div className="community-tool-dropdown-panel">
                  {availableTools.map((tool) => (
                    <label key={tool.key} className="community-tool-filter-item">
                      <input
                        type="checkbox"
                        checked={selectedTools.includes(tool.key)}
                        onChange={() => toggleToolFilter(tool.key)}
                      />
                      <span>{tool.name} ({formatToolTypeLabel(tool.type)})</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
          {selectedTools.length > 0 && (
            <div className="community-filter-actions">
              <button
                type="button"
                className="btn-secondary btn-small"
                onClick={() => setSelectedTools([])}
              >
                Clear tool filters
              </button>
            </div>
          )}
          {!loading && (
            <div className="community-filter-summary">
              Showing {(paginatedPipelines.length > 0 ? (currentPageSafe - 1) * ITEMS_PER_PAGE + 1 : 0)}-
              {(currentPageSafe - 1) * ITEMS_PER_PAGE + paginatedPipelines.length} of {pipelines.length} matching shared pipeline{pipelines.length === 1 ? '' : 's'}.
            </div>
          )}
        </section>

        {loading ? (
          <div className="loading-state">Loading community pipelines...</div>
        ) : (
          <>
            {error && <div className="error-message">{error}</div>}

            {pipelines.length === 0 && !error ? (
              <div className="empty-state">
                <p>No community pipelines matched your filters.</p>
                <p className="empty-state-secondary">
                  Try a broader name, clear the tool filter, or search for a different tool label.
                </p>
              </div>
            ) : (
              <div className="community-results-grid">
                {paginatedPipelines.map((pipeline) => (
                  <div
                    key={pipeline.id}
                    className="card pipeline-card pipeline-card-immersive"
                    onClick={() => handleViewPipeline(pipeline.id)}
                  >
                    <button
                      type="button"
                      className="engagement-symbol-button engagement-symbol-report pipeline-report-button"
                      onClick={(e) => openReportPipeline(pipeline, e)}
                      aria-label={`Report pipeline ${pipeline.name}`}
                      title="Report"
                    >
                      !
                    </button>
                    <h3 className="pipeline-card-title">{pipeline.name}</h3>
                    {pipeline.description && (
                      <p className="pipeline-card-description">
                        {pipeline.description}
                      </p>
                    )}

                    {pipeline.tool_labels && pipeline.tool_labels.length > 0 && (
                      <div className="profile-mini-meta" style={{ marginTop: '0.25rem' }}>
                        {pipeline.tool_labels.map((toolLabel) => (
                          <span key={`${pipeline.id}-${toolLabel}`}>{toolLabel}</span>
                        ))}
                      </div>
                    )}

                    {pipeline.publisher && (
                      <button
                        type="button"
                        className="community-publisher-card"
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(`/profile/${pipeline.publisher?.id}`)
                        }}
                      >
                        {pipeline.publisher.avatar_url ? (
                          <img
                            className="community-publisher-avatar"
                            src={pipeline.publisher.avatar_url}
                            alt={pipeline.publisher.username}
                          />
                        ) : (
                          <span className="community-publisher-avatar community-publisher-avatar-fallback">
                            {(pipeline.publisher.display_name || pipeline.publisher.username).slice(0, 1).toUpperCase()}
                          </span>
                        )}
                        <span className="community-publisher-text">
                          <strong>{pipeline.publisher.display_name || pipeline.publisher.username}</strong>
                          <small>
                            @{pipeline.publisher.username}
                            {pipeline.publisher.affiliation ? ` | ${pipeline.publisher.affiliation}` : ''}
                          </small>
                        </span>
                      </button>
                    )}

                    <div className="pipeline-card-footer">
                      <div className="community-engagement-bar">
                        <div className="community-engagement-actions engagement-vote-cluster">
                          {renderVoteButton(pipeline, 'upvote', pipeline.upvote_count || 0)}
                          {renderVoteButton(pipeline, 'downvote', pipeline.downvote_count || 0)}
                        </div>
                      </div>

                      <div className="pipeline-card-meta">
                        <span className="pipeline-card-date">
                          {new Date(pipeline.saved_at).toLocaleDateString()}
                        </span>
                        <div className="button-row compact-actions">
                          {isAuthenticated ? (
                            <>
                              <button
                                onClick={(e) => handleSavePipeline(pipeline.id, e)}
                                disabled={savingPipelineId === pipeline.id}
                                className="btn-secondary"
                              >
                                {savingPipelineId === pipeline.id ? 'Saving...' : 'Save'}
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  navigate('/login')
                                }}
                                className="btn-secondary"
                              >
                                Login to Save
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {pipelines.length > ITEMS_PER_PAGE && (
              <nav className="forum-pagination forum-list-pagination community-pagination" aria-label="Community pages">
                <button
                  type="button"
                  className="btn-secondary btn-small forum-page-arrow"
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={currentPageSafe === 1}
                  aria-label="Previous community page"
                >
                  &larr;
                </button>
                {communityPageButtons.map((pageNumber, index) => {
                  const previousPage = communityPageButtons[index - 1]
                  const showGap = previousPage && pageNumber - previousPage > 1

                  return (
                    <span key={`community-page-${pageNumber}`} className="forum-pagination-cluster">
                      {showGap && <span className="forum-page-ellipsis">...</span>}
                      <button
                        type="button"
                        className={`btn-secondary btn-small forum-page-chip ${pageNumber === currentPageSafe ? 'active' : ''}`}
                        onClick={() => setCurrentPage(pageNumber)}
                        aria-current={pageNumber === currentPageSafe ? 'page' : undefined}
                      >
                        {pageNumber}
                      </button>
                    </span>
                  )
                })}
                <button
                  type="button"
                  className="btn-secondary btn-small forum-page-arrow"
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  disabled={currentPageSafe === totalPages}
                  aria-label="Next community page"
                >
                  &rarr;
                </button>
              </nav>
            )}
          </>
        )}
        <ReportDialog
          isOpen={Boolean(reportingPipeline)}
          title="Report Pipeline"
          targetLabel="pipeline"
          submitting={submittingReport}
          onClose={() => {
            if (!submittingReport) {
              setReportingPipeline(null)
            }
          }}
          onSubmit={handleReportPipeline}
        />
      </div>
    </div>
  )
}
