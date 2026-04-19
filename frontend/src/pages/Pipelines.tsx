import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPipelines, deletePipeline, sharePipeline, unsharePipeline, Pipeline } from '../services/pipelineService'
import { getToken } from '../services/authService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function Pipelines() {
  const navigate = useNavigate()
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [authRequired, setAuthRequired] = useState(false)
  const isAuthenticated = !!getToken()

  const handleCreatePipeline = () => {
    if (isAuthenticated) {
      navigate('/pipelines/builder')
    } else {
      navigate('/login')
    }
  }

  useEffect(() => {
    loadPipelines()
  }, [])

  const loadPipelines = async () => {
    try {
      setLoading(true)
      setError('')
      setAuthRequired(false)
      const data = await getPipelines()
      setPipelines(data)
    } catch (err: any) {
      console.error('Failed to load pipelines:', err)
      if (err.response?.status === 401) {
        setAuthRequired(true)
        setPipelines([])
      } else {
        setError(err.response?.data?.message || err.message || 'Failed to load pipelines')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this pipeline?')) {
      return
    }

    try {
      setDeleting(id)
      await deletePipeline(id)
      await loadPipelines()
    } catch (err: any) {
      console.error('Failed to delete pipeline:', err)
      alert(`Failed to delete pipeline: ${err.message || 'Unknown error'}`)
    } finally {
      setDeleting(null)
    }
  }

  const handleShare = async (id: number, isShared: boolean) => {
    try {
      if (isShared) {
        await unsharePipeline(id)
      } else {
        await sharePipeline(id)
      }
      await loadPipelines()
    } catch (err: any) {
      console.error('Failed to share/unshare pipeline:', err)
      alert(`Failed to ${isShared ? 'unshare' : 'share'} pipeline: ${err.message || 'Unknown error'}`)
    }
  }

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">Loading pipelines...</div>
      </div>
    )
  }

  return (
    <div className="page-container pipelines-classic-page">
      <Navigation />
      <div className="page-content">
        <header className="page-header">
          <h1 className="page-title">Pipelines</h1>
          <div className="header-actions">
            <button type="button" onClick={() => navigate('/pipelines/templates')} className="btn-secondary">
              Starter Templates
            </button>
            <button onClick={handleCreatePipeline} className="btn-primary">
              {isAuthenticated ? 'Create New Pipeline' : 'Login to Create Pipeline'}
            </button>
          </div>
        </header>

        <div className="jobs-page-content">
          {error && <div className="error-message">{error}</div>}

          {pipelines.length === 0 ? (
            <div className="empty-state">
              <p>
                {authRequired || !isAuthenticated
                  ? 'Login to view and save your own pipelines.'
                  : 'No pipelines yet. Create your first pipeline or start from a starter template.'}
              </p>
              <button onClick={handleCreatePipeline} className="btn-primary">
                {isAuthenticated ? 'Create Pipeline' : 'Login to Create Pipeline'}
              </button>
            </div>
          ) : (
            <div className="jobs-grid">
              {pipelines.map((pipeline) => (
                <div key={pipeline.id} className="job-card pipeline-list-card">
                  <div className="job-header">
                    <h3>{pipeline.name}</h3>
                    <span className={`status-badge ${pipeline.is_shared ? 'status-completed' : 'status-pending'}`}>
                      {pipeline.is_shared ? 'Shared' : 'Private'}
                    </span>
                  </div>
                  {pipeline.description && (
                    <p className="pipeline-card-description">{pipeline.description}</p>
                  )}
                  <div className="job-details">
                    <p><strong>Pipeline ID:</strong> {pipeline.id}</p>
                    <p><strong>Created:</strong> {new Date(pipeline.saved_at).toLocaleDateString()}</p>
                  </div>
                  <div className="job-actions pipeline-card-actions">
                    <button
                      onClick={() => navigate(`/pipelines/builder/${pipeline.id}`)}
                      className="btn-secondary"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => navigate('/jobs/create', { state: { pipelineId: pipeline.id } })}
                      className="btn-primary"
                    >
                      Use in Job
                    </button>
                    {isAuthenticated && (
                      <button
                        onClick={() => handleShare(pipeline.id, pipeline.is_shared || false)}
                        className="btn-secondary"
                        style={{
                          backgroundColor: pipeline.is_shared ? 'var(--success)' : 'var(--gray-300)',
                          color: pipeline.is_shared ? 'white' : 'var(--gray-700)'
                        }}
                        title={pipeline.is_shared ? 'Shared with community' : 'Share with community'}
                      >
                        {pipeline.is_shared ? 'Shared' : 'Share'}
                      </button>
                    )}
                    {isAuthenticated && (
                      <button
                        onClick={() => handleDelete(pipeline.id)}
                        disabled={deleting === pipeline.id}
                        className="btn-danger"
                      >
                        {deleting === pipeline.id ? 'Deleting...' : 'Delete'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
