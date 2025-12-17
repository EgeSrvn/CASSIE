"use client"

import { useState, useEffect } from 'react'
import Link from 'next/link'
import axios from 'axios'

export default function Jobs() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [isAuthed, setIsAuthed] = useState(false)
  // Keep track of expanded jobs (ids)
  const [expanded, setExpanded] = useState([])

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
          name: 'Hybrid Assembly + QC Run',
          // pipeline is an array of tools used
          pipeline: ['fastqc', 'genomescope2', 'spades', 'quast'],
          analyses: [],
          files: [],
          createdAt: new Date().toISOString(),
          completedAt: new Date().toISOString(),
          status: 'completed',
          owner: user.email,
          // Link results to a location under the frontend public folder for easy editing later
          results: {
            folder: '/sample-results/hybrid-assembly/',
            report: '/sample-results/hybrid-assembly/fastqc_report.html',
            files: ['/sample-results/hybrid-assembly/result.txt']
          },
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

              {/* UPDATED HARDCODED EXAMPLE JOB */}
              <div className="card mt-6">
                <div className="flex justify-between items-start">
                  <div
                    className="flex-1 cursor-pointer"
                    onClick={() => {
                      const jid = 'hardcoded-hybrid-example';
                      setExpanded(prev => prev.includes(jid) ? prev.filter(x => x !== jid) : [...prev, jid])
                    }}
                  >
                    <h3 className="text-xl font-semibold text-primary-blue mb-2">
                      Hybrid Assembly + QC Run
                    </h3>
                    <p className="text-gray-600 mb-2">Pipeline: fastqc, genomescope2, spades, quast</p>
                    <p className="text-sm text-gray-500">
                      Created: {new Date().toLocaleString()}
                    </p>
                    <p className="text-sm text-gray-500">
                      Completed: {new Date().toLocaleString()}
                    </p>

                    {expanded.includes('hardcoded-hybrid-example') && (
                      <div className="mt-3 text-sm text-gray-700">
                        <p className="mb-2">Notes: This is a static example of a hybrid assembly run.</p>
                        
                        <div className="mb-2">
                          <strong>Analyses:</strong>
                          <ul className="list-disc list-inside">
                            <li>Quality Control (FastQC)</li>
                            <li>Genome Profiling (GenomeScope)</li>
                            <li>Assembly (SPAdes)</li>
                          </ul>
                        </div>

                        <div className="mb-2">
                          <strong>Files:</strong>
                          <ul className="list-disc list-inside">
                            <li>sample_R1.fastq.gz</li>
                            <li>sample_R2.fastq.gz</li>
                            <li>nanopore_reads.fastq.gz</li>
                          </ul>
                        </div>

                        <div className="mb-2">
                          <strong>Results Preview:</strong>
                          <pre className="whitespace-pre-wrap bg-gray-50 p-3 rounded">
                            SPAdes Assembly stats:
                            N50: 124,500 bp
                            Total Length: 4.6 Mbp
                            GC Content: 50.8%
                          </pre>
                        </div>
                        
                        <div className="mt-2">
                          <span className="btn-ghost text-sm inline-block mr-2 opacity-50 cursor-not-allowed">Open Job Page</span>
                        </div>
                      </div>
                    )}
                    
                    <p className="text-sm text-gray-600 mt-2">Tools: FastQC, Spades, QUAST</p>
                    <p className="text-sm text-gray-600 mt-1">Estimated Time: 4h 15m</p>
                  </div>

                    <div className="flex flex-col items-end gap-2">
                      <span className="px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
                        completed
                      </span>
                      
                      <div className="flex gap-2">
                        {/* Download a pre-zipped results folder from public/ */}
                        <a 
                          href="/sample-results/hybrid-assembly/results.zip" 
                          download 
                          onClick={(e) => e.stopPropagation()} 
                          className="btn-secondary text-sm"
                        >
                          Download Results
                        </a>
                        {/* Open a QC viewer that renders FastQC SVGs from a folder */}
                        <Link 
                          href={`/qc?folder=${encodeURIComponent('/sample-results/hybrid-assembly/fastqc')}`} 
                          onClick={(e) => e.stopPropagation()} 
                          className="btn-primary text-sm"
                        >
                          See Quality Control
                        </Link>
                      </div>
                    </div>
                </div>
              </div>
              {/* END UPDATED HARDCODED EXAMPLE JOB */}
            </>
          ) : (
            <div className="space-y-4">
              {filteredJobs.map(job => (
                <div key={job.id || job._id} className="card">
                  <div className="flex justify-between items-start">
                    <div
                      className="flex-1 cursor-pointer"
                      onClick={() => {
                        const jid = job.id || job._id
                        setExpanded(prev => prev.includes(jid) ? prev.filter(x => x !== jid) : [...prev, jid])
                      }}
                    >
                      <h3 className="text-xl font-semibold text-primary-blue mb-2">
                        {job.name}
                      </h3>
                      <p className="text-gray-600 mb-2">Pipeline: {Array.isArray(job.pipeline) ? job.pipeline.join(', ') : job.pipeline}</p>
                      <p className="text-sm text-gray-500">
                        Created: {new Date(job.createdAt).toLocaleString()}
                      </p>
                      {job.completedAt && (
                        <p className="text-sm text-gray-500">
                          Completed: {new Date(job.completedAt).toLocaleString()}
                        </p>
                      )}

                      {expanded.includes(job.id || job._id) && (
                        <div className="mt-3 text-sm text-gray-700">
                          {job.notes && <p className="mb-2">Notes: {job.notes}</p>}
                          {Array.isArray(job.analyses) && job.analyses.length > 0 && (
                            <div className="mb-2">
                              <strong>Analyses:</strong>
                              <ul className="list-disc list-inside">
                                {job.analyses.map((a, i) => <li key={i}>{a}</li>)}
                              </ul>
                            </div>
                          )}
                          {Array.isArray(job.files) && job.files.length > 0 && (
                            <div className="mb-2">
                              <strong>Files:</strong>
                              <ul className="list-disc list-inside">
                                {job.files.map((f, i) => (
                                  <li key={i}><a href={typeof f === 'string' ? f : f.url || '#'} onClick={(e)=>e.stopPropagation()} target="_blank" rel="noopener">{typeof f === 'string' ? f : f.name || f.url}</a></li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {job.results && job.results.content && (
                            <div className="mb-2">
                              <strong>Results:</strong>
                              <pre className="whitespace-pre-wrap bg-gray-50 p-3 rounded">{job.results.content}</pre>
                            </div>
                          )}
                          <div className="mt-2">
                            <Link href={`/jobs/${job.id}`} onClick={(e)=>e.stopPropagation()} className="btn-ghost text-sm inline-block mr-2">Open Job Page</Link>
                          </div>
                        </div>
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
                      {job.status === 'completed' && (() => {
                        const hasFastQC = Array.isArray(job.pipeline)
                          ? job.pipeline.includes('fastqc')
                          : (typeof job.pipeline === 'string' && job.pipeline.toLowerCase().includes('fastqc'))

                        // Attempt to find a QC report path from results or files
                        const reportFromResults = job.results && (job.results.report || job.results.folder)
                        let reportFromFiles = Array.isArray(job.files)
                          ? job.files.find(f => f.toLowerCase().includes('fastqc') && f.toLowerCase().endsWith('.html'))
                          : null
                        // If file is relative and a results.folder exists, build an absolute path
                        if (reportFromFiles && !reportFromFiles.startsWith('/') && job.results && job.results.folder) {
                          reportFromFiles = job.results.folder.replace(/\/$/, '') + '/' + reportFromFiles
                        }
                        // If file is a bare filename and we didn't find a folder, prefix with / for relative resolution
                        if (reportFromFiles && !reportFromFiles.startsWith('/') && !reportFromFiles.startsWith('http')) {
                          reportFromFiles = '/' + reportFromFiles
                        }

                        const qcReport = reportFromResults ? (job.results.report || job.results.folder) : reportFromFiles

                        return (
                          <div className="flex gap-2">
                            <button
                              onClick={(e) => { e.stopPropagation(); downloadJobResults(job) }}
                              className="btn-secondary text-sm"
                            >
                              Download Results
                            </button>
                            {hasFastQC && qcReport && (
                              <Link href={`/qc?report=${encodeURIComponent(qcReport)}`} onClick={(e)=>e.stopPropagation()} className="btn-primary text-sm">
                                See Quality Control
                              </Link>
                            )}
                          </div>
                        )
                      })()}
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

  // If results.files exists, open the first file or download it
  if (job.results && Array.isArray(job.results.files) && job.results.files.length > 0) {
    const file = job.results.files[0]
    // If it's an absolute or relative URL path, open it
    if (file.startsWith('http') || file.startsWith('/')) {
      window.open(file, '_blank', 'noopener')
      return
    }
    // Otherwise, show it as text in a new tab
    const blob = new Blob([file], { type: 'text/plain' })
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