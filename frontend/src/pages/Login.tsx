import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, LoginRequest } from '../services/authService'
import '../styles/globals.css'

interface LoginProps {
  onLogin: () => void
}

export default function Login({ onLogin }: LoginProps) {
  const [formData, setFormData] = useState<LoginRequest>({
    username: '',
    password: '',
  })
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setError('')
    setLoading(true)

    try {
      const result = await login(formData)
      // Ensure token is set before updating state
      if (result && result.access_token) {
        onLogin()
        // Small delay to ensure token is saved before navigation
        setTimeout(() => {
          // Trigger auth change event for Navigation component
          window.dispatchEvent(new Event('auth-change'))
          navigate('/dashboard')
        }, 50)
      } else {
        throw new Error('Login failed: No token received')
      }
    } catch (err: any) {
      // Extract error message - could be from axios error or Error object
      const errorMessage = err.message || err.response?.data?.message || err.response?.data?.detail || 'Login failed. Please check your credentials.'
      setError(errorMessage)
      console.error('Login error:', err)
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <span className="page-kicker">Welcome Back</span>
        <h1>CASSIE</h1>
        <h2>Pick up where your analysis left off</h2>
        <p className="auth-intro">
          Sign in to return to active jobs, revisit saved pipelines, and continue your
          genomics work without losing context.
        </p>
        
        {error && <div className="error-message">{error}</div>}
        
        <form onSubmit={handleSubmit}>
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
          
          <button type="submit" disabled={loading} className="btn-primary auth-submit">
            {loading ? 'Logging in...' : 'Enter Workspace'}
          </button>
        </form>
        
        <p className="auth-link">
          Don't have an account? <Link to="/register">Register here</Link>
        </p>
      </div>
    </div>
  )
}
