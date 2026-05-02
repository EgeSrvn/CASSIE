import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import {
  createJob,
  executeJob,
  getJob,

  JobCreate,
  JobPipelineVisualization,
  PipelinePlanPreviewRequest,
  estimateRuntime,
  getAvailableVMs,
  previewPipelinePlan,
  RuntimeEstimate,
  RuntimeInputAssignment,
  VM,
} from '../services/jobService'
import {
  EditableFlagDefinition,
  getAvailableTools,
  Tool,
  getToolRequirements,
  ToolRequirementInfo,
  ToolRequirement,
  getRecommendationIntents,
  getPipelineRecommendations,
  RecommendationIntent,
  RecommendationOption,
} from '../services/toolService'
import { getPipelines, getPipeline, Pipeline, getPipelineRequirements, PipelineRequirement, PipelineRequirements } from '../services/pipelineService'
import { getDataFileTree } from '../services/dataFileService'
import { FolderTreeItem, FileItem } from '../services/folderService'

import { getToken } from '../services/authService'
import { getCreateJobCatConfig } from '../../cats/config_cat_job_builder'
import CatCornerCard from '../components/CatCornerCard'
import Navigation from '../components/Navigation'
import PipelineVisualization from '../components/PipelineVisualization'
import {
  buildManualExecutionPreferences,
  buildPipelineExecutionPreferences,
  computeManualPriorityGroups,
  computePipelinePriorityGroups,
  PriorityGroup,
} from '../utils/pipelinePriority'
import {
  buildDefaultFlagValues,
  FlagValue,
  hasCustomizedFlagValues,
  normalizeDraftFlagValues,
  resolveToolRequirementsForFlags,
} from '../utils/toolFlagConfig'
import './PipelineBuilder.css'
import '../styles/globals.css'

const formatVmCpu = (cpuMillis: number): string => `${(cpuMillis / 1000).toFixed(2)} cores`
const formatVmMemory = (memoryMib: number): string => `${(memoryMib / 1024).toFixed(2)} GiB`
const formatVmStorage = (storageMib: number): string => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'
const formatVmSlots = (vm: VM): string => `${vm.available_job_slots}/${vm.max_jobs} jobs available`
const formatUsd = (value: number): string => `$${value.toFixed(2)}`
const formatRuntimeEstimate = (minutes: number): string => {
  if (minutes < 60) {
    return `${minutes} min`
  }
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}

type BuilderLevel = 1 | 2 | 3 | 4
type SlideDirection = 'forward' | 'backward'

interface BuilderLevelDefinition {
  level: BuilderLevel
  title: string
  description: string
}

interface ManualToolInputBlock {
  id: string
  toolReq: ToolRequirementInfo
  toolDefinition: Tool | null
  requirements: ToolRequirement[]
  externalRequirements: ToolRequirement[]
  upstreamRequirements: ToolRequirement[]
}

interface SavedPipelineToolPlan {
  nodeId: string
  toolId: string
  toolIndex: number
  toolName: string
  requirements: ToolRequirement[]
  toolConfig: Record<string, FlagValue>
}

interface SavedPipelineExecutionPlan {
  toolIndices: number[]
  toolPlans: SavedPipelineToolPlan[]
  manualInputBindings: Array<{
    file_id: number
    binding_id: string
    tool_id: string
    requirement_type: string
    label: string
  }>
  inputSourceOverrides: Array<{
    tool_id: string
    requirement_type: string
    source: 'external' | 'upstream'
  }>
  manualToolConfigs: Array<{
    tool_id: string
    tool_index: number
    tool_config: Record<string, FlagValue>
  }>
  manualPriorityGroups: Array<{
    priority: number
    ordered_tool_ids: string[]
  }>
  plannedInputs: Array<{
    id: number
    binding_id: string
    tool_id: string
    requirement_type: string
    label: string
    filename: string
    file_format: string | null
    size_bytes: number
    s3_key?: string
    source: 'library'
  }>
}

const getManualInputBlockDefaultName = (block: ManualToolInputBlock): string => {
  if (block.externalRequirements.length === 1) {
    return block.externalRequirements[0].label
  }
  if (block.externalRequirements.length > 1) {
    return `${block.toolReq.tool_name} tool block`
  }
  return `${block.toolReq.tool_name} upstream inputs`
}

const PIPELINE_STAGE_NODE_TYPES = new Set(['tool', 'checkpoint'])
const PIPELINE_INPUT_NODE_TYPES = new Set(['fastqinput', 'fastainput', 'input', 'inputnode', 'start'])
const CREATE_JOB_DRAFT_STORAGE_KEY = 'cassie:create-job-draft:v6'

interface CreateJobDraft {
  version: 6
  jobName: string
  selectionMode: 'tools' | 'pipeline'
  selectedTools: number[]
  selectedPipelineId: number | null
  selectedPipelineDetails: Pipeline | null
  pipelineRequirements: PipelineRequirements | null
  toolFileMappings: Record<string, Record<string, number[]>>
  pipelineInputMappings: Record<string, number[]>
  requirementSourceSelections: Record<string, 'external' | 'upstream'>
  selectedIntentIds: string[]
  priorityGroups: PriorityGroup[]
  openPriorityGroups: number[]
  currentLevel: BuilderLevel
  inputBlockNames: Record<string, string>
  manualToolFlagValues: Record<string, Record<string, FlagValue>>
  selectedVM: string
  executionDataImprovementConsent?: boolean
}

const shouldRestoreCreateJobDraft = (): boolean => {
  if (typeof window === 'undefined') {
    return false
  }

  const navigationEntry = window.performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
  return navigationEntry?.type === 'reload'
}

const readCreateJobDraft = (): CreateJobDraft | null => {
  if (typeof window === 'undefined') {
    return null
  }

  if (!shouldRestoreCreateJobDraft()) {
    clearCreateJobDraft()
    return null
  }

  try {
    const rawDraft = window.sessionStorage.getItem(CREATE_JOB_DRAFT_STORAGE_KEY)
    if (!rawDraft) {
      return null
    }

    const parsed = JSON.parse(rawDraft)
    if (!parsed || parsed.version !== 6) {
      return null
    }

    return parsed as CreateJobDraft
  } catch (error) {
    console.error('Failed to read create job draft:', error)
    return null
  }
}

const clearCreateJobDraft = () => {
  if (typeof window === 'undefined') {
    return
  }
  window.sessionStorage.removeItem(CREATE_JOB_DRAFT_STORAGE_KEY)
}

const resolvePipelineGraphPayload = (value: any): any => {
  let current = value
  for (let depth = 0; depth < 3 && typeof current === 'string'; depth += 1) {
    const trimmed = current.trim()
    if (!trimmed) {
      return null
    }
    try {
      current = JSON.parse(trimmed)
    } catch {
      return current
    }
  }
  return current
}

const normalizePipelineNodeList = (nodes: any): any[] => {
  const resolvedNodes = resolvePipelineGraphPayload(nodes)
  if (Array.isArray(resolvedNodes)) {
    if (
      resolvedNodes.length === 1 &&
      resolvedNodes[0] &&
      typeof resolvedNodes[0] === 'object' &&
      Array.isArray(resolvePipelineGraphPayload(resolvedNodes[0].nodes))
    ) {
      return normalizePipelineNodeList(resolvedNodes[0].nodes)
    }
    return resolvedNodes.filter((item) => item && typeof item === 'object')
  }
  if (resolvedNodes && typeof resolvedNodes === 'object') {
    const nestedNodes = resolvePipelineGraphPayload(resolvedNodes.nodes)
    if (Array.isArray(nestedNodes)) {
      return nestedNodes.filter((item) => item && typeof item === 'object')
    }
    const nestedData = resolvePipelineGraphPayload(resolvedNodes.data)
    if (Array.isArray(nestedData)) {
      return nestedData.filter((item) => item && typeof item === 'object')
    }
    return Object.values(resolvedNodes).filter((item) => item && typeof item === 'object')
  }
  return []
}

const normalizePipelineEdgeList = (edges: any): any[] => {
  const resolvedEdges = resolvePipelineGraphPayload(edges)
  if (Array.isArray(resolvedEdges)) {
    if (
      resolvedEdges.length === 1 &&
      resolvedEdges[0] &&
      typeof resolvedEdges[0] === 'object' &&
      Array.isArray(resolvePipelineGraphPayload(resolvedEdges[0].edges))
    ) {
      return normalizePipelineEdgeList(resolvedEdges[0].edges)
    }
    return resolvedEdges.filter((item) => item && typeof item === 'object')
  }
  if (resolvedEdges && typeof resolvedEdges === 'object') {
    const nestedEdges = resolvePipelineGraphPayload(resolvedEdges.edges)
    if (Array.isArray(nestedEdges)) {
      return nestedEdges.filter((item) => item && typeof item === 'object')
    }
    const nestedData = resolvePipelineGraphPayload(resolvedEdges.data)
    if (Array.isArray(nestedData)) {
      return nestedData.filter((item) => item && typeof item === 'object')
    }
    return Object.values(resolvedEdges).filter((item) => item && typeof item === 'object')
  }
  return []
}

const resolvePipelineNodeType = (node: any): string => (
  String(node?.type ?? node?.nodeType ?? '').trim().toLowerCase()
)

const resolvePipelineNodeLabel = (node: any, fallbackLabel: string): string => (
  String(node?.data?.label ?? node?.label ?? fallbackLabel)
)

const PIPELINE_TOOL_LABEL_ALIASES: Array<{ toolId: string; aliases: string[] }> = [
  { toolId: 'GENOMESCOPE2', aliases: ['Genomic Property Estimation (GenomeScope2)', 'GenomeScope2'] },
  { toolId: 'METASPADES', aliases: ['Metagenome Assembly (metaSPAdes)', 'metaSPAdes', 'MetaSPAdes'] },
  { toolId: 'HIFIASM', aliases: ['Assembly (Hifiasm)', 'Hifiasm', 'hifiasm'] },
  { toolId: 'VERKKO', aliases: ['Assembly (Verkko)', 'Verkko', 'verkko'] },
  { toolId: 'MERQURY', aliases: ['Assembly k-mer Evaluation (Merqury)', 'Merqury'] },
  { toolId: 'FASTQC', aliases: ['Read Quality (FastQC)', 'FastQC'] },
  { toolId: 'SPADES', aliases: ['Assembly (Spades)', 'SPAdes', 'Spades'] },
  { toolId: 'QUAST', aliases: ['Quality Assessment for Assembly (QUAST)', 'QUAST', 'Quast'] },
  { toolId: 'LIFTOFF', aliases: ['Annotation Transfer (Liftoff)', 'Liftoff'] },
  { toolId: 'BUSCO', aliases: ['Assembly Completeness (BUSCO)', 'BUSCO'] },
  { toolId: 'MERYL', aliases: ['K-mer Database (Meryl)', 'Meryl'] },
  { toolId: 'CAT', aliases: ['Comparative Annotation Toolkit (CAT)', 'CAT'] },
]

const inferPipelineToolIdFromLabel = (label: string): string => {
  const normalizedLabel = label.trim().toLowerCase()
  if (!normalizedLabel) {
    return ''
  }

  const aliases = PIPELINE_TOOL_LABEL_ALIASES.flatMap(({ toolId, aliases }) =>
    aliases.map((alias) => ({ toolId, alias: alias.trim().toLowerCase() }))
  ).sort((left, right) => right.alias.length - left.alias.length)

  const match = aliases.find(({ alias }) => alias && (alias === normalizedLabel || normalizedLabel.includes(alias)))
  return match?.toolId || ''
}

const resolvePipelineToolId = (node: any): string => (
  String(node?.data?.toolId ?? node?.data?.tool_id ?? node?.toolId ?? node?.tool_id ?? '').trim().toUpperCase() ||
  inferPipelineToolIdFromLabel(resolvePipelineNodeLabel(node, ''))
)

const buildOrderedPipelineToolNodeIds = (nodes: any[], edges: any[]): string[] => {
  const toolNodes = nodes.filter((node) => resolvePipelineNodeType(node) === 'tool' && node?.id != null)
  const toolNodeIds = new Set(toolNodes.map((node) => String(node.id)))
  const originalPosition = new Map<string, number>()
  const inDegree = new Map<string, number>()
  const dependents = new Map<string, string[]>()

  toolNodes.forEach((node, index) => {
    const nodeId = String(node.id)
    originalPosition.set(nodeId, index)
    inDegree.set(nodeId, 0)
    dependents.set(nodeId, [])
  })

  edges.forEach((edge) => {
    const sourceId = String(edge?.source || '').trim()
    const targetId = String(edge?.target || '').trim()
    if (!toolNodeIds.has(sourceId) || !toolNodeIds.has(targetId)) {
      return
    }
    dependents.set(sourceId, [...(dependents.get(sourceId) || []), targetId])
    inDegree.set(targetId, (inDegree.get(targetId) || 0) + 1)
  })

  const ready = Array.from(toolNodeIds)
    .filter((nodeId) => (inDegree.get(nodeId) || 0) === 0)
    .sort((left, right) => (originalPosition.get(left) || 0) - (originalPosition.get(right) || 0))
  const ordered: string[] = []

  while (ready.length > 0) {
    const nodeId = ready.shift() as string
    ordered.push(nodeId)
    ;(dependents.get(nodeId) || [])
      .sort((left, right) => (originalPosition.get(left) || 0) - (originalPosition.get(right) || 0))
      .forEach((dependentId) => {
        const nextDegree = (inDegree.get(dependentId) || 0) - 1
        inDegree.set(dependentId, nextDegree)
        if (nextDegree === 0) {
          ready.push(dependentId)
          ready.sort((left, right) => (originalPosition.get(left) || 0) - (originalPosition.get(right) || 0))
        }
      })
  }

  toolNodes.forEach((node) => {
    const nodeId = String(node.id)
    if (!ordered.includes(nodeId)) {
      ordered.push(nodeId)
    }
  })

  return ordered
}

const renderPageModal = (content: ReactNode) => {
  if (typeof document === 'undefined') {
    return null
  }

  return createPortal(content, document.body)
}

// Keep this hoisted: several render-time memos need it before the JSX section.
function flattenFiles(tree: FolderTreeItem[]): Array<FileItem & { folderPath?: string }> {
  if (!tree || tree.length === 0) {
    return []
  }

  const files: Array<FileItem & { folderPath?: string }> = []
  const traverse = (folders: FolderTreeItem[], parentPath: string = '') => {
    if (!folders || folders.length === 0) return

    folders.forEach(folder => {
      if (!folder) return

      const currentPath = parentPath ? `${parentPath}/${folder.name}` : (folder.name || '')

      if (folder.files && Array.isArray(folder.files)) {
        folder.files.forEach(file => {
          if (file && file.id) {
            files.push({ ...file, folderPath: currentPath || undefined })
          }
        })
      }

      if (folder.children && Array.isArray(folder.children) && folder.children.length > 0) {
        traverse(folder.children, currentPath)
      }
    })
  }
  traverse(tree)
  return files
}

