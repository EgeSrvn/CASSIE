import { useState, useCallback, useEffect } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
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
import { getToken, isTokenExpired, logout } from '../services/authService'
import { StarterPipelineTemplate } from '../services/starterPipelines'
import Navigation from '../components/Navigation'
import './PipelineBuilder.css'
import '../styles/globals.css'

interface NodeData {
  label: string
  description?: string[]
}

const NodeBox = ({
  label,
  description,
  color,
  showTarget = true,
  showSource = true,
}: {
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
          <p key={idx} className="pipeline-node-description">- {line}</p>
        ))}
      </div>
    )}
    {showSource && (
      <Handle
        type="source"
        position={Position.Right}
        className="pipeline-handle-source"
        id="output"
        isConnectable={true}
      />
    )}
  </div>
)

const nodeTypes = {
  tool: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#2563eb" />
  ),
  fastqInput: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" showTarget={false} />
  ),
  fastaInput: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#8b5cf6" showTarget={false} />
  ),
  result: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#22c55e" showSource={false} />
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
  const location = useLocation()
  const [nodes, setNodes, onNodesChange] = useNodesState<NodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [pipelineName, setPipelineName] = useState('')
  const [pipelineDescription, setPipelineDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(() => !!getToken())

  useEffect(() => {
    const syncAuthState = () => {
      setIsAuthenticated(!!getToken())
    }

    syncAuthState()
    window.addEventListener('auth-change', syncAuthState)
    window.addEventListener('storage', syncAuthState)

    return () => {
      window.removeEventListener('auth-change', syncAuthState)
      window.removeEventListener('storage', syncAuthState)
    }
  }, [])

  useEffect(() => {
    if (id) {
      return
    }

    const state = location.state as { starterTemplate?: StarterPipelineTemplate } | null
    const starterTemplate = state?.starterTemplate

    if (!starterTemplate) {
      return
    }

    setPipelineName(starterTemplate.name)
    setPipelineDescription(starterTemplate.description)
    setNodes(starterTemplate.nodes as Node<NodeData>[])
    setEdges(starterTemplate.edges as Edge[])
  }, [id, location.state, setEdges, setNodes])

  useEffect(() => {
    if (id) {
      setLoading(true)
      getPipeline(parseInt(id, 10))
        .then((pipeline: Pipeline) => {
          setPipelineName(pipeline.name)
          setPipelineDescription(pipeline.description || '')

          if (pipeline.nodes) {
            const nodeList = Array.isArray(pipeline.nodes)
              ? pipeline.nodes
              : (pipeline.nodes as { nodes?: unknown[] }).nodes || Object.values(pipeline.nodes)
            setNodes(nodeList as Node<NodeData>[])
          }

          if (pipeline.edges) {
            const edgeList = Array.isArray(pipeline.edges)
              ? pipeline.edges
              : (pipeline.edges as { edges?: unknown[] }).edges || Object.values(pipeline.edges)
            setEdges(edgeList as Edge[])
          }
        })
        .catch((err: any) => {
          console.error('Failed to load pipeline:', err)
          if (err.response?.status === 401 && !isAuthenticated) {
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
    const currentToken = getToken()

    if (!currentToken) {
      alert('Please log in to save this pipeline.')
      navigate('/login')
      return
    }

    if (isTokenExpired(currentToken)) {
      logout()
      alert('Your session has expired. Please log in again to save this pipeline.')
      navigate('/login')
      return
    }

    if (!pipelineName.trim()) {
      alert('Please enter a pipeline name')
      return
    }

    setSaving(true)
    try {
      const pipelineData = {
        name: pipelineName,
        description: pipelineDescription || undefined,
        nodes,
        edges,
      }

      if (id) {
        await updatePipeline(parseInt(id, 10), pipelineData)
        alert('Pipeline updated successfully!')
      } else {
        await createPipeline(pipelineData)
        alert('Pipeline created successfully!')
      }
      navigate('/pipelines')
    } catch (err: any) {
      console.error('Failed to save pipeline:', err)
      if (err.response?.status === 401) {
        alert('Your session is no longer valid. Please log in again to save this pipeline.')
        navigate('/login')
        return
      }
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
    <div className="page-container pipeline-builder-page">
      <Navigation />
      <div className="page-content">
        <div className="pipeline-builder">
          <h1 className="page-title">Visual Pipeline Builder</h1>

          <div className="pipeline-builder-grid">
            <div className="pipeline-sidebar">
              <div className="card">
                <h2 className="sidebar-title">Components</h2>
                <p className="sidebar-description">
                  Click a component to add it to the canvas. Connect nodes by dragging from blue dots
                  (right) to gray dots (left).
                </p>
                <div className="sidebar-buttons">
                  <button
                    onClick={() =>
                      addNode('fastqInput', 'FASTQ Input', [
                        'One FASTQ file per node',
                        'Use separate nodes for R1 and R2',
                      ])
                    }
                    className="btn-primary"
                  >
                    FASTQ Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('fastaInput', 'FASTA Input', [
                        'Reference or assembly FASTA',
                        'Use separate nodes per FASTA file',
                      ])
                    }
                    className="btn-primary"
                  >
                    FASTA Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('input', 'GFF/GTF Input', [
                        'Reference or lifted annotation',
                        'Supports GFF, GFF3, and GTF files',
                      ])
                    }
                    className="btn-primary"
                  >
                    GFF/GTF Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('input', 'HAL Alignment Input', [
                        'Whole-genome HAL alignment',
                        'Used by CAT',
                      ])
                    }
                    className="btn-primary"
                  >
                    HAL Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('input', 'Reference Genome Name (TXT)', [
                        'Plain text file with the HAL reference genome name',
                        'Used by CAT',
                      ])
                    }
                    className="btn-primary"
                  >
                    TXT Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('input', 'Meryl DB Input', [
                        'Upload a .meryl directory archive',
                        'Used by Merqury',
                      ])
                    }
                    className="btn-primary"
                  >
                    Meryl Input
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Read Quality (FastQC)', [
                        'Input: FASTQ',
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
                        'Note: outputs are collected automatically',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Assembly (Spades)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Metagenome Assembly (metaSPAdes)', [
                        'Input: paired metagenomic reads',
                        'Output: metagenome contigs (FASTA)',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Metagenome Assembly (metaSPAdes)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Assembly (Hifiasm)', [
                        'Input: PacBio HiFi reads (FASTQ/FASTA)',
                        'Output: primary contigs and assembly graph',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Assembly (Hifiasm)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Assembly (Verkko)', [
                        'Input: HiFi reads, optional ONT reads',
                        'Output: phased assembly FASTA/GFA',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Assembly (Verkko)
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
                    onClick={() =>
                      addNode('tool', 'Annotation Lift Over (Liftoff)', [
                        'Input: target FASTA, reference FASTA, annotation GFF/GTF',
                        'Output: lifted annotation',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Annotation Lift Over (Liftoff)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Comparative Annotation Toolkit (CAT)', [
                        'Input: HAL alignment, reference annotation, reference genome name',
                        'Output: comparative annotations',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Comparative Annotation Toolkit (CAT)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Assembly Completeness (BUSCO)', [
                        'Input: assembly or genome FASTA',
                        'Output: completeness summaries',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Assembly Completeness (BUSCO)
                  </button>
                  <button
                    onClick={() =>
                      addNode('tool', 'Assembly k-mer Evaluation (Merqury)', [
                        'Input: assembly FASTA and Meryl DB',
                        'Output: reference-free assembly quality reports',
                      ])
                    }
                    className="btn-secondary"
                  >
                    Assembly k-mer Evaluation (Merqury)
                  </button>
                  <button
                    onClick={() =>
                      addNode('result', 'Result Block', [
                        'Connect every tool to a result node',
                        'Intermediate tools can also connect onward',
                      ])
                    }
                    className="btn-success"
                  >
                    Result Block
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
                  {isAuthenticated ? (
                    <button
                      onClick={handleSave}
                      disabled={saving || !pipelineName.trim()}
                      className="btn-primary"
                    >
                      {saving ? 'Saving...' : id ? 'Update Pipeline' : 'Save Pipeline'}
                    </button>
                  ) : (
                    <button
                      onClick={() => {
                        alert('Please log in to save this pipeline.')
                        navigate('/login')
                      }}
                      className="btn-primary"
                    >
                      Login to Save
                    </button>
                  )}
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
                defaultEdgeOptions={{
                  type: 'smoothstep',
                  markerEnd: { type: MarkerType.ArrowClosed, color: '#2563eb' },
                  style: { stroke: '#2563eb' },
                }}
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
