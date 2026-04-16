import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

interface DashboardProps {
  onLogout: () => void
}

export default function Dashboard({ onLogout }: DashboardProps) {
  const navigate = useNavigate()

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
      </div>
    </div>
  )
}
