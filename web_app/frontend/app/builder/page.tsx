'use client'

import { useState } from 'react'
import ReactFlow, { Node, Edge, addEdge, Connection, Background, Controls } from 'reactflow'
import 'reactflow/dist/style.css'

const nodeTypes = {
  input: ({ data }: any) => (
    <div className="px-4 py-2 bg-primary-blue text-white rounded-lg shadow">
      {data.label}
    </div>
  ),
  process: ({ data }: any) => (
    <div className="px-4 py-2 bg-secondary-pink text-white rounded-lg shadow">
      {data.label}
    </div>
  ),
  output: ({ data }: any) => (
    <div className="px-4 py-2 bg-green-500 text-white rounded-lg shadow">
      {data.label}
    </div>
  ),
}

const initialNodes: Node[] = [
  {
    id: '1',
    type: 'input',
    data: { label: 'Input Data' },
    position: { x: 100, y: 100 },
  },
]

const initialEdges: Edge[] = []

export default function Builder() {
  const [nodes, setNodes] = useState<Node[]>(initialNodes)
  const [edges, setEdges] = useState<Edge[]>(initialEdges)
  const [pipelineName, setPipelineName] = useState('')
  const [pipelineDescription, setPipelineDescription] = useState('')

  const onConnect = (params: Connection) => {
    setEdges((eds) => addEdge(params, eds))
  }

  const addNode = (type: string, label: string) => {
    const newNode: Node = {
      id: `${nodes.length + 1}`,
      type,
      data: { label },
      position: {
        x: Math.random() * 400 + 100,
        y: Math.random() * 400 + 100,
      },
    }
    setNodes((nds) => [...nds, newNode])
  }

  const savePipeline = async () => {
    const token = localStorage.getItem('token')
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/pipelines`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: pipelineName,
          description: pipelineDescription,
          nodes,
          edges,
        }),
      })
      alert('Pipeline saved successfully!')
    } catch (error) {
      console.error('Failed to save pipeline:', error)
      alert('Failed to save pipeline')
    }
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-primary-blue mb-8">
        Visual Pipeline Builder
      </h1>

      <div className="grid lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1">
          <div className="card">
            <h2 className="text-xl font-semibold text-primary-blue mb-4">
              Components
            </h2>
            <div className="space-y-2">
              <button
                onClick={() => addNode('input', 'Input Data')}
                className="w-full btn-primary text-sm"
              >
                Add Input
              </button>
              <button
                onClick={() => addNode('process', 'Read QC')}
                className="w-full btn-secondary text-sm"
              >
                Read QC
              </button>
              <button
                onClick={() => addNode('process', 'Assembly')}
                className="w-full btn-secondary text-sm"
              >
                Assembly
              </button>
              <button
                onClick={() => addNode('process', 'Scaffolding')}
                className="w-full btn-secondary text-sm"
              >
                Scaffolding
              </button>
              <button
                onClick={() => addNode('process', 'Annotation')}
                className="w-full btn-secondary text-sm"
              >
                Annotation
              </button>
              <button
                onClick={() => addNode('output', 'Results')}
                className="w-full bg-green-500 hover:bg-green-600 text-white px-4 py-2 rounded-lg text-sm"
              >
                Add Output
              </button>
            </div>

            <div className="mt-6">
              <h3 className="text-lg font-semibold mb-3">Pipeline Info</h3>
              <input
                type="text"
                placeholder="Pipeline Name"
                value={pipelineName}
                onChange={(e) => setPipelineName(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg mb-3"
              />
              <textarea
                placeholder="Description"
                value={pipelineDescription}
                onChange={(e) => setPipelineDescription(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg mb-3"
                rows={4}
              />
              <button
                onClick={savePipeline}
                className="w-full btn-primary"
              >
                Save Pipeline
              </button>
            </div>
          </div>
        </div>

        <div className="lg:col-span-3">
          <div className="card" style={{ height: '600px' }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onConnect={onConnect}
              nodeTypes={nodeTypes}
              fitView
            >
              <Background />
              <Controls />
            </ReactFlow>
          </div>
        </div>
      </div>
    </div>
  )
}

