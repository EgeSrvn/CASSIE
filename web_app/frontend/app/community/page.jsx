'use client'

import { useState, useEffect } from 'react'
import axios from 'axios'
import { useRouter } from 'next/navigation'

export default function Community() {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')

  useEffect(() => {
    fetchWorkflows()
  }, [])

  const fetchWorkflows = async () => {
    try {
      const { data } = await axios.get(
        `${process.env.NEXT_PUBLIC_API_URL}/api/community/workflows`
      )
      setWorkflows(data)
    } catch (error) {
      console.error('Failed to fetch workflows:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleVote = async (workflowId) => {
    const token = localStorage.getItem('token')
    try {
      await axios.post(
        `${process.env.NEXT_PUBLIC_API_URL}/api/community/workflows/${workflowId}/vote`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      )
      fetchWorkflows()
    } catch (error) {
      console.error('Failed to vote:', error)
    }
  }

  const filteredWorkflows = workflows.filter(workflow =>
    workflow.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    workflow.description.toLowerCase().includes(searchTerm.toLowerCase())
  )

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
              {workflow.tags.map(tag => (
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
            <div className="flex gap-2">
              <button
                onClick={() => handleVote(workflow._id)}
                className="flex-1 btn-secondary text-sm"
              >
                ↑ Vote ({workflow.votes})
              </button>
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

