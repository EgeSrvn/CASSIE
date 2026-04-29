import { useEffect, useState } from 'react'
import type { CatCornerConfig } from '../../cats/types'
import '../styles/CatCornerCard.css'

interface CatCornerCardProps {
  config: CatCornerConfig
  className?: string
}

function CatToggleIcon({ direction }: { direction: 'left' | 'right' }) {
  return (
    <svg
      className="cat-corner-toggle__icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d={direction === 'left' ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'} />
    </svg>
  )
}

export default function CatCornerCard({ config, className = '' }: CatCornerCardProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen])

  return (
    <>
      <div
        className={`cat-corner-shell ${isExpanded ? 'cat-corner-shell--expanded' : 'cat-corner-shell--collapsed'} ${className}`.trim()}
      >
        <button
          type="button"
          className="cat-corner-card"
          aria-label={config.title}
          onClick={() => setIsOpen(true)}
        >
          <img
            className="cat-corner-card__image"
            src={config.mediaSrc}
            alt={config.mediaAlt}
          />
          {isExpanded && (
            <span className="cat-corner-card__content">
              <strong className="cat-corner-card__title">{config.title}</strong>
              <span className="cat-corner-card__description">{config.description}</span>
            </span>
          )}
        </button>
        <button
          type="button"
          className="cat-corner-toggle"
          aria-label={isExpanded ? 'Collapse cat card' : 'Expand cat card'}
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded((current) => !current)}
        >
          <CatToggleIcon direction={isExpanded ? 'left' : 'right'} />
        </button>
      </div>

      {isOpen && (
        <div
          className="cat-corner-modal"
          role="presentation"
          onClick={() => setIsOpen(false)}
        >
          <div
            className="cat-corner-modal__content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="cat-corner-modal-title"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="cat-corner-modal__close"
              aria-label="Close cat popup"
              onClick={() => setIsOpen(false)}
            >
              ×
            </button>
            <img
              className="cat-corner-modal__image"
              src={config.mediaSrc}
              alt={config.mediaAlt}
            />
            <div className="cat-corner-modal__copy">
              <h2 id="cat-corner-modal-title" className="cat-corner-modal__title">
                {config.title}
              </h2>
              <p className="cat-corner-modal__description">{config.description}</p>
              <p className="cat-corner-modal__detail">{config.detailText}</p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

