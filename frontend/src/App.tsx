import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Login from './pages/Login'
import Register from './pages/Register'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import CreateJob from './pages/CreateJob'
import JobDetails from './pages/JobDetails'
import Pipelines from './pages/Pipelines'
import StarterTemplates from './pages/StarterTemplates'
import PipelineBuilder from './pages/PipelineBuilder'
import Community from './pages/Community'
import Forum from './pages/Forum'
import ForumComposer from './pages/ForumComposer'
import ForumThread from './pages/ForumThread'
import Profile from './pages/Profile'
import StaticPage from './pages/StaticPage'
import VerifyEmail from './pages/VerifyEmail'
import ForgotPassword from './pages/ForgotPassword'
import { getToken } from './services/authService'
import { startPendingJobUploadProcessor } from './services/pendingJobUploadService'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)

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
  }, [])

  if (isAuthenticated === null) {
    return <div>Loading...</div>
  }

  return (
    <Router>
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
          element={isAuthenticated ? <Dashboard onLogout={() => setIsAuthenticated(false)} /> : <Navigate to="/login" />} 
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
          path="/profile/:userId"
          element={<Profile />}
        />
        <Route
          path="/contact"
          element={<Navigate to="/pages/contact" replace />}
        />
        <Route
          path="/about"
          element={<Navigate to="/pages/about" replace />}
        />
        <Route
          path="/help"
          element={<Navigate to="/pages/help" replace />}
        />
        <Route
          path="/tutorial"
          element={<Navigate to="/pages/tutorial" replace />}
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
    </Router>
  )
}

export default App
