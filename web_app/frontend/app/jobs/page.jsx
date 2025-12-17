"use client"

import { useState, useEffect } from 'react'
import Link from 'next/link'
import axios from 'axios'

export default function Jobs() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [isAuthed, setIsAuthed] = useState(false)
  // Clock tick used to keep remaining time live
  const [, setNow] = useState(Date.now())
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 5000)
    return () => clearInterval(iv)
  }, [])

  const apiUrl = process.env.NEXT_PUBLIC_API_URL

  // Refresh jobs from backend (keeps estimated time and status up-to-date)
  const refreshFromApi = async () => {
    const token = localStorage.getItem('token')
    if (!token || !apiUrl) return
    try {
      const { data } = await axios.get(`${apiUrl}/api/jobs`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const mapped = data.map(j => ({
        id: j.id,
        name: j.name,
        pipeline: j.pipeline,
        notes: j.notes,
        analyses: j.analyses || [],
        files: j.files || [],
        status: j.status,
        estimatedTime: j.estimated_time ?? null,
        estimatedPrice: j.estimated_price ?? null,
        // backend can optionally return an estimated_finish timestamp (ISO)
        estimatedFinish: j.estimated_finish ?? null,
        createdAt: j.created_at,
        completedAt: j.completed_at,
        results: j.results,
      }))
      setJobs(mapped)
    } catch (err) {
      console.error('Failed to refresh jobs from backend.', err)
    }
  }

  // Poll backend for updates when authed
  useEffect(() => {
    let poll = null
    if (isAuthed && apiUrl) {
      poll = setInterval(refreshFromApi, 5000)
    }
    return () => { if (poll) clearInterval(poll) }
  }, [isAuthed, apiUrl])

  const formatPrice = (p) => {
    const n = Number(p)
    if (!Number.isFinite(n)) return null
    return `$${n.toFixed(2)}`
  }

  const formatTime = (t) => {
    const n = Number(t)
    if (!Number.isFinite(n)) return null
    return `${n} hr${n !== 1 ? 's' : ''}`
  }

  const formatRemaining = (job) => {
    if (!job) return null
    let remainingHours = null
    // Prefer explicit estimatedFinish if provided by backend
    if (job.estimatedFinish) {
      const finishMs = new Date(job.estimatedFinish).getTime()
      const diffMs = finishMs - Date.now()
      remainingHours = diffMs / (1000 * 60 * 60)
    } else if (job.estimatedTime != null && job.createdAt) {
      const start = new Date(job.createdAt).getTime()
      const finishMs = start + (Number(job.estimatedTime) * 60 * 60 * 1000)
      remainingHours = (finishMs - Date.now()) / (1000 * 60 * 60)
    } else {
      return null
    }

    const abs = Math.abs(remainingHours)
    const rounded = Math.round(abs * 100) / 100
    if (remainingHours >= 0) {
      return `${rounded} hr${rounded !== 1 ? 's' : ''} remaining`
    }
    return `+${rounded} hr${rounded !== 1 ? 's' : ''}`
  }

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      setIsAuthed(false)
      setLoading(false)
      return
    }
    setIsAuthed(true)
    const user = JSON.parse(localStorage.getItem('user') || 'null')

    const apiUrl = process.env.NEXT_PUBLIC_API_URL

    const loadFromLocal = () => {
      const jobsObjRaw = localStorage.getItem('jobs')
      let jobsObj = JSON.parse(jobsObjRaw || 'null')
      if (!jobsObj || typeof jobsObj !== 'object') jobsObj = {}
      const userJobs = user ? (jobsObj[user.email] || []) : []

      const hasCompleted = userJobs.some(j => j.status === 'completed')
      if (!hasCompleted && user) {
        const sample = {
          id: `sample-${Date.now()}`,
          name: 'A. naeslundii Genome Analysis',
          pipeline: 'A. naeslundii Genome Analysis',
          analyses: [],
          files: [],
          createdAt: new Date().toISOString(),
          completedAt: new Date().toISOString(),
          status: 'completed',
          owner: user.email,
          results: { content: 'Example job results\nSample metrics: accuracy=0.98\nFiles: result.txt' },
        }
        const updated = [...userJobs, sample]
        jobsObj[user.email] = updated
        localStorage.setItem('jobs', JSON.stringify(jobsObj))
        setJobs(updated)
      } else {
        setJobs(userJobs)
      }
    }

    const fetchFromApi = async () => {
      if (!apiUrl) {
        loadFromLocal()
        setLoading(false)
        return
      }
      // Use refreshFromApi which also handles mapping and error handling
      await refreshFromApi()
      setLoading(false)
    }

    fetchFromApi()

    // Refresh jobs when the user explicitly clicks the Jobs link in the navbar
    const handleJobsRefresh = () => { refreshFromApi() }
    window.addEventListener('jobs:refresh', handleJobsRefresh)
    return () => window.removeEventListener('jobs:refresh', handleJobsRefresh)
  }, [])

  const filteredJobs = jobs.filter(job => {
    if (filter === 'active') {
      return job.status === 'pending' || job.status === 'running'
    }
    if (filter === 'completed') {
      return job.status === 'completed' || job.status === 'failed'
    }
    return true
  })

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-800'
      case 'running':
        return 'bg-blue-100 text-blue-800'
      case 'failed':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-yellow-100 text-yellow-800'
    }
  }

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-12">
        <p className="text-center text-gray-600">Loading jobs...</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-primary-blue">
          Jobs
        </h1>
        <Link href="/configure" className="btn-primary">
          Create New Job
        </Link>
      </div>

      {!isAuthed ? (
        <div className="card text-center py-12">
          <p className="text-gray-600 text-lg mb-3">Login required to view jobs.</p>
          <div className="flex justify-center gap-4">
            <Link href="/login" className="btn-primary">
              Login
            </Link>
            <Link href="/register" className="btn-secondary">
              Register
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="flex gap-4 mb-6">
            <button
              onClick={() => setFilter('all')}
              className={`px-4 py-2 rounded-lg ${
                filter === 'all' ? 'bg-primary-blue text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setFilter('active')}
              className={`px-4 py-2 rounded-lg ${
                filter === 'active' ? 'bg-primary-blue text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              Active
            </button>
            <button
              onClick={() => setFilter('completed')}
              className={`px-4 py-2 rounded-lg ${
                filter === 'completed' ? 'bg-primary-blue text-white' : 'bg-gray-200 text-gray-700'
              }`}
            >
              Completed
            </button>
          </div>

          {filteredJobs.length === 0 ? (
            <>
              <div className="card text-center py-12">
                <p className="text-gray-600 text-lg mb-2">No jobs in this template.</p>
                <p className="text-sm text-gray-500 mb-4">
                  Configure a run to imagine how results would appear once a backend is added.
                </p>
                <Link href="/configure" className="btn-primary inline-block mt-4">
                  Draft a Job
                </Link>
              </div>

              {/* Example completed job to demonstrate download link */}
              <div className="card mt-6">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <h3 className="text-xl font-semibold text-primary-blue mb-2">A. naeslundii Genome Analysis</h3>
                    <p className="text-gray-600 mb-2">A. naeslundii Genome Analysis</p>
                    <p className="text-sm text-gray-500">Created: {new Date().toLocaleString()}</p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800`}>
                      completed
                    </span>
                    <button
                      onClick={() => downloadSampleResults()}
                      className="btn-secondary text-sm"
                    >
                      Download Results
                    </button>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="space-y-4">
              {filteredJobs.map(job => (
                <div key={job.id || job._id} className="card">
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <Link href={`/jobs/${job.id}`} className="inline-block">
                        <h3 className="text-xl font-semibold text-primary-blue mb-2">
                          {job.name}
                        </h3>
                      </Link>
                      <p className="text-gray-600 mb-2">Pipeline: {job.pipeline}</p>
                      <p className="text-sm text-gray-500">
                        Created: {new Date(job.createdAt).toLocaleString()}
                      </p>
                      {job.completedAt && (
                        <p className="text-sm text-gray-500">
                          Completed: {new Date(job.completedAt).toLocaleString()}
                        </p>
                      )}

                      {job.analyses && job.analyses.length > 0 && (
                        <p className="text-sm text-gray-600 mt-2">Tools: {job.analyses.join(', ')}</p>
                      )}

                      {job.files && job.files.length > 0 && (
                        <p className="text-sm text-gray-600 mt-1">Data: {job.files.map(f => (typeof f === 'string' ? f : f.name)).join(', ')}</p>
                      )} 

                      {job.estimatedTime != null && formatTime(job.estimatedTime) && (
                        <>
                          <p className="text-sm text-gray-600 mt-2">
                            Estimated Time: {formatTime(job.estimatedTime)}
                          </p>
                          {(job.status === 'running' || job.status === 'pending') && (
                            <p className="text-sm text-gray-700 mt-1 font-semibold">
                              {formatRemaining(job)}
                            </p>
                          )}
                        </>
                      )}

                      {job.estimatedPrice != null && formatPrice(job.estimatedPrice) && (
                        <p className="text-sm text-gray-600">
                          Estimated Price: {formatPrice(job.estimatedPrice)}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(job.status)}`}>
                        {job.status}
                      </span>
                      {job.status === 'completed' && (
                        <button
                          onClick={() => downloadJobResults(job)}
                          className="btn-secondary text-sm"
                        >
                          Download Results
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function downloadSampleResults() {
  const content = 'Example job results\nSample metrics: accuracy=0.98\nFiles: result.txt'
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'example-results.txt'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

function downloadJobResults(job) {
  // If the job has a results.content string, download it directly.
  if (job.results && job.results.content) {
    const blob = new Blob([job.results.content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(job.name || 'results').replace(/\s+/g, '_')}-results.txt`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 5000)
    return
  }

  // If results has a URL, open it in a new tab
  if (job.results && (job.results.s3Path || job.results.report)) {
    const url = job.results.s3Path || job.results.report
    window.open(url, '_blank', 'noopener')
    return
  }

  // Fallback to the generic sample downloader
  downloadSampleResults()
}

