'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function Navbar() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [user, setUser] = useState(null)
  const router = useRouter()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      setIsAuthenticated(true)
      // Fetch user info - gracefully handle if backend is not available
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(res => {
          if (res.ok) return res.json()
          throw new Error('Backend not available')
        })
        .then(data => setUser(data))
        .catch(() => {
          // Keep authentication state if token exists, even if backend is down
          // This allows frontend-only browsing
          setUser({ email: 'Demo User' })
        })
    }
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('token')
    setIsAuthenticated(false)
    setUser(null)
    router.push('/')
  }

  return (
    <nav className="bg-primary-blue text-white shadow-lg">
      <div className="container mx-auto px-4">
        <div className="flex justify-between items-center py-4">
          <Link href="/" className="text-2xl font-bold">
            Cassie
          </Link>
          
          <div className="flex items-center gap-6">
            <Link href="/" className="hover:text-secondary-pink transition-colors">
              Home
            </Link>
            <Link href="/upload" className="hover:text-secondary-pink transition-colors">
              Upload
            </Link>
            <Link href="/configure" className="hover:text-secondary-pink transition-colors">
              Configure
            </Link>
            <Link href="/jobs" className="hover:text-secondary-pink transition-colors">
              Jobs
            </Link>
            <Link href="/community" className="hover:text-secondary-pink transition-colors">
              Community
            </Link>
            <Link href="/builder" className="hover:text-secondary-pink transition-colors">
              Builder
            </Link>
            
            {isAuthenticated ? (
              <div className="flex items-center gap-4">
                <span className="text-sm">Welcome, {user?.email || 'User'}</span>
                <button
                  onClick={handleLogout}
                  className="bg-secondary-pink hover:bg-secondary-pink-dark px-4 py-2 rounded-lg transition-colors"
                >
                  Logout
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-4">
                <Link
                  href="/login"
                  className="bg-secondary-pink hover:bg-secondary-pink-dark px-4 py-2 rounded-lg transition-colors"
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="bg-white text-primary-blue hover:bg-gray-100 px-4 py-2 rounded-lg transition-colors"
                >
                  Register
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  )
}

