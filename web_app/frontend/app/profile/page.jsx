"use client"

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import axios from 'axios'

export default function ProfilePage() {
  const router = useRouter()
  const [user, setUser] = useState(null)
  const [pipelines, setPipelines] = useState([])

  useEffect(() => {
    const token = localStorage.getItem('token')
    const storedUser = localStorage.getItem('user')
    if (!token || !storedUser) {
      // if not authed, redirect to login
      router.push('/login')
      return
    }
    const parsedUser = JSON.parse(storedUser)
    setUser(parsedUser)

    const apiUrl = process.env.NEXT_PUBLIC_API_URL

    const loadFromLocal = () => {
      let pipelinesObj = JSON.parse(localStorage.getItem('pipelines') || 'null')
      const userEmail = parsedUser.email
      if (Array.isArray(pipelinesObj)) {
        setPipelines(pipelinesObj)
      } else {
        pipelinesObj = pipelinesObj || {}
        setPipelines(pipelinesObj[userEmail] || [])
      }
    }

    const fetchFromApi = async () => {
      if (!apiUrl || !token) {
        loadFromLocal()
        return
      }
      try {
        const { data } = await axios.get(`${apiUrl}/api/pipelines`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        const mapped = data.map(p => ({
          id: p.id,
          name: p.name,
          description: p.description,
          nodes: p.nodes || [],
          edges: p.edges || [],
          savedAt: p.saved_at,
        }))
        setPipelines(mapped)
      } catch (err) {
        console.error('Failed to fetch pipelines from backend, using local store.', err)
        loadFromLocal()
      }
    }

    fetchFromApi()
    const handleAuthChange = () => {
      const sUser = localStorage.getItem('user')
      if (!sUser) {
        router.push('/login')
        return
      }
      const u = JSON.parse(sUser)
      setUser(u)
      const pObj = JSON.parse(localStorage.getItem('pipelines') || '{}')
      setPipelines(pObj[u.email] || [])
    }

    window.addEventListener('authChanged', handleAuthChange)
    // For backwards-compatibility with the builder's local fallback
    const handlePipelinesChanged = () => {
      const sUser = localStorage.getItem('user')
      if (!sUser) return
      const u = JSON.parse(sUser)
      let pObj = JSON.parse(localStorage.getItem('pipelines') || 'null')
      if (Array.isArray(pObj)) {
        setPipelines(pObj)
        return
      }
      pObj = pObj || {}
      setPipelines(pObj[u.email] || [])
    }
    window.addEventListener('pipelinesChanged', handlePipelinesChanged)
    return () => {
      window.removeEventListener('authChanged', handleAuthChange)
      window.removeEventListener('pipelinesChanged', handlePipelinesChanged)
    }
  }, [router])

  return (
    <div className="container mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-primary-blue mb-6">Profile</h1>

      {user && (
        <div className="card mb-6 p-6">
          <h2 className="text-xl font-semibold mb-2">Account</h2>
          <p className="text-sm text-gray-700">Email: {user.email}</p>
        </div>
      )}

      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Saved Pipelines</h2>
          <Link href="/builder" className="text-primary-blue hover:underline">Create New</Link>
        </div>

        {pipelines.length === 0 ? (
          <p className="text-sm text-gray-600">No saved pipelines yet.</p>
        ) : (
          <div className="space-y-4">
            {pipelines.map((p) => (
              <div key={p.id} className="border rounded-lg p-4 bg-white">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold">{p.name}</h3>
                    <p className="text-xs text-gray-500">Saved {new Date(p.savedAt).toLocaleString()}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => {
                        localStorage.setItem('pipelineDraft', JSON.stringify(p))
                        router.push('/builder?draft=true')
                      }}
                      className="btn-secondary px-3 py-1"
                    >
                      Load
                    </button>
                    <button
                      onClick={async () => {
                        const apiUrl = process.env.NEXT_PUBLIC_API_URL
                        const token = localStorage.getItem('token')

                        // If no backend, keep previous local-only delete
                        if (!apiUrl || !token) {
                          const remaining = pipelines.filter((x) => x.id !== p.id)
                          setPipelines(remaining)
                          const pipelinesObj = JSON.parse(localStorage.getItem('pipelines') || '{}')
                          const owner = user.email
                          pipelinesObj[owner] = remaining
                          localStorage.setItem('pipelines', JSON.stringify(pipelinesObj))
                          return
                        }

                        try {
                          await axios.delete(`${apiUrl}/api/pipelines/${p.id}`, {
                            headers: { Authorization: `Bearer ${token}` },
                          })
                          setPipelines((prev) => prev.filter((x) => x.id !== p.id))
                        } catch (err) {
                          console.error('Failed to delete pipeline from backend, falling back to local delete.', err)
                          const remaining = pipelines.filter((x) => x.id !== p.id)
                          setPipelines(remaining)
                          const pipelinesObj = JSON.parse(localStorage.getItem('pipelines') || '{}')
                          const owner = user.email
                          pipelinesObj[owner] = remaining
                          localStorage.setItem('pipelines', JSON.stringify(pipelinesObj))
                        }
                      }}
                      className="btn-danger px-3 py-1"
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {p.description && <p className="text-sm text-gray-700 mt-2">{p.description}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
