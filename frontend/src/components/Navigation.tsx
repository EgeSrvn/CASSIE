import { useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { logout, getToken, getCurrentUser, getStoredUser, User } from '../services/authService'
import '../styles/Navigation.css'
import cassieLogo from '../../images/cassie_logo.png'

interface NavigationProps {
  onLogout?: () => void
}

const uiPreferenceKey = 'cassie-ui-preference'

export default function Navigation({ onLogout }: NavigationProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken())
  const [user, setUser] = useState<User | null>(() => getStoredUser())
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isModernUi, setIsModernUi] = useState(() => localStorage.getItem(uiPreferenceKey) === 'modern')
  const userMenuRef = useRef<HTMLDivElement | null>(null)
  const mobileUserMenuRef = useRef<HTMLDivElement | null>(null)

  const formatUsd = (value?: number | null): string => `$${Number(value || 0).toFixed(2)}`

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
    const syncUiPreference = () => {
      setIsModernUi(localStorage.getItem(uiPreferenceKey) === 'modern')
    }

    window.addEventListener('storage', syncUiPreference)
    window.addEventListener('ui-preference-change', syncUiPreference)
    return () => {
      window.removeEventListener('storage', syncUiPreference)
      window.removeEventListener('ui-preference-change', syncUiPreference)
    }
  }, [])

  useEffect(() => {
    setIsUserMenuOpen(false)
    setIsMobileMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (!userMenuRef.current?.contains(target) && !mobileUserMenuRef.current?.contains(target)) {
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

  const navigateAndClose = (path: string) => {
    setIsUserMenuOpen(false)
    setIsMobileMenuOpen(false)
    navigate(path)
  }

  const toggleModernUi = () => {
    const nextPreference = isModernUi ? 'classic' : 'modern'
    localStorage.setItem(uiPreferenceKey, nextPreference)
    document.documentElement.dataset.ui = nextPreference
    setIsModernUi(!isModernUi)
    window.dispatchEvent(new Event('ui-preference-change'))
  }

  const renderAvatar = () => {
    if (!isAuthenticated || !user) {
      return (
        <span className="nav-user-avatar nav-user-avatar-empty" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M12 12.2a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Z" />
            <path d="M4.7 20.2c.95-3.45 3.58-5.25 7.3-5.25s6.35 1.8 7.3 5.25" />
          </svg>
        </span>
      )
    }

    if (user.avatar_url) {
      return (
        <img
          className="nav-user-avatar nav-user-avatar-image"
          src={user.avatar_url}
          alt={user.username}
        />
      )
    }

    return (
      <span className="nav-user-avatar">
        {(user.display_name || user.username).slice(0, 1).toUpperCase()}
      </span>
    )
  }

  const renderUserMenu = () => {
    if (isAuthenticated) {
      return (
        <div className="nav-user-menu" role="menu">
          <button
            type="button"
            className="nav-user-menu-item nav-user-menu-toggle"
            onClick={toggleModernUi}
            role="switch"
            aria-checked={isModernUi}
          >
            <span>Dark Mode</span>
            <span className="nav-toggle-track" aria-hidden="true">
              <span className="nav-toggle-thumb" />
            </span>
          </button>
          <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/profile')}>
            Go Profile
          </button>
          <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/about')}>
            About
          </button>
          <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/faq')}>
            FAQ
          </button>
          <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/terms')}>
            Terms
          </button>
          <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/kvkk')}>
            KVKK
          </button>
          <button type="button" className="nav-user-menu-item nav-user-menu-item-danger" onClick={handleLogout}>
            Logout
          </button>
        </div>
      )
    }

    return (
      <div className="nav-user-menu" role="menu">
        <button
          type="button"
          className="nav-user-menu-item nav-user-menu-toggle"
          onClick={toggleModernUi}
          role="switch"
          aria-checked={isModernUi}
        >
          <span>Dark Mode</span>
          <span className="nav-toggle-track" aria-hidden="true">
            <span className="nav-toggle-thumb" />
          </span>
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/register')}>
          Register
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/login')}>
          Login
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/about')}>
          About
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/faq')}>
          FAQ
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/terms')}>
          Terms
        </button>
        <button type="button" className="nav-user-menu-item" onClick={() => navigateAndClose('/kvkk')}>
          KVKK
        </button>
      </div>
    )
  }

  return (
    <nav className={`top-navigation ${isMobileMenuOpen ? 'top-navigation--mobile-open' : ''}`}>
      <div className="nav-container">
        <div className="nav-brand" onClick={() => navigateAndClose('/')}>
          <img
            className="nav-logo"
            src={cassieLogo}
            alt="CASSIE logo"
          />
          <div>
            <h1 className="nav-title">CASSIE</h1>
          </div>
        </div>

        <button
          type="button"
          className="nav-mobile-menu-button"
          aria-label={isMobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
          aria-expanded={isMobileMenuOpen}
          onClick={() => setIsMobileMenuOpen((current) => !current)}
        >
          <svg
            className="nav-mobile-menu-icon"
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            {isMobileMenuOpen ? (
              <path d="M6 6l12 12M18 6L6 18" />
            ) : (
              <path d="M5 7h14M5 12h14M5 17h14" />
            )}
          </svg>
        </button>

        <div className="nav-mobile-account" ref={mobileUserMenuRef}>
          <button
            type="button"
            className={`nav-user-chip nav-user-chip-mobile ${!isAuthenticated ? 'nav-user-chip-guest' : ''}`}
            onClick={() => setIsUserMenuOpen((current) => !current)}
            aria-haspopup="menu"
            aria-expanded={isUserMenuOpen}
            aria-label="Open account menu"
          >
            {renderAvatar()}
          </button>
          {isUserMenuOpen && renderUserMenu()}
        </div>
        
        <div className="nav-links">
          <button
            type="button"
            className={`nav-link ${isActive('/') && location.pathname === '/' ? 'active' : ''}`}
            onClick={() => navigateAndClose('/')}
          >
            Home
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/jobs') ? 'active' : ''}`}
            onClick={() => navigateAndClose('/jobs')}
          >
            Jobs
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/pipelines') ? 'active' : ''}`}
            onClick={() => navigateAndClose('/pipelines')}
          >
            Pipelines
          </button>
          {isAuthenticated && (
            <button
              type="button"
              className={`nav-link ${isActive('/storage') ? 'active' : ''}`}
              onClick={() => navigateAndClose('/storage')}
            >
              Storage
            </button>
          )}
          <button
            type="button"
            className={`nav-link ${isActive('/community') ? 'active' : ''}`}
            onClick={() => navigateAndClose('/community')}
          >
            Community
          </button>
          <button
            type="button"
            className={`nav-link ${isActive('/forum') ? 'active' : ''}`}
            onClick={() => navigateAndClose('/forum')}
          >
            Forum
          </button>
        </div>

        <div className={`nav-actions ${!isAuthenticated ? 'nav-actions-account-only' : ''}`}>
          {isAuthenticated ? (
            <>
            {user && (
              <button
                type="button"
                className={`nav-balance-chip ${isActive('/balance') ? 'active' : ''}`}
                onClick={() => navigateAndClose('/balance')}
                title={`Balance ${formatUsd(user.cash_balance_usd)}; reserved ${formatUsd(user.cash_reserved_usd)}`}
              >
                <span>
                  <small>Balance</small>
                  <strong>{formatUsd(user.cash_balance_usd)}</strong>
                </span>
                <span>
                  <small>Reserved</small>
                  <strong>{formatUsd(user.cash_reserved_usd)}</strong>
                </span>
              </button>
            )}
            <div className="nav-user-menu-shell" ref={userMenuRef}>
              {user && (
                <button
                  type="button"
                  className="nav-user-chip"
                  onClick={() => setIsUserMenuOpen((current) => !current)}
                  aria-haspopup="menu"
                  aria-expanded={isUserMenuOpen}
                >
                  {renderAvatar()}
                  <span className="nav-user-text">
                    <strong>{user.display_name || user.username}</strong>
                    <small>@{user.username}</small>
                  </span>
                </button>
              )}
              {isUserMenuOpen && renderUserMenu()}
            </div>
            </>
          ) : (
            <div className="nav-user-menu-shell" ref={userMenuRef}>
              <button
                type="button"
                className="nav-user-chip nav-user-chip-guest"
                onClick={() => setIsUserMenuOpen((current) => !current)}
                aria-haspopup="menu"
                aria-expanded={isUserMenuOpen}
                aria-label="Open account menu"
              >
                {renderAvatar()}
              </button>
              {isUserMenuOpen && renderUserMenu()}
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
