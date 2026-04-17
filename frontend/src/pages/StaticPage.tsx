import { Navigate, useParams } from 'react-router-dom'
import Navigation from '../components/Navigation'
import { STATIC_PAGES } from '../config/staticPages'
import '../styles/globals.css'

export default function StaticPage() {
  const { slug } = useParams()
  const page = slug ? STATIC_PAGES[slug] : undefined

  if (!page) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <section className="card forum-composer-page-card">
          <div className="section-heading">
            <h2>{page.title}</h2>
            <p>{page.description}</p>
          </div>
          <div className="static-page-sections">
            {page.sections.map((section) => (
              <div key={section.heading} className="static-page-section">
                <h3>{section.heading}</h3>
                {section.body.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
