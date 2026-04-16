import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSharedPipelines, getPipeline, createPipeline, Pipeline, PipelineCreate } from '../services/pipelineService'
import { getToken } from '../services/authService'
import { STARTER_PIPELINE_TEMPLATES, StarterPipelineTemplate } from '../services/starterPipelines'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function Community() {
  const navigate = useNavigate()
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [savingPipelineId, setSavingPipelineId] = useState<number | null>(null)
  const isAuthenticated = !!getToken()

  useEffect(() => {
    loadPipelines()
  }, [])

  const loadPipelines = async () => {
    try {
      setLoading(true)
      setError('')
      const data = await getSharedPipelines()
      setPipelines(data)
    } catch (err: any) {
      console.error('Failed to load shared pipelines:', err)
      const errorMessage = err.response?.data?.message || err.message || 'Failed to load community pipelines'
      setError(errorMessage)
      setPipelines([])
    } finally {
      setLoading(false)
    }
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
        edges: sharedPipeline.edges
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

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <div className="loading-state">Loading community pipelines...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <section className="feature-hero">
          <div className="feature-hero-copy">
            <span className="page-kicker">Community</span>
            <h1 className="page-title">Discover workflows other researchers decided were worth sharing.</h1>
            <p className="dashboard-subtitle">
              Browse public pipelines, open a template, or save a copy into your own
              workspace to iterate from a solid starting point.
            </p>
          </div>
          <div className="hero-info-card">
            <span className="hero-stat-label">How this page helps</span>
            <div className="hero-stat-grid">
              <div>
                <strong>Discover</strong>
                <span>See what the community is already using in practice.</span>
              </div>
              <div>
                <strong>Reuse</strong>
                <span>Copy a shared workflow into your own collection.</span>
              </div>
              <div>
                <strong>Bootstrap</strong>
                <span>Open curated starter templates even before the catalog grows.</span>
              </div>
            </div>
          </div>
        </section>

        {error && <div className="error-message">{error}</div>}

        {pipelines.length === 0 && !error ? (
          <div className="empty-state">
            <p>No shared pipelines are published yet.</p>
            <p className="empty-state-secondary">
              Starter templates are available below so the page stays useful even before the first community share.
            </p>
            <div className="pipeline-grid pipeline-grid-showcase">
              {STARTER_PIPELINE_TEMPLATES.map((template) => (
                <div key={template.id} className="card pipeline-card pipeline-card-immersive">
                  <span className="dashboard-card-eyebrow">Starter Template</span>
                  <h3 className="pipeline-card-title">{template.name}</h3>
                  <p className="pipeline-card-description">{template.description}</p>
                  <div className="button-row compact-actions">
                    <button
                      onClick={() => handleUseTemplate(template)}
                      className="btn-primary"
                    >
                      Open Template
                    </button>
                    {isAuthenticated && (
                      <button
                        onClick={() => handleUseTemplate(template)}
                        className="btn-secondary"
                      >
                        Customize
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="pipeline-grid pipeline-grid-showcase">
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
      </div>
    </div>
  )
}
