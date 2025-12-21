import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getJobs, Job, deleteJob } from '../services/jobService'
import { getToken } from '../services/authService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const navigate = useNavigate()
  const isAuthenticated = !!getToken()

  const handleCreateJob = () => {
    if (isAuthenticated) {
      navigate('/jobs/create')
    } else {
      navigate('/login')
    }
  }

  const loadJobs = async () => {
    try {
      setLoading(true)
      const response = await getJobs(statusFilter || undefined)
      setJobs(response.data || [])
      setError('')
    } catch (err: any) {
      if (err.response?.status === 401) {
        setError('Please login to view your jobs')
        setJobs([])
      } else {
        setError('Failed to load jobs')
        console.error(err)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadJobs()
  }, [statusFilter])

  const handleDelete = async (jobId: number) => {
    if (!confirm('Are you sure you want to delete this job?')) return
    
    try {
      await deleteJob(jobId)
      loadJobs()
    } catch (err) {
      alert('Failed to delete job')
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'status-completed'
      case 'running': return 'status-running'
      case 'failed': return 'status-failed'
      case 'pending': return 'status-pending'
      default: return ''
    }
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <header className="page-header">
          <h1 className="page-title">Jobs</h1>
          <div className="header-actions">
            <button onClick={handleCreateJob} className="btn-primary">
              {isAuthenticated ? 'Create New Job' : 'Login to Create Job'}
            </button>
          </div>
        </header>

      <div className="jobs-page-content">
        <div className="filters">
          <label>
            Filter by Status:
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <button onClick={loadJobs} className="btn-secondary">Refresh</button>
        </div>

        {error && <div className="error-message">{error}</div>}

        {loading && jobs.length === 0 ? (
          <div className="loading-state">Loading jobs...</div>
        ) : jobs.length === 0 ? (
          <div className="empty-state">
            <p>No jobs found. {isAuthenticated ? 'Create your first job to get started!' : 'Login to create jobs.'}</p>
            <button onClick={handleCreateJob} className="btn-primary">
              {isAuthenticated ? 'Create Job' : 'Login to Create Job'}
            </button>
          </div>
        ) : (
          <div className="jobs-grid">
            {jobs.map((job) => (
              <div key={job.id} className="job-card">
                <div className="job-header">
                  <h3>{job.name}</h3>
                  <span className={`status-badge ${getStatusColor(job.status)}`}>
                    {job.status}
                  </span>
                </div>
                <div className="job-details">
                  <p><strong>Job ID:</strong> {job.id}</p>
                  {job.workflow_id && (
                    <p><strong>Workflow ID:</strong> {job.workflow_id}</p>
                  )}
                  <p><strong>Created:</strong> {new Date(job.created_at).toLocaleString()}</p>
                  {job.updated_at && (
                    <p><strong>Updated:</strong> {new Date(job.updated_at).toLocaleString()}</p>
                  )}
                </div>
                <div className="job-actions">
                  <button
                    onClick={() => navigate(`/jobs/${job.id}`)}
                    className="btn-primary"
                  >
                    View Details
                  </button>
                  <button
                    onClick={() => handleDelete(job.id)}
                    className="btn-danger"
                  >
                    Delete
                  </button>
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

