import { useNavigate } from 'react-router-dom'
import { getToken } from '../services/authService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function Home() {
  const navigate = useNavigate()
  const isAuthenticated = !!getToken()

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <div className="dashboard-hero">
          <h1 className="page-title" style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>
            CASSIE Genomics Platform
          </h1>
          <p className="dashboard-subtitle">
            Comprehensive genomic data analysis with multi-cloud support
          </p>
        </div>

        <div className="dashboard-cards-grid dashboard-cards-grid-four-up">
          <div className="dashboard-card">
            <h2 className="dashboard-card-title">View Jobs</h2>
            <p className="dashboard-card-description">
              Monitor active jobs and access results from completed analyses. View job details, outputs, and execution history.
            </p>
            <button
              className="btn-primary"
              onClick={() => navigate('/jobs')}
            >
              View Jobs
            </button>
          </div>

          <div className="dashboard-card">
            <h2 className="dashboard-card-title">View Pipelines</h2>
            <p className="dashboard-card-description">
              Browse available pipelines and workflows. Explore pre-configured analysis pipelines for various genomic tasks.
            </p>
            <button
              className="btn-primary"
              onClick={() => navigate('/pipelines')}
            >
              View Pipelines
            </button>
          </div>

          {isAuthenticated ? (
            <>
              <div className="dashboard-card">
                <h2 className="dashboard-card-title">Create Job</h2>
                <p className="dashboard-card-description">
                  Start a new analysis job by selecting tools, input files, and configuration options.
                </p>
                <button
                  className="btn-primary"
                  onClick={() => navigate('/jobs/create')}
                >
                  Create Job
                </button>
              </div>

              <div className="dashboard-card">
                <h2 className="dashboard-card-title">Pipeline Builder</h2>
                <p className="dashboard-card-description">
                  Visually create and customize your analysis pipelines with drag-and-drop interface.
                </p>
                <button
                  className="btn-primary"
                  onClick={() => navigate('/pipelines/builder')}
                >
                  Build Pipeline
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="dashboard-card">
                <h2 className="dashboard-card-title">Create Job</h2>
                <p className="dashboard-card-description">
                  Start a new analysis job by selecting tools, input files, and configuration options.
                </p>
                <button
                  className="btn-primary"
                  onClick={() => navigate('/login')}
                >
                  Login to Create Job
                </button>
              </div>

              <div className="dashboard-card">
                <h2 className="dashboard-card-title">Pipeline Builder</h2>
                <p className="dashboard-card-description">
                  Visually create and customize your analysis pipelines with drag-and-drop interface.
                </p>
                <button
                  className="btn-primary"
                  onClick={() => navigate('/login')}
                >
                  Login to Build Pipeline
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
