"use client"

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import axios from 'axios'

export default function JobDetail({ params }) {
  const { id } = params
  const router = useRouter()
  const [job, setJob] = useState(null)
  const [, setNow] = useState(Date.now())
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem('token')
    const apiUrl = process.env.NEXT_PUBLIC_API_URL

    const loadFromLocal = () => {
      const jobsObjRaw = localStorage.getItem('jobs')
      let jobsObj = JSON.parse(jobsObjRaw || 'null')
      if (!jobsObj || typeof jobsObj !== 'object') jobsObj = {}
      const allJobs = Object.values(jobsObj).flat()
      const found = allJobs.find(j => String(j.id) === String(id))
      setJob(found || null)
    }

    const fetchFromApi = async () => {
      if (!token || !apiUrl) {
        loadFromLocal()
        return
      }
      try {
        const { data } = await axios.get(`${apiUrl}/api/jobs/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        const mapped = {
          id: data.id,
          name: data.name,
          pipeline: data.pipeline,
          notes: data.notes,
          analyses: data.analyses || [],
          files: data.files || [],
          status: data.status,
          estimatedTime: data.estimated_time ?? null,
          estimatedPrice: data.estimated_price ?? null,
          createdAt: data.created_at,
          completedAt: data.completed_at,
          results: data.results,
        }
        setJob(mapped)
      } catch (err) {
        console.error('Failed to fetch job from backend, trying local draft store.', err)
        loadFromLocal()
      }
    }

    fetchFromApi()
  }, [id])

  // Update clock every 5 seconds to keep remaining time live
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 5000)
    return () => clearInterval(iv)
  }, [])

  const formatTime = (t) => {
    const n = Number(t)
    if (!Number.isFinite(n)) return null
    return `${n} hr${n !== 1 ? 's' : ''}`
  }

  const formatBytes = (bytes) => {
    if (bytes == null) return ''
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    let n = Number(bytes) || 0
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
    return `${Math.round(n * 10) / 10} ${units[i]}`
  }

  const remainingDisplay = useMemo(() => {
    if (!job || job.estimatedTime == null) return null
    const start = new Date(job.createdAt).getTime()
    const elapsedMs = Date.now() - start
    const elapsedHours = elapsedMs / (1000 * 60 * 60)
    const remaining = job.estimatedTime - elapsedHours
    const abs = Math.abs(remaining)
    const rounded = Math.round(abs * 100) / 100
    if (remaining >= 0) {
      return `${rounded} hr${rounded !== 1 ? 's' : ''} remaining`
    }
    // Overrun - show with plus sign per request
    return `+${rounded} hr${rounded !== 1 ? 's' : ''}`
  }, [job, /* re-evaluated by the interval via state change */ Date.now()])

  if (!job) {
    return (
      <div className="container mx-auto px-4 py-12">
        <div className="card">
          <p className="text-gray-600">Job not found.</p>
          <div className="mt-4">
            <button onClick={() => router.back()} className="btn-secondary">Go back</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-3xl font-bold text-primary-blue">{job.name}</h1>
          <p className="text-gray-600">Pipeline: {job.pipeline || '—'}</p>
          <p className={`inline-block mt-2 px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(job.status)}`}>
            {job.status}
          </p>
        </div>
        <div className="text-right">
          {job.estimatedTime != null && (
            <p className="text-sm text-gray-700">Estimated Time: <strong>{formatTime(job.estimatedTime)}</strong></p>
          )}
          {job.estimatedPrice != null && (
            <p className="text-sm text-gray-700">Estimated Price: <strong>${Number(job.estimatedPrice).toFixed(2)}</strong></p>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="card">
          <h2 className="text-xl font-semibold text-primary-blue mb-3">Details</h2>
          <p className="text-sm text-gray-500">Created: {new Date(job.createdAt).toLocaleString()}</p>
          {job.completedAt && <p className="text-sm text-gray-500">Completed: {new Date(job.completedAt).toLocaleString()}</p>}

          {remainingDisplay && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-700">Estimated Remaining</h3>
              <p className="text-lg font-semibold mt-1">{remainingDisplay}</p>
            </div>
          )}

          {job.notes && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-700">Notes</h3>
              <pre className="bg-gray-50 p-3 rounded mt-2 whitespace-pre-wrap text-sm">{job.notes}</pre>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="text-xl font-semibold text-primary-blue mb-3">Pipeline & Data</h2>

          <div>
            <h3 className="text-sm font-medium text-gray-700">Tools / Analyses</h3>
            {job.analyses && job.analyses.length > 0 ? (
              <ul className="mt-2 space-y-1 text-sm text-gray-600">
                {job.analyses.map(a => (
                  <li key={a} className="px-2 py-1 bg-gray-50 rounded border border-gray-200">{a}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 mt-2">No tools selected.</p>
            )}
          </div>

          <div className="mt-4">
            <h3 className="text-sm font-medium text-gray-700">Data Files</h3>
            {job.files && job.files.length > 0 ? (
              <ul className="mt-2 space-y-1 text-sm text-gray-600">
                {job.files.map(f => {
                  const name = typeof f === 'string' ? f : f.name
                  const size = typeof f === 'string' ? null : f.size
                  return (
                    <li key={name} className="px-2 py-1 bg-gray-50 rounded border border-gray-200">{name}{size ? ` — ${formatBytes(size)}` : ''}</li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 mt-2">No data files uploaded.</p>
            )}
          </div>

          <div className="mt-6">
            <button
              onClick={async () => await attemptDownload()}
              className={`btn-secondary ${job?.status !== 'completed' ? 'opacity-50 cursor-not-allowed' : ''}`}
              disabled={job?.status !== 'completed' || downloading}
            >
              {downloading ? 'Checking...' : 'Download Results'}
            </button>
            <Link href="/jobs" className="btn-primary ml-3">Back to Jobs</Link>
          </div>
        </div>
      </div>
    </div>
  )
}

async function attemptDownload() {
  if (!job) return
  const token = localStorage.getItem('token')
  const apiUrl = process.env.NEXT_PUBLIC_API_URL

  // If we have a backend, refetch the job from DB to get authoritative status
  if (token && apiUrl) {
    try {
      setDownloading(true)
      const { data } = await axios.get(`${apiUrl}/api/jobs/${job.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const latest = {
        id: data.id,
        name: data.name,
        pipeline: data.pipeline,
        notes: data.notes,
        analyses: data.analyses || [],
        files: data.files || [],
        status: data.status,
        estimatedTime: data.estimated_time ?? null,
        estimatedPrice: data.estimated_price ?? null,
        createdAt: data.created_at,
        completedAt: data.completed_at,
        results: data.results,
      }
      setJob(latest)
      if (latest.status !== 'completed') {
        alert('Job is not finished yet. Results will be available once the job completes.')
        return
      }
      // if completed, proceed to download using existing helper
      downloadJobResults(latest)
    } catch (err) {
      console.error('Failed to fetch latest job status; aborting download', err)
      alert('Unable to check job status with backend. Please try again later.')
    } finally {
      setDownloading(false)
    }
    return
  }

  // Fallback if no backend: rely on local job object and existing helper
  if (job.status !== 'completed') {
    alert('Job is not finished yet. Results will be available once the job completes.')
    return
  }
  downloadJobResults(job)
}

function downloadJobResults(job) {
  if (!job) return

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
  if (job.results && (job.results.s3Path || job.results.report)) {
    const url = job.results.s3Path || job.results.report
    window.open(url, '_blank', 'noopener')
    return
  }
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

function getStatusColor(status) {
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
