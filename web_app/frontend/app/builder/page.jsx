"use client"

import { useCallback, useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  addEdge,
  useEdgesState,
  useNodesState,
} from 'reactflow'
import 'reactflow/dist/style.css'

const NodeBox = ({ label, description, color, showTarget = true, showSource = true }) => (
  <div className="relative w-52 bg-white rounded-lg shadow border border-gray-200 overflow-hidden">
    {showTarget && (
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-gray-500"
        style={{ width: 18, height: 18, borderRadius: 6 }}
      />
    )}
    <div
      className="px-4 py-3 text-white rounded-lg rounded-b-none"
      style={{ backgroundColor: color }}
    >
      <p className="text-sm font-semibold text-center leading-snug">{label}</p>
    </div>
    <div className="px-4 py-3 text-xs text-gray-700 space-y-1 bg-white">
      {description?.map((line) => (
        <p key={line} className="leading-snug">• {line}</p>
      ))}
    </div>
    {showSource && (
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-primary-blue"
        style={{ width: 18, height: 18, borderRadius: 6 }}
      />
    )}
  </div>
)

const nodeTypes = {
  tool: ({ data }) => (
    <NodeBox label={data.label} description={data.description} color="#2563eb" />
  ),
  inputNode: ({ data }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" showTarget={false} />
  ),
  // support legacy 'input' node type as well
  input: ({ data }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" showTarget={false} />
  ),
  start: ({ data }) => (
    <NodeBox label={data.label} description={data.description} color="#ec4899" showTarget={false} />
  ),
  end: ({ data }) => (
    <NodeBox label={data.label} description={data.description} color="#22c55e" showSource={false} />
  ),
}

const initialNodes = []

const initialEdges = []

export default function Builder() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [pipelineName, setPipelineName] = useState('')
  const [pipelineDescription, setPipelineDescription] = useState('')
  const router = useRouter()
  useEffect(() => {
    // only auto-load a draft if the URL explicitly requests it (e.g. ?draft=true)
    const params = new URLSearchParams(window.location.search)
    if (params.get('draft') !== 'true') return

    const draft = JSON.parse(localStorage.getItem('pipelineDraft') || 'null')
    if (draft) {
      setPipelineName(draft.name || '')
      setPipelineDescription(draft.description || '')
      if (draft.nodes) setNodes(draft.nodes)
      if (draft.edges) setEdges(draft.edges)
      // remove draft so it doesn't auto-load again unless explicitly requested
      localStorage.removeItem('pipelineDraft')
    }
  }, [])

  const onConnect = useCallback(
    (connection) =>
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed, color: '#2563eb' },
            style: { stroke: '#2563eb' },
          },
          eds
        )
      ),
    [setEdges]
  )

  const addNode = (type, label, description = []) => {
    const newNode = {
      id: `${nodes.length + 1}`,
      type,
      data: { label, description },
      position: {
        x: Math.random() * 400 + 100,
        y: Math.random() * 400 + 100,
      },
    }
    setNodes((nds) => [...nds, newNode])
  }

  const savePipeline = () => {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    const owner = user?.email || 'anonymous'

    // read raw and migrate legacy array format if needed
    let pipelinesObjRaw = localStorage.getItem('pipelines')
    let pipelinesObj = JSON.parse(pipelinesObjRaw || 'null')
    if (Array.isArray(pipelinesObj)) {
      // migrate global list into current owner's list
      pipelinesObj = { [owner]: pipelinesObj }
    }
    if (!pipelinesObj || typeof pipelinesObj !== 'object') pipelinesObj = {}

    const userList = pipelinesObj[owner] || []
    const newPipeline = {
      id: Date.now().toString(),
      name: pipelineName || `Pipeline ${userList.length + 1}`,
      description: pipelineDescription,
      nodes,
      edges,
      savedAt: new Date().toISOString(),
    }
    pipelinesObj[owner] = [...userList, newPipeline]
    localStorage.setItem('pipelines', JSON.stringify(pipelinesObj))
    // notify other pages and redirect to profile page after saving
    try {
      window.dispatchEvent(new Event('pipelinesChanged'))
    } catch (e) {}
    router.push('/profile')
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
            <p className="text-sm text-gray-600 mb-3">
              Drag a component onto the canvas. Use the blue dots (right) to connect to gray dots (left) for directed flow.
            </p>
            <div className="space-y-2">
              <button
                onClick={() =>
                  addNode('inputNode', 'Input Data', [
                    'FASTQ (Illumina/ONT)',
                    'BAM/CRAM alignments',
                    'FASTA assemblies',
                  ])
                }
                className="w-full btn-primary text-sm"
              >
                Input Data
              </button>
              <button
                onClick={() =>
                  addNode('tool', 'Read Quality (FastQC)', [
                    'Input: FASTQ/FASTA',
                    'Output: QC reports (HTML/JSON)',
                  ])
                }
                className="w-full btn-secondary text-sm"
              >
                Read Quality (FastQC)
              </button>
              <button
                onClick={() =>
                  addNode('tool', 'Genomic Property Estimation (GenomeScope2)', [
                    'Input: k-mer histogram',
                    'Output: genome size, heterozygosity, repeats',
                  ])
                }
                className="w-full btn-secondary text-sm"
              >
                Genomic Property Estimation (GenomeScope2)
              </button>
              <button
                onClick={() =>
                  addNode('tool', 'Assembly (Spades)', [
                    'Input: paired/long reads',
                    'Output: assembled contigs/scaffolds (FASTA)',
                  ])
                }
                className="w-full btn-secondary text-sm"
              >
                Assembly (Spades)
              </button>
              <button
                onClick={() =>
                  addNode('tool', 'Quality Assessment for Assembly (QUAST)', [
                    'Input: assembly FASTA',
                    'Output: assembly metrics (TSV/HTML)',
                  ])
                }
                className="w-full btn-secondary text-sm"
              >
                Quality Assessment for Assembly (QUAST)
              </button>
              <button
                onClick={() => addNode('end', 'Results')}
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
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
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


