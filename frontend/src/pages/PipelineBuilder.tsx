import { ReactNode, useState, useCallback, useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
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
  CoordinateExtent,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { createPipeline, updatePipeline, getPipeline, Pipeline } from '../services/pipelineService'
import { getToken, isTokenExpired, logout } from '../services/authService'
import { StarterPipelineTemplate } from '../services/starterPipelines'
import { EditableFlagDefinition, getAvailableTools, Tool } from '../services/toolService'
import { configCatPipelineBuilder } from '../../cats/config_cat_pipeline_builder'
import CatCornerCard from '../components/CatCornerCard'
import Navigation from '../components/Navigation'
import TrashIcon from '../components/TrashIcon'
import {
  applyPipelinePriorityGroupOrder,
  computePipelinePriorityGroups,
  PriorityGroup,
} from '../utils/pipelinePriority'
import {
  buildDefaultFlagValues,
  FlagValue,
  hasCustomizedFlagValues,
  normalizeDraftFlagValues,
} from '../utils/toolFlagConfig'
import './PipelineBuilder.css'
import '../styles/globals.css'

interface NodeData {
  label: string
  description?: string[]
  toolId?: string
  accentColor?: string
  nodeClassName?: string
  flagValues?: Record<string, FlagValue>
  priorityOrder?: number
  prioritySelected?: boolean
  isMenuOpen?: boolean
  hasCustomConfig?: boolean
  onToggleMenu?: () => void
  onEdit?: () => void
  onCopy?: () => void
  onDelete?: () => void
}

interface ToolNodeTemplate {
  toolId: string
  label: string
  description: string[]
}

interface PaletteSectionDefinition {
  id: string
  title: string
  description: string
  items: ToolNodeTemplate[]
}

const INPUT_NODE_TYPES = new Set(['fastqinput', 'fastainput', 'input', 'inputnode', 'start'])
const RESULT_NODE_TYPES = new Set(['result', 'end'])
const CHECKPOINT_NODE_TYPES = new Set(['checkpoint'])
const STAGE_NODE_TYPES = new Set(['tool', 'checkpoint'])
const PIPELINE_NODE_EXTENT: CoordinateExtent = [[48, 48], [2800, 2200]]
const PIPELINE_TRANSLATE_EXTENT: CoordinateExtent = [[-160, -120], [3200, 2600]]

const TOOL_NODE_TEMPLATES: ToolNodeTemplate[] = [
  {
    toolId: 'FASTQC',
    label: 'Read Quality (FastQC)',
    description: ['Input: FASTQ', 'Output: QC reports (HTML/JSON)'],
  },
  {
    toolId: 'GENOMESCOPE2',
    label: 'Genomic Property Estimation (GenomeScope2)',
    description: ['Input: k-mer histogram', 'Output: genome size, heterozygosity, repeats'],
  },
  {
    toolId: 'SPADES',
    label: 'Assembly (Spades)',
    description: ['Input: paired/long reads', 'Output: assembled contigs/scaffolds (FASTA)', 'Note: outputs are collected automatically'],
  },
  {
    toolId: 'METASPADES',
    label: 'Metagenome Assembly (metaSPAdes)',
    description: ['Input: paired metagenomic reads', 'Output: metagenome contigs (FASTA)'],
  },
  {
    toolId: 'HIFIASM',
    label: 'Assembly (Hifiasm)',
    description: ['Input: PacBio HiFi reads (FASTQ/FASTA)', 'Output: primary contigs and assembly graph'],
  },
  {
    toolId: 'VERKKO',
    label: 'Assembly (Verkko)',
    description: ['Input: HiFi reads, optional ONT reads', 'Output: phased assembly FASTA/GFA'],
  },
  {
    toolId: 'QUAST',
    label: 'Quality Assessment for Assembly (QUAST)',
    description: ['Input: assembly FASTA', 'Output: assembly metrics (TSV/HTML)'],
  },
  {
    toolId: 'LIFTOFF',
    label: 'Annotation Lift Over (Liftoff)',
    description: ['Input: target FASTA, reference FASTA, annotation GFF/GTF', 'Output: lifted annotation'],
  },
  {
    toolId: 'CAT',
    label: 'Comparative Annotation Toolkit (CAT)',
    description: ['Input: HAL alignment, reference annotation, reference genome name', 'Output: comparative annotations'],
  },
  {
    toolId: 'BUSCO',
    label: 'Assembly Completeness (BUSCO)',
    description: ['Input: assembly or genome FASTA', 'Output: completeness summaries'],
  },
  {
    toolId: 'MERYL',
    label: 'Read k-mer Database Build (Meryl)',
    description: ['Input: FASTQ reads', 'Output: .meryl.tar.gz archive for Merqury'],
  },
  {
    toolId: 'MERQURY',
    label: 'Assembly k-mer Evaluation (Merqury)',
    description: ['Input: assembly FASTA and Meryl DB', 'Output: reference-free assembly quality reports'],
  },
]

const getToolPaletteSectionMeta = (toolType: string) => {
  const normalized = String(toolType || '').trim().toLowerCase()
  if (normalized === 'transform' || normalized === 'assembly') {
    return {
      id: 'tool-type-assembly',
      title: 'Assembly Blocks',
      description: 'Core assembly and graph-construction stages.',
    }
  }
  if (normalized === 'qc' || normalized === 'quality_control') {
    return {
      id: 'tool-type-quality-control',
      title: 'Quality Control Blocks',
      description: 'Evaluation, profiling, and validation tools.',
    }
  }
  if (normalized === 'annotation') {
    return {
      id: 'tool-type-annotation',
      title: 'Annotation Blocks',
      description: 'Lift-over and comparative annotation stages.',
    }
  }
  return {
    id: `tool-type-${normalized || 'specialized'}`,
    title: normalized ? `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)} Blocks` : 'Specialized Blocks',
    description: 'Additional specialized processing stages.',
  }
}

const getNodeEditorHelpText = (nodeType: string) => {
  const normalized = String(nodeType || '').trim().toLowerCase()
  if (normalized === 'tool') {
    return 'Rename this tool block without changing its tool selection or editable flags.'
  }
  if (normalized === 'result' || normalized === 'end') {
    return 'This result label is used when CASSIE names pipeline outputs.'
  }
  if (normalized === 'checkpoint') {
    return 'Use a descriptive checkpoint name so paused branches are easier to follow later.'
  }
  return 'Choose a clear block name so this input is easier to identify during later job uploads.'
}

const createUniqueNodeId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `node-${crypto.randomUUID()}`
  }
  return `node-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const createUniqueEdgeId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `edge-${crypto.randomUUID()}`
  }
  return `edge-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const clonePipelineGraph = (
  rawNodes: unknown[],
  rawEdges: unknown[],
  remapIds = true
): { nodes: Node<NodeData>[]; edges: Edge[] } => {
  const idMap = new Map<string, string>()

  const normalizedNodes = (rawNodes as Node<NodeData>[]).map((node, index) => {
    const originalId = String(node.id ?? `node-${index + 1}`)
    const normalizedId = remapIds ? createUniqueNodeId() : originalId
    idMap.set(originalId, normalizedId)

    return {
      ...node,
      id: normalizedId,
      data: {
        ...(node.data || { label: 'Node' }),
        description: Array.isArray(node.data?.description) ? [...node.data.description] : node.data?.description,
        toolId: typeof node.data?.toolId === 'string' ? node.data.toolId : undefined,
        flagValues: node.data?.flagValues ? { ...node.data.flagValues } : undefined,
        priorityOrder: Number.isFinite(Number(node.data?.priorityOrder)) ? Number(node.data?.priorityOrder) : undefined,
        prioritySelected: Boolean(node.data?.prioritySelected),
      },
      position: {
        x: Number(node.position?.x ?? 0),
        y: Number(node.position?.y ?? 0),
      },
      style: node.style ? { ...node.style } : node.style,
    }
  })

  const normalizedEdges = (rawEdges as Edge[]).map((edge) => ({
    ...edge,
    id: remapIds || !edge.id ? createUniqueEdgeId() : String(edge.id),
    source: idMap.get(String(edge.source)) || String(edge.source),
    target: idMap.get(String(edge.target)) || String(edge.target),
    data: edge.data ? { ...edge.data } : edge.data,
    markerEnd:
      edge.markerEnd && typeof edge.markerEnd === 'object'
        ? { ...edge.markerEnd }
        : edge.markerEnd,
    markerStart:
      edge.markerStart && typeof edge.markerStart === 'object'
        ? { ...edge.markerStart }
        : edge.markerStart,
    style: edge.style ? { ...edge.style } : edge.style,
  }))

  return { nodes: normalizedNodes, edges: normalizedEdges }
}

