'use client'

import { useState, useEffect } from 'react'
import axios from 'axios'
import { useRouter } from 'next/navigation'

export default function Community() {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  // Reload from storage when user navigates back to the page
  useEffect(() => {
    const onFocus = () => {
      const local = localStorage.getItem('community_workflows')
      if (local) setWorkflows(JSON.parse(local))
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  useEffect(() => {
    fetchWorkflows()
  }, [])

  // Helpers to persist community workflows locally when no backend is available
  const STORAGE_KEY = 'community_workflows'
  const loadLocal = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      return raw ? JSON.parse(raw) : null
    } catch (e) {
      return null
    }
  }
  const saveLocal = (arr) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(arr))
    } catch (e) {
      /* ignore */
    }
  }

  const fetchWorkflows = async () => {
    // Define a sample workflow to show if the API is unavailable or returns none
    const sample = {
      _id: 'sample-community-1',
      name: 'Hybrid Assembly + QC Pipeline',
      description:
        'A compact pipeline that performs hybrid assembly and quality control. Works well for bacterial genomes. Comment: "Great for small genomes!"',
      tags: ['assembly', 'qc', 'hybrid'],
      author: 'community_user',
      downloads: 42,
      upvotes: 12,
      downvotes: 3,
      votes: 12 - 3,
      comments: [
        { author: 'alice', text: 'Clean and fast — produced good contigs on my test dataset' },
      ],
      nodes: [],
      edges: [],
    }

    // If local data exists, use it (persisted from previous interaction)
    const local = loadLocal()
    if (local && Array.isArray(local) && local.length > 0) {
      setWorkflows(local)
      setLoading(false)
      return
    }

    // If no backend is configured, seed local storage with sample and stop
    if (!process.env.NEXT_PUBLIC_API_URL) {
      saveLocal([sample])
      setWorkflows([sample])
      setLoading(false)
      return
    }

    try {
      const { data } = await axios.get(
        `${process.env.NEXT_PUBLIC_API_URL}/api/community/workflows`
      )
      // Prepend the sample so it's always visible at the top
      const combined = [sample, ...(Array.isArray(data) ? data : [])]
      setWorkflows(combined)
      // Persist so users see any changes locally later
      saveLocal(combined)
    } catch (error) {
      console.error('Failed to fetch workflows:', error)
      // Fallback to only the sample so the page isn't empty
      saveLocal([sample])
      setWorkflows([sample])
    } finally {
      setLoading(false)
    }
  }

  const handleVote = async (workflowId) => {
    // Optimistically update the local state so votes feel instant when offline
    setWorkflows(prev => {
      const updated = prev.map(w => {
        if (w._id === workflowId) {
          const up = (w.upvotes || 0) + 1
          const votes = (w.votes || 0) + 1
          return { ...w, upvotes: up, votes }
        }
        return w
      })
      // Persist quick local update
      saveLocal(updated)
      return updated
    })

    // If no backend is configured, stop here (local-only behavior)
    if (!process.env.NEXT_PUBLIC_API_URL) return

    const token = localStorage.getItem('token')
    try {
      await axios.post(
        `${process.env.NEXT_PUBLIC_API_URL}/api/community/workflows/${workflowId}/vote`,
        { vote: 'up' },
        { headers: { Authorization: `Bearer ${token}` } }
      )
      // Optionally refresh from server; already updated optimistically
    } catch (error) {
      console.error('Failed to vote:', error)
    }
  }

  const handleDownvote = async (workflowId) => {
    // Optimistically update the local state for downvotes
    setWorkflows(prev => {
      const updated = prev.map(w => {
        if (w._id === workflowId) {
          const down = (w.downvotes || 0) + 1
          const votes = (w.votes || 0) - 1
          return { ...w, downvotes: down, votes }
        }
        return w
      })
      saveLocal(updated)
      return updated
    })

    if (!process.env.NEXT_PUBLIC_API_URL) return

    const token = localStorage.getItem('token')
    try {
      await axios.post(
        `${process.env.NEXT_PUBLIC_API_URL}/api/community/workflows/${workflowId}/vote`,
        { vote: 'down' },
        { headers: { Authorization: `Bearer ${token}` } }
      )
    } catch (error) {
      console.error('Failed to downvote:', error)
    }
  }

  const filteredWorkflows = workflows.filter(workflow => {
    const q = searchTerm.toLowerCase()
    const name = (workflow.name || '').toLowerCase()
    const desc = (workflow.description || '').toLowerCase()
    const author = (workflow.author || '').toLowerCase()
    const tags = (workflow.tags || []).join(' ').toLowerCase()
    return (
      name.includes(q) ||
      desc.includes(q) ||
      author.includes(q) ||
      tags.includes(q)
    )
  })

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-12">
        <p className="text-center text-gray-600">Loading workflows...</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-primary-blue">
          Community Workflows
        </h1>
      </div>

      <div className="mb-6">
        <input
          type="text"
          placeholder="Search workflows..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full max-w-md px-4 py-2 border border-gray-300 rounded-lg"
        />
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredWorkflows.map(workflow => (
          <div key={workflow._id} className="card">
            <h3 className="text-xl font-semibold text-primary-blue mb-2">
              {workflow.name}
            </h3>
            <p className="text-gray-600 mb-4 line-clamp-3">
              {workflow.description}
            </p>
            <div className="flex flex-wrap gap-2 mb-4">
              {(workflow.tags || []).map(tag => (
                <span
                  key={tag}
                  className="px-2 py-1 bg-secondary-pink-light text-primary-blue rounded text-sm"
                >
                  {tag}
                </span>
              ))}
            </div>
            <div className="flex justify-between items-center text-sm text-gray-500 mb-4">
              <span>By {workflow.author}</span>
              <span>{workflow.downloads} downloads</span>
            </div>
            {(workflow.upvotes || workflow.downvotes || (workflow.comments && workflow.comments.length > 0)) && (
              <div className="text-sm text-gray-500 mb-4">
                {(workflow.upvotes || 0) > 0 && <span className="mr-3">↑ {workflow.upvotes}</span>}
                {(workflow.downvotes || 0) > 0 && <span className="mr-3">↓ {workflow.downvotes}</span>}
                {workflow.comments && workflow.comments.length > 0 && (
                  <span>“{workflow.comments[0].text}” — {workflow.comments[0].author}</span>
                )}
              </div>
            )}
            <div className="flex gap-2 items-center">
              <button
                onClick={() => handleVote(workflow._id)}
                className="btn-secondary text-sm"
                title="Upvote"
              >
                ↑ {workflow.upvotes || 0}
              </button>
              <button
                onClick={() => handleDownvote(workflow._id)}
                className="btn-secondary text-sm"
                title="Downvote"
              >
                ↓ {workflow.downvotes || 0}
              </button>
              <div className="ml-2 text-sm text-gray-600">Score: {workflow.votes || 0}</div>
              <div className="flex-1" />
              <UseButton workflow={workflow} />
            </div>
          </div>
        ))}
      </div>

      {filteredWorkflows.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-600">No workflows found</p>
        </div>
      )}
    </div>
  )
}

function UseButton({ workflow }) {
  const router = useRouter()
  const handleUse = () => {
    // store the workflow as a draft pipeline for Builder
    const draft = {
      id: workflow._id || workflow.id || Date.now().toString(),
      name: workflow.name,
      description: workflow.description,
      nodes: workflow.nodes || [],
      edges: workflow.edges || [],
    }
    localStorage.setItem('pipelineDraft', JSON.stringify(draft))
    router.push('/builder?draft=true')
  }

  return (
    <button onClick={handleUse} className="flex-1 btn-primary text-sm">
      Use Pipeline
    </button>
  )
}

