import { useState, useCallback, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  addEdge,
  useEdgesState,
  useNodesState,
  Node,
  Edge,
  Connection,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { createPipeline, updatePipeline, getPipeline, Pipeline } from '../services/pipelineService'
import { getToken } from '../services/authService'
import Navigation from '../components/Navigation'
import './PipelineBuilder.css'
import '../styles/globals.css'

interface NodeData {
  label: string
  description?: string[]
}

const NodeBox = ({ label, description, color, showTarget = true, showSource = true }: { 
  label: string
  description?: string[]
  color: string
  showTarget?: boolean
  showSource?: boolean
}) => (
  <div className="pipeline-node-box">
    {showTarget && (
      <Handle
        type="target"
        position={Position.Left}
        className="pipeline-handle-target"
      />
    )}
    <div className="pipeline-node-header" style={{ backgroundColor: color }}>
      <p className="pipeline-node-label">{label}</p>
    </div>
    {description && (
      <div className="pipeline-node-body">
        {description.map((line, idx) => (
          <p key={idx} className="pipeline-node-description">• {line}</p>
        ))}
      </div>
    )}
    {showSource && (
      <Handle
        type="source"
        position={Position.Right}
        className="pipeline-handle-source"
      />
    )}
  </div>
)

const nodeTypes = {
  tool: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#2563eb" />
  ),
  inputNode: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" showTarget={false} />
  ),
  input: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" showTarget={false} />
  ),
  start: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#ec4899" showTarget={false} />
  ),
  end: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#22c55e" showSource={false} />
  ),
}

export default function PipelineBuilder() {
  const { id } = useParams<{ id?: string }>()
  const navigate = useNavigate()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge[]>([])
  const [pipelineName, setPipelineName] = useState('')
  const [pipelineDescription, setPipelineDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const isAuthenticated = !!getToken()

  useEffect(() => {
    if (id) {
      setLoading(true)
      getPipeline(parseInt(id))
        .then((pipeline: Pipeline) => {
          setPipelineName(pipeline.name)
          setPipelineDescription(pipeline.description || '')
          if (pipeline.nodes) {
            // Handle different node structures
            const nodeList = Array.isArray(pipeline.nodes) 
              ? pipeline.nodes 
              : (pipeline.nodes as any).nodes || Object.values(pipeline.nodes)
            setNodes(nodeList as Node<NodeData>[])
          }
          if (pipeline.edges) {
            // Handle different edge structures
            const edgeList = Array.isArray(pipeline.edges)
              ? pipeline.edges
              : (pipeline.edges as any).edges || Object.values(pipeline.edges)
            setEdges(edgeList as Edge[])
          }
        })
        .catch((err: any) => {
          console.error('Failed to load pipeline:', err)
          // If not authenticated, don't redirect - let user build new pipeline
          if (err.response?.status === 401 && !isAuthenticated) {
            // Silently fail - user can still build, just won't load existing pipeline
            setPipelineName('')
            setPipelineDescription('')
          } else {
            alert('Failed to load pipeline')
          }
        })
        .finally(() => setLoading(false))
    }
  }, [id, setNodes, setEdges, isAuthenticated])

  const onConnect = useCallback(
    (params: Connection) =>
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed, color: '#2563eb' },
            style: { stroke: '#2563eb' },
          },
          eds
        )
      ),
    [setEdges]
  )

  const addNode = (type: string, label: string, description: string[] = []) => {
    const newNode: Node<NodeData> = {
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

  const handleSave = async () => {
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    
    if (!pipelineName.trim()) {
      alert('Please enter a pipeline name')
      return
    }

    setSaving(true)
    try {
      // Save all nodes including Input and Results nodes
      // The backend will infer input requirements from tool nodes only
      const pipelineData = {
        name: pipelineName,
        description: pipelineDescription || undefined,
        nodes: nodes,
        edges: edges,
      }

      if (id) {
        await updatePipeline(parseInt(id), pipelineData)
        alert('Pipeline updated successfully!')
      } else {
        await createPipeline(pipelineData)
        alert('Pipeline created successfully!')
      }
      navigate('/pipelines')
    } catch (err: any) {
      console.error('Failed to save pipeline:', err)
      alert(`Failed to save pipeline: ${err.message || 'Unknown error'}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">Loading pipeline...</div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <div className="pipeline-builder">
          <h1 className="page-title">Visual Pipeline Builder</h1>

      <div className="pipeline-builder-grid">
        <div className="pipeline-sidebar">
          <div className="card">
            <h2 className="sidebar-title">Components</h2>
            <p className="sidebar-description">
              Click a component to add it to the canvas. Connect nodes by dragging from blue dots (right) to gray dots (left).
            </p>
            <div className="sidebar-buttons">
              <button
                onClick={() =>
                  addNode('inputNode', 'Input Data', [
                    'FASTQ (Illumina/ONT)',
                    'BAM/CRAM alignments',
                    'FASTA assemblies',
                  ])
                }
                className="btn-primary"
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
                className="btn-secondary"
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
                className="btn-secondary"
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
                className="btn-secondary"
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
                className="btn-secondary"
              >
                Quality Assessment for Assembly (QUAST)
              </button>
              <button
                onClick={() => addNode('end', 'Results')}
                className="btn-success"
              >
                Results
              </button>
            </div>
          </div>

          <div className="card pipeline-form">
            <h2 className="sidebar-title">Pipeline Details</h2>
            <div className="form-group">
              <label htmlFor="pipeline-name">Name *</label>
              <input
                id="pipeline-name"
                type="text"
                value={pipelineName}
                onChange={(e) => setPipelineName(e.target.value)}
                placeholder="Enter pipeline name"
                className="form-input"
              />
            </div>
            <div className="form-group">
              <label htmlFor="pipeline-description">Description</label>
              <textarea
                id="pipeline-description"
                value={pipelineDescription}
                onChange={(e) => setPipelineDescription(e.target.value)}
                placeholder="Enter pipeline description"
                className="form-textarea"
                rows={3}
              />
            </div>
            <div className="form-actions">
              <button
                onClick={handleSave}
                disabled={saving || !pipelineName.trim()}
                className="btn-primary"
              >
                {saving ? 'Saving...' : id ? 'Update Pipeline' : 'Save Pipeline'}
              </button>
              <button
                onClick={() => navigate('/pipelines')}
                className="btn-secondary"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>

        <div className="pipeline-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
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
    </div>
  )
}

