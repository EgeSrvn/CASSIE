import { useNavigate } from 'react-router-dom'

import Navigation from '../components/Navigation'
import { getToken } from '../services/authService'
import { STARTER_PIPELINE_TEMPLATES, StarterPipelineTemplate } from '../services/starterPipelines'
import '../styles/globals.css'

export default function StarterTemplates() {
  const navigate = useNavigate()
  const isAuthenticated = !!getToken()

  const openTemplate = (template: StarterPipelineTemplate) => {
    navigate('/pipelines/builder', { state: { starterTemplate: template } })
  }

  return (
    <div className="page-container pipelines-classic-page starter-templates-page">
      <Navigation />
      <div className="page-content">
        <header className="page-header">
          <h1 className="page-title">Starter Templates</h1>
          <div className="header-actions">
            <button type="button" onClick={() => navigate('/pipelines')} className="btn-secondary">
              Back to Pipelines
            </button>
          </div>
        </header>

        <div className="jobs-page-content">
          <section className="card starter-templates-intro-card">
            <div className="section-heading">
              <h2>Start From a Curated Workflow</h2>
              <p>Choose a template, open it in the visual builder, and adapt it to your own data and tools.</p>
            </div>
          </section>

          <div className="community-template-grid starter-template-grid-page">
            {STARTER_PIPELINE_TEMPLATES.map((template) => (
              <div key={template.id} className="card pipeline-card community-template-card starter-template-card">
                <div>
                  <h3 className="pipeline-card-title community-template-title">{template.name}</h3>
                  <p className="pipeline-card-description community-template-description">{template.description}</p>
                </div>
                <div className="pipeline-card-actions starter-template-actions">
                  <button type="button" onClick={() => openTemplate(template)} className="btn-secondary">
                    Open Template
                  </button>
                  {isAuthenticated && (
                    <button type="button" onClick={() => openTemplate(template)} className="btn-primary">
                      Customize
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
