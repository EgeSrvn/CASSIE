import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AuthError, LoginRequest, LoginTwoFactorChallenge, confirmLoginTwoFactor, login, resendLoginTwoFactor } from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import '../styles/globals.css'

interface LoginProps {
  onLogin: () => void
}

export default function Login({ onLogin }: LoginProps) {
  const [formData, setFormData] = useState<LoginRequest>({
    username: '',
    password: '',
  })
  const location = useLocation()
  const [error, setError] = useState<string>('')
  const [twoFactorChallenge, setTwoFactorChallenge] = useState<LoginTwoFactorChallenge | null>(null)
  const [twoFactorCode, setTwoFactorCode] = useState('')
  const [successMessage] = useState<string>(() => {
    const state = location.state as { verifiedEmail?: string; passwordReset?: boolean; resetEmail?: string } | null
    if (state?.verifiedEmail) {
      return `Email verified for ${state.verifiedEmail}. You can log in now.`
    }
    if (state?.passwordReset && state?.resetEmail) {
      return `Password updated for ${state.resetEmail}. You can log in now.`
    }
    return ''
  })
  const [loading, setLoading] = useState(false)
  const [resendingCode, setResendingCode] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setError('')
    setLoading(true)

    try {
      if (twoFactorChallenge) {
        await confirmLoginTwoFactor(twoFactorChallenge.username, twoFactorCode)
        onLogin()
        setTimeout(() => {
          window.dispatchEvent(new Event('auth-change'))
          navigate('/')
        }, 50)
        return
      }

      const result = await login(formData)
      if ('two_factor_required' in result && result.two_factor_required) {
        setTwoFactorChallenge(result)
        setTwoFactorCode('')
        setLoading(false)
        return
      }

      if ('access_token' in result && result.access_token) {
        onLogin()
        setTimeout(() => {
          window.dispatchEvent(new Event('auth-change'))
          navigate('/')
        }, 50)
        return
      }
      throw new Error('Login failed: No token received')
    } catch (err: any) {
      const authError = err as AuthError
      const verificationEmail =
        authError.verificationEmail ||
        err?.response?.data?.error?.details?.email ||
        err?.response?.data?.data?.email
      const verificationRequired =
        authError.verificationRequired ||
        err?.response?.data?.error?.details?.verification_required === true

      if (verificationRequired && typeof verificationEmail === 'string' && verificationEmail.trim()) {
        navigate('/verify-email', {
          state: {
            email: verificationEmail,
            requestNewCode: true,
          },
        })
        return
      }

      const errorMessage = extractApiErrorMessage(err, 'Login failed. Please check your credentials.')
      setError(errorMessage)
      console.error('Login error:', err)
      setLoading(false)
    }
  }

  const handleResendCode = async () => {
    if (!twoFactorChallenge) {
      return
    }
    try {
      setError('')
      setResendingCode(true)
      const refreshedChallenge = await resendLoginTwoFactor(twoFactorChallenge.username)
      setTwoFactorChallenge(refreshedChallenge)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to resend login code'))
    } finally {
      setResendingCode(false)
    }
  }

  const handleBackToPassword = () => {
    setTwoFactorChallenge(null)
    setTwoFactorCode('')
    setError('')
    setLoading(false)
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <span className="page-kicker">{twoFactorChallenge ? 'Two-Factor Login' : 'Welcome Back'}</span>
        <h1>CASSIE</h1>
        <h2>{twoFactorChallenge ? 'Enter your login code' : 'Pick up where your analysis left off'}</h2>
        <p className="auth-intro">
          {twoFactorChallenge
            ? `A sign-in code was sent to ${twoFactorChallenge.email}. Enter it below to finish logging in.`
            : 'Sign in to return to active jobs, revisit saved pipelines, and continue your genomics work without losing context.'}
        </p>
        
        {successMessage && <div className="success-message">{successMessage}</div>}
        {error && <div className="error-message">{error}</div>}
        {twoFactorChallenge?.verification_preview_code && (
          <div className="success-message">
            Development login code: <strong>{twoFactorChallenge.verification_preview_code}</strong>
          </div>
        )}
        
        <form onSubmit={handleSubmit}>
          {twoFactorChallenge ? (
            <div className="form-group">
              <label htmlFor="two_factor_code">Login Code</label>
              <input
                type="text"
                id="two_factor_code"
                value={twoFactorCode}
                onChange={(e) => setTwoFactorCode(e.target.value)}
                required
                disabled={loading}
                inputMode="numeric"
                autoComplete="one-time-code"
              />
            </div>
          ) : (
            <>
              <div className="form-group">
                <label htmlFor="username">Username</label>
                <input
                  type="text"
                  id="username"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  required
                  disabled={loading}
                />
              </div>
              
              <div className="form-group">
                <label htmlFor="password">Password</label>
                <input
                  type="password"
                  id="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required
                  disabled={loading}
                />
              </div>
            </>
          )}
          
          <button type="submit" disabled={loading} className="btn-primary auth-submit">
            {loading ? (twoFactorChallenge ? 'Checking Code...' : 'Logging in...') : (twoFactorChallenge ? 'Finish Sign-In' : 'Enter Workspace')}
          </button>
        </form>

        {twoFactorChallenge ? (
          <div className="button-row auth-code-actions">
            <button type="button" className="btn-secondary" onClick={handleResendCode} disabled={resendingCode || loading}>
              {resendingCode ? 'Sending...' : 'Resend Code'}
            </button>
            <button type="button" className="btn-secondary" onClick={handleBackToPassword} disabled={loading || resendingCode}>
              Back
            </button>
          </div>
        ) : null}
        
        <p className="auth-link">
          <Link to="/forgot-password">Forgot password?</Link>
        </p>
        <p className="auth-link">
          Don't have an account? <Link to="/register">Register here</Link>
        </p>
      </div>
    </div>
  )
}
