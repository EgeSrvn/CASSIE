import { useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { logout, getToken, getCurrentUser, User } from '../services/authService'
import '../styles/Navigation.css'

interface NavigationProps {
  onLogout?: () => void
}

export default function Navigation({ onLogout }: NavigationProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken())
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    // Check authentication status
    const checkAuth = () => {
      const token = getToken()
      const authenticated = !!token
      setIsAuthenticated(authenticated)
      
      // Fetch user info if authenticated (with delay to avoid race conditions after login)
      if (authenticated) {
        // Add a small delay to ensure token is properly set after login/register
        setTimeout(() => {
          getCurrentUser()
            .then((userData) => {
              setUser(userData)
            })
            .catch((err) => {
              // Silently handle errors - don't log to console unless it's a real issue
              // If getting user fails, might be invalid token
              if (err.response?.status === 401) {
                logout()
                setIsAuthenticated(false)
                setUser(null)
              }
            })
        }, 100)
      } else {
        setUser(null)
      }
    }

    // Initial check
    checkAuth()

    // Listen for storage changes (logout from other tabs/windows)
    const handleStorageChange = () => {
      checkAuth()
    }

    // Listen for custom auth change events
    const handleAuthChange = () => {
      checkAuth()
    }

    window.addEventListener('storage', handleStorageChange)
    window.addEventListener('auth-change', handleAuthChange)
    
    // Also check periodically in case of same-tab logout (but less frequently)
    const interval = setInterval(checkAuth, 5000)

    return () => {
      window.removeEventListener('storage', handleStorageChange)
      window.removeEventListener('auth-change', handleAuthChange)
      clearInterval(interval)
    }
  }, [])

  const handleLogout = () => {
    logout()
    setIsAuthenticated(false)
    setUser(null)
    if (onLogout) {
      onLogout()
    }
    // Trigger custom event for other components
    window.dispatchEvent(new Event('auth-change'))
    // Navigate to home
    navigate('/')
  }

  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  return (
    <nav className="top-navigation">
      <div className="nav-container">
        <div className="nav-brand" onClick={() => navigate('/')}>
          <div>
            <h1 className="nav-title">CASSIE</h1>
          </div>
        </div>
        
        <div className="nav-links">
          <button
            type="button"
            className={`nav-link ${isActive('/') && location.pathname === '/' ? 'active' : ''}`}
            onClick={() => navigate('/')}
          >
            Home
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/jobs') ? 'active' : ''}`}
            onClick={() => navigate('/jobs')}
          >
            Jobs
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/pipelines') ? 'active' : ''}`}
            onClick={() => navigate('/pipelines')}
          >
            Pipelines
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/community') ? 'active' : ''}`}
            onClick={() => navigate('/community')}
          >
            Community
          </button>
        </div>

        <div className="nav-actions">
          {isAuthenticated ? (
            <>
              {user && (
                <button
                  type="button"
                  className="nav-user-chip"
                  onClick={() => navigate('/profile')}
                >
                  {user.avatar_url ? (
                    <img
                      className="nav-user-avatar nav-user-avatar-image"
                      src={user.avatar_url}
                      alt={user.username}
                    />
                  ) : (
                    <span className="nav-user-avatar">
                      {(user.display_name || user.username).slice(0, 1).toUpperCase()}
                    </span>
                  )}
                  <span className="nav-user-text">
                    <strong>{user.display_name || user.username}</strong>
                    <small>@{user.username}</small>
                  </span>
                </button>
              )}
              <button type="button" onClick={handleLogout} className="btn-secondary btn-small">
                Logout
              </button>
            </>
          ) : (
            <>
              <button 
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  navigate('/login')
                }} 
                className="btn-secondary btn-small"
                style={{ backgroundColor: 'var(--secondary)', color: 'white', border: 'none' }}
              >
                Login
              </button>
              <button 
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  navigate('/register')
                }} 
                className="btn-primary btn-small"
                style={{ backgroundColor: 'white', color: 'var(--primary)', border: '1px solid var(--primary)' }}
              >
                Register
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}
