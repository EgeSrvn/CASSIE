import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register, RegisterRequest } from '../services/authService'
import '../styles/globals.css'

interface RegisterProps {
  onRegister: () => void
}

export default function Register({ onRegister }: RegisterProps) {
  const [formData, setFormData] = useState<RegisterRequest>({
    username: '',
    email: '',
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
      const result = await register(formData)
      // Ensure token is set before updating state
      if (result && result.access_token) {
        onRegister()
        // Small delay to ensure token is saved before navigation
        setTimeout(() => {
          // Trigger auth change event for Navigation component
          window.dispatchEvent(new Event('auth-change'))
          navigate('/dashboard')
        }, 50)
      } else {
        throw new Error('Registration failed: No token received')
      }
    } catch (err: any) {
      // Extract error message - could be from axios error or Error object
      const errorMessage = err.message || err.response?.data?.message || err.response?.data?.detail || 'Registration failed. Please try again.'
      setError(errorMessage)
      console.error('Registration error:', err)
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h1>CASSIE</h1>
        <h2>Register</h2>
        
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
          
          <button type="submit" disabled={loading} className="btn-primary">
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

