'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const router = useRouter()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    const stored = localStorage.getItem('user')
    const storedUser = stored ? JSON.parse(stored) : { email: 'demo@cassie.dev', password: 'demo123' }
    const isValid =
      (email === storedUser.email && password === storedUser.password) ||
      (email === 'demo@cassie.dev' && password === 'demo123')

    if (!isValid) {
      setError('Invalid credentials. Try demo@cassie.dev / demo123.')
      return
    }

    localStorage.setItem('token', 'demo-token')
    localStorage.setItem('user', JSON.stringify({ email }))
    // notify other components that auth changed
    window.dispatchEvent(new Event('authChanged'))
    router.push('/')
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="max-w-md mx-auto card">
        <h1 className="text-3xl font-bold text-primary-blue mb-6 text-center">
          Login
        </h1>
        
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-gray-700 font-medium mb-2">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-blue focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-gray-700 font-medium mb-2">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-blue focus:border-transparent"
            />
          </div>

          <button
            type="submit"
            className="w-full btn-primary"
          >
            Login
          </button>
        </form>

        <p className="mt-4 text-center text-gray-600">
          Don't have an account?{' '}
          <Link href="/register" className="text-primary-blue hover:underline">
            Register here
          </Link>
        </p>
      </div>
    </div>
  )
}

