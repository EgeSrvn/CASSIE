import { useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { logout, getToken, getCurrentUser, getStoredUser, User } from '../services/authService'
import '../styles/Navigation.css'

interface NavigationProps {
  onLogout?: () => void
}

export default function Navigation({ onLogout }: NavigationProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken())
  const [user, setUser] = useState<User | null>(() => getStoredUser())
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let isMounted = true

    const checkAuth = async () => {
      const token = getToken()
      const authenticated = !!token
      if (!isMounted) {
        return
      }

      setIsAuthenticated(authenticated)

      if (authenticated) {
        try {
          const userData = await getCurrentUser()
          if (isMounted) {
            setUser(userData)
          }
        } catch (err: any) {
          if (err.response?.status === 401 && isMounted) {
            logout()
            setIsAuthenticated(false)
            setUser(null)
          }
        }
      } else {
        setUser(null)
      }
    }

    void checkAuth()

    const handleStorageChange = () => {
      void checkAuth()
    }

    const handleAuthChange = () => {
      void checkAuth()
    }

    window.addEventListener('storage', handleStorageChange)
    window.addEventListener('auth-change', handleAuthChange)

    return () => {
      isMounted = false
      window.removeEventListener('storage', handleStorageChange)
      window.removeEventListener('auth-change', handleAuthChange)
    }
  }, [])

  useEffect(() => {
    setIsUserMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }

    window.addEventListener('mousedown', handlePointerDown)
    return () => window.removeEventListener('mousedown', handlePointerDown)
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
          {isAuthenticated && (
            <button
              type="button"
              className={`nav-link ${isActive('/storage') ? 'active' : ''}`}
              onClick={() => navigate('/storage')}
            >
              Storage
            </button>
          )}
          <button
            type="button"
            className={`nav-link ${isActive('/community') ? 'active' : ''}`}
            onClick={() => navigate('/community')}
          >
            Community
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/forum') ? 'active' : ''}`}
            onClick={() => navigate('/forum')}
          >
            Forum
          </button>
        </div>

        <div className="nav-actions">
          {isAuthenticated ? (
            <div className="nav-user-menu-shell" ref={userMenuRef}>
              {user && (
                <button
                  type="button"
                  className="nav-user-chip"
                  onClick={() => setIsUserMenuOpen((current) => !current)}
                  aria-haspopup="menu"
                  aria-expanded={isUserMenuOpen}
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
              {isUserMenuOpen && (
                <div className="nav-user-menu" role="menu">
                  <button type="button" className="nav-user-menu-item" onClick={() => navigate('/profile')}>
                    Go Profile
                  </button>
                  <button type="button" className="nav-user-menu-item" onClick={() => navigate('/about')}>
                    About
                  </button>
                  <button type="button" className="nav-user-menu-item" onClick={() => navigate('/faq')}>
                    FAQ
                  </button>
                  <button type="button" className="nav-user-menu-item nav-user-menu-item-danger" onClick={handleLogout}>
                    Logout
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <button 
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  navigate('/login')
                }} 
                className={`nav-link nav-auth-link ${isActive('/login') ? 'active' : ''}`}
              >
                Login
              </button>
              <button 
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  navigate('/register')
                }} 
                className={`nav-link nav-auth-link ${isActive('/register') ? 'active' : ''}`}
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
