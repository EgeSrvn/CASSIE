import { FormEvent, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

interface ReportDialogProps {
  isOpen: boolean
  title: string
  targetLabel: string
  submitting?: boolean
  onClose: () => void
  onSubmit: (payload: { reason: string; details?: string }) => Promise<void> | void
}

export default function ReportDialog({
  isOpen,
  title,
  targetLabel,
  submitting = false,
  onClose,
  onSubmit,
}: ReportDialogProps) {
  const [reason, setReason] = useState('')
  const [details, setDetails] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isOpen) {
      setReason('')
      setDetails('')
      setError('')
    }
  }, [isOpen])

  if (!isOpen) {
    return null
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const normalizedReason = reason.trim()
    const normalizedDetails = details.trim()

    if (normalizedReason.length < 3) {
      setError('Please enter at least 3 characters for the report reason.')
      return
    }
    if (normalizedReason.length > 160) {
      setError('Report reason must stay within 160 characters.')
      return
    }
    if (normalizedDetails.length > 2000) {
      setError('Additional details must stay within 2000 characters.')
      return
    }

    setError('')
    await onSubmit({
      reason: normalizedReason,
      details: normalizedDetails || undefined,
    })
  }

  return createPortal(
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="report-dialog-title">
      <div className="modal-content report-dialog-modal">
        <div className="modal-header">
          <h2 id="report-dialog-title">{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close report dialog">
            ×
          </button>
        </div>
        <form className="modal-body report-dialog-form" onSubmit={handleSubmit}>
          <p className="report-dialog-copy">
            Tell the admin team what is wrong with this {targetLabel}. Reports need a short reason before they can be submitted.
          </p>
          <label className="profile-info-label" htmlFor="report-reason">Reason</label>
          <input
            id="report-reason"
            type="text"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={160}
            placeholder="Spam, abuse, misleading content..."
          />
          <label className="profile-info-label" htmlFor="report-details">Details</label>
          <textarea
            id="report-details"
            rows={5}
            value={details}
            onChange={(event) => setDetails(event.target.value)}
            maxLength={2000}
            placeholder="Optional context for the admin team"
          />
          {error ? <div className="error-message report-dialog-error">{error}</div> : null}
          <div className="modal-footer">
            <button type="button" className="btn-secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Sending...' : 'Submit Report'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  )
}
