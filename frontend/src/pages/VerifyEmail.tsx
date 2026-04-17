import { FormEvent, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { extractApiErrorMessage } from '../services/apiClient'
import { confirmEmailVerification, requestEmailVerification } from '../services/authService'
import '../styles/globals.css'

interface VerifyEmailLocationState {
  email?: string
  requestNewCode?: boolean
}

export default function VerifyEmail() {
  const navigate = useNavigate()
  const location = useLocation()
  const locationState = (location.state as VerifyEmailLocationState | null) || null
  const [email, setEmail] = useState(locationState?.email || '')
  const [code, setCode] = useState('')
  const [message, setMessage] = useState(
    locationState?.email && !locationState?.requestNewCode
      ? `Verification code sent to ${locationState.email}.`
      : ''
  )
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [resending, setResending] = useState(false)

  useEffect(() => {
    if (!locationState?.requestNewCode || !locationState?.email) {
      return
    }

    const requestCode = async () => {
      setError('')
      setResending(true)
      try {
        await requestEmailVerification(locationState.email || '')
        setMessage(`Verification code sent to ${locationState.email}.`)
      } catch (err: any) {
        setError(extractApiErrorMessage(err, 'Failed to resend verification code'))
      } finally {
        setResending(false)
      }
    }

    void requestCode()
  }, [locationState?.email, locationState?.requestNewCode])

  const handleVerify = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      await confirmEmailVerification(email, code)
      navigate('/login', {
        state: { verifiedEmail: email },
      })
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to verify email'))
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setError('')
    setResending(true)
    try {
      await requestEmailVerification(email)
      setMessage(`Verification code sent to ${email}.`)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to resend verification code'))
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <span className="page-kicker">Verify Email</span>
        <h1>CASSIE</h1>
        <h2>Confirm your email address</h2>
        <p className="auth-intro">
          New accounts need email verification before login. If SMTP is configured, the code will be delivered to the email address you entered.
        </p>
        {message && <div className="success-message">{message}</div>}
        {error && <div className="error-message">{error}</div>}
        <form onSubmit={handleVerify}>
          <div className="form-group">
            <label htmlFor="verify-email">Email</label>
            <input id="verify-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={loading || resending} />
          </div>
          <div className="form-group">
            <label htmlFor="verify-code">Verification Code</label>
            <input id="verify-code" value={code} onChange={(e) => setCode(e.target.value)} required disabled={loading || resending} />
          </div>
          <button type="submit" disabled={loading} className="btn-primary auth-submit">
            {loading ? 'Verifying...' : 'Verify Email'}
          </button>
        </form>
        <div className="button-row" style={{ marginTop: '1rem' }}>
          <button type="button" className="btn-secondary" onClick={handleResend} disabled={resending || !email.trim()}>
            {resending ? 'Sending...' : 'Resend Code'}
          </button>
        </div>
        <p className="auth-link">
          Already verified? <Link to="/login">Go to login</Link>
        </p>
      </div>
    </div>
  )
}
