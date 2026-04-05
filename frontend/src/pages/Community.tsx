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
    if (isAuthenticated) {
      navigate(`/pipelines/builder/${pipelineId}`)
    } else {
      navigate('/login')
    }
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
        <header className="page-header">
          <h1 className="page-title">Community Pipelines</h1>
          <p style={{ color: 'var(--gray-600)', marginTop: '0.5rem' }}>
            Browse and discover pipelines shared by the community
            {isAuthenticated && ' - Click "Save" to add any pipeline to your collection'}
          </p>
        </header>

        {error && <div className="error-message">{error}</div>}

        {pipelines.length === 0 && !error ? (
          <div className="empty-state">
            <p>No shared pipelines are published yet.</p>
            <p style={{ marginTop: '1rem', color: 'var(--gray-600)' }}>
              Starter templates are available below so the page stays useful even before the first community share.
            </p>
            <div className="pipeline-grid" style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: '1.5rem',
              marginTop: '2rem',
              width: '100%'
            }}>
              {STARTER_PIPELINE_TEMPLATES.map((template) => (
                <div key={template.id} className="card pipeline-card" style={{
                  background: 'var(--bg-primary)',
                  borderRadius: 'var(--radius-lg)',
                  padding: 'var(--spacing-xl)',
                  boxShadow: 'var(--shadow-md)',
                  border: '1px solid var(--gray-200)'
                }}>
                  <h3 className="pipeline-card-title" style={{
                    fontSize: '1.25rem',
                    fontWeight: '600',
                    color: 'var(--primary)',
                    marginBottom: '0.75rem'
                  }}>
                    {template.name}
                  </h3>
                  <p className="pipeline-card-description" style={{
                    color: 'var(--gray-600)',
                    marginBottom: '1rem',
                    lineHeight: '1.6'
                  }}>
                    {template.description}
                  </p>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={() => handleUseTemplate(template)}
                      className="btn-primary"
                      style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                    >
                      Open Template
                    </button>
                    {isAuthenticated && (
                      <button
                        onClick={() => handleUseTemplate(template)}
                        className="btn-secondary"
                        style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
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
          <div className="pipeline-grid" style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
            gap: '1.5rem'
          }}>
            {pipelines.map((pipeline) => (
              <div
                key={pipeline.id}
                className="card pipeline-card"
                style={{
                  background: 'var(--bg-primary)',
                  borderRadius: 'var(--radius-lg)',
                  padding: 'var(--spacing-xl)',
                  boxShadow: 'var(--shadow-md)',
                  border: '1px solid var(--gray-200)',
                  transition: 'all 0.3s ease',
                  cursor: 'pointer'
                }}
                onClick={() => handleViewPipeline(pipeline.id)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-4px)'
                  e.currentTarget.style.boxShadow = 'var(--shadow-lg)'
                  e.currentTarget.style.borderColor = 'var(--primary-light)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)'
                  e.currentTarget.style.boxShadow = 'var(--shadow-md)'
                  e.currentTarget.style.borderColor = 'var(--gray-200)'
                }}
              >
                <h3 className="pipeline-card-title" style={{
                  fontSize: '1.25rem',
                  fontWeight: '600',
                  color: 'var(--primary)',
                  marginBottom: '0.75rem'
                }}>
                  {pipeline.name}
                </h3>
                {pipeline.description && (
                  <p className="pipeline-card-description" style={{
                    color: 'var(--gray-600)',
                    marginBottom: '1rem',
                    lineHeight: '1.6'
                  }}>
                    {pipeline.description}
                  </p>
                )}
                <div className="pipeline-card-meta" style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: 'auto',
                  paddingTop: '1rem',
                  borderTop: '1px solid var(--gray-200)'
                }}>
                  <span className="pipeline-card-date" style={{
                    color: 'var(--gray-500)',
                    fontSize: '0.875rem'
                  }}>
                    {new Date(pipeline.saved_at).toLocaleDateString()}
                  </span>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    {isAuthenticated ? (
                      <>
                        <button
                          onClick={(e) => handleSavePipeline(pipeline.id, e)}
                          disabled={savingPipelineId === pipeline.id}
                          className="btn-secondary"
                          style={{
                            padding: '0.5rem 1rem',
                            fontSize: '0.875rem',
                            opacity: savingPipelineId === pipeline.id ? 0.6 : 1
                          }}
                        >
                          {savingPipelineId === pipeline.id ? 'Saving...' : 'Save'}
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleViewPipeline(pipeline.id)
                          }}
                          className="btn-primary"
                          style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                        >
                          View
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate('/login')
                        }}
                        className="btn-primary"
                        style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                      >
                        Login to View
                      </button>
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
