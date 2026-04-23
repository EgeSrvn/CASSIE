import { useEffect, useState } from 'react'
import type { CatCornerConfig } from '../../cats/types'
import '../styles/CatCornerCard.css'

interface CatCornerCardProps {
  config: CatCornerConfig
}

export default function CatCornerCard({ config }: CatCornerCardProps) {
  const [isOpen, setIsOpen] = useState(false)

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
        <span className="cat-corner-card__content">
          <strong className="cat-corner-card__title">{config.title}</strong>
          <span className="cat-corner-card__description">{config.description}</span>
        </span>
      </button>

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
