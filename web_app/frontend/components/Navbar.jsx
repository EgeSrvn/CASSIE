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
    const storedUser = localStorage.getItem('user')
    if (token && storedUser) {
      setIsAuthenticated(true)
      setUser(JSON.parse(storedUser))
    }
    const handleAuthChange = () => {
      const token2 = localStorage.getItem('token')
      const storedUser2 = localStorage.getItem('user')
      if (token2 && storedUser2) {
        setIsAuthenticated(true)
        setUser(JSON.parse(storedUser2))
      } else {
        setIsAuthenticated(false)
        setUser(null)
      }
    }

    window.addEventListener('authChanged', handleAuthChange)
    return () => window.removeEventListener('authChanged', handleAuthChange)
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setIsAuthenticated(false)
    setUser(null)
    // notify other components
    window.dispatchEvent(new Event('authChanged'))
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
            <Link href="/configure" className="hover:text-secondary-pink transition-colors">
              Configure
            </Link>
            <Link href="/jobs" className="hover:text-secondary-pink transition-colors" onClick={() => window.dispatchEvent(new Event('jobs:refresh'))}>
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
                          <Link href="/profile" className="hover:text-secondary-pink transition-colors">
                            Profile
                          </Link>
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

