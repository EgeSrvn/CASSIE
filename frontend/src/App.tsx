import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { Component, FormEvent, ReactNode, useState, useEffect } from 'react'
import Login from './pages/Login'
import Register from './pages/Register'
import Home from './pages/Home'
import Jobs from './pages/Jobs'
import CreateJob from './pages/CreateJob'
import JobDetails from './pages/JobDetails'
import Storage from './pages/Storage'
import StorageUpgrade from './pages/StorageUpgrade'
import Balance from './pages/Balance'
import Pipelines from './pages/Pipelines'
import StarterTemplates from './pages/StarterTemplates'
import PipelineBuilder from './pages/PipelineBuilder'
import Community from './pages/Community'
import Forum from './pages/Forum'
import ForumComposer from './pages/ForumComposer'
import ForumThread from './pages/ForumThread'
import Profile from './pages/Profile'
import SiteCatWidget from './components/SiteCatWidget'
import StaticPage from './pages/StaticPage'
import VerifyEmail from './pages/VerifyEmail'
import ForgotPassword from './pages/ForgotPassword'
import { getToken } from './services/authService'
import { startPendingJobUploadProcessor } from './services/pendingJobUploadService'
import { startStorageUploadProcessor } from './services/storageUploadService'

const generalAccessPassword = import.meta.env.VITE_GENERAL_ACCESS_PASSWORD?.trim() || ''
const generalAccessSessionKey = 'cassie-general-access-authenticated'
const generalAccessReturnPathKey = 'cassie-general-access-return-path'

class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('Unhandled app render error:', error)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page-container">
          <div className="page-content">
            <div className="error-message">
              Something went wrong while rendering this page. {this.state.error.message}
            </div>
            <button type="button" className="btn-primary" onClick={() => window.location.reload()}>
              Reload Page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

function GeneralAccessLogin({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (password === generalAccessPassword) {
      sessionStorage.setItem(generalAccessSessionKey, 'true')
      setError('')
      onAuthenticated()
      return
    }

    setError('Invalid access code.')
    setPassword('')
  }

  return (
    <div className="general-access-page">
      <form className="general-access-card" onSubmit={handleSubmit}>
        <div className="general-access-brand">CASSIE</div>
        <h1>Admin Authentication</h1>
        <p>Enter the general access code to continue.</p>
        <label htmlFor="general-access-password">Access code</label>
        <input
          id="general-access-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        {error ? <div className="error-message general-access-error">{error}</div> : null}
        <button type="submit" className="btn-primary">
          Continue
        </button>
      </form>
    </div>
  )
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!getToken())
  const [hasGeneralAccess, setHasGeneralAccess] = useState<boolean>(() => {
    if (!generalAccessPassword) {
      return true
    }

    return sessionStorage.getItem(generalAccessSessionKey) === 'true'
  })

  useEffect(() => {
    if (hasGeneralAccess || !generalAccessPassword) {
      return
    }

    const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (currentPath !== '/admin-auth') {
      sessionStorage.setItem(generalAccessReturnPathKey, currentPath)
      window.history.replaceState(null, '', '/admin-auth')
    }
  }, [hasGeneralAccess])

  useEffect(() => {
    // Check if user is authenticated
    const checkAuth = () => {
      const token = getToken()
      setIsAuthenticated(!!token)
    }
    
    checkAuth()
    
    // Listen for auth changes
    const handleStorageChange = () => {
      checkAuth()
    }
    
    const handleAuthChange = () => {
      checkAuth()
    }
    
    window.addEventListener('storage', handleStorageChange)
    window.addEventListener('auth-change', handleAuthChange)
    return () => {
      window.removeEventListener('storage', handleStorageChange)
      window.removeEventListener('auth-change', handleAuthChange)
    }
  }, [])

  useEffect(() => {
    if (!hasGeneralAccess) {
      return
    }

    void startPendingJobUploadProcessor()
    void startStorageUploadProcessor()
  }, [hasGeneralAccess])

  return (
    <AppErrorBoundary>
      {!hasGeneralAccess ? (
        <GeneralAccessLogin
          onAuthenticated={() => {
            setHasGeneralAccess(true)
            const returnPath = sessionStorage.getItem(generalAccessReturnPathKey) || '/'
            sessionStorage.removeItem(generalAccessReturnPathKey)
            window.history.replaceState(null, '', returnPath)
          }}
        />
      ) : (
      <Router>
        <>
          <Routes>
          <Route 
            path="/login" 
            element={!isAuthenticated ? <Login onLogin={() => setIsAuthenticated(true)} /> : <Navigate to="/" />} 
          />
          <Route 
            path="/register" 
            element={!isAuthenticated ? <Register /> : <Navigate to="/" />} 
          />
          <Route
            path="/verify-email"
            element={<VerifyEmail />}
          />
          <Route
            path="/forgot-password"
            element={<ForgotPassword />}
          />
          <Route 
            path="/" 
            element={<Home />} 
          />
          <Route 
            path="/dashboard" 
            element={<Navigate to="/" replace />} 
          />
          {/* Public routes - can view but not create */}
          <Route 
            path="/jobs" 
            element={<Jobs />} 
          />
          <Route 
            path="/jobs/:jobId" 
            element={<JobDetails />} 
          />
          <Route 
            path="/pipelines" 
            element={<Pipelines />} 
          />
          <Route
            path="/pipelines/templates"
            element={<StarterTemplates />}
          />
          <Route 
            path="/community" 
            element={<Community />} 
          />
          <Route
            path="/forum"
            element={<Forum />}
          />
          <Route
            path="/forum/new"
            element={<ForumComposer />}
          />
          <Route
            path="/forum/:threadId"
            element={<ForumThread />}
          />
          <Route
            path="/profile"
            element={isAuthenticated ? <Profile /> : <Navigate to="/login" />}
          />
          <Route
            path="/storage"
            element={isAuthenticated ? <Storage /> : <Navigate to="/login" />}
          />
          <Route
            path="/storage/upgrade"
            element={isAuthenticated ? <StorageUpgrade /> : <Navigate to="/login" />}
          />
          <Route
            path="/balance"
            element={isAuthenticated ? <Balance /> : <Navigate to="/login" />}
          />
          <Route
            path="/profile/:userId"
            element={<Profile />}
          />
          <Route
            path="/about"
            element={<StaticPage slugOverride="about" />}
          />
          <Route
            path="/contact"
            element={<Navigate to="/about" replace />}
          />
          <Route
            path="/faq"
            element={<StaticPage slugOverride="faq" />}
          />
          <Route
            path="/terms"
            element={<StaticPage slugOverride="terms" />}
          />
          <Route
            path="/kvkk"
            element={<StaticPage slugOverride="kvkk" />}
          />
          <Route
            path="/help"
            element={<Navigate to="/faq" replace />}
          />
          <Route
            path="/tutorial"
            element={<Navigate to="/about" replace />}
          />
          <Route
            path="/pages/:slug"
            element={<StaticPage />}
          />
          {/* Public routes - can view but not save/execute */}
          <Route 
            path="/jobs/create" 
            element={<CreateJob />} 
          />
          <Route 
            path="/pipelines/builder" 
            element={<PipelineBuilder />} 
          />
          <Route 
            path="/pipelines/builder/:id" 
            element={<PipelineBuilder />} 
          />
          </Routes>
          <SiteCatWidget />
        </>
      </Router>
      )}
    </AppErrorBoundary>
  )
}

export default App
