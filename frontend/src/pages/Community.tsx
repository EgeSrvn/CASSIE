import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createPipeline, getPipeline, getSharedPipelines, Pipeline, PipelineCreate } from '../services/pipelineService'
import { getToken } from '../services/authService'
import { STARTER_PIPELINE_TEMPLATES, StarterPipelineTemplate } from '../services/starterPipelines'
import { getAvailableTools } from '../services/toolService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function Community() {
  const navigate = useNavigate()
  const [allPipelines, setAllPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [savingPipelineId, setSavingPipelineId] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [toolFilterOpen, setToolFilterOpen] = useState(false)
  const [toolCatalog, setToolCatalog] = useState<string[]>([])
  const isAuthenticated = !!getToken()

  useEffect(() => {
    void loadPipelines()
    void loadToolCatalog()
  }, [])

  const loadPipelines = async () => {
    try {
      setLoading(true)
      setError('')
      const data = await getSharedPipelines()
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
          .map((tool) => tool.name)
          .sort((a, b) => a.localeCompare(b))
      )
    } catch (err) {
      console.warn('Failed to load tool catalog for community filters', err)
      setToolCatalog([])
    }
  }

  const availableTools = useMemo(() => {
    const labels = new Set<string>()
    toolCatalog.forEach((toolLabel) => labels.add(toolLabel))
    allPipelines.forEach((pipeline) => {
      ;(pipeline.tool_labels || []).forEach((toolLabel) => labels.add(toolLabel))
    })
    return Array.from(labels).sort((a, b) => a.localeCompare(b))
  }, [allPipelines, toolCatalog])

  const pipelines = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()

    return allPipelines.filter((pipeline) => {
      const matchesSearch =
        !normalizedSearch ||
        pipeline.name.toLowerCase().includes(normalizedSearch) ||
        (pipeline.description || '').toLowerCase().includes(normalizedSearch) ||
        (pipeline.tool_labels || []).some((toolLabel) => toolLabel.toLowerCase().includes(normalizedSearch))

      const matchesTool =
        selectedTools.length === 0 ||
        selectedTools.every((selectedTool) => (pipeline.tool_labels || []).some((toolLabel) => toolLabel === selectedTool))

      return matchesSearch && matchesTool
    })
  }, [allPipelines, search, selectedTools])

  const toggleToolFilter = (toolLabel: string) => {
    setSelectedTools((current) =>
      current.includes(toolLabel)
        ? current.filter((item) => item !== toolLabel)
        : [...current, toolLabel]
    )
  }

  const handleViewPipeline = (pipelineId: number) => {
    navigate(`/pipelines/builder/${pipelineId}`)
  }

  const handleUseTemplate = (template: StarterPipelineTemplate) => {
    navigate('/pipelines/builder', { state: { starterTemplate: template } })
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

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <section className="feature-hero">
          <div className="feature-hero-copy community-hero-copy">
            <span className="page-kicker">Community</span>

            <div className="community-template-strip">
              <div className="section-heading">
                <h2>Starter Templates</h2>
                <p>Start from a curated template directly from the top of the community workspace.</p>
              </div>
              <div className="community-template-grid">
                {STARTER_PIPELINE_TEMPLATES.map((template) => (
                  <div key={template.id} className="card pipeline-card community-template-card">
                    <h3 className="pipeline-card-title community-template-title">{template.name}</h3>
                    <p className="pipeline-card-description community-template-description">{template.description}</p>
                    <div className="pipeline-card-actions">
                      <button onClick={() => handleUseTemplate(template)} className="btn-secondary">
                        Open Template
                      </button>
                      {isAuthenticated && (
                        <button onClick={() => handleUseTemplate(template)} className="btn-primary">
                          Customize
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="hero-info-card">
            <span className="hero-stat-label">How this page helps</span>
            <div className="hero-stat-grid">
              <div>
                <strong>Search</strong>
                <span>Find workflows by partial pipeline names or tool labels.</span>
              </div>
              <div>
                <strong>Inspect</strong>
                <span>Open the shared pipeline or visit the publisher&apos;s profile.</span>
              </div>
              <div>
                <strong>Reuse</strong>
                <span>Copy a community workflow into your own private workspace.</span>
              </div>
            </div>
          </div>
        </section>

        <section className="card profile-community-card profile-community-main">
          <div className="section-heading">
            <h2>Search Community Pipelines</h2>
            <p>Search is applied instantly on the loaded catalog, and tool filtering lets you narrow the list without page flicker.</p>
          </div>
          <div className="community-search-row">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="community-search-input"
              placeholder="Search pipeline name or tool, for example: spades, quast, fastqc"
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
                  {availableTools.map((toolLabel) => (
                    <label key={toolLabel} className="community-tool-filter-item">
                      <input
                        type="checkbox"
                        checked={selectedTools.includes(toolLabel)}
                        onChange={() => toggleToolFilter(toolLabel)}
                      />
                      <span>{toolLabel}</span>
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
              Showing {pipelines.length} of {allPipelines.length} shared pipeline{allPipelines.length === 1 ? '' : 's'}.
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
                {pipelines.map((pipeline) => (
                  <div
                    key={pipeline.id}
                    className="card pipeline-card pipeline-card-immersive"
                    onClick={() => handleViewPipeline(pipeline.id)}
                  >
                    <span className="dashboard-card-eyebrow">Community Share</span>
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
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                handleViewPipeline(pipeline.id)
                              }}
                              className="btn-primary"
                            >
                              View
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
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                handleViewPipeline(pipeline.id)
                              }}
                              className="btn-primary"
                            >
                              View
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