const validatePipelineGraph = (nodes: Node<NodeData>[], edges: Edge[]) => {
  const errors: string[] = []
  const incoming = new Map<string, string[]>()
  const outgoing = new Map<string, string[]>()

  edges.forEach((edge) => {
    if (!edge.source || !edge.target) {
      return
    }
    outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge.target])
    incoming.set(edge.target, [...(incoming.get(edge.target) || []), edge.source])
  })

  const inputs = nodes.filter((node) => INPUT_NODE_TYPES.has(String(node.type || '').toLowerCase()))
  const tools = nodes.filter((node) => String(node.type || '').toLowerCase() === 'tool')
  const checkpoints = nodes.filter((node) => CHECKPOINT_NODE_TYPES.has(String(node.type || '').toLowerCase()))
  const results = nodes.filter((node) => RESULT_NODE_TYPES.has(String(node.type || '').toLowerCase()))

  if (nodes.length === 0) {
    errors.push('Add at least one node to the pipeline.')
  }
  if (tools.length === 0) {
    errors.push('Add at least one tool node.')
  }
  if (inputs.length === 0) {
    errors.push('Add at least one input node.')
  }
  if (results.length === 0) {
    errors.push('Add at least one result node.')
  }
  if (edges.length === 0) {
    errors.push('Connect the nodes before saving the pipeline.')
  }

  inputs.forEach((node) => {
    const label = node.data?.label || 'Input'
    if ((incoming.get(node.id) || []).length > 0) {
      errors.push(`"${label}" is an input node and cannot have incoming connections.`)
    }
    if ((outgoing.get(node.id) || []).length === 0) {
      errors.push(`"${label}" is not connected to any downstream tool.`)
    }
  })

  tools.forEach((node) => {
    const label = node.data?.label || 'Tool'
    if ((incoming.get(node.id) || []).length === 0) {
      errors.push(`Tool "${label}" must have at least one incoming connection.`)
    }
    if ((outgoing.get(node.id) || []).length === 0) {
      errors.push(`Tool "${label}" must connect to another tool or a result node.`)
    }
  })

  checkpoints.forEach((node) => {
    const label = node.data?.label || 'Checkpoint'
    const nodeId = String(node.id || '')
    if ((incoming.get(nodeId) || []).length === 0) {
      errors.push(`Checkpoint "${label}" must have at least one incoming connection.`)
    }
    if ((outgoing.get(nodeId) || []).length === 0) {
      errors.push(`Checkpoint "${label}" must connect to a downstream tool or result.`)
    }
  })

  results.forEach((node) => {
    const label = node.data?.label || 'Result'
    if ((incoming.get(node.id) || []).length === 0) {
      errors.push(`"${label}" is not connected to any upstream tool.`)
    }
    if ((outgoing.get(node.id) || []).length > 0) {
      errors.push(`"${label}" is a result node and cannot have outgoing connections.`)
    }
  })

  const reachableFromInputs = new Set<string>()
  const stack = inputs.map((node) => node.id)
  while (stack.length > 0) {
    const current = stack.pop() as string
    if (reachableFromInputs.has(current)) {
      continue
    }
    reachableFromInputs.add(current)
    ;(outgoing.get(current) || []).forEach((target) => {
      if (!reachableFromInputs.has(target)) {
        stack.push(target)
      }
    })
  }

  nodes
    .filter((node) => STAGE_NODE_TYPES.has(String(node.type || '').toLowerCase()))
    .forEach((node) => {
    if (!reachableFromInputs.has(node.id)) {
      const nodeType = CHECKPOINT_NODE_TYPES.has(String(node.type || '').toLowerCase()) ? 'Checkpoint' : 'Tool'
      errors.push(`${nodeType} "${node.data?.label || nodeType}" is not reachable from any input node.`)
    }
    })

  const reachableToResults = new Set<string>()
  const reverseStack = results.map((node) => node.id)
  while (reverseStack.length > 0) {
    const current = reverseStack.pop() as string
    if (reachableToResults.has(current)) {
      continue
    }
    reachableToResults.add(current)
    ;(incoming.get(current) || []).forEach((source) => {
      if (!reachableToResults.has(source)) {
        reverseStack.push(source)
      }
    })
  }

  nodes
    .filter((node) => STAGE_NODE_TYPES.has(String(node.type || '').toLowerCase()))
    .forEach((node) => {
    if (!reachableToResults.has(node.id)) {
      const nodeType = CHECKPOINT_NODE_TYPES.has(String(node.type || '').toLowerCase()) ? 'Checkpoint' : 'Tool'
      errors.push(`${nodeType} "${node.data?.label || nodeType}" does not lead to a result node.`)
    }
    })

  const visiting = new Set<string>()
  const visited = new Set<string>()
  const hasCycle = (nodeId: string): boolean => {
    if (visiting.has(nodeId)) {
      return true
    }
    if (visited.has(nodeId)) {
      return false
    }
    visiting.add(nodeId)
    for (const next of outgoing.get(nodeId) || []) {
      if (hasCycle(next)) {
        return true
      }
    }
    visiting.delete(nodeId)
    visited.add(nodeId)
    return false
  }

  if (nodes.some((node) => hasCycle(node.id))) {
    errors.push('Pipeline cycles are not allowed.')
  }

  return Array.from(new Set(errors))
}