export default function CreateJob() {
  const location = useLocation()
  const retryJobId = (location.state as { retryJobId?: number } | null)?.retryJobId
  const storedDraftRef = useRef<CreateJobDraft | null>(readCreateJobDraft())
  const shouldPersistDraftRef = useRef(true)
  const isDocumentUnloadingRef = useRef(false)
  const [jobName, setJobName] = useState(() => storedDraftRef.current?.jobName || '')
  const isAuthenticated = !!getToken()
  const [selectionMode, setSelectionMode] = useState<'tools' | 'pipeline'>(() => storedDraftRef.current?.selectionMode || 'tools')
  const [availableTools, setAvailableTools] = useState<Tool[]>([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [selectedTools, setSelectedTools] = useState<number[]>(() => storedDraftRef.current?.selectedTools || [])
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [selectedPipelineId, setSelectedPipelineId] = useState<number | null>(() => storedDraftRef.current?.selectedPipelineId ?? null)
  const [selectedPipelineDetails, setSelectedPipelineDetails] = useState<Pipeline | null>(() => storedDraftRef.current?.selectedPipelineDetails || null)
  const [loadingPipelines, setLoadingPipelines] = useState(false)
  const [loadingSelectedPipeline, setLoadingSelectedPipeline] = useState(false)
  const [pipelineRequirements, setPipelineRequirements] = useState<PipelineRequirements | null>(() => storedDraftRef.current?.pipelineRequirements || null)
  const [loadingRequirements, setLoadingRequirements] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>('')
  const [dataFileTree, setDataFileTree] = useState<FolderTreeItem[]>([])
  const [loadingDataTree, setLoadingDataTree] = useState(false)
  const [submitStatus, setSubmitStatus] = useState<string>('')
  const [availableVMs, setAvailableVMs] = useState<VM[]>([])
  const [loadingVMs, setLoadingVMs] = useState(false)
  const [selectedVM, setSelectedVM] = useState<string>(() => storedDraftRef.current?.selectedVM || '')
  const [runtimeEstimate, setRuntimeEstimate] = useState<RuntimeEstimate | null>(null)
  const [loadingRuntimeEstimate, setLoadingRuntimeEstimate] = useState(false)
  const [runtimeEstimateError, setRuntimeEstimateError] = useState('')
  const [toolRequirements, setToolRequirements] = useState<ToolRequirementInfo[]>([])
  const [loadingToolRequirements, setLoadingToolRequirements] = useState(false)
  const [toolFileMappings, setToolFileMappings] = useState<Record<string, Record<string, number[]>>>(() => storedDraftRef.current?.toolFileMappings || {}) // Maps tool_index -> requirement_type -> file_id[]
  const [pipelineInputMappings, setPipelineInputMappings] = useState<Record<string, number[]>>(() => storedDraftRef.current?.pipelineInputMappings || {})
  const [requirementSourceSelections, setRequirementSourceSelections] = useState<Record<string, 'external' | 'upstream'>>(() => storedDraftRef.current?.requirementSourceSelections || {})
  const [manualToolFlagValues, setManualToolFlagValues] = useState<Record<string, Record<string, FlagValue>>>(() => storedDraftRef.current?.manualToolFlagValues || {})
  const [recommendationIntents, setRecommendationIntents] = useState<RecommendationIntent[]>([])
  const [selectedIntentIds, setSelectedIntentIds] = useState<string[]>(() => storedDraftRef.current?.selectedIntentIds || [])
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationOption[]>([])
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [priorityGroups, setPriorityGroups] = useState<PriorityGroup[]>(() => storedDraftRef.current?.priorityGroups || [])
  const [openPriorityGroups, setOpenPriorityGroups] = useState<number[]>(() => storedDraftRef.current?.openPriorityGroups?.length ? storedDraftRef.current.openPriorityGroups : [0])
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false)
  const [currentLevel, setCurrentLevel] = useState<BuilderLevel>(() => storedDraftRef.current?.currentLevel || 1)
  const [slideDirection, setSlideDirection] = useState<SlideDirection>('forward')
  const [inputBlockNames, setInputBlockNames] = useState<Record<string, string>>(() => storedDraftRef.current?.inputBlockNames || {})
  const [backendReviewPipelinePreview, setBackendReviewPipelinePreview] = useState<JobPipelineVisualization | null>(null)
  const [loadingReviewPipelinePreview, setLoadingReviewPipelinePreview] = useState(false)
  const [reviewPipelinePreviewError, setReviewPipelinePreviewError] = useState('')
  const [openManualToolMenuId, setOpenManualToolMenuId] = useState<string | null>(null)
  const [editingManualTool, setEditingManualTool] = useState<ToolRequirementInfo | null>(null)
  const [editingManualToolDraftValues, setEditingManualToolDraftValues] = useState<Record<string, FlagValue>>({})
  const [editingManualToolErrors, setEditingManualToolErrors] = useState<Record<string, string>>({})
  const [retryPrefillApplied, setRetryPrefillApplied] = useState(false)

  const [executionDataImprovementConsent, setExecutionDataImprovementConsent] = useState(
    () => Boolean(storedDraftRef.current?.executionDataImprovementConsent)
  )
  const navigate = useNavigate()
  const sharedRequirementCardStyle = {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.5rem',
    padding: '1rem',
    border: '1px solid #e5e7eb',
    borderRadius: '4px',
    backgroundColor: 'var(--bg-primary)',
  }
  const selectedVMDetails = availableVMs.find(vm => vm.name === selectedVM) || null
  const selectedPipelineSummary = useMemo(
    () => pipelines.find((pipeline) => pipeline.id === selectedPipelineId) || null,
    [pipelines, selectedPipelineId]
  )
  const toolCatalogById = useMemo(() => {
    const map = new Map<string, Tool>()
    availableTools.forEach((tool) => {
      if (tool.tool_id) {
        map.set(tool.tool_id, tool)
      }
    })
    return map
  }, [availableTools])
  const selectedPipeline = selectedPipelineDetails || selectedPipelineSummary
  const selectedPipelineNodes = useMemo(
    () => selectedPipeline ? normalizePipelineNodeList(selectedPipeline.nodes) : [],
    [selectedPipeline]
  )
  const selectedPipelineEdges = useMemo(
    () => selectedPipeline ? normalizePipelineEdgeList(selectedPipeline.edges) : [],
    [selectedPipeline]
  )
  const pipelineRequirementTools = useMemo(
    () => Array.isArray(pipelineRequirements?.tools) ? pipelineRequirements.tools : [],
    [pipelineRequirements]
  )
  const pipelineToolRequirements = useMemo(
    () => Array.isArray(pipelineRequirements?.tool_requirements) ? pipelineRequirements.tool_requirements : [],
    [pipelineRequirements]
  )
  const rawPipelineInputRequirements = useMemo(
    () => Array.isArray(pipelineRequirements?.input_requirements) ? pipelineRequirements.input_requirements : [],
    [pipelineRequirements]
  )
  const savedPipelineToolRequirementCards = useMemo<ToolRequirementInfo[]>(() => {
    if (selectionMode !== 'pipeline' || !pipelineRequirements) {
      return []
    }

    const orderedToolNodes = selectedPipelineNodes.filter((node: any) => resolvePipelineNodeType(node) === 'tool' && node?.id != null)
    const cards = pipelineToolRequirements.map((item) => ({ ...item }))
    const cardsByToolId = new Map<string, ToolRequirementInfo[]>()
    cards.forEach((card) => {
      const key = String(card.tool_id || '').toUpperCase()
      cardsByToolId.set(key, [...(cardsByToolId.get(key) || []), card])
    })
    const consumedByToolId = new Map<string, number>()

    return orderedToolNodes.map((node: any) => {
      const nodeId = String(node.id)
      const toolId = resolvePipelineToolId(node)
      const withNodeId = cards.find((card) => String(card.node_id || '') === nodeId)
      if (withNodeId) {
        return withNodeId
      }

      const sameToolCards = cardsByToolId.get(toolId) || []
      const occurrence = consumedByToolId.get(toolId) || 0
      consumedByToolId.set(toolId, occurrence + 1)
      return sameToolCards[occurrence] || sameToolCards[0] || {
        node_id: nodeId,
        tool_index: occurrence,
        tool_id: toolId,
        tool_name: resolvePipelineNodeLabel(node, toolId),
        tool_type: 'tool',
        requirements: [],
      }
    }).map((card, index) => ({
      ...card,
      node_id: String(card.node_id || orderedToolNodes[index]?.id || ''),
    }))
  }, [pipelineRequirements, pipelineToolRequirements, selectedPipelineNodes, selectionMode])
  const savedPipelineExecutionPlan = useMemo<SavedPipelineExecutionPlan | null>(() => {
    if (selectionMode !== 'pipeline' || !pipelineRequirements || selectedPipelineNodes.length === 0) {
      return null
    }

    const filesById = new Map<number, FileItem & { folderPath?: string }>(
      flattenFiles(dataFileTree).map((file) => [file.id, file])
    )
    const nodesById = new Map<string, any>(
      selectedPipelineNodes
        .filter((node: any) => node && typeof node === 'object' && node.id != null)
        .map((node: any) => [String(node.id), node])
    )
    const inputNodesById = new Map<string, any>(
      selectedPipelineNodes
        .filter((node: any) => PIPELINE_INPUT_NODE_TYPES.has(resolvePipelineNodeType(node)) && node?.id != null)
        .map((node: any) => [String(node.id), node])
    )
    const toolRequirementsByNodeId = new Map<string, ToolRequirementInfo>(
      savedPipelineToolRequirementCards
        .filter((item) => item?.node_id)
        .map((item) => [String(item.node_id), item])
    )
    const toolIndexByToolId = new Map<string, number>()
    availableTools.forEach((tool) => {
      if (tool.tool_id) {
        toolIndexByToolId.set(tool.tool_id.toUpperCase(), tool.id)
      }
    })

    const orderedNodeIds = buildOrderedPipelineToolNodeIds(selectedPipelineNodes, selectedPipelineEdges)
    const toolPlans: SavedPipelineToolPlan[] = orderedNodeIds
      .map((nodeId) => {
        const node = nodesById.get(nodeId)
        const requirementCard = toolRequirementsByNodeId.get(nodeId)
        const toolId = String(requirementCard?.tool_id || resolvePipelineToolId(node)).trim().toUpperCase()
        const toolIndex = toolIndexByToolId.get(toolId)
        if (!toolId || toolIndex === undefined) {
          return null
        }
        const rawToolConfig = requirementCard?.tool_config || node?.data?.flagValues || node?.data?.toolConfig || {}
        return {
          nodeId,
          toolId,
          toolIndex,
          toolName: String(requirementCard?.tool_name || resolvePipelineNodeLabel(node, toolId)),
          requirements: requirementCard?.requirements || [],
          toolConfig: rawToolConfig as Record<string, FlagValue>,
        }
      })
      .filter((item): item is SavedPipelineToolPlan => Boolean(item))

    if (toolPlans.length === 0) {
      return null
    }

    const toolPlanByNodeId = new Map(toolPlans.map((plan) => [plan.nodeId, plan]))
    const incomingInputNodeIdsByToolNode = new Map<string, string[]>()
    selectedPipelineEdges.forEach((edge: any) => {
      const sourceId = String(edge?.source || '').trim()
      const targetId = String(edge?.target || '').trim()
      if (!inputNodesById.has(sourceId) || !toolPlanByNodeId.has(targetId)) {
        return
      }
      const current = incomingInputNodeIdsByToolNode.get(targetId) || []
      if (!current.includes(sourceId)) {
        incomingInputNodeIdsByToolNode.set(targetId, [...current, sourceId])
      }
    })

    const manualInputBindings: SavedPipelineExecutionPlan['manualInputBindings'] = []
    const inputSourceOverrides: SavedPipelineExecutionPlan['inputSourceOverrides'] = []
    const manualToolConfigs: SavedPipelineExecutionPlan['manualToolConfigs'] = []
    const plannedInputs: SavedPipelineExecutionPlan['plannedInputs'] = []
    const bindingDedup = new Set<string>()
    const overrideDedup = new Set<string>()
    const plannedInputDedup = new Set<string>()

    toolPlans.forEach((plan) => {
      if (Object.keys(plan.toolConfig || {}).length > 0) {
        manualToolConfigs.push({
          tool_id: plan.toolId,
          tool_index: plan.toolIndex,
          tool_config: plan.toolConfig,
        })
      }

      const connectedInputNodeIds = incomingInputNodeIdsByToolNode.get(plan.nodeId) || []
      plan.requirements.forEach((req, requirementIndex) => {
        const requirementFormats = new Set((req.formats || []).map((format) => String(format).toLowerCase()))
        const matchingInputNodeIds = connectedInputNodeIds.filter((inputNodeId) => {
          const inputNode = inputNodesById.get(inputNodeId)
          const inputType = resolvePipelineNodeType(inputNode)
          if (inputType === 'fastqinput') {
            return requirementFormats.has('fastq')
          }
          if (inputType === 'fastainput') {
            return requirementFormats.has('fasta')
          }
          return true
        })

        const hasExternalBinding = matchingInputNodeIds.some((inputNodeId) => (pipelineInputMappings[inputNodeId] || []).length > 0)
        const source: 'external' | 'upstream' = hasExternalBinding ? 'external' : (req.default_source === 'upstream' ? 'upstream' : 'external')
        const overrideKey = `${plan.toolId}:${req.type}:${source}`
        if (!overrideDedup.has(overrideKey)) {
          inputSourceOverrides.push({
            tool_id: plan.toolId,
            requirement_type: req.type,
            source,
          })
          overrideDedup.add(overrideKey)
        }

        if (!hasExternalBinding) {
          return
        }

        const bindingId = req.requirement_id || `pipeline:${plan.nodeId}:${plan.toolId}:${req.type}:${requirementIndex}`
        matchingInputNodeIds.forEach((inputNodeId) => {
          const selectedFileIds = pipelineInputMappings[inputNodeId] || []
          selectedFileIds.forEach((fileId) => {
            const file = filesById.get(fileId)
            if (!file) {
              return
            }
            const bindingKey = `${fileId}:${bindingId}:${plan.toolId}:${req.type}`
            if (!bindingDedup.has(bindingKey)) {
              manualInputBindings.push({
                file_id: fileId,
                binding_id: bindingId,
                tool_id: plan.toolId,
                requirement_type: req.type,
                label: req.label,
              })
              bindingDedup.add(bindingKey)
            }
            if (!plannedInputDedup.has(bindingKey)) {
              plannedInputs.push({
                id: file.id,
                binding_id: bindingId,
                tool_id: plan.toolId,
                requirement_type: req.type,
                label: req.label,
                filename: file.filename,
                file_format: file.file_format || null,
                size_bytes: file.size_bytes || 0,
                s3_key: file.s3_key,
                source: 'library',
              })
              plannedInputDedup.add(bindingKey)
            }
          })
        })
      })
    })

    const toolIdByNodeId = new Map(toolPlans.map((plan) => [plan.nodeId, plan.toolId]))
    const manualPriorityGroups = priorityGroups
      .map((group) => ({
        priority: group.priority,
        ordered_tool_ids: group.items
          .filter((item) => item.selected)
          .map((item) => toolIdByNodeId.get(String(item.nodeId || item.id)) || '')
          .filter(Boolean),
      }))
      .filter((group) => group.ordered_tool_ids.length > 0)

    return {
      toolIndices: toolPlans.map((plan) => plan.toolIndex),
      toolPlans,
      manualInputBindings,
      inputSourceOverrides,
      manualToolConfigs,
      manualPriorityGroups,
      plannedInputs,
    }
  }, [
    availableTools,
    dataFileTree,
    pipelineInputMappings,
    pipelineRequirements,
    priorityGroups,
    savedPipelineToolRequirementCards,
    selectedPipelineEdges,
    selectedPipelineNodes,
    selectionMode,
  ])
  const getManualToolDefaultFlagValues = useCallback((toolReq: ToolRequirementInfo): Record<string, FlagValue> => {
    if (toolReq.default_flag_values) {
      return { ...toolReq.default_flag_values }
    }
    return buildDefaultFlagValues(toolReq.editable_flags || [])
  }, [])

  useEffect(() => {
    shouldPersistDraftRef.current = true
  }, [])

  useEffect(() => {
    const markDocumentUnloading = () => {
      isDocumentUnloadingRef.current = true
    }

    window.addEventListener('beforeunload', markDocumentUnloading)
    window.addEventListener('pagehide', markDocumentUnloading)

    return () => {
      window.removeEventListener('beforeunload', markDocumentUnloading)
      window.removeEventListener('pagehide', markDocumentUnloading)
    }
  }, [])

  useEffect(() => (
    () => {
      if (!shouldPersistDraftRef.current || isDocumentUnloadingRef.current) {
        return
      }
      clearCreateJobDraft()
    }
  ), [])

  // Check if pipeline_id was passed via navigation state
  useEffect(() => {
    const state = location.state as { pipelineId?: number; retryJobId?: number } | null
    if (state?.pipelineId) {
      setSelectionMode('pipeline')
      setSelectedPipelineId(state.pipelineId)
    }
  }, [location])

  useEffect(() => {
    if (!retryJobId || retryPrefillApplied || availableTools.length === 0) {
      return
    }

    let cancelled = false

    const prefillRetryJob = async () => {
      try {
        setError('')
        clearCreateJobDraft()
        const sourceJob = await getJob(retryJobId)
        if (cancelled) return

        const sourcePreferences = (sourceJob.execution_preferences || {}) as Record<string, any>

        setJobName(sourceJob.name)
        setSelectedVM(sourceJob.vm_name || '')
        setSelectedIntentIds([])
        setCurrentLevel(1)
        setSlideDirection('forward')
        setPipelineInputMappings({})
        setToolFileMappings({})

        if (sourceJob.pipeline_id) {
          setSelectionMode('pipeline')
          setSelectedPipelineId(sourceJob.pipeline_id)
          setSelectedTools([])
        } else {
          const snapshotStages = (sourcePreferences.visualization_snapshot?.stages || []) as Array<Record<string, any>>
          const sourceToolIds = snapshotStages
            .map(stage => String(stage.tool_id || '').trim().toUpperCase())
            .filter(toolId => toolId && toolId !== 'CHECKPOINT')
          const selectedToolIndices = availableTools
            .filter(tool => sourceToolIds.includes(String(tool.tool_id || '').trim().toUpperCase()))
            .map(tool => tool.id)
          setSelectionMode('tools')
          setSelectedTools(selectedToolIndices)
          setSelectedPipelineId(null)
          setSelectedPipelineDetails(null)
          setPipelineRequirements(null)
        }

        const manualConfigs: Record<string, Record<string, FlagValue>> = {}
        for (const entry of sourcePreferences.manual_tool_configs || []) {
          const toolId = String(entry?.tool_id || '').trim().toUpperCase()
          const toolConfig = entry?.tool_config
          if (toolId && toolConfig && typeof toolConfig === 'object') {
            manualConfigs[toolId] = toolConfig
          }
        }
        if (Object.keys(manualConfigs).length > 0) {
          setManualToolFlagValues(manualConfigs)
        }

        const sourceOverrides: Record<string, 'external' | 'upstream'> = {}
        for (const item of sourcePreferences.input_source_overrides || []) {
          const toolId = String(item?.tool_id || '').trim().toUpperCase()
          const requirementType = String(item?.requirement_type || '').trim()
          const source = String(item?.source || '').trim().toLowerCase()
          if (toolId && requirementType && (source === 'external' || source === 'upstream')) {
            sourceOverrides[`${toolId}:${requirementType}`] = source
          }
        }
        if (Object.keys(sourceOverrides).length > 0) {
          setRequirementSourceSelections(sourceOverrides)
        }

        setRetryPrefillApplied(true)
      } catch (err: any) {
        if (!cancelled) {
          setError(err.message || 'Failed to load the original job for retry')
          setRetryPrefillApplied(true)
        }
      }
    }

    void prefillRetryJob()

    return () => {
      cancelled = true
    }
  }, [availableTools, retryJobId, retryPrefillApplied])

  // Fetch available tools on component mount
  useEffect(() => {
    const fetchTools = async () => {
      try {
        setLoadingTools(true)
        const tools = await getAvailableTools()
        setAvailableTools(tools)
        // No default tool selection - user must explicitly select tools
      } catch (err: any) {
        console.error('Failed to load tools:', err)
        // If not authenticated, don't redirect - let user configure without tools
        // They'll be prompted to login when they try to create the job
        if (err.response?.status === 401 && !isAuthenticated) {
          // Silently fail - user can still configure, just won't see tools until login
          setAvailableTools([])
        } else {
          // Keep fallback behavior - tools will be empty, but component won't crash
          setAvailableTools([])
        }
      } finally {
        setLoadingTools(false)
      }
    }
    fetchTools()
  }, [isAuthenticated])

  useEffect(() => {
    let cancelled = false

    const runEstimate = async () => {
      if (!selectedVM) {
        setRuntimeEstimate(null)
        setRuntimeEstimateError('')
        return
      }

      if (selectionMode === 'tools' && selectedTools.length === 0) {
        setRuntimeEstimate(null)
        setRuntimeEstimateError('')
        return
      }

      if (selectionMode === 'pipeline' && !selectedPipelineId) {
        setRuntimeEstimate(null)
        setRuntimeEstimateError('')
        return
      }

      try {
        setLoadingRuntimeEstimate(true)
        setRuntimeEstimateError('')
        const estimate = await estimateRuntime(
          selectionMode === 'pipeline'
            ? {
                pipeline_id: selectedPipelineId || undefined,
                vm_name: selectedVM,
                input_assignments: getRuntimeInputAssignments(),
              }
            : {
                tool_indices: selectedTools,
                vm_name: selectedVM,
                input_assignments: getRuntimeInputAssignments(),
              }
        )

        if (!cancelled) {
          setRuntimeEstimate(estimate)
        }
      } catch (err: any) {
        if (!cancelled) {
          setRuntimeEstimate(null)
          setRuntimeEstimateError(err.message || 'Failed to estimate runtime')
        }
      } finally {
        if (!cancelled) {
          setLoadingRuntimeEstimate(false)
        }
      }
    }

    const timeoutId = window.setTimeout(() => {
      void runEstimate()
    }, 350)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [
    dataFileTree,
    manualToolFlagValues,
    pipelineInputMappings,
    requirementSourceSelections,
    savedPipelineExecutionPlan,
    selectedPipelineEdges,
    selectedPipelineId,
    selectedPipelineNodes,
    selectedTools,
    selectedVM,
    selectionMode,
    toolFileMappings,
  ])

  useEffect(() => {
    const fetchIntents = async () => {
      const intents = await getRecommendationIntents()
      setRecommendationIntents(intents)
    }
    fetchIntents()
  }, [])

  // Fetch pipelines when pipeline mode is selected
  useEffect(() => {
    if (selectionMode === 'pipeline') {
      const fetchPipelines = async () => {
        try {
          setLoadingPipelines(true)
          const data = await getPipelines()
          setPipelines(data)
        } catch (err: any) {
          console.error('Failed to load pipelines:', err)
          // If not authenticated, don't redirect - let user configure without pipelines
          if (err.response?.status === 401 && !isAuthenticated) {
            setPipelines([])
          }
        } finally {
          setLoadingPipelines(false)
        }
      }
      fetchPipelines()
    }
  }, [selectionMode, isAuthenticated])

  // Fetch pipeline requirements when a pipeline is selected
  useEffect(() => {
    if (selectedPipelineId && selectionMode === 'pipeline') {
      const fetchRequirements = async () => {
        try {
          setLoadingRequirements(true)
          const requirements = await getPipelineRequirements(selectedPipelineId)
          setPipelineRequirements(requirements)
        } catch (err) {
          console.error('Failed to load pipeline requirements:', err)
          setError('Failed to load pipeline requirements')
        } finally {
          setLoadingRequirements(false)
        }
      }
      fetchRequirements()
    } else {
      setPipelineRequirements(null)
    }
  }, [selectedPipelineId, selectionMode])

  useEffect(() => {
    if (selectionMode !== 'pipeline' || !selectedPipelineId) {
      setSelectedPipelineDetails(null)
      setLoadingSelectedPipeline(false)
      return
    }

    let cancelled = false

    const loadSelectedPipeline = async () => {
      try {
        setLoadingSelectedPipeline(true)
        const pipeline = await getPipeline(selectedPipelineId)
        if (!cancelled) {
          setSelectedPipelineDetails(pipeline)
        }
      } catch (err) {
        console.error('Failed to load selected pipeline details:', err)
        // Keep the last successful pipeline details in place so the review
        // visualization does not disappear during transient refresh failures.
      } finally {
        if (!cancelled) {
          setLoadingSelectedPipeline(false)
        }
      }
    }

    void loadSelectedPipeline()

    return () => {
      cancelled = true
    }
  }, [selectedPipelineId, selectionMode])

  // Fetch data file tree on component mount
  useEffect(() => {
    const fetchDataTree = async () => {
      try {
        setLoadingDataTree(true)
        const tree = await getDataFileTree()
        setDataFileTree(tree)
      } catch (err: any) {
        console.error('Failed to load data file tree:', err)
        // If not authenticated, don't redirect - let user configure without data library
        if (err.response?.status === 401 && !isAuthenticated) {
          setDataFileTree([])
        } else {
          setError('Failed to load data library')
        }
      } finally {
        setLoadingDataTree(false)
      }
    }
    fetchDataTree()
  }, [isAuthenticated])

  // Fetch available VMs on component mount and refresh silently.
  useEffect(() => {
    let cancelled = false

    const fetchVMs = async (showLoading = false) => {
      try {
        if (showLoading) {
          setLoadingVMs(true)
        }
        const vms = await getAvailableVMs()
        if (cancelled) {
          return
        }
        setAvailableVMs(vms)
        // Auto-select first VM if available
        setSelectedVM((current) => current || vms[0]?.name || '')
      } catch (err: any) {
        console.error('Failed to load VMs:', err)
        // If not authenticated, don't redirect - let user configure without VMs
        if (!cancelled && err.response?.status === 401 && !isAuthenticated) {
          setAvailableVMs([])
        }
      } finally {
        if (!cancelled && showLoading) {
          setLoadingVMs(false)
        }
      }
    }

    void fetchVMs(true)
    const intervalId = window.setInterval(() => {
      void fetchVMs(false)
    }, 30000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [isAuthenticated])

  const handleToolToggle = (toolId: number) => {
    let newSelectedTools: number[]
    if (selectedTools.includes(toolId)) {
      // Allow deselecting any tool (validation happens on form submit)
      newSelectedTools = selectedTools.filter(id => id !== toolId)
    } else {
      newSelectedTools = [...selectedTools, toolId]
    }
    setSelectedTools(newSelectedTools)
    
    // Clear file mappings for deselected tool
    if (!newSelectedTools.includes(toolId)) {
      setToolFileMappings(prev => {
        const updated = { ...prev }
        delete updated[toolId.toString()]
        return updated
      })
    }
  }

  const handlePriorityReorder = (group: PriorityGroup, itemIndex: number, direction: -1 | 1) => {
    const selectedItems = group.items.filter((item) => item.selected)
    const nextIndex = itemIndex + direction
    if (nextIndex < 0 || nextIndex >= selectedItems.length) {
      return
    }

    setPriorityGroups((currentGroups) =>
      currentGroups.map((currentGroup) => {
        if (currentGroup.priority !== group.priority) {
          return currentGroup
        }
        const reorderedSelectedItems = currentGroup.items.filter((item) => item.selected)
        const [moved] = reorderedSelectedItems.splice(itemIndex, 1)
        reorderedSelectedItems.splice(nextIndex, 0, moved)
        const reorderedSelectedIds = reorderedSelectedItems.map((item) => item.id)
        return {
          ...currentGroup,
          items: currentGroup.items.map((item) => ({
            ...item,
            priorityOrder: item.selected
              ? reorderedSelectedIds.indexOf(item.id)
              : item.priorityOrder,
          })).sort((left, right) => {
            if (Boolean(left.selected) !== Boolean(right.selected)) {
              return left.selected ? -1 : 1
            }
            return left.priorityOrder - right.priorityOrder || left.label.localeCompare(right.label)
          }),
        }
      })
    )
  }

  const handlePriorityItemToggle = (group: PriorityGroup, itemId: string) => {
    setPriorityGroups((currentGroups) =>
      currentGroups.map((currentGroup) => {
        if (currentGroup.priority !== group.priority) {
          return currentGroup
        }

        const updatedItems = currentGroup.items.map((item) =>
          item.id === itemId
            ? { ...item, selected: !item.selected }
            : item
        )

        const selectedItems = updatedItems.filter((item) => item.selected)
        return {
          ...currentGroup,
          items: updatedItems
            .map((item) => ({
              ...item,
              priorityOrder: item.selected
                ? selectedItems.findIndex((selectedItem) => selectedItem.id === item.id)
                : item.priorityOrder,
            }))
            .sort((left, right) => {
              if (Boolean(left.selected) !== Boolean(right.selected)) {
                return left.selected ? -1 : 1
              }
              return left.priorityOrder - right.priorityOrder || left.label.localeCompare(right.label)
            }),
        }
      })
    )
  }

  const handleIntentToggle = (intentId: string) => {
    setSelectedIntentIds(prev => (
      prev.includes(intentId)
        ? prev.filter(id => id !== intentId)
        : [...prev, intentId]
    ))
  }

  const activeToolRequirementCards = useMemo<ToolRequirementInfo[]>(() => (
    toolRequirements.map((toolReq) => {
      const currentFlagValues = {
        ...getManualToolDefaultFlagValues(toolReq),
        ...(manualToolFlagValues[toolReq.tool_id] || {}),
      }
      const resolvedRequirements = resolveToolRequirementsForFlags(
        toolReq.tool_id,
        toolReq.requirements || [],
        currentFlagValues
      ).map((requirement, index) => ({
        ...requirement,
        requirement_id:
          requirement.requirement_id || `manual:${toolReq.tool_index}:${toolReq.tool_id}:${requirement.type}:${index}`,
      }))

      return {
        ...toolReq,
        tool_config: currentFlagValues,
        requirements: resolvedRequirements,
      }
    })
  ), [getManualToolDefaultFlagValues, manualToolFlagValues, toolRequirements])
  const pipelineInputRequirements = useMemo<PipelineRequirement[]>(() => {
    if (selectionMode !== 'pipeline') {
      return rawPipelineInputRequirements
    }

    const inputNodes = selectedPipelineNodes.filter((node: any) => PIPELINE_INPUT_NODE_TYPES.has(resolvePipelineNodeType(node)) && node?.id != null)
    if (inputNodes.length === 0) {
      return []
    }

    const toolRequirementByNodeId = new Map<string, ToolRequirementInfo>(
      savedPipelineToolRequirementCards
        .filter((card) => card.node_id)
        .map((card) => [String(card.node_id), card])
    )
    const outgoingToolIdsByInput = new Map<string, string[]>()
    selectedPipelineEdges.forEach((edge: any) => {
      const sourceId = String(edge?.source || '').trim()
      const targetId = String(edge?.target || '').trim()
      if (!sourceId || !targetId) {
        return
      }
      if (!inputNodes.some((node: any) => String(node.id) === sourceId) || !toolRequirementByNodeId.has(targetId)) {
        return
      }
      outgoingToolIdsByInput.set(sourceId, [...(outgoingToolIdsByInput.get(sourceId) || []), targetId])
    })

    return inputNodes.map((node: any, index: number) => {
      const nodeId = String(node.id)
      const inputType = resolvePipelineNodeType(node)
      const defaultLabel = resolvePipelineNodeLabel(node, `Pipeline Input ${index + 1}`)
      const downstreamCards = (outgoingToolIdsByInput.get(nodeId) || [])
        .map((toolNodeId) => toolRequirementByNodeId.get(toolNodeId))
        .filter((card): card is ToolRequirementInfo => Boolean(card))

      const downstreamRequirements = downstreamCards.flatMap((card) => card.requirements || [])
      const matchedRequirements = downstreamRequirements.filter((requirement) => {
        const formats = new Set((requirement.formats || []).map((format) => String(format).toLowerCase()))
        if (inputType === 'fastqinput') {
          return formats.has('fastq')
        }
        if (inputType === 'fastainput') {
          return formats.has('fasta')
        }
        return true
      })
      const requirementsForFormats = matchedRequirements.length > 0
        ? matchedRequirements
        : downstreamRequirements

      const formatSet = new Set<string>()
      requirementsForFormats.forEach((requirement) => {
        ;(requirement.formats || []).forEach((format) => formatSet.add(String(format).toLowerCase()))
      })
      if (formatSet.size === 0 && inputType === 'fastqinput') {
        formatSet.add('fastq')
      }
      if (formatSet.size === 0 && inputType === 'fastainput') {
        formatSet.add('fasta')
      }

      const usedBy = Array.from(new Set(downstreamCards.map((card) => card.tool_name).filter(Boolean)))

      return {
        id: nodeId,
        type: inputType || 'input',
        label: defaultLabel,
        formats: Array.from(formatSet),
        used_by: usedBy,
      }
    })
  }, [
    pipelineRequirements,
    rawPipelineInputRequirements,
    savedPipelineToolRequirementCards,
    selectedPipelineEdges,
    selectedPipelineNodes,
    selectionMode,
  ])
  const selectedToolIds = useMemo(
    () => selectedTools
      .map((toolIndex) => availableTools.find((tool) => tool.id === toolIndex)?.tool_id)
      .filter((toolId): toolId is string => Boolean(toolId)),
    [availableTools, selectedTools]
  )

  const defaultPriorityGroups = useMemo(() => {
    if (selectionMode === 'pipeline' && selectedPipeline) {
      return computePipelinePriorityGroups(selectedPipelineNodes as any[], selectedPipelineEdges as any[])
    }
    if (selectionMode === 'tools' && activeToolRequirementCards.length > 0 && selectedToolIds.length > 0) {
      return computeManualPriorityGroups(activeToolRequirementCards, selectedToolIds)
    }
    return []
  }, [activeToolRequirementCards, selectedPipeline, selectedPipelineEdges, selectedPipelineNodes, selectedToolIds, selectionMode])
  const selectedPriorityToolCount = useMemo(
    () => priorityGroups.reduce((count, group) => count + group.items.filter((item) => item.selected).length, 0),
    [priorityGroups]
  )

  const priorityGroupsSignature = useMemo(
    () => JSON.stringify(defaultPriorityGroups.map((group) => ({
      priority: group.priority,
      itemIds: group.items.map((item) => item.id),
    }))),
    [defaultPriorityGroups]
  )

  useEffect(() => {
    setPriorityGroups((currentGroups) => {
      if (currentGroups.length === 0) {
        return defaultPriorityGroups
      }

      const currentSignature = JSON.stringify(currentGroups.map((group) => ({
        priority: group.priority,
        itemIds: group.items.map((item) => item.id),
      })))

      if (currentSignature === priorityGroupsSignature) {
        return currentGroups
      }

      const selectionByItemId = new Map<string, { selected: boolean; priorityOrder: number }>()
      currentGroups.forEach((group) => {
        group.items.forEach((item) => {
          selectionByItemId.set(item.id, {
            selected: Boolean(item.selected),
            priorityOrder: item.priorityOrder,
          })
        })
      })

      return defaultPriorityGroups.map((group) => {
        const mergedItems = group.items.map((item) => {
          const saved = selectionByItemId.get(item.id)
          return saved
            ? {
                ...item,
                selected: saved.selected,
                priorityOrder: saved.selected ? saved.priorityOrder : item.priorityOrder,
              }
            : item
        })

        const selectedItems = mergedItems
          .filter((item) => item.selected)
          .slice()
          .sort((left, right) => left.priorityOrder - right.priorityOrder || left.label.localeCompare(right.label))

        const selectedOrder = new Map(selectedItems.map((item, index) => [item.id, index]))
        return {
          ...group,
          items: mergedItems
            .map((item) => ({
              ...item,
              priorityOrder: item.selected ? (selectedOrder.get(item.id) ?? item.priorityOrder) : item.priorityOrder,
            }))
            .sort((left, right) => {
              if (Boolean(left.selected) !== Boolean(right.selected)) {
                return left.selected ? -1 : 1
              }
              return left.priorityOrder - right.priorityOrder || left.label.localeCompare(right.label)
            }),
        }
      })
    })

    setOpenPriorityGroups((currentOpen) => {
      if (defaultPriorityGroups.length === 0) {
        return []
      }
      const validPriorities = new Set(defaultPriorityGroups.map((group) => group.priority))
      const filtered = currentOpen.filter((priority) => validPriorities.has(priority))
      return filtered.length > 0 ? filtered : [defaultPriorityGroups[0].priority]
    })
  }, [defaultPriorityGroups, priorityGroupsSignature])

  // Fetch tool requirements when tools are selected
  useEffect(() => {
    if (selectionMode === 'pipeline') {
      setToolRequirements([])
      setLoadingToolRequirements(false)
      return
    }

    if (selectedTools.length > 0) {
      const fetchRequirements = async () => {
        try {
          setLoadingToolRequirements(true)
          const requirements = await getToolRequirements(selectedTools)
          setToolRequirements(requirements)
        } catch (err) {
          console.error('Failed to load tool requirements:', err)
          setError('Failed to load tool requirements')
        } finally {
          setLoadingToolRequirements(false)
        }
      }
      fetchRequirements()
    } else {
      setToolRequirements([])
      setToolFileMappings({})
    }
  }, [selectionMode, selectedTools])

  useEffect(() => {
    if (selectionMode !== 'tools') {
      setRequirementSourceSelections({})
      return
    }

    setRequirementSourceSelections((current) => {
      const nextSelections: Record<string, 'external' | 'upstream'> = {}
      activeToolRequirementCards.forEach((toolReq) => {
        toolReq.requirements.forEach((req) => {
          const key = req.requirement_id || `${toolReq.tool_index}:${req.type}`
          const defaultSelection = req.default_source || (req.is_intermediate ? 'upstream' : 'external')
          nextSelections[key] = current[key] || defaultSelection
        })
      })

      const currentKeys = Object.keys(current)
      const nextKeys = Object.keys(nextSelections)
      if (
        currentKeys.length === nextKeys.length &&
        nextKeys.every((key) => current[key] === nextSelections[key])
      ) {
        return current
      }

      return nextSelections
    })
  }, [activeToolRequirementCards, selectionMode])

  const getRequirementSelectionKey = useCallback((toolReq: ToolRequirementInfo, req: ToolRequirement): string => (
    req.requirement_id || `${toolReq.tool_index}:${req.type}`
  ), [])

  const getRequirementSource = useCallback((toolReq: ToolRequirementInfo, req: ToolRequirement): 'external' | 'upstream' => {
    const key = getRequirementSelectionKey(toolReq, req)
    return requirementSourceSelections[key] || req.default_source || (req.is_intermediate ? 'upstream' : 'external')
  }, [getRequirementSelectionKey, requirementSourceSelections])

  const getManualInputSourceOverrides = useCallback(() => activeToolRequirementCards.flatMap((toolReq) =>
    toolReq.requirements
      .filter((req) => (req.available_sources || []).length > 1)
      .map((req) => ({
        tool_id: toolReq.tool_id,
        requirement_type: req.type,
        source: getRequirementSource(toolReq, req),
      }))
  ), [activeToolRequirementCards, getRequirementSource])

  const getManualInputBlockId = (toolReq: ToolRequirementInfo): string => (
    `manual:${toolReq.tool_id}`
  )

  const manualToolInputBlocks = useMemo<ManualToolInputBlock[]>(
    () => activeToolRequirementCards.map((toolReq) => {
      const externalRequirements = toolReq.requirements.filter((req) => getRequirementSource(toolReq, req) !== 'upstream')
      const upstreamRequirements = toolReq.requirements.filter((req) => getRequirementSource(toolReq, req) === 'upstream')
      return {
        id: getManualInputBlockId(toolReq),
        toolReq,
        toolDefinition: toolCatalogById.get(toolReq.tool_id) || null,
        requirements: toolReq.requirements,
        externalRequirements,
        upstreamRequirements,
      }
    }),
    [activeToolRequirementCards, getRequirementSource, toolCatalogById]
  )

  useEffect(() => {
    if (selectionMode !== 'tools' || activeToolRequirementCards.length === 0) {
      setManualToolFlagValues({})
      setOpenManualToolMenuId(null)
      setEditingManualTool(null)
      setEditingManualToolDraftValues({})
      setEditingManualToolErrors({})
      return
    }

    setManualToolFlagValues((current) => {
      const next: Record<string, Record<string, FlagValue>> = {}
      activeToolRequirementCards.forEach((toolReq) => {
        const toolId = toolReq.tool_id
        const defaultValues = getManualToolDefaultFlagValues(toolReq)
        next[toolId] = {
          ...defaultValues,
          ...(current[toolId] || {}),
        }
      })

      const currentToolIds = Object.keys(current)
      const nextToolIds = Object.keys(next)
      const isSame =
        currentToolIds.length === nextToolIds.length &&
        nextToolIds.every((toolId) => {
          const currentValues = current[toolId] || {}
          const nextValues = next[toolId] || {}
          const currentKeys = Object.keys(currentValues)
          const nextKeys = Object.keys(nextValues)
          return (
            currentKeys.length === nextKeys.length &&
            nextKeys.every((key) => String(currentValues[key]) === String(nextValues[key]))
          )
        })

      return isSame ? current : next
    })
  }, [activeToolRequirementCards, getManualToolDefaultFlagValues, selectionMode])

  useEffect(() => {
    if (selectionMode !== 'tools') {
      return
    }

    setToolFileMappings((current) => {
      let changed = false
      const activeRequirementsByTool = new Map(
        activeToolRequirementCards.map((toolReq) => [
          toolReq.tool_index.toString(),
          new Set(toolReq.requirements.map((requirement) => requirement.type)),
        ])
      )
      const nextMappings: Record<string, Record<string, number[]>> = {}

      Object.entries(current).forEach(([toolKey, requirementMap]) => {
        const activeRequirements = activeRequirementsByTool.get(toolKey)
        if (!activeRequirements) {
          changed = true
          return
        }

        const nextRequirementMap: Record<string, number[]> = {}
        Object.entries(requirementMap).forEach(([requirementType, fileIds]) => {
          if (!activeRequirements.has(requirementType)) {
            changed = true
            return
          }
          nextRequirementMap[requirementType] = fileIds
        })

        if (Object.keys(nextRequirementMap).length > 0) {
          nextMappings[toolKey] = nextRequirementMap
        } else if (Object.keys(requirementMap).length > 0) {
          changed = true
        }
      })

      return changed ? nextMappings : current
    })
  }, [activeToolRequirementCards, selectionMode])

  const openManualToolEditModal = useCallback((toolReq: ToolRequirementInfo) => {
    const defaultValues = getManualToolDefaultFlagValues(toolReq)
    const draftValues = {
      ...defaultValues,
      ...(manualToolFlagValues[toolReq.tool_id] || {}),
    }
    const validation = normalizeDraftFlagValues(toolReq.editable_flags || [], draftValues)
    setEditingManualTool(toolReq)
    setEditingManualToolDraftValues(validation.normalized)
    setEditingManualToolErrors(validation.errors)
    setOpenManualToolMenuId(null)
  }, [getManualToolDefaultFlagValues, manualToolFlagValues])

  const closeManualToolEditModal = useCallback(() => {
    setEditingManualTool(null)
    setEditingManualToolDraftValues({})
    setEditingManualToolErrors({})
  }, [])

  const handleManualToolFlagChange = useCallback((flag: EditableFlagDefinition, value: FlagValue) => {
    const nextDraftValues = {
      ...editingManualToolDraftValues,
      [flag.key]: value,
    }
    const validation = normalizeDraftFlagValues(editingManualTool?.editable_flags || [], nextDraftValues)
    setEditingManualToolDraftValues(nextDraftValues)
    setEditingManualToolErrors(validation.errors)
  }, [editingManualTool, editingManualToolDraftValues])

  const saveManualToolConfiguration = useCallback(() => {
    if (!editingManualTool) {
      return
    }

    const validation = normalizeDraftFlagValues(editingManualTool.editable_flags || [], editingManualToolDraftValues)
    setEditingManualToolErrors(validation.errors)
    if (Object.keys(validation.errors).length > 0) {
      return
    }

    setManualToolFlagValues((current) => ({
      ...current,
      [editingManualTool.tool_id]: validation.normalized,
    }))
    closeManualToolEditModal()
  }, [closeManualToolEditModal, editingManualTool, editingManualToolDraftValues])

  const getManualToolConfigEntries = useCallback(() => (
    activeToolRequirementCards
      .filter((toolReq) => (toolReq.editable_flags || []).length > 0)
      .map((toolReq) => {
        const defaultValues = getManualToolDefaultFlagValues(toolReq)
        const currentValues = {
          ...defaultValues,
          ...(manualToolFlagValues[toolReq.tool_id] || {}),
        }
        return {
          tool_id: toolReq.tool_id,
          tool_index: toolReq.tool_index,
          tool_name: toolReq.tool_name,
          tool_config: currentValues,
          has_custom_config: hasCustomizedFlagValues(toolReq.editable_flags || [], currentValues),
        }
      })
  ), [activeToolRequirementCards, getManualToolDefaultFlagValues, manualToolFlagValues])

  const getManualInputBindings = useCallback(() => (
    activeToolRequirementCards.flatMap((toolReq) => {
      const toolKey = toolReq.tool_index.toString()
      return toolReq.requirements.flatMap((req, requirementIndex) => {
        if (getRequirementSource(toolReq, req) === 'upstream') {
          return []
        }

        const bindingId = req.requirement_id || `manual:${toolReq.tool_index}:${toolReq.tool_id}:${req.type}:${requirementIndex}`
        const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []

        return mappedFileIds.map((fileId) => ({
          file_id: fileId,
          binding_id: bindingId,
          tool_id: toolReq.tool_id,
          requirement_type: req.type,
          label: req.label,
        }))
      })
    })
  ), [activeToolRequirementCards, getRequirementSource, toolFileMappings])

  useEffect(() => {
    if (selectionMode === 'pipeline') {
      setInputBlockNames((current) => {
        const next: Record<string, string> = {}
        pipelineInputRequirements.forEach((inputReq) => {
          const inputKey = inputReq.id || inputReq.label
          next[inputKey] = current[inputKey] || inputReq.label
        })
        return next
      })
      return
    }

    if (selectionMode === 'tools') {
      setInputBlockNames((current) => {
        const next: Record<string, string> = {}
        manualToolInputBlocks.forEach((block) => {
          next[block.id] = current[block.id] || getManualInputBlockDefaultName(block)
        })
        return next
      })
      return
    }

    setInputBlockNames({})
  }, [manualToolInputBlocks, pipelineInputRequirements, selectionMode])

  const handleRequirementSourceChange = (
    toolReq: ToolRequirementInfo,
    req: ToolRequirement,
    source: 'external' | 'upstream'
  ) => {
    const key = getRequirementSelectionKey(toolReq, req)
    setRequirementSourceSelections(prev => ({ ...prev, [key]: source }))

    if (source === 'upstream') {
      setToolFileMappings(prev => {
        const toolKey = toolReq.tool_index.toString()
        if (!prev[toolKey]?.[req.type]) {
          return prev
        }

        const updatedToolMappings = { ...(prev[toolKey] || {}) }
        delete updatedToolMappings[req.type]

        if (Object.keys(updatedToolMappings).length === 0) {
          const next = { ...prev }
          delete next[toolKey]
          return next
        }

        return {
          ...prev,
          [toolKey]: updatedToolMappings,
        }
      })
    }
  }

  const handleToolFileMapping = (toolIndex: number, requirementType: string, fileId: number) => {
    setToolFileMappings(prev => {
      const toolKey = toolIndex.toString()
      const currentFileIds = prev[toolKey]?.[requirementType] || []
      // Toggle: if file is already selected, remove it; otherwise add it
      const isSelected = currentFileIds.includes(fileId)
      const newFileIds = isSelected
        ? currentFileIds.filter(id => id !== fileId)
        : [...currentFileIds, fileId]
      
      const newMappings = { ...prev }
      if (newFileIds.length === 0) {
        // Remove requirement if no files selected
        if (newMappings[toolKey]) {
          delete newMappings[toolKey][requirementType]
          if (Object.keys(newMappings[toolKey]).length === 0) {
            delete newMappings[toolKey]
          }
        }
      } else {
        // Update with new file list
        newMappings[toolKey] = {
          ...newMappings[toolKey],
          [requirementType]: newFileIds
        }
      }
      return newMappings
    })
  }

  const handlePipelineInputMapping = (inputId: string, fileId: number) => {
    setPipelineInputMappings(prev => {
      const currentFileIds = prev[inputId] || []
      const isSelected = currentFileIds.includes(fileId)
      const newFileIds = isSelected
        ? currentFileIds.filter(id => id !== fileId)
        : [...currentFileIds, fileId]

      if (newFileIds.length === 0) {
        const next = { ...prev }
        delete next[inputId]
        return next
      }

      return {
        ...prev,
        [inputId]: newFileIds,
      }
    })
  }

  const handleApplyRecommendation = (option: RecommendationOption) => {
    setSelectionMode('tools')
    setSelectedPipelineId(null)
    setSelectedTools(option.tool_indices)
    setToolFileMappings({})
  }

  const normalizeFileFormats = (file: FileItem & { folderPath?: string }): string[] => {
    const filename = (file.filename || '').toLowerCase()
    const formats = new Set<string>()
    const declared = (file.file_format || '').toLowerCase().replace(/^\./, '')
    if (declared) formats.add(declared)

    if (filename.endsWith('.fastq') || filename.endsWith('.fastq.gz') || filename.endsWith('.fq') || filename.endsWith('.fq.gz')) {
      formats.add('fastq')
      if (filename.endsWith('.gz')) formats.add(filename.endsWith('.fq.gz') ? 'fq.gz' : 'fastq.gz')
    }
    if (filename.endsWith('.fasta') || filename.endsWith('.fasta.gz') || filename.endsWith('.fa') || filename.endsWith('.fa.gz') || filename.endsWith('.fna') || filename.endsWith('.fna.gz')) {
      formats.add('fasta')
      if (filename.endsWith('.fasta.gz')) formats.add('fasta.gz')
      if (filename.endsWith('.fa.gz')) formats.add('fa.gz')
      if (filename.endsWith('.fna.gz')) formats.add('fna.gz')
    }
    if (filename.endsWith('.gff3') || filename.endsWith('.gff3.gz')) {
      formats.add('gff')
      formats.add('gff3')
      if (filename.endsWith('.gz')) formats.add('gff3.gz')
    }
    if (filename.endsWith('.gff') || filename.endsWith('.gff.gz')) {
      formats.add('gff')
      if (filename.endsWith('.gz')) formats.add('gff.gz')
    }
    if (filename.endsWith('.gtf') || filename.endsWith('.gtf.gz')) {
      formats.add('gtf')
      if (filename.endsWith('.gz')) formats.add('gtf.gz')
    }
    if (filename.endsWith('.hal') || filename.endsWith('.hal.gz')) {
      formats.add('hal')
      if (filename.endsWith('.gz')) formats.add('hal.gz')
    }
    if (filename.endsWith('.gfa') || filename.endsWith('.gfa.gz')) {
      formats.add('gfa')
      if (filename.endsWith('.gz')) formats.add('gfa.gz')
    }
    if (filename.endsWith('.meryl') || filename.endsWith('.meryl.tar') || filename.endsWith('.meryl.tar.gz') || filename.endsWith('.meryl.tgz')) formats.add('meryl')
    if (filename.endsWith('.cfg') || filename.endsWith('.cfg.gz')) formats.add('cfg')
    if (filename.endsWith('.cfg.gz')) formats.add('cfg.gz')
    if (filename.endsWith('.conf') || filename.endsWith('.conf.gz')) formats.add('conf')
    if (filename.endsWith('.conf.gz')) formats.add('conf.gz')
    if (filename.endsWith('.ini') || filename.endsWith('.ini.gz')) formats.add('ini')
    if (filename.endsWith('.ini.gz')) formats.add('ini.gz')
    if (filename.endsWith('.json') || filename.endsWith('.json.gz')) formats.add('json')
    if (filename.endsWith('.json.gz')) formats.add('json.gz')
    if (filename.endsWith('.txt') || filename.endsWith('.txt.gz')) formats.add('txt')
    if (filename.endsWith('.txt.gz')) formats.add('txt.gz')
    if (filename.endsWith('.tsv') || filename.endsWith('.tsv.gz')) formats.add('tsv')
    if (filename.endsWith('.tsv.gz')) formats.add('tsv.gz')
    if (filename.endsWith('.csv') || filename.endsWith('.csv.gz')) formats.add('csv')
    if (filename.endsWith('.csv.gz')) formats.add('csv.gz')
    if (filename.endsWith('.tar') || filename.endsWith('.tar.gz')) formats.add('tar')
    if (filename.endsWith('.tgz')) formats.add('tgz')

    return Array.from(formats)
  }

  const fileMatchesRequirement = (
    file: FileItem & { folderPath?: string },
    requirement: { formats: string[]; filename_pattern?: string }
  ): boolean => {
    const normalizedFormats = new Set(normalizeFileFormats(file))
    const formatMatches = requirement.formats.length === 0
      ? true
      : requirement.formats.some(format => normalizedFormats.has(format.toLowerCase()))
    if (!formatMatches) {
      return false
    }

    if (requirement.filename_pattern) {
      try {
        const regex = new RegExp(requirement.filename_pattern, 'i')
        return regex.test(file.filename || '')
      } catch (error) {
        console.warn('Invalid filename pattern in requirement', requirement.filename_pattern, error)
      }
    }

    return true
  }

  const getCombinedSelectableFiles = (): Array<FileItem & { folderPath?: string }> => {
    return flattenFiles(dataFileTree)
  }

  const getRuntimeInputAssignments = (): RuntimeInputAssignment[] => {
    if (selectionMode === 'pipeline') {
      if (!savedPipelineExecutionPlan) {
        return []
      }

      const groupedAssignments = new Map<string, RuntimeInputAssignment>()
      savedPipelineExecutionPlan.plannedInputs.forEach((input) => {
        const toolId = String(input.tool_id || '').trim().toUpperCase()
        const requirementType = String(input.requirement_type || input.binding_id || '').trim()
        if (!toolId || !requirementType) {
          return
        }

        const key = `${toolId}:${requirementType}`
        const sizeMib = (Number(input.size_bytes || 0) / (1024 * 1024)) || 0
        const normalizedFormat = String(input.file_format || '').trim().toLowerCase()
        const isCompressed =
          normalizedFormat.includes('gz') ||
          normalizedFormat.includes('bz2') ||
          normalizedFormat.includes('xz') ||
          normalizedFormat.includes('zip') ||
          String(input.filename || '').toLowerCase().endsWith('.gz') ||
          String(input.filename || '').toLowerCase().endsWith('.bz2') ||
          String(input.filename || '').toLowerCase().endsWith('.xz') ||
          String(input.filename || '').toLowerCase().endsWith('.zip')

        const existing = groupedAssignments.get(key)
        if (existing) {
          existing.total_input_size_mib = Number((existing.total_input_size_mib + sizeMib).toFixed(2))
          existing.compressed_input_size_mib = Number((existing.compressed_input_size_mib + (isCompressed ? sizeMib : 0)).toFixed(2))
          if (normalizedFormat && !existing.file_formats.includes(normalizedFormat)) {
            existing.file_formats.push(normalizedFormat)
          }
          return
        }

        groupedAssignments.set(key, {
          tool_id: toolId,
          requirement_type: requirementType,
          total_input_size_mib: Number(sizeMib.toFixed(2)),
          compressed_input_size_mib: Number((isCompressed ? sizeMib : 0).toFixed(2)),
          file_formats: normalizedFormat ? [normalizedFormat] : [],
        })
      })

      return Array.from(groupedAssignments.values())
    }

    const selectableFiles = getCombinedSelectableFiles()
    const fileById = new Map<number, FileItem & { folderPath?: string }>(
      selectableFiles.map((file) => [file.id, file])
    )

    const assignments: RuntimeInputAssignment[] = []
    activeToolRequirementCards.forEach((toolReq) => {
      const toolKey = toolReq.tool_index.toString()
      toolReq.requirements.forEach((req) => {
        if (getRequirementSource(toolReq, req) === 'upstream') {
          return
        }

        const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
        const totalInputSizeMib = mappedFileIds.reduce((sum, fileId) => {
          const file = fileById.get(fileId)
          const sizeBytes = typeof file?.size_bytes === 'number' ? file.size_bytes : 0
          return sum + (sizeBytes > 0 ? sizeBytes / (1024 * 1024) : 0)
        }, 0)
        const compressedInputSizeMib = mappedFileIds.reduce((sum, fileId) => {
          const file = fileById.get(fileId)
          const filename = String(file?.filename || '').toLowerCase()
          const fileFormat = String(file?.file_format || '').toLowerCase()
          const isCompressed =
            filename.endsWith('.gz') ||
            filename.endsWith('.bz2') ||
            filename.endsWith('.xz') ||
            filename.endsWith('.zip') ||
            fileFormat.includes('gz') ||
            fileFormat.includes('bz2') ||
            fileFormat.includes('xz') ||
            fileFormat.includes('zip')
          const sizeBytes = typeof file?.size_bytes === 'number' ? file.size_bytes : 0
          return sum + (isCompressed && sizeBytes > 0 ? sizeBytes / (1024 * 1024) : 0)
        }, 0)
        const uniqueFormats = Array.from(new Set(
          mappedFileIds
            .map((fileId) => String(fileById.get(fileId)?.file_format || '').trim().toLowerCase())
            .filter(Boolean)
        ))

        if (totalInputSizeMib > 0) {
          assignments.push({
            tool_id: toolReq.tool_id,
            requirement_type: req.type,
            total_input_size_mib: Number(totalInputSizeMib.toFixed(2)),
            compressed_input_size_mib: Number(compressedInputSizeMib.toFixed(2)),
            file_formats: uniqueFormats,
          })
        }
      })
    })

    return assignments
  }

  const renderSelectableFileChip = (file: FileItem & { folderPath?: string }, keyPrefix: string, selected = false) => {
    const title = file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename

    return (
      <div
        key={`${keyPrefix}-${file.id}`}
        className={`builder-file-chip ${selected ? 'selected' : ''}`}
        title={title}
      >
        <strong>{file.filename}</strong>
        {file.folderPath && <span>{file.folderPath}</span>}
      </div>
    )
  }

  const handleGenerateRecommendations = async () => {
    const selectedFiles = getCombinedSelectableFiles()
    setLoadingRecommendations(true)
    try {
      const response = await getPipelineRecommendations(
        selectedIntentIds,
        selectedFiles.map(file => ({
          filename: file.filename,
          file_format: file.file_format || null,
        }))
      )
      const options = response?.pipeline_options || []
      setRecommendationOptions(options)
      if (options.length === 0) {
        setError('No recommendation could be generated from the selected intentions and Storage files')
      } else {
        setError('')
      }
    } finally {
      setLoadingRecommendations(false)
    }
  }

  const builderLevels: BuilderLevelDefinition[] = [
    {
      level: 1,
      title: 'Pick workflow',
      description: 'Name the job and choose tools, a saved pipeline, or an intent-driven suggestion.',
    },
    {
      level: 2,
      title: 'Attach inputs',
      description: 'Review available files, then map them to each named pipeline or tool block.',
    },
    {
      level: 3,
      title: 'Configure run',
      description: 'Choose compute resources and tune same-level priorities after inputs are assigned.',
    },
    {
      level: 4,
      title: 'Review and submit',
      description: 'Inspect the final pipeline, estimated runtime, and expected price before launch.',
    },
  ]

  const selectedToolDefinitions = useMemo(
    () => availableTools.filter((tool) => selectedTools.includes(tool.id)),
    [availableTools, selectedTools]
  )

  const finalPipelineStages = useMemo(() => {
    if (priorityGroups.length > 0) {
      return priorityGroups.map((group) => ({
        level: group.priority,
        title: group.title,
        items: group.items.filter((item) => item.selected).map((item) => item.label),
        fallbackCount: group.items.filter((item) => !item.selected).length,
      }))
    }

    if (selectionMode === 'pipeline') {
      const savedStageLabels = selectedPipelineNodes
        .filter((node: any) => PIPELINE_STAGE_NODE_TYPES.has(resolvePipelineNodeType(node)))
        .map((node: any, index: number) => resolvePipelineNodeLabel(node, `Stage ${index + 1}`))
        .filter((label: string) => label.trim().length > 0)

      const pipelineToolLabels = savedStageLabels.length > 0
        ? savedStageLabels
        : (pipelineRequirementTools.map((toolId) => {
            const matchingTool = availableTools.find((tool) => tool.tool_id === toolId || tool.name.toUpperCase() === toolId)
            return matchingTool?.name || toolId
          }) || [])

      return pipelineToolLabels.length > 0
        ? [{
            level: 1,
            title: selectedPipeline?.name || 'Saved pipeline',
            items: pipelineToolLabels,
            fallbackCount: 0,
          }]
        : []
    }

    return selectedToolDefinitions.length > 0
      ? [{
          level: 1,
          title: 'Automatic pipeline',
          items: selectedToolDefinitions.map((tool) => tool.name),
          fallbackCount: 0,
        }]
      : []
  }, [availableTools, pipelineRequirementTools, priorityGroups, selectedPipeline, selectedPipelineNodes, selectedToolDefinitions, selectionMode])

  const totalMappedInputCount = useMemo(() => {
    if (selectionMode === 'pipeline') {
      return Object.values(pipelineInputMappings).reduce((sum, fileIds) => sum + fileIds.length, 0)
    }

    return Object.values(toolFileMappings).reduce(
      (sum, requirementMap) => sum + Object.values(requirementMap).reduce((innerSum, fileIds) => innerSum + fileIds.length, 0),
      0
    )
  }, [pipelineInputMappings, selectionMode, toolFileMappings])

  const missingPipelineInputCount = useMemo(() => {
    if (selectionMode !== 'pipeline') {
      return 0
    }

    return pipelineInputRequirements.filter((inputReq) => {
      const inputKey = inputReq.id || inputReq.label
      return (pipelineInputMappings[inputKey] || []).length === 0
    }).length
  }, [pipelineInputMappings, pipelineInputRequirements, selectionMode])

  const missingManualInputBlockCount = useMemo(() => {
    if (selectionMode !== 'tools') {
      return 0
    }

    return manualToolInputBlocks.filter((block) => {
      const toolKey = block.toolReq.tool_index.toString()
      return block.externalRequirements.some((req) => (toolFileMappings[toolKey]?.[req.type] || []).length === 0)
    }).length
  }, [manualToolInputBlocks, selectionMode, toolFileMappings])

  const canAdvanceFromLevelOne = Boolean(
    jobName.trim() &&
    (
      (selectionMode === 'tools' && selectedTools.length > 0) ||
      (selectionMode === 'pipeline' && selectedPipelineId)
    )
  )

  const inputStepMappingsComplete = selectionMode === 'pipeline'
    ? (pipelineInputRequirements.length === 0 || missingPipelineInputCount === 0)
    : (manualToolInputBlocks.length === 0 || missingManualInputBlockCount === 0)

  const canAdvanceFromLevelThree = Boolean(selectedVM)

  const inputBlockDisplayName = useCallback((inputId: string, fallbackLabel: string): string => (
    inputBlockNames[inputId]?.trim() || fallbackLabel
  ), [inputBlockNames])

  const handleInputBlockNameChange = (inputId: string, value: string) => {
    setInputBlockNames((prev) => ({ ...prev, [inputId]: value }))
  }

  const goToNextLevel = () => {
    setSlideDirection('forward')
    setCurrentLevel((current) => Math.min(4, current + 1) as BuilderLevel)
  }

  const goToPreviousLevel = () => {
    setSlideDirection('backward')
    setCurrentLevel((current) => Math.max(1, current - 1) as BuilderLevel)
  }

  const handleCancelCreateJob = () => {
    shouldPersistDraftRef.current = false
    clearCreateJobDraft()
    navigate('/')
  }

  const shouldShowRuntimeEstimateCard = Boolean(loadingRuntimeEstimate || runtimeEstimate || runtimeEstimateError)
  const storageSelectableFiles = useMemo(
    () => flattenFiles(dataFileTree),
    [dataFileTree]
  )
  const combinedSelectableFiles = useMemo(
    () => getCombinedSelectableFiles(),
    [dataFileTree]
  )
  const canAdvanceFromLevelTwo = inputStepMappingsComplete

  const selectedLibraryFiles = useMemo(() => combinedSelectableFiles.filter((file) => {
    if (selectionMode === 'pipeline') {
      return Object.values(pipelineInputMappings).some((fileIds) => fileIds.includes(file.id))
    }

    return Object.values(toolFileMappings).some((requirementMap) =>
      Object.values(requirementMap).some((fileIds) => fileIds.includes(file.id))
    )
  }), [combinedSelectableFiles, pipelineInputMappings, selectionMode, toolFileMappings])

  const reviewPipelinePlanRequest = useMemo<PipelinePlanPreviewRequest | null>(() => {
    if (currentLevel !== 4) {
      return null
    }

    const filesById = new Map(combinedSelectableFiles.map((file) => [file.id, file]))

    if (selectionMode === 'pipeline') {
      if (!selectedPipelineId) {
        return null
      }
      const executionPreferences: Record<string, unknown> = buildPipelineExecutionPreferences(priorityGroups)
      if (savedPipelineExecutionPlan) {
        if (savedPipelineExecutionPlan.manualToolConfigs.length > 0) {
          executionPreferences.manual_tool_configs = savedPipelineExecutionPlan.manualToolConfigs
        }
        if (savedPipelineExecutionPlan.manualInputBindings.length > 0) {
          executionPreferences.manual_input_bindings = savedPipelineExecutionPlan.manualInputBindings
        }
        if (savedPipelineExecutionPlan.inputSourceOverrides.length > 0) {
          executionPreferences.input_source_overrides = savedPipelineExecutionPlan.inputSourceOverrides
        }
      }
      executionPreferences.source_pipeline_id = selectedPipelineId

      return {
        pipeline_id: selectedPipelineId,
        planned_inputs: (savedPipelineExecutionPlan?.plannedInputs || []).map((input) => ({
          ...input,
          id: filesById.get(input.id)?.id || input.id,
        })),
        execution_preferences: Object.keys(executionPreferences).length > 0
          ? executionPreferences
          : undefined,
      }
    }

    if (selectionMode !== 'tools') {
      return null
    }

    if (selectedTools.length === 0) {
      return null
    }

    const plannedInputs = activeToolRequirementCards.flatMap((toolReq) => {
      const toolKey = toolReq.tool_index.toString()

      return toolReq.requirements.flatMap((req) => {
        if (getRequirementSource(toolReq, req) === 'upstream') {
          return []
        }

        const bindingId = req.requirement_id || `${toolReq.tool_id}:${req.type}`
        const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []

        return mappedFileIds
          .map((fileId) => filesById.get(fileId))
          .filter((file): file is FileItem & { folderPath?: string } => Boolean(file))
          .map((file) => ({
            id: file.id,
            binding_id: bindingId,
            tool_id: toolReq.tool_id,
            requirement_type: req.type,
            label: req.label,
            filename: file.filename,
            file_format: file.file_format || null,
            size_bytes: file.size_bytes || 0,
            s3_key: file.s3_key,
            source: 'library',
          }))
      })
    })

    const executionPreferences: Record<string, unknown> = buildManualExecutionPreferences(priorityGroups)

    const inputSourceOverrides = getManualInputSourceOverrides()
    if (inputSourceOverrides.length > 0) {
      executionPreferences.input_source_overrides = inputSourceOverrides
    }
    const manualInputBindings = getManualInputBindings()
    if (manualInputBindings.length > 0) {
      executionPreferences.manual_input_bindings = manualInputBindings
    }
    const manualToolConfigs = getManualToolConfigEntries().map(({ tool_id, tool_index, tool_config }) => ({
      tool_id,
      tool_index,
      tool_config,
    }))
    if (manualToolConfigs.length > 0) {
      executionPreferences.manual_tool_configs = manualToolConfigs
    }

    return {
      tool_indices: selectedTools,
      planned_inputs: plannedInputs,
      execution_preferences: Object.keys(executionPreferences).length > 0
        ? executionPreferences
        : undefined,
    }
  }, [
    activeToolRequirementCards,
    combinedSelectableFiles,
    currentLevel,
    getManualToolConfigEntries,
    getManualInputBindings,
    getManualInputSourceOverrides,
    getRequirementSource,
    inputBlockDisplayName,
    pipelineInputMappings,
    priorityGroups,
    savedPipelineExecutionPlan,
    selectedPipelineId,
    selectedTools,
    selectionMode,
    toolFileMappings,
  ])

  const reviewPipelinePlanSignature = useMemo(
    () => reviewPipelinePlanRequest ? JSON.stringify(reviewPipelinePlanRequest) : '',
    [reviewPipelinePlanRequest]
  )

  useEffect(() => {
    if (!reviewPipelinePlanRequest) {
      setBackendReviewPipelinePreview(null)
      setLoadingReviewPipelinePreview(false)
      setReviewPipelinePreviewError('')
      return
    }

    let cancelled = false

    const loadPipelinePlanPreview = async () => {
      try {
        setLoadingReviewPipelinePreview(true)
        setReviewPipelinePreviewError('')
        setBackendReviewPipelinePreview(null)
        const preview = await previewPipelinePlan(reviewPipelinePlanRequest)
        if (!cancelled) {
          setBackendReviewPipelinePreview(preview)
        }
      } catch (err: any) {
        if (!cancelled) {
          console.error('Failed to preview pipeline plan:', err)
          setBackendReviewPipelinePreview(null)
          setReviewPipelinePreviewError(err.message || 'Failed to build pipeline preview')
        }
      } finally {
        if (!cancelled) {
          setLoadingReviewPipelinePreview(false)
        }
      }
    }

    const timeoutId = window.setTimeout(() => {
      void loadPipelinePlanPreview()
    }, 350)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [reviewPipelinePlanRequest, reviewPipelinePlanSignature])

  const livePipelineBox = (
    <div className="builder-live-pipeline-card">
      <div className="builder-live-pipeline-header">
        <div>
          <h3>Final Pipeline</h3>
          <p>
            {selectionMode === 'pipeline'
              ? `Using saved pipeline${selectedPipeline?.name ? `: ${selectedPipeline.name}` : ''}`
              : 'Built dynamically from the selected tools'}
          </p>
        </div>
        <span className="builder-live-pipeline-badge">
          {selectionMode === 'pipeline' ? 'Use Pipeline' : 'Configure Job'}
        </span>
      </div>
      {finalPipelineStages.length === 0 ? (
        <p className="builder-live-pipeline-empty">
          Select tools or a saved pipeline to preview the final execution flow here.
        </p>
      ) : (
        <div className="builder-stage-grid">
          {finalPipelineStages.map((stage) => (
            <div key={`live-${stage.level}-${stage.title}`} className="builder-stage-card">
              <span className="builder-stage-badge">Level {stage.level}</span>
              <strong>{stage.title}</strong>
              <p>{stage.items.length > 0 ? stage.items.join(', ') : 'Default scheduler order'}</p>
              {stage.fallbackCount > 0 && (
                <small>{stage.fallbackCount} additional tool(s) remain in default order for this level.</small>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const effectiveReviewPipelinePreview = backendReviewPipelinePreview

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    if (!shouldPersistDraftRef.current) {
      return
    }

    const draft: CreateJobDraft = {
      version: 6,
      jobName,
      selectionMode,
      selectedTools,
      selectedPipelineId,
      selectedPipelineDetails,
      pipelineRequirements,
      toolFileMappings,
      pipelineInputMappings,
      requirementSourceSelections,
      selectedIntentIds,
      priorityGroups,
      openPriorityGroups,
      currentLevel,
      inputBlockNames,
      manualToolFlagValues,
      selectedVM,
      executionDataImprovementConsent,
    }

    window.sessionStorage.setItem(CREATE_JOB_DRAFT_STORAGE_KEY, JSON.stringify(draft))
  }, [
    currentLevel,
    effectiveReviewPipelinePreview,
    executionDataImprovementConsent,
    inputBlockNames,
    jobName,
    manualToolFlagValues,
    openPriorityGroups,
    pipelineInputMappings,
    pipelineRequirements,
    priorityGroups,
    requirementSourceSelections,
    selectedIntentIds,
    selectedPipelineDetails,
    selectedPipelineId,
    selectedTools,
    selectedVM,
    selectionMode,
    toolFileMappings,
  ])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (currentLevel !== 4) {
      setSlideDirection('forward')
      setCurrentLevel(4)
      return
    }
    
    // Check authentication first - redirect to login if not authenticated
    // Users can configure the job, but need to login to create/start it
    if (!isAuthenticated) {
      navigate('/login')
      return
    }
    
    if (!jobName.trim()) {
      setError('Please enter a job name')
      return
    }

    if (selectionMode === 'tools' && selectedTools.length === 0) {
      setError('Please select at least one tool')
      return
    }

    // Validate that all non-intermediate requirements have files mapped
    if (selectionMode === 'tools' && selectedTools.length > 0) {
      const missingRequirements: string[] = []
      activeToolRequirementCards.forEach(toolReq => {
        toolReq.requirements.forEach(req => {
          if (getRequirementSource(toolReq, req) !== 'upstream') {
            const toolKey = toolReq.tool_index.toString()
            const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
            if (mappedFileIds.length === 0) {
              const blockId = getManualInputBlockId(toolReq)
              const block = manualToolInputBlocks.find((item) => item.id === blockId)
              const fallbackName = block ? getManualInputBlockDefaultName(block) : `${toolReq.tool_name} tool block`
              missingRequirements.push(`${inputBlockDisplayName(blockId, fallbackName)}: ${req.label}`)
            }
          }
        })
      })
      if (missingRequirements.length > 0) {
        setError(`Please select at least one file for all required inputs:\n${missingRequirements.join('\n')}`)
        return
      }
    }

    if (selectionMode === 'pipeline' && pipelineInputRequirements.length > 0) {
      const missingInputs = pipelineInputRequirements
        .filter((inputReq) => (pipelineInputMappings[inputReq.id || inputReq.label] || []).length === 0)
        .map((inputReq) => inputBlockDisplayName(inputReq.id || inputReq.label, inputReq.label))

      if (missingInputs.length > 0) {
        setError(`Please select at least one file for each pipeline input:\n${missingInputs.join('\n')}`)
        return
      }
    }

    if (selectionMode === 'pipeline' && !selectedPipelineId) {
      setError('Please select a pipeline')
      return
    }

    // Collect all mapped files from visible tool requirements
    const fileIdSet = new Set<number>()
    if (selectionMode === 'pipeline') {
      pipelineInputRequirements.forEach((inputReq) => {
        const inputKey = inputReq.id || inputReq.label
        const mappedFileIds = pipelineInputMappings[inputKey] || []
        mappedFileIds.forEach((fileId) => fileIdSet.add(fileId))
      })
    } else {
      activeToolRequirementCards.forEach(toolReq => {
        toolReq.requirements.forEach(req => {
          if (getRequirementSource(toolReq, req) !== 'upstream') {
            const toolKey = toolReq.tool_index.toString()
            const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
            mappedFileIds.forEach(fileId => fileIdSet.add(fileId))
          }
        })
      })
    }
    const uploadedFileIds = Array.from(fileIdSet)

    if (selectionMode === 'pipeline' && !selectedPipeline) {
      setError('The selected pipeline could not be loaded for job creation')
      return
    }

    if (loadingRuntimeEstimate) {
      setError('Please wait for the job cost estimate before starting.')
      return
    }

    if (!runtimeEstimate) {
      setError(runtimeEstimateError || 'A job cost estimate is required before starting.')
      return
    }

    if (!executionDataImprovementConsent) {
      setError('Please accept the job submission terms and execution data use checkbox before submitting.')
      return
    }

    try {
      setCreating(true)
      setSubmitStatus('Creating job...')
      
      // Create job with tool selection or pipeline and input files
      const jobData: JobCreate = {
        name: jobName,
        vm_name: selectedVM || undefined,
        estimated_price_usd: runtimeEstimate.estimated_price_usd,
      }
      
      const existingLibraryFileIds = uploadedFileIds.filter(id => id > 0)

      // Only include already-uploaded library files at create time
      if (existingLibraryFileIds.length > 0) {
        jobData.input_file_ids = existingLibraryFileIds
      }

      const inputSourceOverrides = selectionMode === 'tools'
        ? getManualInputSourceOverrides()
        : []

      if (selectionMode === 'pipeline') {
        if (!savedPipelineExecutionPlan || savedPipelineExecutionPlan.toolIndices.length === 0) {
          setError('The selected pipeline could not be converted into a runnable job')
          setCreating(false)
          return
        }
        jobData.pipeline_id = selectedPipelineId || undefined
        const manualExecutionPreferences: Record<string, unknown> = buildPipelineExecutionPreferences(priorityGroups)
        if (savedPipelineExecutionPlan.manualToolConfigs.length > 0) {
          manualExecutionPreferences.manual_tool_configs = savedPipelineExecutionPlan.manualToolConfigs
        }
        if (savedPipelineExecutionPlan.manualInputBindings.length > 0) {
          manualExecutionPreferences.manual_input_bindings = savedPipelineExecutionPlan.manualInputBindings
        }
        if (savedPipelineExecutionPlan.inputSourceOverrides.length > 0) {
          manualExecutionPreferences.input_source_overrides = savedPipelineExecutionPlan.inputSourceOverrides
        }
        if (selectedPipelineId) {
          manualExecutionPreferences.source_pipeline_id = selectedPipelineId
        }
        if (Object.keys(manualExecutionPreferences).length > 0) {
          jobData.execution_preferences = manualExecutionPreferences
        }
      } else {
        if (selectedTools.length === 0) {
          setError('Please select at least one tool')
          setCreating(false)
          return
        }
        jobData.tool_indices = selectedTools
        const manualExecutionPreferences: Record<string, unknown> = {}
        if (priorityGroups.length > 0) {
          Object.assign(manualExecutionPreferences, buildManualExecutionPreferences(priorityGroups))
        }
        const manualToolConfigs = getManualToolConfigEntries().map(({ tool_id, tool_index, tool_config }) => ({
          tool_id,
          tool_index,
          tool_config,
        }))
        if (manualToolConfigs.length > 0) {
          manualExecutionPreferences.manual_tool_configs = manualToolConfigs
        }
        const manualInputBindings = getManualInputBindings()
        if (manualInputBindings.length > 0) {
          manualExecutionPreferences.manual_input_bindings = manualInputBindings
        }
        if (Object.keys(manualExecutionPreferences).length > 0) {
          jobData.execution_preferences = manualExecutionPreferences
        }
      }

      if (inputSourceOverrides.length > 0) {
        jobData.execution_preferences = {
          ...(jobData.execution_preferences || {}),
          input_source_overrides: inputSourceOverrides,
        }
      }

      jobData.execution_preferences = {
        ...(jobData.execution_preferences || {}),
        job_submission_legal_acceptance: {
          accepted: true,
          captured_at: new Date().toISOString(),
          source: 'create_job_submit',
          terms_document: 'agreement.txt',
          kvkk_document: 'kvkk.txt',
        },
        product_improvement_execution_data_consent: {
          granted: true,
          captured_at: new Date().toISOString(),
          source: 'create_job_submit',
          text: 'Use my job execution metadata, tool settings, runtime metrics, logs, and non-identifying outputs to improve CASSIE products.',
        },
      }
      
      // Remove undefined values to ensure clean JSON serialization
      // But preserve null values and numbers (including 0)
      const cleanJobData = Object.fromEntries(
        Object.entries(jobData).filter(([_, v]) => {
          // Keep all values except undefined
          // This ensures pipeline_id (which is a number) is preserved
          return v !== undefined
        })
      ) as JobCreate

      const job = await createJob(cleanJobData)

      if (job && job.id) {
        setSubmitStatus('Starting job...')
        await executeJob(job.id)
        shouldPersistDraftRef.current = false
        clearCreateJobDraft()
        navigate(`/jobs/${job.id}`)
      } else {
        setError('Job created but invalid response received. Please check the jobs list.')
        console.error('Invalid job response:', job)
      }
    } catch (err: any) {
      console.error('Job creation error:', err)
      setError(err.message || err.response?.data?.message || 'Failed to create job')
    } finally {
      setCreating(false)
      setSubmitStatus('')
    }
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <header className="page-header">
          <h1 className="page-title">{retryJobId ? 'Retry Job' : 'Create New Job'}</h1>
        </header>

        <div className="form-container create-job-form">
        {error && <div className="error-message">{error}</div>}

        <form onSubmit={handleSubmit}>
          {submitStatus && (
            <div style={{ marginBottom: '1rem', padding: '0.75rem 1rem', borderRadius: '6px', backgroundColor: '#eff6ff', color: '#1d4ed8' }}>
              {submitStatus}
            </div>
          )}

          <div className="builder-stepper">
            {builderLevels.map((builderLevel) => {
              const canOpenLevel =
                builderLevel.level === 1 ||
                (builderLevel.level === 2 && canAdvanceFromLevelOne) ||
                (builderLevel.level === 3 && canAdvanceFromLevelOne && canAdvanceFromLevelTwo) ||
                (builderLevel.level === 4 && canAdvanceFromLevelOne && canAdvanceFromLevelTwo && canAdvanceFromLevelThree)

              return (
                <button
                  key={builderLevel.level}
                  type="button"
                  className={`builder-step ${currentLevel === builderLevel.level ? 'active' : ''}`}
                  disabled={!canOpenLevel}
                  onClick={() => {
                    setSlideDirection(builderLevel.level > currentLevel ? 'forward' : 'backward')
                    setCurrentLevel(builderLevel.level)
                  }}
                >
                  <span className="builder-step-number">{builderLevel.level}</span>
                  <span className="builder-step-copy">
                    <strong>{builderLevel.title}</strong>
                    <small>{builderLevel.description}</small>
                  </span>
                </button>
              )
            })}
          </div>

          <div className="builder-level-header">
            <div>
              <p className="builder-level-kicker">Level {currentLevel}</p>
              <h2>{builderLevels.find((builderLevel) => builderLevel.level === currentLevel)?.title}</h2>
            </div>
            <p>{builderLevels.find((builderLevel) => builderLevel.level === currentLevel)?.description}</p>
          </div>

          <div
            key={`builder-level-${currentLevel}`}
            className={`builder-stage-shell ${slideDirection === 'forward' ? 'slide-forward' : 'slide-backward'}`}
          >
          {currentLevel === 1 && (
            <>
          <div className="form-group">
            <label htmlFor="name">Job Name *</label>
            <input
              type="text"
              id="name"
              value={jobName}
              onChange={(e) => setJobName(e.target.value)}
              required
              disabled={creating}
              placeholder="e.g., My FastQC Analysis"
            />
          </div>

          {selectionMode === 'tools' && (
            <div className="form-group">
              <label>Intent-Based Suggestions</label>
              <div className="builder-section-card">
                <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                  Choose what you want to achieve. Suggestions will consider files already uploaded in Storage.
                </p>

                <div style={{ marginBottom: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {recommendationIntents.map(intent => {
                    const selected = selectedIntentIds.includes(intent.id)
                    return (
                      <button
                        key={intent.id}
                        type="button"
                        onClick={() => handleIntentToggle(intent.id)}
                        className={selected ? 'btn-primary' : 'btn-secondary'}
                        style={{ padding: '0.5rem 0.75rem' }}
                        title={intent.description}
                      >
                        {intent.label}
                      </button>
                    )
                  })}
                </div>

                {loadingDataTree ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading Storage files...</p>
                ) : (
                  <div style={{ marginBottom: '1rem' }}>
                    <div style={sharedRequirementCardStyle}>
                      {getCombinedSelectableFiles().length === 0 ? (
                        <p style={{ margin: 0, color: '#666', fontStyle: 'italic' }}>
                          No Storage files found yet. Upload inputs from Storage before using them in a job.
                        </p>
                      ) : getCombinedSelectableFiles().map(file => (
                        <span
                          key={`rec-file-${file.id}`}
                          className="builder-file-chip"
                          title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                        >
                          <strong>{file.filename}</strong>
                          {file.folderPath && <span>{file.folderPath}</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleGenerateRecommendations}
                  className="btn-primary"
                  disabled={loadingRecommendations || selectedIntentIds.length === 0}
                >
                  {loadingRecommendations ? 'Generating Suggestions...' : 'Suggest Pipelines'}
                </button>

                {recommendationOptions.length > 0 && (
                  <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {recommendationOptions.map(option => (
                      <div
                        key={option.id}
                        style={{ padding: '1rem', border: '1px solid #dbeafe', borderRadius: '8px', backgroundColor: 'var(--bg-primary)' }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                          <div>
                            <strong>{option.title}</strong>
                            <p style={{ margin: '0.25rem 0 0 0', color: '#64748b', fontSize: '0.875rem' }}>{option.summary}</p>
                          </div>
                          <button type="button" className="btn-primary" onClick={() => handleApplyRecommendation(option)}>
                            Use This Plan
                          </button>
                        </div>
                        <p style={{ margin: '0 0 0.5rem 0', fontSize: '0.875rem' }}>
                          <strong>Tools:</strong> {option.tool_names.join(', ')}
                        </p>
                        {option.missing_inputs.length > 0 && (
                          <p style={{ margin: '0 0 0.5rem 0', color: '#b45309', fontSize: '0.875rem' }}>
                            <strong>Missing inputs:</strong> {option.missing_inputs.join(', ')}
                          </p>
                        )}
                        {option.assumptions.length > 0 && (
                          <p style={{ margin: '0 0 0.5rem 0', color: '#475569', fontSize: '0.875rem' }}>
                            <strong>Assumptions:</strong> {option.assumptions.join(' ')}
                          </p>
                        )}
                        <p style={{ margin: 0, color: '#475569', fontSize: '0.875rem' }}>
                          <strong>Why this plan:</strong> {option.rationale.join(', ')}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="form-group">
            <label>Workflow Selection *</label>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              <button
                type="button"
                onClick={() => {
                  setSelectionMode('tools')
                  setSelectedPipelineId(null)
                  setSelectedPipelineDetails(null)
                  setPipelineRequirements(null)
                  setPipelineInputMappings({})
                }}
                className={selectionMode === 'tools' ? 'btn-primary' : 'btn-secondary'}
                style={{ padding: '0.5rem 1rem' }}
              >
                Select Tools
              </button>
              <button
                type="button"
                onClick={() => setSelectionMode('pipeline')}
                className={selectionMode === 'pipeline' ? 'btn-primary' : 'btn-secondary'}
                style={{ padding: '0.5rem 1rem' }}
              >
                Use Pipeline
              </button>
            </div>

            {selectionMode === 'pipeline' ? (
              <div>
                {loadingPipelines ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading pipelines...</p>
                ) : pipelines.length === 0 ? (
                  <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '4px', textAlign: 'center' }}>
                    <p style={{ marginBottom: '1rem' }}>No pipelines available. Create one first!</p>
                    <button
                      type="button"
                      onClick={() => navigate('/pipelines/builder')}
                      className="btn-primary"
                    >
                      Create Pipeline
                    </button>
                  </div>
                ) : (
                  <div className="tool-selection-grid">
                    {pipelines.map((pipeline) => (
                      <button
                        type="button"
                        key={pipeline.id}
                        onClick={() => {
                          if (selectedPipelineId !== pipeline.id) {
                            setPipelineInputMappings({})
                            setInputBlockNames({})
                            setPipelineRequirements(null)
                          }
                          setSelectedPipelineDetails(pipeline)
                          setSelectedPipelineId(pipeline.id)
                        }}
                        className={`tool-option ${selectedPipelineId === pipeline.id ? 'selected' : ''}`}
                        style={{ textAlign: 'left' }}
                      >
                        <div className="tool-option-content">
                          <strong>{pipeline.name}</strong>
                          <p>{pipeline.description || 'Saved pipeline ready for execution.'}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <>
                {loadingTools ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading available tools...</p>
                ) : availableTools.length === 0 ? (
                  <p style={{ color: '#f44336' }}>No tools available. Please check your connection.</p>
                ) : (
                  <div className="tool-selection-grid">
                    {availableTools.map((tool) => (
                    <label
                      key={tool.id}
                      className={`tool-option ${selectedTools.includes(tool.id) ? 'selected' : ''} ${!tool.enabled ? 'disabled' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedTools.includes(tool.id)}
                        onChange={() => handleToolToggle(tool.id)}
                        disabled={!tool.enabled || creating}
                      />
                      <div className="tool-option-content">
                        <strong>{tool.name}</strong>
                        <p>{tool.description}</p>
                      </div>
                    </label>
                    ))}
                  </div>
                )}
                <small style={{ display: 'block', marginTop: '8px', color: '#666' }}>
                  Select the tools you want to use in your pipeline. A workflow will be created automatically.
                </small>
              </>
            )}
          </div>

          {/* Pipeline Requirements Section */}
          {selectionMode === 'pipeline' && selectedPipelineId && (
            <div className="form-group">
              <label>Pipeline Summary</label>
              {loadingRequirements || loadingSelectedPipeline ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading pipeline details...</p>
              ) : pipelineRequirements ? (
                <div className="builder-section-card">
                  <p style={{ marginBottom: '0.75rem', color: '#666', fontSize: '0.875rem' }}>
                    This saved pipeline will run with its existing graph. You only need to provide files for the explicit tool blocks in the pipeline.
                  </p>
                  {selectedPipeline && (
                    <div style={{ marginBottom: '1rem' }}>
                      <div style={{ fontWeight: 600, color: '#183B4E', marginBottom: '0.25rem' }}>{selectedPipeline.name}</div>
                      <div style={{ color: '#5b6470', fontSize: '0.875rem' }}>
                        {selectedPipeline.description || 'Saved pipeline ready for execution.'}
                      </div>
                    </div>
                  )}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {pipelineRequirementTools.length > 0 ? pipelineRequirementTools.map(toolId => {
                      const tool = availableTools.find(item => item.tool_id === toolId || item.name.toUpperCase() === toolId)
                      const label = tool?.name || toolId
                      return (
                        <span
                          key={toolId}
                          style={{
                            display: 'inline-flex',
                            padding: '0.4rem 0.75rem',
                            borderRadius: '999px',
                            backgroundColor: '#eff6ff',
                            color: '#1d4ed8',
                            fontSize: '0.875rem',
                            fontWeight: 500,
                          }}
                        >
                          {label}
                        </span>
                      )
                    }) : (
                      <span style={{ color: '#666', fontStyle: 'italic' }}>No supported tools detected in this pipeline.</span>
                    )}
                  </div>
                </div>
              ) : null}
            </div>
            )}
            </>
          )}

          {currentLevel === 3 && (
            <>
          <div className="form-group">
            <label htmlFor="vm">Virtual Machine *</label>
            {loadingVMs ? (
              <p style={{ color: '#666', fontStyle: 'italic' }}>Loading available VMs...</p>
            ) : availableVMs.length === 0 ? (
              <p style={{ color: '#f59e0b' }}>No VMs available. Please contact administrator.</p>
            ) : (
              <select
                id="vm"
                value={selectedVM}
                onChange={(e) => setSelectedVM(e.target.value)}
                required
                disabled={creating}
                style={{ width: '100%', padding: '0.5rem', fontSize: '1rem', borderRadius: '4px', border: '1px solid #d1d5db' }}
              >
                {availableVMs.map((vm) => (
                  <option key={vm.name} value={vm.name}>
                    {vm.display_name} ({formatVmSlots(vm)})
                  </option>
                ))}
              </select>
            )}
            <small style={{ color: '#666', display: 'block', marginTop: '0.25rem' }}>
              Each VM gets an equal share of cluster resources. The selected VM decides how many concurrent pipeline jobs can use that slice.
            </small>
            {selectedVMDetails && (
              <div className="builder-section-card" style={{ marginTop: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#0f172a', marginBottom: '0.35rem' }}>
                  Per-job resource limits for {selectedVMDetails.display_name}
                </div>
                <div style={{ color: '#475569', fontSize: '0.95rem', lineHeight: 1.6 }}>
                  Available slots: {selectedVMDetails.available_job_slots}/{selectedVMDetails.max_jobs}
                  {' | '}
                  Active jobs: {selectedVMDetails.active_jobs ?? selectedVMDetails.running_jobs}/{selectedVMDetails.max_jobs}
                  {' | '}
                  CPU: {formatVmCpu(selectedVMDetails.available_cpu_millis)}
                  {' | '}
                  Memory: {formatVmMemory(selectedVMDetails.available_memory_mib)}
                  {' | '}
                  Storage: {formatVmStorage(selectedVMDetails.available_storage_mib)}
                </div>
                <div style={{ color: '#64748b', fontSize: '0.875rem', marginTop: '0.35rem' }}>
                  Hard limit per job on this VM profile: total resources / number of VMs / max concurrent jobs on this VM.
                </div>
              </div>
            )}
          </div>
            {priorityGroups.length > 0 && (
              <div className="form-group">
                <label>Priority Sets</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <p style={{ margin: 0, color: '#64748b', fontSize: '0.9rem' }}>
                    Choose only the tools you want to prioritize inside each same-level set. Everything else can keep the default scheduler order.
                  </p>
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ alignSelf: 'flex-start' }}
                    onClick={() => setIsPriorityModalOpen(true)}
                  >
                    Configure Priority Sets ({selectedPriorityToolCount})
                  </button>
                </div>
              </div>
            )}
            </>
          )}

            {currentLevel === 2 && (
              <>
            {selectionMode === 'pipeline' && selectedPipelineId && (
              <div className="form-group">
                <label>Pipeline Inputs *</label>
                {loadingRequirements ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading pipeline inputs...</p>
                ) : (
                  <div>
                    <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                      Each explicit tool block in the saved pipeline needs a file assignment here.
                    </p>

                    {loadingDataTree ? (
                      <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                    ) : pipelineInputRequirements.length === 0 ? (
                      <p style={{ color: '#666', fontStyle: 'italic' }}>
                        This pipeline does not expose any external tool blocks.
                      </p>
                    ) : (
                      <>
                      {storageSelectableFiles.length > 0 && (
                        <div className="builder-section-card builder-input-file-context">
                          <p className="builder-card-kicker">Storage Files</p>
                      <div className="builder-file-chip-grid">
                            {storageSelectableFiles.map((file) => renderSelectableFileChip(
                              file,
                              'pipeline-context',
                              selectedLibraryFiles.some((item) => item.id === file.id)
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="builder-requirements-grid">
                      {pipelineInputRequirements.map((inputReq: PipelineRequirement) => {
                        const inputKey = inputReq.id || inputReq.label
                        const mappedFileIds = pipelineInputMappings[inputKey] || []
                        const compatibleFiles = combinedSelectableFiles.filter(file => fileMatchesRequirement(file, inputReq))

                        return (
                          <div key={inputKey} className="builder-requirement-card builder-block-card">
                            <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                              <input
                                type="text"
                                value={inputBlockDisplayName(inputKey, inputReq.label)}
                                onChange={(event) => handleInputBlockNameChange(inputKey, event.target.value)}
                                disabled={creating}
                                style={{ maxWidth: '280px', fontWeight: 600 }}
                                aria-label={`Rename tool block ${inputReq.label}`}
                              />
                              <span style={{ color: '#666', fontSize: '0.875rem' }}>
                                ({inputReq.formats.join(', ').toUpperCase()})
                              </span>
                              {mappedFileIds.length > 0 ? (
                                <span style={{ marginLeft: '0.5rem', color: '#16a34a', fontSize: '0.875rem', fontWeight: '500' }}>
                                  ✓ {mappedFileIds.length} file{mappedFileIds.length !== 1 ? 's' : ''} selected
                                </span>
                              ) : (
                                <span style={{ marginLeft: '0.5rem', color: '#f59e0b', fontSize: '0.875rem', fontWeight: '500' }}>
                                  ⚠ Required
                                </span>
                              )}
                            </div>
                            {inputReq.used_by && inputReq.used_by.length > 0 && (
                              <p style={{ margin: '0 0 0.75rem 0', color: '#6b7280', fontSize: '0.8rem', lineHeight: 1.5 }}>
                                Used by: {inputReq.used_by.join(', ')}
                              </p>
                            )}
                            {compatibleFiles.length === 0 && mappedFileIds.length === 0 ? (
                              <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                                No compatible files found in Storage. Upload files with formats: {inputReq.formats.join(', ').toUpperCase()}
                              </p>
                            ) : compatibleFiles.length > 0 ? (
                              <div className="builder-file-chip-grid">
                                {compatibleFiles.map((file) => {
                                  const isSelected = mappedFileIds.includes(file.id)
                                  return (
                                    <button
                                      key={`pipeline-input-${inputKey}-${file.id}`}
                                      type="button"
                                      onClick={() => handlePipelineInputMapping(inputKey, file.id)}
                                      disabled={creating}
                                      className={`builder-file-chip builder-file-chip-button ${isSelected ? 'selected' : ''}`}
                                      title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                                    >
                                      <strong>{file.filename}</strong>
                                      {file.folderPath && <span>{file.folderPath}</span>}
                                    </button>
                                  )
                                })}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                      </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {selectionMode === 'tools' && (
              <div className="form-group">
                <label>Tool Blocks</label>
                <div className="builder-section-card">
                  <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                    Add or review the files you want available, then assign them to named tool blocks for the selected tools. This follows the same block-based flow used by saved pipelines.
                  </p>

                  {loadingDataTree || loadingToolRequirements ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading tool inputs...</p>
                  ) : (
                    <>
                  {storageSelectableFiles.length > 0 && (
                    <div className="builder-section-card builder-input-file-context">
                      <p className="builder-card-kicker">Storage Files</p>
                      <div className="builder-file-chip-grid">
                        {storageSelectableFiles.map((file) => renderSelectableFileChip(
                          file,
                          'tool-context',
                          selectedLibraryFiles.some((item) => item.id === file.id)
                        ))}
                      </div>
                    </div>
                  )}

                  {combinedSelectableFiles.length === 0 ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>
                      No input files available yet. Upload input files from the Storage page, then return to connect them to the tool blocks here.
                    </p>
                  ) : null}

                  {manualToolInputBlocks.length === 0 ? (
                    <p style={{ color: '#666', fontStyle: 'italic', margin: 0 }}>
                      The selected tools do not need external tool blocks. Any remaining inputs are provided by upstream tools.
                    </p>
                  ) : (
                    <div className="builder-requirements-grid">
                      {manualToolInputBlocks.map((block) => {
                        const toolKey = block.toolReq.tool_index.toString()
                        const attachedFileCount = Array.from(new Set(
                          block.externalRequirements.flatMap((req) => toolFileMappings[toolKey]?.[req.type] || [])
                        )).length
                        const currentFlagValues = {
                          ...getManualToolDefaultFlagValues(block.toolReq),
                          ...(manualToolFlagValues[block.toolReq.tool_id] || {}),
                        }
                        const hasEditableFlags = (block.toolReq.editable_flags || []).length > 0
                        const hasCustomConfig = hasCustomizedFlagValues(block.toolReq.editable_flags || [], currentFlagValues)
                        return (
                          <div key={block.id} className="builder-requirement-card builder-block-card" style={{ position: 'relative' }}>
                            <div className="pipeline-node-menu-wrap">
                              <button
                                type="button"
                                className="pipeline-node-menu-trigger builder-block-menu-trigger"
                                onClick={(event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  setOpenManualToolMenuId((current) => current === block.id ? null : block.id)
                                }}
                                aria-label={`Open settings for ${block.toolReq.tool_name}`}
                                aria-expanded={openManualToolMenuId === block.id}
                              >
                                ⋮
                              </button>
                              {openManualToolMenuId === block.id && (
                                <div className="pipeline-node-menu">
                                  <button
                                    type="button"
                                    onClick={(event) => {
                                      event.preventDefault()
                                      event.stopPropagation()
                                      openManualToolEditModal(block.toolReq)
                                    }}
                                  >
                                    Edit
                                  </button>
                                </div>
                              )}
                            </div>
                            <div style={{ marginBottom: '0.85rem' }}>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', marginBottom: '0.6rem' }}>
                                <label style={{ color: '#64748b', fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                                  Tool block name
                                </label>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                  <input
                                    type="text"
                                    value={inputBlockDisplayName(block.id, getManualInputBlockDefaultName(block))}
                                    onChange={(event) => handleInputBlockNameChange(block.id, event.target.value)}
                                    disabled={creating}
                                    style={{ maxWidth: '320px', fontWeight: 600 }}
                                    aria-label={`Rename ${getManualInputBlockDefaultName(block)} tool block`}
                                  />
                                  {attachedFileCount > 0 ? (
                                    <span style={{ color: '#16a34a', fontSize: '0.875rem', fontWeight: 500 }}>
                                      {attachedFileCount} file(s) attached
                                    </span>
                                  ) : (
                                    <span style={{ color: '#f59e0b', fontSize: '0.875rem', fontWeight: 500 }}>
                                      {block.externalRequirements.length > 0 ? 'Attach required files' : 'Upstream-only block'}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <p style={{ margin: 0, fontSize: '0.875rem', color: '#6b7280' }}>
                                Tool: {block.toolReq.tool_name}
                              </p>
                              <div className={`pipeline-node-config-chip ${hasCustomConfig ? 'custom' : 'default'}`} style={{ marginTop: '0.65rem' }}>
                                {hasEditableFlags
                                  ? (hasCustomConfig ? 'Custom flags' : 'Default flags')
                                  : 'No editable flags'}
                              </div>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                              {block.requirements.map((req) => {
                                const requirementSource = getRequirementSource(block.toolReq, req)
                                const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
                                const compatibleFiles = combinedSelectableFiles.filter((file) => fileMatchesRequirement(file, req))

                                return (
                                  <div key={`${block.id}-${req.type}`} style={{ paddingTop: '0.25rem', borderTop: '1px solid #ece5d2' }}>
                                    <div style={{ marginBottom: '0.65rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                      <strong>{req.label}</strong>
                                      <span style={{ color: '#666', fontSize: '0.875rem' }}>
                                        ({req.formats.join(', ').toUpperCase()})
                                      </span>
                                      {(req.available_sources || []).length > 1 ? (
                                        <div style={{ display: 'inline-flex', gap: '0.4rem', marginLeft: '0.25rem' }}>
                                          <button
                                            type="button"
                                            className={requirementSource === 'upstream' ? 'btn-primary' : 'btn-secondary'}
                                            style={{ padding: '0.25rem 0.55rem', fontSize: '0.75rem' }}
                                            onClick={() => handleRequirementSourceChange(block.toolReq, req, 'upstream')}
                                          >
                                            Use {req.source_tool || 'upstream output'}
                                          </button>
                                          <button
                                            type="button"
                                            className={requirementSource === 'external' ? 'btn-primary' : 'btn-secondary'}
                                            style={{ padding: '0.25rem 0.55rem', fontSize: '0.75rem' }}
                                            onClick={() => handleRequirementSourceChange(block.toolReq, req, 'external')}
                                          >
                                            Use tool block
                                          </button>
                                        </div>
                                      ) : null}
                                      {requirementSource === 'upstream' ? (
                                        <span style={{
                                          padding: '0.25rem 0.5rem',
                                          backgroundColor: '#dbeafe',
                                          color: '#1e40af',
                                          fontSize: '0.75rem',
                                          borderRadius: '4px',
                                          fontWeight: '500'
                                        }}>
                                          Intermediate from {req.source_tool}
                                        </span>
                                      ) : mappedFileIds.length > 0 ? (
                                        <span style={{ color: '#16a34a', fontSize: '0.875rem', fontWeight: 500 }}>
                                          {mappedFileIds.length} file(s) selected
                                        </span>
                                      ) : (
                                        <span style={{ color: '#f59e0b', fontSize: '0.875rem', fontWeight: 500 }}>
                                          Required
                                        </span>
                                      )}
                                    </div>

                                    {req.validation_message ? (
                                      <p style={{ margin: '0 0 0.65rem 0', color: '#6b7280', fontSize: '0.8rem', lineHeight: 1.5 }}>
                                        {req.validation_message}
                                        {req.filename_example ? ` Example: ${req.filename_example}` : ''}
                                      </p>
                                    ) : null}

                                    {requirementSource === 'upstream' ? (
                                      <p style={{ color: '#6b7280', fontStyle: 'italic', fontSize: '0.875rem', padding: '0.5rem', backgroundColor: '#eff6ff', borderRadius: '4px', margin: 0 }}>
                                        This requirement is currently provided by {req.source_tool}. The tool still keeps this tool block visible so you can review all inputs in one place.
                                      </p>
                                    ) : compatibleFiles.length === 0 && mappedFileIds.length === 0 ? (
                                      <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem', margin: 0 }}>
                                        No compatible files found in Storage. Upload files with formats: {req.formats.join(', ').toUpperCase()}
                                        {req.filename_example ? ` and names like ${req.filename_example}` : ''}
                                      </p>
                                    ) : compatibleFiles.length > 0 ? (
                                      <div className="builder-file-chip-grid">
                                        {compatibleFiles.map((file) => {
                                          const isSelected = mappedFileIds.includes(file.id)
                                          return (
                                            <button
                                              key={`${block.id}-${req.type}-${file.id}`}
                                              type="button"
                                              onClick={() => handleToolFileMapping(block.toolReq.tool_index, req.type, file.id)}
                                              disabled={creating}
                                              className={`builder-file-chip builder-file-chip-button ${isSelected ? 'selected' : ''}`}
                                              title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                                            >
                                              <strong>{file.filename}</strong>
                                              {file.folderPath && <span>{file.folderPath}</span>}
                                            </button>
                                          )
                                        })}
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                    </>
                  )}
                </div>
              </div>
            )}
              </>
            )}

          {currentLevel === 4 && (
            <div className="form-group">
              <label>Submit Job</label>
              <div className="builder-submit-layout">
                <div className="builder-review-grid">
                  <div className="builder-review-card">
                    <h3>Submission Summary</h3>
                    <p><strong>Job:</strong> {jobName || 'Untitled job'}</p>
                    <p><strong>Mode:</strong> {selectionMode === 'pipeline' ? 'Saved pipeline' : 'Manual tool selection'}</p>
                    <p><strong>Workflow:</strong> {selectionMode === 'pipeline' ? (selectedPipeline?.name || 'No pipeline selected') : (selectedToolDefinitions.map((tool) => tool.name).join(', ') || 'No tools selected')}</p>
                    <p><strong>Mapped inputs:</strong> {totalMappedInputCount}</p>
                    <p><strong>VM:</strong> {selectedVMDetails?.display_name || selectedVM || 'Not selected'}</p>
                  </div>
                </div>

                {livePipelineBox}

                <div className="detail-section" style={{ margin: 0 }}>
                  <h2>Pipeline Visualization</h2>
                  {loadingReviewPipelinePreview && (
                    <p style={{ margin: '0 0 0.75rem', color: '#64748b', fontSize: '0.9rem' }}>
                      Building backend execution preview...
                    </p>
                  )}
                  {reviewPipelinePreviewError && (
                    <p style={{ margin: '0 0 0.75rem', color: '#7c4036', fontSize: '0.9rem' }}>
                      {reviewPipelinePreviewError}
                    </p>
                  )}
                  <PipelineVisualization
                    pipeline={effectiveReviewPipelinePreview}
                    emptyMessage="Select tools or a saved pipeline to preview the full execution flow here."
                    description="This locked preview shows the pipeline that will be submitted from the review page."
                    height="min(68vh, 680px)"
                    minHeight={400}
                  />
                </div>

                {shouldShowRuntimeEstimateCard && (
                  <div className="runtime-estimate-card runtime-estimate-submit">
                    <div className="runtime-estimate-header">
                      <strong>Predicted Job Estimate</strong>
                      <span>Ready for submission</span>
                    </div>
                    {loadingRuntimeEstimate ? (
                      <p className="runtime-estimate-copy">Calculating runtime for the current selection...</p>
                    ) : runtimeEstimate ? (
                      <>
                        <div className="runtime-estimate-summary-grid">
                          <div className="runtime-estimate-panel">
                            <span className="runtime-estimate-label">Estimated Runtime</span>
                            <span className="runtime-estimate-value">{formatRuntimeEstimate(runtimeEstimate.estimated_runtime_minutes)}</span>
                            <span className="runtime-estimate-subtle">
                              about {runtimeEstimate.estimated_runtime_hours.toFixed(2)} hours on {runtimeEstimate.vm_display_name}
                            </span>
                          </div>
                          <div className="runtime-estimate-panel">
                            <span className="runtime-estimate-label">Estimated Price</span>
                            <span className="runtime-estimate-value">{formatUsd(runtimeEstimate.estimated_price_usd)}</span>
                            <span className="runtime-estimate-subtle">
                              {formatUsd(runtimeEstimate.vm_price_per_minute)} per minute on {runtimeEstimate.vm_display_name}
                            </span>
                          </div>
                          <div className="runtime-estimate-panel">
                            <span className="runtime-estimate-label">Required Balance Hold</span>
                            <span className="runtime-estimate-value">{formatUsd(runtimeEstimate.estimated_price_usd * 1.5)}</span>
                            <span className="runtime-estimate-subtle">
                              Final charge is actual runtime cost, capped at this hold.
                            </span>
                          </div>
                        </div>
                        <p className="runtime-estimate-copy">
                          Model: {runtimeEstimate.execution_shape}. Partition factor: {runtimeEstimate.partition_factor.toFixed(2)}x. Input size: {runtimeEstimate.total_input_size_mib.toFixed(2)} MiB.
                        </p>
                        <div className="runtime-estimate-breakdown">
                          {runtimeEstimate.tool_breakdown.map((tool) => (
                            <span key={`${tool.tool_id}-${tool.tool_name}`} className="runtime-estimate-chip">
                              {tool.tool_name}: {Math.round(tool.adjusted_minutes)}m, {tool.input_size_mib.toFixed(1)} MiB
                            </span>
                          ))}
                        </div>
                        {runtimeEstimate.assumptions.length > 0 && (
                          <p className="runtime-estimate-copy">{runtimeEstimate.assumptions[0]}</p>
                        )}
                      </>
                    ) : (
                      <p className="runtime-estimate-error">{runtimeEstimateError}</p>
                    )}
                  </div>
                )}

                {selectionMode === 'pipeline' && pipelineInputRequirements.length > 0 && (
                  <div className="builder-review-card" style={{ marginTop: '1rem' }}>
                    <h3>Input Blocks</h3>
                    <div className="builder-input-summary-list">
                      {pipelineInputRequirements.map((inputReq) => {
                        const inputKey = inputReq.id || inputReq.label
                        const mappedFileIds = pipelineInputMappings[inputKey] || []
                        return (
                          <div key={`review-${inputKey}`} className="builder-input-summary-row">
                            <strong>{inputBlockDisplayName(inputKey, inputReq.label)}</strong>
                            <span>{mappedFileIds.length} file(s) selected</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {selectionMode === 'tools' && manualToolInputBlocks.length > 0 && (
                  <div className="builder-review-card" style={{ marginTop: '1rem' }}>
                    <h3>Tool Blocks</h3>
                    <div className="builder-input-summary-list">
                      {manualToolInputBlocks.map((block) => {
                        const toolKey = block.toolReq.tool_index.toString()
                        const mappedFileCount = Array.from(new Set(
                          block.externalRequirements.flatMap((req) => toolFileMappings[toolKey]?.[req.type] || [])
                        )).length
                        const currentFlagValues = {
                          ...getManualToolDefaultFlagValues(block.toolReq),
                          ...(manualToolFlagValues[block.toolReq.tool_id] || {}),
                        }
                        const hasCustomConfig = hasCustomizedFlagValues(block.toolReq.editable_flags || [], currentFlagValues)
                        return (
                          <div key={`review-${block.id}`} className="builder-input-summary-row">
                            <strong>{inputBlockDisplayName(block.id, getManualInputBlockDefaultName(block))}</strong>
                            <span>
                              {mappedFileCount} file(s) | {block.requirements.length} requirement(s) for {block.toolReq.tool_name} | {hasCustomConfig ? 'custom flags' : 'default flags'}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                <label className="legal-consent-row job-consent-row">
                  <input
                    type="checkbox"
                    checked={executionDataImprovementConsent}
                    onChange={(event) => setExecutionDataImprovementConsent(event.target.checked)}
                    disabled={creating}
                    required
                  />
                  <span>
                    I accept the <Link to="/terms">Terms</Link> and <Link to="/kvkk">KVKK notice</Link>, and agree that CASSIE may use this job's execution metadata, tool settings, runtime metrics, logs, and non-identifying outputs to improve its products.
                  </span>
                </label>
              </div>
            </div>
          )}
          </div>

          {editingManualTool && renderPageModal(
            <div className="modal-overlay" onClick={closeManualToolEditModal}>
              <div className="modal-content pipeline-flag-modal" onClick={(event) => event.stopPropagation()}>
                <div className="modal-header">
                  <h2>{editingManualTool.tool_name} Settings</h2>
                  <button type="button" className="modal-close" onClick={closeManualToolEditModal}>
                    ×
                  </button>
                </div>
                <div className="modal-body">
                  {(editingManualTool.editable_flags || []).length > 0 ? (
                    <div className="pipeline-flag-form">
                      {editingManualTool.editable_flags?.map((flag) => {
                        const placeholder = [flag.placeholder, flag.example ? `Example: ${flag.example}` : '']
                          .filter(Boolean)
                          .join(' ')
                        const currentValue = editingManualToolDraftValues[flag.key]

                        return (
                          <div key={flag.key} className="form-group pipeline-flag-field">
                            <label htmlFor={`job-flag-${flag.key}`}>{flag.label}</label>
                            {flag.type === 'boolean' ? (
                              <label className="pipeline-flag-checkbox">
                                <input
                                  id={`job-flag-${flag.key}`}
                                  type="checkbox"
                                  checked={Boolean(currentValue)}
                                  onChange={(event) => handleManualToolFlagChange(flag, event.target.checked)}
                                />
                                <span>{flag.description || 'Enable this option for the tool block.'}</span>
                              </label>
                            ) : flag.type === 'select' ? (
                              <select
                                id={`job-flag-${flag.key}`}
                                value={String(currentValue ?? flag.default ?? '')}
                                className="form-input"
                                onChange={(event) => handleManualToolFlagChange(flag, event.target.value)}
                              >
                                {(flag.options || []).map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <input
                                id={`job-flag-${flag.key}`}
                                type="text"
                                className="form-input"
                                value={String(currentValue ?? '')}
                                placeholder={placeholder}
                                onChange={(event) => handleManualToolFlagChange(flag, event.target.value)}
                              />
                            )}
                            {flag.type !== 'boolean' && flag.description && (
                              <p className="pipeline-flag-help">{flag.description}</p>
                            )}
                            {editingManualToolErrors[flag.key] && (
                              <p className="pipeline-flag-error">{editingManualToolErrors[flag.key]}</p>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="pipeline-flag-empty-state">
                      This tool currently runs with its default settings in CASSIE and has no user-editable flags here.
                    </p>
                  )}
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn-secondary" onClick={closeManualToolEditModal}>
                    Cancel
                  </button>
                  <button type="button" className="btn-primary" onClick={saveManualToolConfiguration}>
                    Save settings
                  </button>
                </div>
              </div>
            </div>
          )}

          {isPriorityModalOpen && (
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
                    Check only the tools you want CASSIE to prioritize inside each level. Once those selected tools finish,
                    the rest of the same level can continue with the default scheduler order.
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
                                        onChange={() => handlePriorityItemToggle(group, item.id)}
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

          <div className="form-actions">
            <button
              type="button"
              onClick={handleCancelCreateJob}
              className="btn-secondary"
              disabled={creating}
            >
              Cancel
            </button>
            {currentLevel > 1 && (
              <button
                type="button"
                onClick={goToPreviousLevel}
                className="btn-secondary"
                disabled={creating}
              >
                Back
              </button>
            )}
            {currentLevel < 4 ? (
              <button
                key={`builder-next-${currentLevel}`}
                type="button"
                className="btn-primary"
                disabled={
                  creating ||
                  (currentLevel === 1 && !canAdvanceFromLevelOne) ||
                  (currentLevel === 2 && !canAdvanceFromLevelTwo) ||
                  (currentLevel === 3 && !canAdvanceFromLevelThree)
                }
                onClick={(event) => {
                  event.preventDefault()
                  goToNextLevel()
                }}
              >
                {currentLevel === 3 ? 'Review Job' : 'Continue'}
              </button>
            ) : (
              <button
                key="builder-submit"
                type="submit"
                className="btn-primary"
                disabled={creating || !executionDataImprovementConsent}
              >
                {creating ? (submitStatus || 'Submitting job...') : 'Submit Job'}
              </button>
            )}
          </div>
        </form>
        </div>
      </div>
      <CatCornerCard
        config={getCreateJobCatConfig(currentLevel)}
        className="cat-corner-card--job-builder"
      />
    </div>
  )
}
