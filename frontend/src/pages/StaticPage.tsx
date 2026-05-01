import { Navigate, useParams } from 'react-router-dom'
import Navigation from '../components/Navigation'
import { STATIC_PAGES } from '../config/staticPages'
import '../styles/globals.css'

interface StaticPageProps {
  slugOverride?: string
}

export default function StaticPage({ slugOverride }: StaticPageProps) {
  const { slug } = useParams()
  const resolvedSlug = slugOverride || slug
  const page = resolvedSlug ? STATIC_PAGES[resolvedSlug] : undefined

  if (!page) {
    return <Navigate to="/" replace />
  }

  const { content } = page

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <section className="card forum-composer-page-card">
          <div className="section-heading">
            <h2>{content.title}</h2>
            {content.description ? <p>{content.description}</p> : null}
          </div>
          {page.type === 'document' ? (
            <div className="static-page-document">
              {page.content.document
                .split(/\n{2,}/)
                .map((paragraph) => paragraph.trim())
                .filter(Boolean)
                .map((paragraph, index) => (
                  <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>
                ))}
            </div>
          ) : page.type === 'faq' ? (
            <div className="static-page-faq-list">
              {page.content.items.map((item) => (
                <details key={item.question} className="static-page-faq-item">
                  <summary>{item.question}</summary>
                  <div className="static-page-faq-answer">
                    {item.answer.map((paragraph) => (
                      <p key={paragraph}>{paragraph}</p>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <div className="static-page-sections">
              {page.content.sections.map((section) => (
                <div key={section.heading} className="static-page-section">
                  <h3>{section.heading}</h3>
                  {section.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