const getToolNodeAccentColor = (toolType: string): string => {
  const normalized = String(toolType || '').trim().toLowerCase()
  if (normalized === 'annotation') {
    return '#7c3aed'
  }
  if (normalized === 'qc') {
    return '#b45309'
  }
  if (normalized === 'transform' || normalized === 'assembly') {
    return '#0f766e'
  }
  return '#2563eb'
}

const getToolNodeClassName = (toolType: string): string => {
  const normalized = String(toolType || '').trim().toLowerCase()
  if (normalized === 'annotation') {
    return 'pipeline-node-box-tool-annotation'
  }
  if (normalized === 'qc') {
    return 'pipeline-node-box-tool-qc'
  }
  if (normalized === 'transform' || normalized === 'assembly') {
    return 'pipeline-node-box-tool-transform'
  }
  return 'pipeline-node-box-tool'
}

const getPaletteButtonClassName = (toolType: string): string => {
  const normalized = String(toolType || '').trim().toLowerCase()
  if (normalized === 'annotation') {
    return 'pipeline-palette-button pipeline-palette-button-annotation'
  }
  if (normalized === 'qc' || normalized === 'quality_control') {
    return 'pipeline-palette-button pipeline-palette-button-qc'
  }
  if (normalized === 'transform' || normalized === 'assembly') {
    return 'pipeline-palette-button pipeline-palette-button-transform'
  }
  return 'pipeline-palette-button pipeline-palette-button-generic'
}

const renderPageModal = (content: ReactNode) => {
  if (typeof document === 'undefined') {
    return null
  }

  return createPortal(content, document.body)
}

const NodeBox = ({
  label,
  description,
  color,
  showTarget = true,
  showSource = true,
  menuSlot,
  footerBadge,
  className,
}: {
  label: string
  description?: string[]
  color: string
  showTarget?: boolean
  showSource?: boolean
  menuSlot?: ReactNode
  footerBadge?: ReactNode
  className?: string
}) => (
  <div className={`pipeline-node-box ${className || ''}`.trim()}>
    {showTarget && (
      <Handle
        type="target"
        position={Position.Left}
        className="pipeline-handle-target"
      />
    )}
    <div className="pipeline-node-header" style={{ backgroundColor: color }}>
      {menuSlot}
      <p className="pipeline-node-label">{label}</p>
    </div>
    {description && (
      <div className="pipeline-node-body">
        {description.map((line, idx) => (
          <p key={idx} className="pipeline-node-description">- {line}</p>
        ))}
        {footerBadge}
      </div>
    )}
    {!description && footerBadge}
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

const NodeMenu = ({ data }: { data: NodeData }) => {
  if (!data.onToggleMenu || !data.onEdit || !data.onCopy || !data.onDelete) {
    return null
  }

  return (
    <div className="pipeline-node-menu-wrap">
      <button
        type="button"
        className="pipeline-node-menu-trigger"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          data.onToggleMenu?.()
        }}
      >
        ⋮
      </button>
      {data.isMenuOpen && (
        <div className="pipeline-node-menu">
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              data.onEdit?.()
            }}
          >
            Edit
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              data.onCopy?.()
            }}
          >
            Copy
          </button>
          <button
            type="button"
            className="danger pipeline-node-menu-icon-button"
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              data.onDelete?.()
            }}
            aria-label={`Delete ${data.label}`}
            title="Delete"
          >
            <TrashIcon />
          </button>
        </div>
      )}
    </div>
  )
}

