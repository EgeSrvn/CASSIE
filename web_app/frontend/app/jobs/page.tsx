'use client'

import { useState, useEffect } from 'react'
import axios from 'axios'
import Link from 'next/link'

interface Job {
  _id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  createdAt: string
  completedAt?: string
  pipeline: string
  results?: {
    s3Path?: string
    report?: string
  }
}

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all')

  useEffect(() => {
    fetchJobs()
  }, [])

  const fetchJobs = async () => {
    const token = localStorage.getItem('token')
    try {
      const { data } = await axios.get(
        `${process.env.NEXT_PUBLIC_API_URL}/api/jobs`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      setJobs(data)
    } catch (error: any) {
      console.error('Failed to fetch jobs:', error)
      // If backend is not available, show empty state with helpful message
      if (error.code === 'ECONNREFUSED' || error.message === 'Network Error') {
        setJobs([])
      }
    } finally {
      setLoading(false)
    }
  }

  const filteredJobs = jobs.filter(job => {
    if (filter === 'active') {
      return job.status === 'pending' || job.status === 'running'
    }
    if (filter === 'completed') {
      return job.status === 'completed' || job.status === 'failed'
    }
    return true
  })

  const getStatusColor = (status: string) => {
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
        <div className="card text-center py-12">
          <p className="text-gray-600 text-lg mb-2">No jobs found</p>
          <p className="text-sm text-gray-500 mb-4">
            {loading ? '' : 'Note: Backend server may not be running. Start the backend to create and view jobs.'}
          </p>
          <Link href="/configure" className="btn-primary inline-block mt-4">
            Create Your First Job
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredJobs.map(job => (
            <div key={job._id} className="card">
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <h3 className="text-xl font-semibold text-primary-blue mb-2">
                    {job.name}
                  </h3>
                  <p className="text-gray-600 mb-2">Pipeline: {job.pipeline}</p>
                  <p className="text-sm text-gray-500">
                    Created: {new Date(job.createdAt).toLocaleString()}
                  </p>
                  {job.completedAt && (
                    <p className="text-sm text-gray-500">
                      Completed: {new Date(job.completedAt).toLocaleString()}
                    </p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-2">
                  <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(job.status)}`}>
                    {job.status}
                  </span>
                  {job.status === 'completed' && job.results && (
                    <a
                      href={job.results.s3Path || job.results.report}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-secondary text-sm"
                    >
                      View Results
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

