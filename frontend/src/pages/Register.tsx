import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register, RegisterRequest } from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import '../styles/globals.css'

interface RegisterProps {
  onRegister?: () => void
}

export default function Register({ onRegister }: RegisterProps) {
  const [formData, setFormData] = useState<RegisterRequest>({
    username: '',
    email: '',
    password: '',
  })
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const submitLockedRef = useRef(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (submitLockedRef.current || loading) {
      return
    }

    submitLockedRef.current = true
    setError('')
    setLoading(true)

    try {
      const challenge = await register(formData)
      onRegister?.()
      navigate('/verify-email', {
        state: {
          email: challenge.email,
        },
      })
    } catch (err: any) {
      const errorMessage = extractApiErrorMessage(err, 'Registration failed. Please try again.')
      setError(errorMessage)
      console.error('Registration error:', err)
      setLoading(false)
      submitLockedRef.current = false
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <span className="page-kicker">Create Account</span>
        <h1>CASSIE</h1>
        <h2>Register</h2>
        <p className="auth-intro">
          Set up your space for running analyses, building pipelines, and sharing them with the community.
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
            <label htmlFor="email">Email</label>
            <input
              type="email"
              id="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
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
              minLength={8}
            />
          </div>
          
          <button type="submit" disabled={loading} className="btn-primary auth-submit">
            {loading ? 'Registering...' : 'Register'}
          </button>
        </form>
        
        <p className="auth-link">
          Already have an account? <Link to="/login">Login here</Link>
        </p>
      </div>
    </div>
  )
}