const ToolNode = ({ data }: { data: NodeData }) => (
  <NodeBox
    label={data.label}
    description={data.description}
    color={data.accentColor || '#2563eb'}
    className={data.nodeClassName || 'pipeline-node-box-tool'}
    menuSlot={<NodeMenu data={data} />}
    footerBadge={
      <div className={`pipeline-node-config-chip ${data.hasCustomConfig ? 'custom' : 'default'}`}>
        {data.hasCustomConfig ? 'Custom flags' : 'Default flags'}
      </div>
    }
  />
)

const nodeTypes = {
  tool: ({ data }: { data: NodeData }) => <ToolNode data={data} />,
  checkpoint: ({ data }: { data: NodeData }) => (
    <NodeBox
      label={data.label}
      description={data.description}
      color="#f59e0b"
      className="pipeline-node-box-checkpoint"
      menuSlot={<NodeMenu data={data} />}
    />
  ),
  fastqInput: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" className="pipeline-node-box-input" showTarget={false} menuSlot={<NodeMenu data={data} />} />
  ),
  fastaInput: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#8b5cf6" className="pipeline-node-box-input" showTarget={false} menuSlot={<NodeMenu data={data} />} />
  ),
  result: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#4f46e5" className="pipeline-node-box-result" showSource={false} menuSlot={<NodeMenu data={data} />} />
  ),
  inputNode: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" className="pipeline-node-box-input" showTarget={false} menuSlot={<NodeMenu data={data} />} />
  ),
  input: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#7c3aed" className="pipeline-node-box-input" showTarget={false} menuSlot={<NodeMenu data={data} />} />
  ),
  start: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#ec4899" className="pipeline-node-box-input" showTarget={false} menuSlot={<NodeMenu data={data} />} />
  ),
  end: ({ data }: { data: NodeData }) => (
    <NodeBox label={data.label} description={data.description} color="#4f46e5" className="pipeline-node-box-result" showSource={false} menuSlot={<NodeMenu data={data} />} />
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
  const [saveValidationPopup, setSaveValidationPopup] = useState<string[] | null>(null)
  const [toolCatalog, setToolCatalog] = useState<Tool[]>([])
  const [openNodeMenuId, setOpenNodeMenuId] = useState<string | null>(null)
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null)
  const [editingTool, setEditingTool] = useState<Tool | null>(null)
  const [editingNodeLabel, setEditingNodeLabel] = useState('')
  const [editingNodeLabelError, setEditingNodeLabelError] = useState('')
  const [editingDraftValues, setEditingDraftValues] = useState<Record<string, FlagValue>>({})
  const [editingErrors, setEditingErrors] = useState<Record<string, string>>({})
  const [openSidebarSections, setOpenSidebarSections] = useState<Record<string, boolean>>({
    inputs: false,
    utility: false,
  })
  const [openPriorityGroups, setOpenPriorityGroups] = useState<number[]>([0])
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false)
  const validationErrors = useMemo(() => validatePipelineGraph(nodes, edges), [nodes, edges])
  const priorityGroups = useMemo(
    () => computePipelinePriorityGroups(nodes as any[], edges as any[]),
    [nodes, edges]
  )
  const selectedPriorityToolCount = useMemo(
    () => priorityGroups.reduce((count, group) => count + group.items.filter((item) => item.selected).length, 0),
    [priorityGroups]
  )

  const toolCatalogById = useMemo(() => {
    const map = new Map<string, Tool>()
    toolCatalog.forEach((tool) => {
      if (tool.tool_id) {
        map.set(tool.tool_id, tool)
      }
    })
    return map
  }, [toolCatalog])

  const resolveToolForNode = useCallback((nodeData?: NodeData | null) => {
    if (!nodeData) {
      return null
    }
    if (nodeData.toolId && toolCatalogById.has(nodeData.toolId)) {
      return toolCatalogById.get(nodeData.toolId) || null
    }
    const template = TOOL_NODE_TEMPLATES.find((item) => item.label === nodeData.label)
    if (template && toolCatalogById.has(template.toolId)) {
      return toolCatalogById.get(template.toolId) || null
    }
    return toolCatalog.find((tool) => tool.name.toLowerCase() === String(nodeData.label || '').toLowerCase()) || null
  }, [toolCatalog, toolCatalogById])

  const editingNodeType = useMemo(
    () => String(nodes.find((node) => node.id === editingNodeId)?.type || '').trim().toLowerCase(),
    [editingNodeId, nodes]
  )
  const toolPaletteSections = useMemo<PaletteSectionDefinition[]>(() => {
    const groups = new Map<string, PaletteSectionDefinition>()
    TOOL_NODE_TEMPLATES.forEach((template) => {
      const sectionMeta = getToolPaletteSectionMeta(toolCatalogById.get(template.toolId)?.type || '')
      const existing = groups.get(sectionMeta.id)
      if (existing) {
        existing.items.push(template)
        return
      }
      groups.set(sectionMeta.id, {
        ...sectionMeta,
        items: [template],
      })
    })
    return Array.from(groups.values())
  }, [toolCatalogById])

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
    getAvailableTools()
      .then((tools) => setToolCatalog(tools.filter((tool) => tool.enabled)))
      .catch((error) => {
        console.error('Failed to load tool catalog for pipeline builder:', error)
        setToolCatalog([])
      })
  }, [])

  useEffect(() => {
    setOpenSidebarSections((current) => {
      const next = { ...current }
      toolPaletteSections.forEach((section) => {
        if (typeof next[section.id] !== 'boolean') {
          next[section.id] = false
        }
      })
      return next
    })
  }, [toolPaletteSections])

  useEffect(() => {
    if (id) {
      return
    }

    const state = location.state as { starterTemplate?: StarterPipelineTemplate } | null
    const starterTemplate = state?.starterTemplate

    if (!starterTemplate) {
      return
    }

    const { nodes: templateNodes, edges: templateEdges } = clonePipelineGraph(
      starterTemplate.nodes,
      starterTemplate.edges
    )

    setPipelineName(starterTemplate.name)
    setPipelineDescription(starterTemplate.description)
    setNodes(templateNodes)
    setEdges(templateEdges)
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
            const edgeList = pipeline.edges
              ? Array.isArray(pipeline.edges)
                ? pipeline.edges
                : (pipeline.edges as { edges?: unknown[] }).edges || Object.values(pipeline.edges)
              : []
            const { nodes: clonedNodes, edges: clonedEdges } = clonePipelineGraph(nodeList, edgeList)
            setNodes(clonedNodes)
            setEdges(clonedEdges)
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

  const addNode = useCallback((type: string, label: string, description: string[] = []) => {
    const newNode: Node<NodeData> = {
      id: createUniqueNodeId(),
      type,
      data: { label, description },
      position: {
        x: Math.random() * 400 + 100,
        y: Math.random() * 400 + 100,
      },
    }

    setNodes((nds) => [...nds, newNode])
  }, [setNodes])

  const addToolNode = useCallback((template: ToolNodeTemplate) => {
    const toolDefinition = toolCatalogById.get(template.toolId)
    const defaultFlagValues = toolDefinition?.default_flag_values
      ? { ...toolDefinition.default_flag_values }
      : buildDefaultFlagValues(toolDefinition?.editable_flags || [])

    const newNode: Node<NodeData> = {
      id: createUniqueNodeId(),
      type: 'tool',
      data: {
        label: template.label,
        description: [...template.description],
        toolId: template.toolId,
        accentColor: getToolNodeAccentColor(toolDefinition?.type || ''),
        flagValues: defaultFlagValues,
        priorityOrder: 10_000,
        prioritySelected: false,
      },
      position: {
        x: Math.random() * 400 + 100,
        y: Math.random() * 400 + 100,
      },
    }

    setNodes((nds) => [...nds, newNode])
  }, [setNodes, toolCatalogById])

  const handleDeleteNode = useCallback((nodeId: string) => {
    setNodes((currentNodes) => currentNodes.filter((node) => node.id !== nodeId))
    setEdges((currentEdges) => currentEdges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId))
    setOpenNodeMenuId((current) => current === nodeId ? null : current)
    setEditingNodeId((current) => current === nodeId ? null : current)
  }, [setEdges, setNodes])

  const handleCopyNode = useCallback((nodeId: string) => {
    const sourceNode = nodes.find((node) => node.id === nodeId)
    if (!sourceNode) {
      return
    }

    const clonedNode: Node<NodeData> = {
      id: createUniqueNodeId(),
      type: sourceNode.type,
      data: {
        label: sourceNode.data.label,
        description: Array.isArray(sourceNode.data.description) ? [...sourceNode.data.description] : sourceNode.data.description,
        toolId: sourceNode.data.toolId,
        flagValues: sourceNode.data.flagValues ? { ...sourceNode.data.flagValues } : undefined,
        priorityOrder: 10_000,
        prioritySelected: false,
      },
      position: {
        x: Number(sourceNode.position?.x ?? 0) + 40,
        y: Number(sourceNode.position?.y ?? 0) + 40,
      },
      style: sourceNode.style ? { ...sourceNode.style } : sourceNode.style,
    }

    setNodes((currentNodes) => [...currentNodes, clonedNode])
    setOpenNodeMenuId(null)
  }, [nodes, setNodes])

  const handlePriorityItemToggle = useCallback((group: PriorityGroup, itemId: string) => {
    const selectedNodeIds = group.items
      .filter((item) => item.selected)
      .map((item) => item.nodeId || item.id)
    const targetNodeId = group.items.find((item) => (item.nodeId || item.id) === itemId)?.nodeId || itemId
    const nextSelectedNodeIds = selectedNodeIds.includes(targetNodeId)
      ? selectedNodeIds.filter((nodeId) => nodeId !== targetNodeId)
      : [...selectedNodeIds, targetNodeId]

    setNodes((currentNodes) =>
      applyPipelinePriorityGroupOrder(
        currentNodes as any[],
        group.priority,
        group.items.map((item) => item.nodeId || item.id),
        nextSelectedNodeIds,
        nextSelectedNodeIds,
      ) as Node<NodeData>[]
    )
  }, [setNodes])

  const handlePriorityReorder = useCallback((group: PriorityGroup, itemIndex: number, direction: -1 | 1) => {
    const selectedItems = group.items.filter((item) => item.selected)
    const nextIndex = itemIndex + direction
    if (nextIndex < 0 || nextIndex >= selectedItems.length) {
      return
    }

    const reorderedItems = selectedItems.slice()
    const [moved] = reorderedItems.splice(itemIndex, 1)
    reorderedItems.splice(nextIndex, 0, moved)
    const selectedNodeIds = reorderedItems.map((item) => item.nodeId || item.id)
    const orderedNodeIds = reorderedItems.map((item) => item.nodeId || item.id)
    setNodes((currentNodes) =>
      applyPipelinePriorityGroupOrder(
        currentNodes as any[],
        group.priority,
        group.items.map((item) => item.nodeId || item.id),
        selectedNodeIds,
        orderedNodeIds,
      ) as Node<NodeData>[]
    )
  }, [setNodes])

  const openEditModal = useCallback((nodeId: string) => {
    const node = nodes.find((candidate) => candidate.id === nodeId)
    if (!node) {
      return
    }

    const tool = resolveToolForNode(node.data)
    const flagDefinitions = tool?.editable_flags || []
    const defaultValues = tool?.default_flag_values
      ? { ...tool.default_flag_values }
      : buildDefaultFlagValues(flagDefinitions)
    const draftValues = {
      ...defaultValues,
      ...(node.data.flagValues || {}),
    }
    const validation = normalizeDraftFlagValues(flagDefinitions, draftValues)

    setEditingNodeId(nodeId)
    setEditingTool(tool)
    setEditingNodeLabel(String(node.data?.label || ''))
    setEditingNodeLabelError('')
    setEditingDraftValues(validation.normalized)
    setEditingErrors(validation.errors)
    setOpenNodeMenuId(null)
  }, [nodes, resolveToolForNode])

  const closeEditModal = useCallback(() => {
    setEditingNodeId(null)
    setEditingTool(null)
    setEditingNodeLabel('')
    setEditingNodeLabelError('')
    setEditingDraftValues({})
    setEditingErrors({})
  }, [])

  const handleEditFieldChange = useCallback((flag: EditableFlagDefinition, value: FlagValue) => {
    const nextDraftValues = {
      ...editingDraftValues,
      [flag.key]: value,
    }
    const validation = normalizeDraftFlagValues(editingTool?.editable_flags || [], nextDraftValues)
    setEditingDraftValues(nextDraftValues)
    setEditingErrors(validation.errors)
  }, [editingDraftValues, editingTool])

  const saveNodeConfiguration = useCallback(() => {
    if (!editingNodeId) {
      return
    }

    const normalizedLabel = editingNodeLabel.trim()
    if (!normalizedLabel) {
      setEditingNodeLabelError('Block name is required.')
      return
    }
    setEditingNodeLabelError('')

    if (editingTool) {
      const validation = normalizeDraftFlagValues(editingTool.editable_flags || [], editingDraftValues)
      setEditingErrors(validation.errors)
      if (Object.keys(validation.errors).length > 0) {
        return
      }

      setNodes((currentNodes) =>
        currentNodes.map((node) => {
          if (node.id !== editingNodeId) {
            return node
          }
          return {
            ...node,
            data: {
              ...node.data,
              label: normalizedLabel,
              toolId: editingTool.tool_id,
              flagValues: validation.normalized,
            },
          }
        })
      )
      closeEditModal()
      return
    }

    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        if (node.id !== editingNodeId) {
          return node
        }
        return {
          ...node,
          data: {
            ...node.data,
            label: normalizedLabel,
          },
        }
      })
    )
    closeEditModal()
  }, [closeEditModal, editingDraftValues, editingNodeId, editingNodeLabel, editingTool, setNodes])

  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const tool = resolveToolForNode(node.data)
        const flagDefinitions = tool?.editable_flags || []
        return {
          ...node,
          data: {
            ...node.data,
            toolId: node.data.toolId || tool?.tool_id,
            accentColor: node.data.accentColor || getToolNodeAccentColor(tool?.type || ''),
            nodeClassName: getToolNodeClassName(tool?.type || ''),
            isMenuOpen: openNodeMenuId === node.id,
            hasCustomConfig: String(node.type || '').toLowerCase() === 'tool'
              ? hasCustomizedFlagValues(flagDefinitions, node.data.flagValues)
              : false,
            onToggleMenu: () => setOpenNodeMenuId((current) => current === node.id ? null : node.id),
            onEdit: () => openEditModal(node.id),
            onCopy: () => handleCopyNode(node.id),
            onDelete: () => handleDeleteNode(node.id),
          },
        }
      }),
    [handleCopyNode, handleDeleteNode, nodes, openEditModal, openNodeMenuId, resolveToolForNode]
  )

  const toggleSidebarSection = useCallback((sectionId: string) => {
    setOpenSidebarSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }))
  }, [])

  const onConnect = useCallback(
    (params: Connection) =>
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            id: createUniqueEdgeId(),
            type: 'smoothstep',
            markerEnd: { type: MarkerType.ArrowClosed, color: '#2563eb' },
            style: { stroke: '#2563eb' },
          },
          eds
        )
      ),
    [setEdges]
  )

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
      setSaveValidationPopup(['Please enter a pipeline name before saving.'])
      return
    }

    if (validationErrors.length > 0) {
      setSaveValidationPopup(validationErrors)
      return
    }

    setSaving(true)
    try {
      const normalizedNodes = priorityGroups.reduce(
        (currentNodes, group) =>
          applyPipelinePriorityGroupOrder(
            currentNodes as any[],
            group.priority,
            group.items.map((item) => item.nodeId || item.id),
            group.items.filter((item) => item.selected).map((item) => item.nodeId || item.id),
            group.items.filter((item) => item.selected).map((item) => item.nodeId || item.id),
          ) as Node<NodeData>[],
        nodes as Node<NodeData>[]
      )

      const cleanNodes = normalizedNodes.map((node) => ({
        ...node,
        data: {
          label: node.data.label,
          description: Array.isArray(node.data.description) ? [...node.data.description] : node.data.description,
          toolId: node.data.toolId,
          flagValues: node.data.flagValues ? { ...node.data.flagValues } : undefined,
          priorityOrder: node.data.priorityOrder,
          prioritySelected: node.data.prioritySelected,
        },
      }))

      const pipelineData = {
        name: pipelineName,
        description: pipelineDescription || undefined,
        nodes: cleanNodes,
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
        <div className="pipeline-builder pipeline-builder--with-cat">
          <div className="pipeline-builder-topbar">
            <div>
              <h1 className="pipeline-builder-title">Visual Pipeline Builder</h1>
            </div>
            <div className="pipeline-builder-topbar-actions">
              {validationErrors.length > 0 && (
                <p className="pipeline-inline-validation">
                  {validationErrors[0].length > 120 ? `${validationErrors[0].slice(0, 117)}...` : validationErrors[0]}
                </p>
              )}
              {priorityGroups.length > 0 && (
                <button
                  type="button"
                  className="btn-secondary pipeline-priority-launch"
                  onClick={() => setIsPriorityModalOpen(true)}
                >
                  Priority Sets ({selectedPriorityToolCount})
                </button>
              )}
            </div>
          </div>
          <div className="pipeline-builder-grid">
            <div className="pipeline-sidebar">
              <div className="card pipeline-sidebar-card pipeline-components-card">
                <h2 className="sidebar-title">Components</h2>
                <p className="sidebar-description">
                  Add blocks by section, collapse groups you are not using, and rename any block later from its menu.
                </p>
                <div className="pipeline-sidebar-sections">
                  <section className="pipeline-sidebar-section">
                    <button type="button" className="pipeline-sidebar-section-header" onClick={() => toggleSidebarSection('inputs')}>
                      <span>
                        <strong>Input Blocks</strong>
                        <small>External files that later appear in job input assignment.</small>
                      </span>
                      <span className={`pipeline-sidebar-chevron ${openSidebarSections.inputs ? 'open' : ''}`}>▾</span>
                    </button>
                    {openSidebarSections.inputs && (
                      <div className="pipeline-sidebar-section-body sidebar-buttons">
                        <button
                          onClick={() =>
                            addNode('fastqInput', 'FASTQ Input', [
                              'One FASTQ file per node',
                              'Use separate nodes for R1 and R2',
                            ])
                          }
                          className="pipeline-palette-button pipeline-palette-button-input"
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
                          className="pipeline-palette-button pipeline-palette-button-input"
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
                          className="pipeline-palette-button pipeline-palette-button-input"
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
                          className="pipeline-palette-button pipeline-palette-button-input"
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
                          className="pipeline-palette-button pipeline-palette-button-input"
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
                          className="pipeline-palette-button pipeline-palette-button-input"
                        >
                          Meryl Input
                        </button>
                      </div>
                    )}
                  </section>

                  <section className="pipeline-sidebar-section">
                    <button type="button" className="pipeline-sidebar-section-header" onClick={() => toggleSidebarSection('utility')}>
                      <span>
                        <strong>Utility Blocks</strong>
                        <small>Checkpoint and result nodes for control flow and output naming.</small>
                      </span>
                      <span className={`pipeline-sidebar-chevron ${openSidebarSections.utility ? 'open' : ''}`}>▾</span>
                    </button>
                    {openSidebarSections.utility && (
                      <div className="pipeline-sidebar-section-body sidebar-buttons">
                        <button
                          onClick={() =>
                            addNode('checkpoint', 'Checkpoint', [
                              'Pause only this branch until the job is resumed',
                              'Other independent branches can continue normally',
                            ])
                          }
                          className="pipeline-palette-button pipeline-palette-button-checkpoint"
                        >
                          Checkpoint
                        </button>
                        <button
                          onClick={() =>
                            addNode('result', 'Result Block', [
                              'Connect every tool to a result node',
                              'Result labels become part of output naming',
                            ])
                          }
                          className="pipeline-palette-button pipeline-palette-button-result"
                        >
                          Result Block
                        </button>
                      </div>
                    )}
                  </section>

                  {toolPaletteSections.map((section) => (
                    <section key={section.id} className="pipeline-sidebar-section">
                      <button type="button" className="pipeline-sidebar-section-header" onClick={() => toggleSidebarSection(section.id)}>
                        <span>
                          <strong>{section.title}</strong>
                          <small>{section.description}</small>
                        </span>
                        <span className={`pipeline-sidebar-chevron ${openSidebarSections[section.id] ? 'open' : ''}`}>▾</span>
                      </button>
                      {openSidebarSections[section.id] && (
                        <div className="pipeline-sidebar-section-body sidebar-buttons">
                          {section.items.map((toolTemplate) => (
                            <button
                              key={toolTemplate.toolId}
                              onClick={() => addToolNode(toolTemplate)}
                              className={getPaletteButtonClassName(toolCatalogById.get(toolTemplate.toolId)?.type || '')}
                            >
                              {toolTemplate.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </section>
                  ))}
                </div>
              </div>

              <div className="card pipeline-sidebar-card pipeline-form">
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
                      disabled={saving}
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
              <div className="pipeline-canvas-flow-shell">
                <ReactFlow
                  className="pipeline-react-flow"
                  nodes={decoratedNodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  nodeTypes={nodeTypes}
                  fitView
                  fitViewOptions={{ padding: 0.16 }}
                  nodeExtent={PIPELINE_NODE_EXTENT}
                  translateExtent={PIPELINE_TRANSLATE_EXTENT}
                  snapToGrid
                  snapGrid={[20, 20]}
                  onPaneClick={() => setOpenNodeMenuId(null)}
                  defaultEdgeOptions={{
                    type: 'smoothstep',
                    markerEnd: { type: MarkerType.ArrowClosed, color: '#2563eb' },
                    style: { stroke: '#2563eb' },
                  }}
                >
                  <Background color="#d5c29d" gap={24} size={1.15} />
                  <Controls />
                </ReactFlow>
              </div>
            </div>
          </div>
        </div>
      </div>
      <CatCornerCard
        config={configCatPipelineBuilder}
        className="cat-corner-card--pipeline-builder"
      />

      {editingNodeId && renderPageModal(
        <div className="modal-overlay" onClick={closeEditModal}>
          <div className="modal-content pipeline-flag-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingTool?.name || 'Block'} Settings</h2>
              <button type="button" className="modal-close" onClick={closeEditModal}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group pipeline-flag-field">
                <label htmlFor="pipeline-node-label">Block Name</label>
                <input
                  id="pipeline-node-label"
                  type="text"
                  className="form-input"
                  value={editingNodeLabel}
                  onChange={(event) => setEditingNodeLabel(event.target.value)}
                  placeholder="Enter a descriptive block name"
                />
                <p className="pipeline-flag-help">{getNodeEditorHelpText(editingNodeType)}</p>
                {editingNodeLabelError && (
                  <p className="pipeline-flag-error">{editingNodeLabelError}</p>
                )}
              </div>
              {editingTool?.editable_flags && editingTool.editable_flags.length > 0 ? (
                <div className="pipeline-flag-form">
                  {editingTool.editable_flags.map((flag) => {
                    const placeholder = [flag.placeholder, flag.example ? `Example: ${flag.example}` : '']
                      .filter(Boolean)
                      .join(' ')
                    const currentValue = editingDraftValues[flag.key]

                    return (
                      <div key={flag.key} className="form-group pipeline-flag-field">
                        <label htmlFor={`flag-${flag.key}`}>{flag.label}</label>
                        {flag.type === 'boolean' ? (
                          <label className="pipeline-flag-checkbox">
                            <input
                              id={`flag-${flag.key}`}
                              type="checkbox"
                              checked={Boolean(currentValue)}
                              onChange={(event) => handleEditFieldChange(flag, event.target.checked)}
                            />
                            <span>{flag.description || 'Enable this option for the tool block.'}</span>
                          </label>
                        ) : flag.type === 'select' ? (
                          <select
                            id={`flag-${flag.key}`}
                            value={String(currentValue ?? flag.default ?? '')}
                            className="form-input"
                            onChange={(event) => handleEditFieldChange(flag, event.target.value)}
                          >
                            {(flag.options || []).map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            id={`flag-${flag.key}`}
                            type="text"
                            className="form-input"
                            value={String(currentValue ?? '')}
                            placeholder={placeholder}
                            onChange={(event) => handleEditFieldChange(flag, event.target.value)}
                          />
                        )}
                        {flag.type !== 'boolean' && flag.description && (
                          <p className="pipeline-flag-help">{flag.description}</p>
                        )}
                        {editingErrors[flag.key] && (
                          <p className="pipeline-flag-error">{editingErrors[flag.key]}</p>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="pipeline-flag-empty-state">
                  {editingNodeType === 'tool'
                    ? 'This tool currently runs with its default settings in CASSIE and has no user-editable flags in the builder.'
                    : 'This block only needs a clear display name to make later pipeline and job steps easier to follow.'}
                </p>
              )}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={closeEditModal}>
                Cancel
              </button>
              <button type="button" className="btn-primary" onClick={saveNodeConfiguration}>
                Save Block Settings
              </button>
            </div>
          </div>
        </div>
      )}

      {isPriorityModalOpen && renderPageModal(
        <div className="modal-overlay" onClick={() => setIsPriorityModalOpen(false)}>
          <div className="modal-content pipeline-priority-modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2>Priority Sets</h2>
              <button type="button" className="modal-close" onClick={() => setIsPriorityModalOpen(false)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <p className="pipeline-priority-modal-copy">
                Check only the tools you want CASSIE to prioritize inside each level. After those selected tools finish,
                the rest of that level can follow the default scheduler order.
              </p>
              <div className="pipeline-priority-modal-groups">
                {priorityGroups.map((group) => {
                  const isOpen = openPriorityGroups.includes(group.priority)
                  const selectedItems = group.items.filter((item) => item.selected)
                  return (
                    <div key={group.priority} className="pipeline-priority-card">
                      <button
                        type="button"
                        className="pipeline-priority-toggle"
                        onClick={() =>
                          setOpenPriorityGroups((current) =>
                            current.includes(group.priority)
                              ? current.filter((item) => item !== group.priority)
                              : [...current, group.priority].sort((a, b) => a - b)
                          )
                        }
                      >
                        <span>{group.title}</span>
                        <strong>{isOpen ? '−' : '+'}</strong>
                      </button>
                      {isOpen && (
                        <div className="pipeline-priority-body">
                          <div className="pipeline-priority-current-tools">
                            <p className="pipeline-priority-section-title">Current tools in this level</p>
                            <div className="pipeline-priority-checkbox-list">
                              {group.items.map((item) => (
                                <label key={item.id} className="pipeline-priority-checkbox-row">
                                  <input
                                    type="checkbox"
                                    checked={Boolean(item.selected)}
                                    onChange={() => handlePriorityItemToggle(group, item.nodeId || item.id)}
                                  />
                                  <span>{item.label}</span>
                                </label>
                              ))}
                            </div>
                          </div>
                          <div className="pipeline-priority-selected-tools">
                            <p className="pipeline-priority-section-title">Selected order for this level</p>
                            {selectedItems.length === 0 ? (
                              <p className="pipeline-priority-empty">
                                No tools selected here. This level will use the default scheduler order.
                              </p>
                            ) : (
                              selectedItems.map((item, index) => (
                                <div key={item.id} className="pipeline-priority-row">
                                  <span>{item.label}</span>
                                  <div className="pipeline-priority-actions">
                                    <button
                                      type="button"
                                      className="pipeline-priority-move"
                                      disabled={index === 0}
                                      onClick={() => handlePriorityReorder(group, index, -1)}
                                    >
                                      ↑
                                    </button>
                                    <button
                                      type="button"
                                      className="pipeline-priority-move"
                                      disabled={index === selectedItems.length - 1}
                                      onClick={() => handlePriorityReorder(group, index, 1)}
                                    >
                                      ↓
                                    </button>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-primary" onClick={() => setIsPriorityModalOpen(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {saveValidationPopup && renderPageModal(
        <div className="modal-overlay" onClick={() => setSaveValidationPopup(null)}>
          <div className="modal-content pipeline-save-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Pipeline Can&apos;t Be Saved Yet</h2>
              <button type="button" className="modal-close" onClick={() => setSaveValidationPopup(null)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <p>Fix the following items and try saving again:</p>
              <ul className="pipeline-save-error-list">
                {saveValidationPopup.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-primary" onClick={() => setSaveValidationPopup(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
