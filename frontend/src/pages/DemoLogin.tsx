import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { demoLogin } from '../services/authService'
import { useAppConfig } from '../contexts/AppConfigContext'
import '../styles/globals.css'

export default function DemoLogin() {
  const { demo_mode_enabled, demo_code_length } = useAppConfig()
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    const trimmed = code.trim().toUpperCase()
    if (trimmed.length !== demo_code_length) {
      setError(`Demo code must be exactly ${demo_code_length} characters.`)
      return
    }

    setLoading(true)
    try {
      await demoLogin(trimmed)
      window.dispatchEvent(new Event('auth-change'))
      navigate('/')
    } catch (err: any) {
      setError(err?.message || 'Invalid or expired demo code.')
    } finally {
      setLoading(false)
    }
  }

  if (!demo_mode_enabled) {
    return (
      <div className="page-container">
        <div className="page-content">
          <p className="error-message">Demo mode is not enabled.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div className="page-content" style={{ maxWidth: 440, margin: '0 auto' }}>
        <h1 style={{ marginBottom: '0.5rem' }}>Use Demo Code</h1>
        <p style={{ marginBottom: '1.5rem', color: 'var(--color-text-secondary, #666)' }}>
          Enter the {demo_code_length}-character code provided by an administrator to start a demo session.
        </p>

        <form onSubmit={handleSubmit} autoComplete="off">
          <div style={{ marginBottom: '1rem' }}>
            <label htmlFor="demo-code" style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
              Demo Code
            </label>
            <input
              id="demo-code"
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              maxLength={demo_code_length + 4}
              placeholder={`${'X'.repeat(demo_code_length)}`}
              autoFocus
              spellCheck={false}
              style={{
                width: '100%',
                padding: '0.625rem 0.75rem',
                fontFamily: 'monospace',
                fontSize: '1.1rem',
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
                boxSizing: 'border-box',
              }}
              disabled={loading}
            />
          </div>

          {error && (
            <div className="error-message" style={{ marginBottom: '1rem' }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn-primary"
            style={{ width: '100%' }}
            disabled={loading || code.trim().length === 0}
          >
            {loading ? 'Verifying…' : 'Start Demo Session'}
          </button>
        </form>

        <div
          style={{
            marginTop: '2rem',
            padding: '1rem',
            background: 'var(--color-surface-secondary, #f5f5f5)',
            borderRadius: '6px',
            fontSize: '0.825rem',
            color: 'var(--color-text-secondary, #666)',
            lineHeight: 1.5,
          }}
        >
          <strong>Privacy notice:</strong> CASSIE demo mode is for academic demonstration only. Do not upload
          human genomic data, patient data, personal data, health data, or any dataset that can identify a real
          person. Demo mode only supports predefined synthetic/mock datasets. Upload, sharing, and community
          features are disabled.
        </div>
      </div>
    </div>
  )
}
