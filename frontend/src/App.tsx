import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
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

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!getToken())

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
    void startPendingJobUploadProcessor()
    void startStorageUploadProcessor()
  }, [])

  return (
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
  )
}

export default App
