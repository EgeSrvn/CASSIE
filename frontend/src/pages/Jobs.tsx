import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getJobs, Job, deleteJob, cancelJob } from '../services/jobService'
import { getToken } from '../services/authService'
import { clearPendingJobUploads } from '../services/pendingJobUploadService'
import { formatLocalDateTime } from '../utils/dateTime'
import Navigation from '../components/Navigation'
import VmCapacitySection from '../components/VmCapacitySection'
import TrashIcon from '../components/TrashIcon'
import '../styles/globals.css'

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [actioningJobId, setActioningJobId] = useState<number | null>(null)
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
      await clearPendingJobUploads(jobId)
      loadJobs()
    } catch (err: any) {
      alert(err.message || 'Failed to delete job')
    }
  }

  const handleCancel = async (job: Job) => {
    if (!confirm(`Cancel job "${job.name}"? Running Kubernetes stages will be stopped, but the job will stay in your list.`)) return

    try {
      setActioningJobId(job.id)
      await cancelJob(job.id)
      await loadJobs()
    } catch (err: any) {
      alert(err.message || 'Failed to cancel job')
    } finally {
      setActioningJobId(null)
    }
  }

  const handleRetry = async (job: Job) => {
    navigate('/jobs/create', { state: { retryJobId: job.id } })
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'status-completed'
      case 'running': return 'status-running'
      case 'failed': return 'status-failed'
      case 'pending': return 'status-pending'
      case 'cancelled': return 'status-failed'
      default: return ''
    }
  }

  return (
    <div className="page-container jobs-classic-page">
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

        {isAuthenticated && <VmCapacitySection />}

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
              <option value="cancelled">Cancelled</option>
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
                  <p><strong>Created:</strong> {formatLocalDateTime(job.created_at)}</p>
                  {job.updated_at && (
                    <p><strong>Updated:</strong> {formatLocalDateTime(job.updated_at)}</p>
                  )}
                </div>
                <div className="job-actions">
                  <button
                    onClick={() => navigate(`/jobs/${job.id}`)}
                    className="btn-primary"
                  >
                    View Details
                  </button>
                  {(job.status === 'failed' || job.status === 'cancelled') && (
                    <button
                      onClick={() => handleRetry(job)}
                      className="btn-primary"
                    >
                      Retry Job
                    </button>
                  )}
                  {(job.status === 'pending' || job.status === 'running') && (
                    <button
                      onClick={() => handleCancel(job)}
                      className="btn-soft-cancel"
                      disabled={actioningJobId === job.id}
                    >
                      {actioningJobId === job.id ? 'Cancelling...' : 'Cancel Job'}
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(job.id)}
                    className="icon-button icon-button-danger"
                    aria-label={`Delete job ${job.name}`}
                    title="Delete job"
                  >
                    <TrashIcon />
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
