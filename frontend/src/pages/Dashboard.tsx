import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import { getAvailableVMs, VM } from '../services/jobService'
import '../styles/globals.css'

interface DashboardProps {
  onLogout: () => void
}

export default function Dashboard({ onLogout }: DashboardProps) {
  const navigate = useNavigate()
  const [vmSummaries, setVmSummaries] = useState<VM[]>([])
  const [loadingVmSummaries, setLoadingVmSummaries] = useState(true)
  const [vmSummaryError, setVmSummaryError] = useState('')

  useEffect(() => {
    let cancelled = false

    const loadVmSummaries = async () => {
      try {
        setLoadingVmSummaries(true)
        setVmSummaryError('')
        const summaries = await getAvailableVMs()
        if (!cancelled) {
          setVmSummaries(summaries)
        }
      } catch (error: any) {
        if (!cancelled) {
          console.error('Failed to load VM capacity summaries:', error)
          setVmSummaries([])
          setVmSummaryError(error.message || 'Failed to load VM capacity summaries')
        }
      } finally {
        if (!cancelled) {
          setLoadingVmSummaries(false)
        }
      }
    }

    void loadVmSummaries()

    return () => {
      cancelled = true
    }
  }, [])

  const formatVmCpu = (cpuMillis: number) => `${(cpuMillis / 1000).toFixed(2)} cores`
  const formatVmMemory = (memoryMib: number) => `${(memoryMib / 1024).toFixed(2)} GiB`
  const formatVmStorage = (storageMib: number) => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'

  return (
    <div className="page-container">
      <Navigation onLogout={onLogout} />
      
      <div className="page-content">
        <header className="page-header dashboard-page-header">
          <h1 className="page-title">CASSIE Genomics Platform</h1>
        </header>

        <div className="dashboard-hero dashboard-hero-compact">
          <p className="dashboard-subtitle">
            Comprehensive genomic data analysis with multi-cloud support
          </p>
        </div>

      <div className="dashboard-cards-grid dashboard-cards-grid-four-up">
        <div className="dashboard-card">
          <h2 className="dashboard-card-title">Build Pipeline</h2>
          <p className="dashboard-card-description">
            Visually create and customize your analysis pipelines using our drag-and-drop builder.
          </p>
          <button
            onClick={() => navigate('/pipelines/builder')}
            className="btn-primary"
          >
            Build Pipeline
          </button>
        </div>

        <div className="dashboard-card">
          <h2 className="dashboard-card-title">Configure Job</h2>
          <p className="dashboard-card-description">
            Set up your analysis job with tool selection or use a saved pipeline configuration.
          </p>
          <button
            onClick={() => navigate('/jobs/create')}
            className="btn-primary"
          >
            Configure Job
          </button>
        </div>

        <div className="dashboard-card">
          <h2 className="dashboard-card-title">View Jobs</h2>
          <p className="dashboard-card-description">
            Monitor active jobs and access results from completed analyses.
          </p>
          <button
            onClick={() => navigate('/jobs')}
            className="btn-primary"
          >
            View Jobs
          </button>
        </div>

        <div className="dashboard-card">
          <h2 className="dashboard-card-title">View Pipelines</h2>
          <p className="dashboard-card-description">
            Browse, edit, and manage your saved pipeline configurations.
          </p>
          <button
            onClick={() => navigate('/pipelines')}
            className="btn-primary"
          >
            View Pipelines
          </button>
        </div>
      </div>

      <section className="dashboard-capacity-card">
        <div className="dashboard-capacity-header">
          <div>
            <p className="dashboard-capacity-kicker">Cluster Capacity</p>
            <h2>Remaining partitions by VM</h2>
          </div>
          <p>
            Track how many concurrent job slots are still open on each execution partition before starting a run.
          </p>
        </div>

        {loadingVmSummaries ? (
          <p className="dashboard-capacity-copy">Loading VM availability...</p>
        ) : vmSummaryError ? (
          <p className="dashboard-capacity-copy warning">{vmSummaryError}</p>
        ) : vmSummaries.length === 0 ? (
          <p className="dashboard-capacity-copy">No VM partitions are available right now.</p>
        ) : (
          <div className="dashboard-capacity-grid">
            {vmSummaries.map((vm) => (
              <article key={vm.name} className="dashboard-capacity-panel">
                <div className="dashboard-capacity-panel-head">
                  <strong>{vm.display_name}</strong>
                  <span>{vm.available_job_slots}/{vm.max_jobs} partitions remaining</span>
                </div>
                <div className="dashboard-capacity-stats">
                  <span>CPU: {formatVmCpu(vm.available_cpu_millis)}</span>
                  <span>Memory: {formatVmMemory(vm.available_memory_mib)}</span>
                  <span>Storage: {formatVmStorage(vm.available_storage_mib)}</span>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      </div>
    </div>
  )
}
