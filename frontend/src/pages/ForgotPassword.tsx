import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { extractApiErrorMessage } from '../services/apiClient'
import { requestPasswordReset, resetPasswordWithCode } from '../services/authService'
import '../styles/globals.css'

export default function ForgotPassword() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [requesting, setRequesting] = useState(false)
  const [resetting, setResetting] = useState(false)

  const handleRequestCode = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setRequesting(true)
    try {
      await requestPasswordReset(email)
      setMessage(`Password reset code sent to ${email}.`)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to request password reset'))
    } finally {
      setRequesting(false)
    }
  }

  const handleResetPassword = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setResetting(true)
    try {
      await resetPasswordWithCode(email, code, newPassword)
      navigate('/login', {
        state: { passwordReset: true, resetEmail: email },
      })
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to reset password'))
    } finally {
      setResetting(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <span className="page-kicker">Password Reset</span>
        <h1>CASSIE</h1>
        <h2>Reset your password</h2>
        <p className="auth-intro">
          Request a reset code first, then enter the code from your email with your new password.
        </p>
        {message && <div className="success-message">{message}</div>}
        {error && <div className="error-message">{error}</div>}
        <form onSubmit={handleRequestCode}>
          <div className="form-group">
            <label htmlFor="forgot-email">Email</label>
            <input id="forgot-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={requesting || resetting} />
          </div>
          <button type="submit" disabled={requesting} className="btn-secondary auth-submit">
            {requesting ? 'Generating Code...' : 'Request Reset Code'}
          </button>
        </form>
        <form onSubmit={handleResetPassword} style={{ marginTop: '1rem' }}>
          <div className="form-group">
            <label htmlFor="forgot-code">Reset Code</label>
            <input id="forgot-code" value={code} onChange={(e) => setCode(e.target.value)} required disabled={requesting || resetting} />
          </div>
          <div className="form-group">
            <label htmlFor="forgot-password-new">New Password</label>
            <input
              id="forgot-password-new"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              disabled={requesting || resetting}
            />
          </div>
          <button type="submit" disabled={resetting} className="btn-primary auth-submit">
            {resetting ? 'Updating Password...' : 'Update Password'}
          </button>
        </form>
        <p className="auth-link">
          Remembered it? <Link to="/login">Back to login</Link>
        </p>
      </div>
    </div>
  )
}
