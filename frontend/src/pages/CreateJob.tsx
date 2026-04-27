import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  createJob,
  executeJob,
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
import {
  PendingGoogleDriveJobImportFile,
  PendingJobUploadFile,
} from '../services/pendingJobUploadService'
import { deleteFile, importGoogleDriveFileToJob, uploadFile } from '../services/fileService'
import Navigation from '../components/Navigation'
import PipelineVisualization from '../components/PipelineVisualization'
import {
  buildManualExecutionPreferences,
  buildPipelineExecutionPreferences,
  computeManualPriorityGroups,
  computePipelinePriorityGroups,
  PriorityGroup,
} from '../utils/pipelinePriority'
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

type BuilderLevel = 1 | 2 | 3 | 4 | 5
type SlideDirection = 'forward' | 'backward'

interface BuilderLevelDefinition {
  level: BuilderLevel
  title: string
  description: string
}

interface ManualToolInputBlock {
  id: string
  toolReq: ToolRequirementInfo
  requirements: ToolRequirement[]
  externalRequirements: ToolRequirement[]
  upstreamRequirements: ToolRequirement[]
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
const CREATE_JOB_DRAFT_STORAGE_KEY = 'cassie:create-job-draft:v2'
const GOOGLE_DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
const GOOGLE_API_SCRIPT_ID = 'cassie-google-api-script'
const GOOGLE_GSI_SCRIPT_ID = 'cassie-google-gsi-script'

const loadExternalScript = (id: string, src: string): Promise<void> => {
  if (typeof document === 'undefined') {
    return Promise.reject(new Error('Browser document is unavailable'))
  }

  const existing = document.getElementById(id) as HTMLScriptElement | null
  if (existing) {
    if (existing.dataset.loaded === 'true') {
      return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)), { once: true })
    })
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.id = id
    script.src = src
    script.async = true
    script.defer = true
    script.onload = () => {
      script.dataset.loaded = 'true'
      resolve()
    }
    script.onerror = () => reject(new Error(`Failed to load ${src}`))
    document.head.appendChild(script)
  })
}

const loadGoogleDriveScripts = async () => {
  await Promise.all([
    loadExternalScript(GOOGLE_API_SCRIPT_ID, 'https://apis.google.com/js/api.js'),
    loadExternalScript(GOOGLE_GSI_SCRIPT_ID, 'https://accounts.google.com/gsi/client'),
  ])
}

const loadGooglePicker = (): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (!window.gapi) {
      reject(new Error('Google API script is not available'))
      return
    }
    window.gapi.load('picker', {
      callback: () => resolve(),
      onerror: () => reject(new Error('Failed to load Google Picker')),
      timeout: 10000,
      ontimeout: () => reject(new Error('Timed out loading Google Picker')),
    })
  })
}

const deriveGoogleDriveAppId = (clientId: string): string => (
  import.meta.env.VITE_GOOGLE_DRIVE_APP_ID ||
  clientId.split('-')[0] ||
  ''
)

interface CreateJobDraft {
  version: 2
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
  recommendationFileIds: number[]
  priorityGroups: PriorityGroup[]
  openPriorityGroups: number[]
  currentLevel: BuilderLevel
  inputBlockNames: Record<string, string>
  selectedVM: string
  reviewPipelinePreview: JobPipelineVisualization | null
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
    if (!parsed || parsed.version !== 2) {
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

export default function CreateJob() {
  const location = useLocation()
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
  const [pendingLocalFiles, setPendingLocalFiles] = useState<PendingJobUploadFile[]>([])
  const [pendingGoogleDriveFiles, setPendingGoogleDriveFiles] = useState<PendingGoogleDriveJobImportFile[]>([])
  const uploadAbortControllersRef = useRef<Map<number, AbortController>>(new Map())
  const uploadProgressTimersRef = useRef<Map<number, number>>(new Map())
  const pendingLocalFilesRef = useRef<PendingJobUploadFile[]>([])
  const pendingGoogleDriveFilesRef = useRef<PendingGoogleDriveJobImportFile[]>([])
  const [importingGoogleDriveFile, setImportingGoogleDriveFile] = useState(false)
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
  const [recommendationIntents, setRecommendationIntents] = useState<RecommendationIntent[]>([])
  const [selectedIntentIds, setSelectedIntentIds] = useState<string[]>(() => storedDraftRef.current?.selectedIntentIds || [])
  const [recommendationFileIds, setRecommendationFileIds] = useState<number[]>(() => storedDraftRef.current?.recommendationFileIds || [])
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationOption[]>([])
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [appliedRecommendationFileIds, setAppliedRecommendationFileIds] = useState<number[] | null>(null)
  const [priorityGroups, setPriorityGroups] = useState<PriorityGroup[]>(() => storedDraftRef.current?.priorityGroups || [])
  const [openPriorityGroups, setOpenPriorityGroups] = useState<number[]>(() => storedDraftRef.current?.openPriorityGroups?.length ? storedDraftRef.current.openPriorityGroups : [0])
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false)
  const [currentLevel, setCurrentLevel] = useState<BuilderLevel>(() => storedDraftRef.current?.currentLevel || 1)
  const [slideDirection, setSlideDirection] = useState<SlideDirection>('forward')
  const [inputBlockNames, setInputBlockNames] = useState<Record<string, string>>(() => storedDraftRef.current?.inputBlockNames || {})
  const [persistedReviewPipelinePreview, setPersistedReviewPipelinePreview] = useState<JobPipelineVisualization | null>(() => storedDraftRef.current?.reviewPipelinePreview || null)
  const [backendReviewPipelinePreview, setBackendReviewPipelinePreview] = useState<JobPipelineVisualization | null>(null)
  const [loadingReviewPipelinePreview, setLoadingReviewPipelinePreview] = useState(false)
  const [reviewPipelinePreviewError, setReviewPipelinePreviewError] = useState('')
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
  const selectedPipeline = selectedPipelineDetails || selectedPipelineSummary
  const selectedPipelineNodes = useMemo(
    () => selectedPipeline ? normalizePipelineNodeList(selectedPipeline.nodes) : [],
    [selectedPipeline]
  )
  const selectedPipelineEdges = useMemo(
    () => selectedPipeline ? normalizePipelineEdgeList(selectedPipeline.edges) : [],
    [selectedPipeline]
  )

  useEffect(() => {
    shouldPersistDraftRef.current = true
  }, [])

  useEffect(() => {
    pendingLocalFilesRef.current = pendingLocalFiles
  }, [pendingLocalFiles])

  useEffect(() => {
    pendingGoogleDriveFilesRef.current = pendingGoogleDriveFiles
  }, [pendingGoogleDriveFiles])

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
      cancelSelectedUploads({ clearState: false })
      clearCreateJobDraft()
    }
  ), [])

  // Check if pipeline_id was passed via navigation state
  useEffect(() => {
    const state = location.state as { pipelineId?: number } | null
    if (state?.pipelineId) {
      setSelectionMode('pipeline')
      setSelectedPipelineId(state.pipelineId)
    }
  }, [location])

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

    void runEstimate()

    return () => {
      cancelled = true
    }
  }, [selectedVM, selectionMode, selectedPipelineId, selectedTools, toolFileMappings, pendingLocalFiles, pendingGoogleDriveFiles, dataFileTree])

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

  const activeToolRequirementCards = toolRequirements
  const pipelineInputRequirements = useMemo(
    () => pipelineRequirements?.input_requirements || [],
    [pipelineRequirements]
  )
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
    if (selectionMode !== 'tools' || !appliedRecommendationFileIds || toolRequirements.length === 0) {
      return
    }

    const candidateFiles = getCombinedSelectableFiles().filter(file => appliedRecommendationFileIds.includes(file.id))
    const suggestedMappings: Record<string, Record<string, number[]>> = {}

    toolRequirements.forEach(toolReq => {
      const toolKey = toolReq.tool_index.toString()
      const requirementMappings: Record<string, number[]> = {}

      toolReq.requirements.forEach(req => {
        if (req.is_intermediate) return
        const compatibleIds = getCompatibleCandidateFileIds(req, candidateFiles)
        if (compatibleIds.length > 0) {
          requirementMappings[req.type] = compatibleIds
        }
      })

      if (Object.keys(requirementMappings).length > 0) {
        suggestedMappings[toolKey] = requirementMappings
      }
    })

    setToolFileMappings(suggestedMappings)
    setAppliedRecommendationFileIds(null)
  }, [selectionMode, appliedRecommendationFileIds, toolRequirements, pendingLocalFiles, pendingGoogleDriveFiles, dataFileTree])

  useEffect(() => {
    if (selectionMode !== 'tools') {
      setRequirementSourceSelections({})
      return
    }

    const nextSelections: Record<string, 'external' | 'upstream'> = {}
    toolRequirements.forEach((toolReq) => {
      toolReq.requirements.forEach((req) => {
        const key = req.requirement_id || `${toolReq.tool_index}:${req.type}`
        nextSelections[key] = req.default_source || (req.is_intermediate ? 'upstream' : 'external')
      })
    })
    setRequirementSourceSelections(nextSelections)
  }, [selectionMode, toolRequirements])

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
        requirements: toolReq.requirements,
        externalRequirements,
        upstreamRequirements,
      }
    }),
    [activeToolRequirementCards, getRequirementSource]
  )

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
    setAppliedRecommendationFileIds([...recommendationFileIds])
  }

  // Helper function to flatten file tree into a list of files with folder paths
  const flattenFiles = (tree: FolderTreeItem[]): Array<FileItem & { folderPath?: string }> => {
    if (!tree || tree.length === 0) {
      return []
    }
    
    const files: Array<FileItem & { folderPath?: string }> = []
    const traverse = (folders: FolderTreeItem[], parentPath: string = '') => {
      if (!folders || folders.length === 0) return
      
      folders.forEach(folder => {
        if (!folder) return
        
        const currentPath = parentPath ? `${parentPath}/${folder.name}` : (folder.name || '')
        
        // Add files from this folder
        if (folder.files && Array.isArray(folder.files)) {
          folder.files.forEach(file => {
            if (file && file.id) {
              files.push({ ...file, folderPath: currentPath || undefined })
            }
          })
        }
        
        // Recursively traverse children
        if (folder.children && Array.isArray(folder.children) && folder.children.length > 0) {
          traverse(folder.children, currentPath)
        }
      })
    }
    traverse(tree)
    return files
  }

  const inferFileFormat = (filename: string): string | null => {
    const lower = filename.toLowerCase()
    if (lower.endsWith('.fastq') || lower.endsWith('.fastq.gz') || lower.endsWith('.fq') || lower.endsWith('.fq.gz')) return 'fastq'
    if (lower.endsWith('.fasta') || lower.endsWith('.fasta.gz') || lower.endsWith('.fa') || lower.endsWith('.fa.gz') || lower.endsWith('.fna') || lower.endsWith('.fna.gz')) return 'fasta'
    if (lower.endsWith('.gff3')) return 'gff3'
    if (lower.endsWith('.gff')) return 'gff'
    if (lower.endsWith('.gtf')) return 'gtf'
    if (lower.endsWith('.hal')) return 'hal'
    if (lower.endsWith('.gfa')) return 'gfa'
    if (lower.endsWith('.meryl') || lower.endsWith('.meryl.tar') || lower.endsWith('.meryl.tar.gz') || lower.endsWith('.meryl.tgz')) return 'meryl'
    if (lower.endsWith('.cfg')) return 'cfg'
    if (lower.endsWith('.conf')) return 'conf'
    if (lower.endsWith('.ini')) return 'ini'
    if (lower.endsWith('.json')) return 'json'
    if (lower.endsWith('.tsv')) return 'tsv'
    if (lower.endsWith('.csv')) return 'csv'
    if (lower.endsWith('.txt')) return 'txt'
    if (lower.endsWith('.html')) return 'html'
    return null
  }

  const normalizeFileFormats = (file: FileItem & { folderPath?: string }): string[] => {
    const filename = (file.filename || '').toLowerCase()
    const formats = new Set<string>()
    const declared = (file.file_format || '').toLowerCase().replace(/^\./, '')
    if (declared) formats.add(declared)

    if (filename.endsWith('.fastq') || filename.endsWith('.fastq.gz') || filename.endsWith('.fq') || filename.endsWith('.fq.gz')) formats.add('fastq')
    if (filename.endsWith('.fasta') || filename.endsWith('.fasta.gz') || filename.endsWith('.fa') || filename.endsWith('.fa.gz') || filename.endsWith('.fna') || filename.endsWith('.fna.gz')) formats.add('fasta')
    if (filename.endsWith('.gff3')) {
      formats.add('gff')
      formats.add('gff3')
    }
    if (filename.endsWith('.gff')) formats.add('gff')
    if (filename.endsWith('.gtf')) formats.add('gtf')
    if (filename.endsWith('.hal')) formats.add('hal')
    if (filename.endsWith('.gfa')) formats.add('gfa')
    if (filename.endsWith('.meryl') || filename.endsWith('.meryl.tar') || filename.endsWith('.meryl.tar.gz') || filename.endsWith('.meryl.tgz')) formats.add('meryl')
    if (filename.endsWith('.cfg')) formats.add('cfg')
    if (filename.endsWith('.conf')) formats.add('conf')
    if (filename.endsWith('.ini')) formats.add('ini')
    if (filename.endsWith('.json')) formats.add('json')
    if (filename.endsWith('.txt')) formats.add('txt')
    if (filename.endsWith('.tsv')) formats.add('tsv')
    if (filename.endsWith('.csv')) formats.add('csv')
    if (filename.endsWith('.tar') || filename.endsWith('.tar.gz')) formats.add('tar')
    if (filename.endsWith('.tgz')) formats.add('tgz')

    return Array.from(formats)
  }

  const fileMatchesRequirement = (
    file: FileItem & { folderPath?: string },
    requirement: { formats: string[]; filename_pattern?: string }
  ): boolean => {
    const normalizedFormats = new Set(normalizeFileFormats(file))
    const formatMatches = requirement.formats.some(format => normalizedFormats.has(format.toLowerCase()))
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
    const libraryFiles = flattenFiles(dataFileTree)
    const pendingFilesAsItems: Array<FileItem & { folderPath?: string }> = pendingLocalFiles.map(file => ({
      id: file.tempId,
      filename: file.filename,
      s3_key: `pending://${file.tempId}/${file.filename}`,
      file_type: 'input',
      file_format: file.file_format,
      size_bytes: file.size_bytes,
      checksum: '',
      uploaded_at: null,
      created_at: file.created_at,
      folderPath: 'Selected Files',
    }))
    const pendingGoogleDriveFilesAsItems: Array<FileItem & { folderPath?: string }> = pendingGoogleDriveFiles.map(file => ({
      id: file.tempId,
      filename: file.filename,
      s3_key: `gdrive://${file.googleFileId}/${file.filename}`,
      file_type: 'input',
      file_format: file.file_format,
      size_bytes: file.size_bytes,
      checksum: '',
      uploaded_at: null,
      created_at: file.created_at,
      folderPath: 'Selected Google Drive Files',
    }))

    return [...pendingGoogleDriveFilesAsItems, ...pendingFilesAsItems, ...libraryFiles]
  }

  const getRuntimeInputAssignments = (): RuntimeInputAssignment[] => {
    if (selectionMode === 'pipeline') {
      return []
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

        if (totalInputSizeMib > 0) {
          assignments.push({
            tool_id: toolReq.tool_id,
            requirement_type: req.type,
            total_input_size_mib: Number(totalInputSizeMib.toFixed(2)),
          })
        }
      })
    })

    return assignments
  }

  const getCompatibleCandidateFileIds = (
    requirement: { type: string; formats: string[] },
    candidateFiles: Array<FileItem & { folderPath?: string }>
  ): number[] => {
    const compatibleFiles = candidateFiles.filter(file => fileMatchesRequirement(file, requirement))

    if (requirement.type === 'forward_reads') {
      return compatibleFiles.slice(0, 1).map(file => file.id)
    }
    if (requirement.type === 'reverse_reads') {
      return compatibleFiles.slice(1, 2).map(file => file.id)
    }
    if (requirement.type === 'assembly') {
      return compatibleFiles.slice(0, 1).map(file => file.id)
    }
    if (requirement.type === 'reference') {
      const alternate = compatibleFiles.slice(1, 2).map(file => file.id)
      return alternate.length > 0 ? alternate : compatibleFiles.slice(0, 1).map(file => file.id)
    }
    return compatibleFiles.map(file => file.id)
  }

  const isCanceledUploadError = (err: any): boolean => (
    err?.code === 'ERR_CANCELED' ||
    err?.name === 'CanceledError' ||
    String(err?.message || '').toLowerCase().includes('canceled')
  )

  const stopUploadProgressTimer = (tempId: number) => {
    const timerId = uploadProgressTimersRef.current.get(tempId)
    if (timerId !== undefined) {
      window.clearInterval(timerId)
      uploadProgressTimersRef.current.delete(tempId)
    }
  }

  const startUploadProgressTimer = (
    tempId: number,
    updateProgress: (updater: (progress: number) => number) => void
  ) => {
    stopUploadProgressTimer(tempId)
    updateProgress(progress => Math.max(progress, 1))
    const timerId = window.setInterval(() => {
      updateProgress(progress => {
        if (progress >= 95) {
          return progress
        }
        if (progress < 30) {
          return progress + 3
        }
        if (progress < 70) {
          return progress + 2
        }
        return progress + 1
      })
    }, 700)
    uploadProgressTimersRef.current.set(tempId, timerId)
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || [])
    if (selectedFiles.length === 0) return

    try {
      setError('')
      const existingKeys = new Set(pendingLocalFilesRef.current.map(file => `${file.file.name}:${file.size_bytes}:${file.file.lastModified}`))
      const uploadCandidates = selectedFiles
        .filter(file => !existingKeys.has(`${file.name}:${file.size}:${file.lastModified}`))
        .map((file, index) => ({
          tempId: -(Date.now() + index + Math.floor(Math.random() * 1000)),
          file,
          filename: file.name,
          original_filename: file.name,
          size_bytes: file.size,
          file_format: inferFileFormat(file.name),
          uploaded_at: null,
          created_at: new Date().toISOString(),
          folderPath: 'Selected Files',
          upload_status: 'uploading' as const,
          upload_progress: 1,
        }))

      if (uploadCandidates.length === 0) {
        e.target.value = ''
        return
      }

      setPendingLocalFiles(prev => [...uploadCandidates, ...prev])
      e.target.value = '' // Reset input

      uploadCandidates.forEach((pendingFile) => {
        void (async () => {
          const abortController = new AbortController()
          uploadAbortControllersRef.current.set(pendingFile.tempId, abortController)
          const updateProgress = (updater: (progress: number) => number) => {
            setPendingLocalFiles(prev => prev.map(file => (
              file.tempId === pendingFile.tempId
                ? { ...file, upload_status: 'uploading', upload_progress: Math.min(99, updater(file.upload_progress || 0)) }
                : file
            )))
          }
          startUploadProgressTimer(pendingFile.tempId, updateProgress)
          try {
            const uploadedFile = await uploadFile(
              pendingFile.file,
              null,
              'input',
              pendingFile.file_format || undefined,
              (progress) => {
                updateProgress(current => Math.max(current, progress))
              },
              undefined,
              abortController.signal
            )

            stopUploadProgressTimer(pendingFile.tempId)
            setPendingLocalFiles(prev => prev.map(file => (
              file.tempId === pendingFile.tempId
                ? {
                    ...file,
                    staged_file_id: uploadedFile.id,
                    upload_status: 'uploaded',
                    upload_progress: 100,
                    uploaded_at: null,
                    size_bytes: uploadedFile.size_bytes,
                    file_format: uploadedFile.file_format || file.file_format,
                  }
                : file
            )))
          } catch (err: any) {
            stopUploadProgressTimer(pendingFile.tempId)
            if (isCanceledUploadError(err)) {
              return
            }
            setPendingLocalFiles(prev => prev.map(file => (
              file.tempId === pendingFile.tempId
                ? {
                    ...file,
                    upload_status: 'failed',
                    upload_error: err?.message || 'Failed to upload file',
                  }
                : file
            )))
          } finally {
            stopUploadProgressTimer(pendingFile.tempId)
            uploadAbortControllersRef.current.delete(pendingFile.tempId)
          }
        })()
      })
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Failed to select file')
    }
  }

  const addPickedGoogleDriveFiles = (
    accessToken: string,
    docs: Array<{ id: string; name?: string; mimeType?: string; sizeBytes?: string | number; size?: string | number }>
  ) => {
    const selectedAt = Date.now()
    const existingIds = new Set(pendingGoogleDriveFilesRef.current.map(file => file.googleFileId))
    const importCandidates = docs
      .filter(doc => doc.id && !existingIds.has(doc.id))
      .map((doc, index) => {
        const filename = sanitizeSelectedFilename(doc.name || `google-drive-${doc.id}`)
        const rawSize = doc.sizeBytes ?? doc.size
        const parsedSize = rawSize !== undefined && rawSize !== null ? Number(rawSize) : 0

        return {
          tempId: -(selectedAt + index + Math.floor(Math.random() * 1000)),
          googleFileId: doc.id,
          accessToken,
          filename,
          original_filename: doc.name || filename,
          size_bytes: Number.isFinite(parsedSize) && parsedSize > 0 ? parsedSize : null,
          file_format: inferFileFormat(filename),
          mime_type: doc.mimeType,
          created_at: new Date().toISOString(),
          folderPath: 'Selected Google Drive Files',
          upload_status: 'uploading' as const,
          upload_progress: 1,
        }
      })

    if (importCandidates.length === 0) {
      return
    }

    setPendingGoogleDriveFiles(prev => [...importCandidates, ...prev])

    importCandidates.forEach((pendingFile) => {
      void (async () => {
        const abortController = new AbortController()
        uploadAbortControllersRef.current.set(pendingFile.tempId, abortController)
        const updateProgress = (updater: (progress: number) => number) => {
          setPendingGoogleDriveFiles(prev => prev.map(file => (
            file.tempId === pendingFile.tempId
              ? { ...file, upload_status: 'uploading', upload_progress: Math.min(99, updater(file.upload_progress || 0)) }
              : file
          )))
        }
        startUploadProgressTimer(pendingFile.tempId, updateProgress)
        try {
          const importedFile = await importGoogleDriveFileToJob(
            null,
            {
              file_id: pendingFile.googleFileId,
              access_token: pendingFile.accessToken,
              filename: pendingFile.filename,
              mime_type: pendingFile.mime_type,
              file_format: pendingFile.file_format,
            },
            undefined,
            abortController.signal
          )

          stopUploadProgressTimer(pendingFile.tempId)
          setPendingGoogleDriveFiles(prev => prev.map(file => (
            file.tempId === pendingFile.tempId
              ? {
                  ...file,
                  staged_file_id: importedFile.id,
                  upload_status: 'uploaded',
                  upload_progress: 100,
                  size_bytes: importedFile.size_bytes,
                  file_format: importedFile.file_format || file.file_format,
                }
              : file
          )))
        } catch (err: any) {
          stopUploadProgressTimer(pendingFile.tempId)
          if (isCanceledUploadError(err)) {
            return
          }
          setPendingGoogleDriveFiles(prev => prev.map(file => (
            file.tempId === pendingFile.tempId
              ? {
                  ...file,
                  upload_status: 'failed',
                  upload_error: err?.message || 'Failed to import Google Drive file',
                }
              : file
          )))
        } finally {
          stopUploadProgressTimer(pendingFile.tempId)
          uploadAbortControllersRef.current.delete(pendingFile.tempId)
        }
      })()
    })
  }

  const openGoogleDrivePicker = async () => {
    const clientId = import.meta.env.VITE_GOOGLE_DRIVE_CLIENT_ID
    const apiKey = import.meta.env.VITE_GOOGLE_DRIVE_API_KEY
    const appId = clientId ? deriveGoogleDriveAppId(clientId) : ''

    if (!clientId || !apiKey || !appId) {
      setError(
        'Google Drive sign-in is not configured. CASSIE needs Google OAuth app credentials, but files still come from each user\'s own Drive account.'
      )
      return
    }

    try {
      setError('')
      setImportingGoogleDriveFile(true)
      await loadGoogleDriveScripts()
      await loadGooglePicker()

      await new Promise<void>((resolve, reject) => {
        const tokenClient = window.google?.accounts?.oauth2?.initTokenClient({
          client_id: clientId,
          scope: GOOGLE_DRIVE_SCOPE,
          callback: async (tokenResponse: any) => {
            if (tokenResponse?.error) {
              reject(new Error(tokenResponse.error_description || tokenResponse.error))
              return
            }

            const accessToken = tokenResponse?.access_token
            if (!accessToken) {
              reject(new Error('Google did not return an access token.'))
              return
            }

            const picker = new window.google.picker.PickerBuilder()
              .setDeveloperKey(apiKey)
              .setAppId(appId)
              .setOAuthToken(accessToken)
              .addView(
                new window.google.picker.DocsView(window.google.picker.ViewId.DOCS)
                  .setIncludeFolders(false)
                  .setSelectFolderEnabled(false)
              )
              .enableFeature(window.google.picker.Feature.SUPPORT_DRIVES)
              .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
              .setCallback((data: any) => {
                if (data.action === window.google.picker.Action.CANCEL) {
                  resolve()
                  return
                }
                if (data.action !== window.google.picker.Action.PICKED) {
                  return
                }

                const docs = (data.docs || []).filter((doc: any) => doc?.id)
                if (docs.length === 0) {
                  reject(new Error('No Google Drive file was selected.'))
                  return
                }

                addPickedGoogleDriveFiles(accessToken, docs)
                resolve()
              })
              .build()

            picker.setVisible(true)
          },
        })

        if (!tokenClient) {
          reject(new Error('Google Identity Services could not be initialized.'))
          return
        }

        tokenClient.requestAccessToken({ prompt: 'consent' })
      })
    } catch (err: any) {
      setError(
        err.response?.data?.error?.message ||
        err.response?.data?.message ||
        err.message ||
        'Failed to import from Google Drive'
      )
    } finally {
      setImportingGoogleDriveFile(false)
    }
  }

  const renderFileSourceControls = () => (
    <div className="job-file-source-controls">
      <label className="btn-secondary" style={{ cursor: 'pointer', display: 'inline-block' }}>
        Select New File(s)
        <input
          type="file"
          onChange={handleFileUpload}
          disabled={creating}
          multiple
          style={{ display: 'none' }}
          accept=".fastq,.fastq.gz,.fq,.fq.gz,.fasta,.fasta.gz,.fa,.fa.gz,.fna,.fna.gz,.gff,.gff3,.gtf,.hal,.gfa,.meryl,.meryl.tar,.meryl.tar.gz,.meryl.tgz,.cfg,.conf,.ini,.json,.txt,.tsv,.csv,.gz"
        />
      </label>
      <button
        type="button"
        className="btn-secondary"
        onClick={() => void openGoogleDrivePicker()}
        disabled={creating || importingGoogleDriveFile}
      >
        {importingGoogleDriveFile ? 'Opening Your Drive...' : 'Choose from Your Google Drive'}
      </button>
      {pendingLocalFiles.length > 0 && (
        <div style={{ width: '100%', marginTop: '0.85rem', color: '#475569', fontSize: '0.9rem' }}>
          {pendingLocalFiles.filter(file => file.upload_status === 'uploaded').length}/{pendingLocalFiles.length} PC file{pendingLocalFiles.length !== 1 ? 's' : ''} uploaded for this job.
          {pendingLocalUploadCount > 0 && ` ${pendingLocalUploadCount} still uploading.`}
          {failedLocalUploadCount > 0 && ` ${failedLocalUploadCount} failed.`}
        </div>
      )}
      {pendingGoogleDriveFiles.length > 0 && (
        <div style={{ width: '100%', color: '#475569', fontSize: '0.9rem' }}>
          {pendingGoogleDriveFiles.filter(file => file.upload_status === 'uploaded').length}/{pendingGoogleDriveFiles.length} Google Drive file{pendingGoogleDriveFiles.length !== 1 ? 's' : ''} imported for this job.
          {pendingGoogleDriveUploadCount > 0 && ` ${pendingGoogleDriveUploadCount} still importing.`}
          {failedGoogleDriveUploadCount > 0 && ` ${failedGoogleDriveUploadCount} failed.`}
        </div>
      )}
    </div>
  )

  const sanitizeSelectedFilename = (value: string): string => (
    value.replace(/[\\/:*?"<>|]/g, '_').trim()
  )

  const handleSelectedFileRename = (tempId: number, nextFilename: string) => {
    const sanitizedName = sanitizeSelectedFilename(nextFilename)
    setPendingLocalFiles(prev => prev.map(file => (
      file.tempId === tempId
        ? {
            ...file,
            filename: sanitizedName,
            file_format: inferFileFormat(sanitizedName),
          }
        : file
    )))
    setPendingGoogleDriveFiles(prev => prev.map(file => (
      file.tempId === tempId
        ? {
            ...file,
            filename: sanitizedName,
            file_format: inferFileFormat(sanitizedName),
          }
        : file
    )))
  }

  const renderSelectableFileChip = (file: FileItem & { folderPath?: string }, keyPrefix: string, selected = false) => {
    const pendingFile = pendingLocalFiles.find(item => item.tempId === file.id)
    const pendingGoogleDriveFile = pendingGoogleDriveFiles.find(item => item.tempId === file.id)
    const title = file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename

    return (
      <div
        key={`${keyPrefix}-${file.id}`}
        className={`builder-file-chip ${selected ? 'selected' : ''}`}
        title={title}
      >
        {pendingFile ? (
          <>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', width: '100%' }}>
              <span style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                File name
              </span>
              <input
                type="text"
                value={pendingFile.filename}
                onChange={(event) => handleSelectedFileRename(pendingFile.tempId, event.target.value)}
                disabled={creating || pendingFile.upload_status === 'uploading' || pendingFile.upload_status === 'uploaded'}
                style={{ minWidth: '220px', fontWeight: 700 }}
                aria-label={`Rename selected file ${pendingFile.original_filename || pendingFile.file.name}`}
              />
            </label>
            <span>From PC: {pendingFile.original_filename || pendingFile.file.name}</span>
            {pendingFile.upload_status === 'uploaded' ? (
              <span>Uploaded and ready</span>
            ) : pendingFile.upload_status === 'failed' ? (
              <span style={{ color: '#b91c1c' }}>{pendingFile.upload_error || 'Upload failed'}</span>
            ) : (
              <span style={{ width: '100%' }}>
                <span>Uploading... {pendingFile.upload_progress || 0}%</span>
                <span style={{ display: 'block', height: '6px', marginTop: '0.35rem', borderRadius: '999px', backgroundColor: '#e5e7eb', overflow: 'hidden' }}>
                  <span style={{ display: 'block', width: `${pendingFile.upload_progress || 0}%`, height: '100%', backgroundColor: '#2563eb' }} />
                </span>
              </span>
            )}
          </>
        ) : pendingGoogleDriveFile ? (
          <>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', width: '100%' }}>
              <span style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                File name
              </span>
              <input
                type="text"
                value={pendingGoogleDriveFile.filename}
                onChange={(event) => handleSelectedFileRename(pendingGoogleDriveFile.tempId, event.target.value)}
                disabled={creating || pendingGoogleDriveFile.upload_status === 'uploading' || pendingGoogleDriveFile.upload_status === 'uploaded'}
                style={{ minWidth: '220px', fontWeight: 700 }}
                aria-label={`Rename selected Google Drive file ${pendingGoogleDriveFile.original_filename || pendingGoogleDriveFile.filename}`}
              />
            </label>
            <span>From Google Drive: {pendingGoogleDriveFile.original_filename || pendingGoogleDriveFile.filename}</span>
            {pendingGoogleDriveFile.upload_status === 'uploaded' ? (
              <span>Imported and ready</span>
            ) : pendingGoogleDriveFile.upload_status === 'failed' ? (
              <span style={{ color: '#b91c1c' }}>{pendingGoogleDriveFile.upload_error || 'Import failed'}</span>
            ) : (
              <span style={{ width: '100%' }}>
                <span>Importing... {pendingGoogleDriveFile.upload_progress || 0}%</span>
                <span style={{ display: 'block', height: '6px', marginTop: '0.35rem', borderRadius: '999px', backgroundColor: '#e5e7eb', overflow: 'hidden' }}>
                  <span style={{ display: 'block', width: `${pendingGoogleDriveFile.upload_progress || 0}%`, height: '100%', backgroundColor: '#2563eb' }} />
                </span>
              </span>
            )}
          </>
        ) : (
          <>
            <strong>{file.filename}</strong>
            {file.folderPath && <span>{file.folderPath}</span>}
          </>
        )}
      </div>
    )
  }

  const handleRecommendationFileToggle = (fileId: number) => {
    setRecommendationFileIds(prev => (
      prev.includes(fileId)
        ? prev.filter(id => id !== fileId)
        : [...prev, fileId]
    ))
  }

  const handleGenerateRecommendations = async () => {
    const selectedFiles = getCombinedSelectableFiles().filter(file => recommendationFileIds.includes(file.id))
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
        setError('No recommendation could be generated from the selected intentions and candidate files')
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
      title: 'Select files',
      description: 'Choose the files you want available for this run before assigning them to blocks.',
    },
    {
      level: 3,
      title: 'Attach inputs',
      description: 'Map the selected files to each named tool block.',
    },
    {
      level: 4,
      title: 'Configure run',
      description: 'Choose compute resources and tune same-level priorities after inputs are assigned.',
    },
    {
      level: 5,
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
        : (pipelineRequirements?.tools.map((toolId) => {
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
  }, [availableTools, pipelineRequirements, priorityGroups, selectedPipeline, selectedPipelineNodes, selectedToolDefinitions, selectionMode])

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

  const canAdvanceFromLevelThree = selectionMode === 'pipeline'
    ? (pipelineInputRequirements.length === 0 || missingPipelineInputCount === 0)
    : (manualToolInputBlocks.length === 0 || missingManualInputBlockCount === 0)

  const canAdvanceFromLevelFour = Boolean(selectedVM)

  const inputBlockDisplayName = useCallback((inputId: string, fallbackLabel: string): string => (
    inputBlockNames[inputId]?.trim() || fallbackLabel
  ), [inputBlockNames])

  const handleInputBlockNameChange = (inputId: string, value: string) => {
    setInputBlockNames((prev) => ({ ...prev, [inputId]: value }))
  }

  const goToNextLevel = () => {
    setSlideDirection('forward')
    setCurrentLevel((current) => Math.min(5, current + 1) as BuilderLevel)
  }

  const cancelSelectedUploads = ({ clearState = true }: { clearState?: boolean } = {}) => {
    uploadAbortControllersRef.current.forEach(controller => controller.abort())
    uploadAbortControllersRef.current.clear()
    uploadProgressTimersRef.current.forEach(timerId => window.clearInterval(timerId))
    uploadProgressTimersRef.current.clear()

    const currentPendingLocalFiles = pendingLocalFilesRef.current
    const currentPendingGoogleDriveFiles = pendingGoogleDriveFilesRef.current
    const pendingTempIds = new Set<number>([
      ...currentPendingLocalFiles.map(file => file.tempId),
      ...currentPendingGoogleDriveFiles.map(file => file.tempId),
    ])
    const stagedFileIds = [
      ...currentPendingLocalFiles.map(file => file.staged_file_id),
      ...currentPendingGoogleDriveFiles.map(file => file.staged_file_id),
    ].filter((fileId): fileId is number => typeof fileId === 'number' && fileId > 0)

    stagedFileIds.forEach(fileId => {
      void deleteFile(fileId).catch(() => {
        // Best effort cleanup. The staged file may already have been removed or never committed.
      })
    })

    if (!clearState) {
      return
    }

    setPendingLocalFiles([])
    setPendingGoogleDriveFiles([])
    setRecommendationFileIds(prev => prev.filter(fileId => !pendingTempIds.has(fileId)))
    setToolFileMappings(prev => Object.fromEntries(
      Object.entries(prev).map(([toolKey, requirementMap]) => [
        toolKey,
        Object.fromEntries(
          Object.entries(requirementMap).map(([requirementType, fileIds]) => [
            requirementType,
            fileIds.filter(fileId => !pendingTempIds.has(fileId)),
          ])
        ),
      ])
    ))
    setPipelineInputMappings(prev => Object.fromEntries(
      Object.entries(prev).map(([inputKey, fileIds]) => [
        inputKey,
        fileIds.filter(fileId => !pendingTempIds.has(fileId)),
      ])
    ))
  }

  const goToPreviousLevel = () => {
    if (currentLevel === 2 && (pendingLocalFilesRef.current.length > 0 || pendingGoogleDriveFilesRef.current.length > 0)) {
      cancelSelectedUploads()
    }
    setSlideDirection('backward')
    setCurrentLevel((current) => Math.max(1, current - 1) as BuilderLevel)
  }

  const handleCancelCreateJob = () => {
    cancelSelectedUploads()
    shouldPersistDraftRef.current = false
    clearCreateJobDraft()
    navigate('/')
  }

  const shouldShowRuntimeEstimateCard = Boolean(loadingRuntimeEstimate || runtimeEstimate || runtimeEstimateError)
  const combinedSelectableFiles = useMemo(
    () => getCombinedSelectableFiles(),
    [dataFileTree, pendingGoogleDriveFiles, pendingLocalFiles]
  )
  const pendingLocalUploadCount = pendingLocalFiles.filter(file => file.upload_status === 'queued' || file.upload_status === 'uploading').length
  const failedLocalUploadCount = pendingLocalFiles.filter(file => file.upload_status === 'failed').length
  const pendingGoogleDriveUploadCount = pendingGoogleDriveFiles.filter(file => file.upload_status === 'queued' || file.upload_status === 'uploading').length
  const failedGoogleDriveUploadCount = pendingGoogleDriveFiles.filter(file => file.upload_status === 'failed').length
  const pendingFileUploadCount = pendingLocalUploadCount + pendingGoogleDriveUploadCount
  const failedFileUploadCount = failedLocalUploadCount + failedGoogleDriveUploadCount
  const hasSelectableInputFiles = combinedSelectableFiles.length > 0

  const canAdvanceFromLevelTwo = hasSelectableInputFiles && pendingFileUploadCount === 0 && failedFileUploadCount === 0

  const selectedLibraryFiles = useMemo(() => combinedSelectableFiles.filter((file) => {
    if (selectionMode === 'pipeline') {
      return Object.values(pipelineInputMappings).some((fileIds) => fileIds.includes(file.id))
    }

    return Object.values(toolFileMappings).some((requirementMap) =>
      Object.values(requirementMap).some((fileIds) => fileIds.includes(file.id))
    )
  }), [combinedSelectableFiles, pipelineInputMappings, selectionMode, toolFileMappings])

  const reviewPipelinePlanRequest = useMemo<PipelinePlanPreviewRequest | null>(() => {
    if (currentLevel !== 5) {
      return null
    }

    const filesById = new Map(combinedSelectableFiles.map((file) => [file.id, file]))

    if (selectionMode === 'pipeline') {
      if (!selectedPipelineId) {
        return null
      }

      const plannedInputs = pipelineInputRequirements.flatMap((inputReq) => {
        const inputKey = String(inputReq.id || inputReq.label)
        const mappedFileIds = pipelineInputMappings[inputKey] || []

        return mappedFileIds
          .map((fileId) => filesById.get(fileId))
          .filter((file): file is FileItem & { folderPath?: string } => Boolean(file))
          .map((file) => ({
            id: file.id,
            binding_id: inputKey,
            label: inputBlockDisplayName(inputKey, inputReq.label),
            filename: file.filename,
            file_format: file.file_format || null,
            size_bytes: file.size_bytes || 0,
            s3_key: file.s3_key,
            source: file.id < 0 ? 'pending-local' : 'library',
          }))
      })

      const executionPreferences = buildPipelineExecutionPreferences(priorityGroups)

      return {
        pipeline_id: selectedPipelineId,
        planned_inputs: plannedInputs,
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
            source: file.id < 0 ? 'pending-local' : 'library',
          }))
      })
    })

    const executionPreferences: Record<string, unknown> = buildManualExecutionPreferences(priorityGroups)

    const inputSourceOverrides = getManualInputSourceOverrides()
    if (inputSourceOverrides.length > 0) {
      executionPreferences.input_source_overrides = inputSourceOverrides
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
    getManualInputSourceOverrides,
    getRequirementSource,
    inputBlockDisplayName,
    pipelineInputMappings,
    pipelineInputRequirements,
    priorityGroups,
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

    void loadPipelinePlanPreview()

    return () => {
      cancelled = true
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
    || persistedReviewPipelinePreview

  useEffect(() => {
    if (effectiveReviewPipelinePreview) {
      setPersistedReviewPipelinePreview(effectiveReviewPipelinePreview)
    }
  }, [effectiveReviewPipelinePreview])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    if (!shouldPersistDraftRef.current) {
      return
    }

    const draft: CreateJobDraft = {
      version: 2,
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
      recommendationFileIds,
      priorityGroups,
      openPriorityGroups,
      currentLevel,
      inputBlockNames,
      selectedVM,
      reviewPipelinePreview: effectiveReviewPipelinePreview || persistedReviewPipelinePreview,
    }

    window.sessionStorage.setItem(CREATE_JOB_DRAFT_STORAGE_KEY, JSON.stringify(draft))
  }, [
    currentLevel,
    effectiveReviewPipelinePreview,
    inputBlockNames,
    jobName,
    openPriorityGroups,
    persistedReviewPipelinePreview,
    pipelineInputMappings,
    pipelineRequirements,
    priorityGroups,
    recommendationFileIds,
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

    if (currentLevel !== 5) {
      setSlideDirection('forward')
      setCurrentLevel(5)
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

    try {
      setCreating(true)
      setSubmitStatus('Creating job...')
      
      // Create job with tool selection or pipeline and input files
      const jobData: JobCreate = {
        name: jobName,
        vm_name: selectedVM || undefined,
        estimated_price_usd: runtimeEstimate.estimated_price_usd,
      }
      
      const selectedPendingGoogleDriveFiles = pendingGoogleDriveFiles.filter(file => uploadedFileIds.includes(file.tempId))
      const blankPendingGoogleDriveFile = selectedPendingGoogleDriveFiles.find(file => !file.filename.trim())
      if (blankPendingGoogleDriveFile) {
        setError(`Please give every selected Google Drive file a name before starting the job. Original file: ${blankPendingGoogleDriveFile.original_filename || blankPendingGoogleDriveFile.googleFileId}`)
        return
      }
      const duplicatePendingGoogleDriveName = selectedPendingGoogleDriveFiles.find((file, index, allFiles) => (
        allFiles.findIndex(candidate => candidate.filename.trim().toLowerCase() === file.filename.trim().toLowerCase()) !== index
      ))
      if (duplicatePendingGoogleDriveName) {
        setError(`Selected Google Drive files must have unique names before import. Duplicate name: ${duplicatePendingGoogleDriveName.filename}`)
        return
      }
      const unimportedGoogleDriveFile = selectedPendingGoogleDriveFiles.find(file => file.upload_status !== 'uploaded' || !file.staged_file_id)
      if (unimportedGoogleDriveFile) {
        setError(`Please wait for every selected Google Drive file to finish importing before submitting. Still waiting on: ${unimportedGoogleDriveFile.filename}`)
        return
      }
      const selectedGoogleDriveStagedFileIds = selectedPendingGoogleDriveFiles
        .map(file => file.staged_file_id)
        .filter((fileId): fileId is number => typeof fileId === 'number' && fileId > 0)

      const selectedPendingLocalFiles = pendingLocalFiles.filter(file => uploadedFileIds.includes(file.tempId))
      const unuploadedPendingFile = selectedPendingLocalFiles.find(file => file.upload_status !== 'uploaded' || !file.staged_file_id)
      if (unuploadedPendingFile) {
        setError(`Please wait for every selected PC file to finish uploading before submitting. Still waiting on: ${unuploadedPendingFile.filename}`)
        return
      }
      const selectedStagedFileIds = selectedPendingLocalFiles
        .map(file => file.staged_file_id)
        .filter((fileId): fileId is number => typeof fileId === 'number' && fileId > 0)
      const selectedNewStagedFileIds = [...selectedStagedFileIds, ...selectedGoogleDriveStagedFileIds]
      const pendingLocalTempIds = new Set(selectedPendingLocalFiles.map(file => file.tempId))
      const pendingGoogleDriveTempIds = new Set(selectedPendingGoogleDriveFiles.map(file => file.tempId))
      const existingLibraryFileIds = uploadedFileIds.filter(id => id > 0 && !pendingLocalTempIds.has(id) && !pendingGoogleDriveTempIds.has(id))
      const blankPendingFile = selectedPendingLocalFiles.find(file => !file.filename.trim())
      if (blankPendingFile) {
        setError(`Please give every selected PC file a name before starting the job. Original file: ${blankPendingFile.original_filename || blankPendingFile.file.name}`)
        return
      }
      const duplicatePendingName = selectedPendingLocalFiles.find((file, index, allFiles) => (
        allFiles.findIndex(candidate => candidate.filename.trim().toLowerCase() === file.filename.trim().toLowerCase()) !== index
      ))
      if (duplicatePendingName) {
        setError(`Selected PC files must have unique names before upload. Duplicate name: ${duplicatePendingName.filename}`)
        return
      }

      // Only include already-uploaded library files at create time
      if (existingLibraryFileIds.length > 0) {
        jobData.input_file_ids = existingLibraryFileIds
      }
      if (selectedNewStagedFileIds.length > 0) {
        jobData.staged_input_file_ids = selectedNewStagedFileIds
      }

      const inputSourceOverrides = selectionMode === 'tools'
        ? getManualInputSourceOverrides()
        : []

      if (selectionMode === 'pipeline') {
        if (!selectedPipelineId) {
          setError('Please select a pipeline')
          setCreating(false)
          return
        }
        jobData.pipeline_id = selectedPipelineId
        if (priorityGroups.length > 0) {
          jobData.execution_preferences = buildPipelineExecutionPreferences(priorityGroups)
        }
      } else {
        if (selectedTools.length === 0) {
          setError('Please select at least one tool')
          setCreating(false)
          return
        }
        jobData.tool_indices = selectedTools
        if (priorityGroups.length > 0) {
          jobData.execution_preferences = buildManualExecutionPreferences(priorityGroups)
        }
      }

      if (inputSourceOverrides.length > 0) {
        jobData.execution_preferences = {
          ...(jobData.execution_preferences || {}),
          input_source_overrides: inputSourceOverrides,
        }
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
          <h1 className="page-title">Create New Job</h1>
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
                (builderLevel.level === 4 && canAdvanceFromLevelOne && canAdvanceFromLevelTwo && canAdvanceFromLevelThree) ||
                (builderLevel.level === 5 && canAdvanceFromLevelOne && canAdvanceFromLevelTwo && canAdvanceFromLevelThree && canAdvanceFromLevelFour)

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
                  Choose what you want to achieve, provide candidate input files, and the system will suggest a few possible pipelines.
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

                <div style={{ marginBottom: '1rem' }}>
                  <label className="btn-secondary" style={{ cursor: 'pointer', display: 'inline-block' }}>
                    Select Candidate File(s)
                    <input
                      type="file"
                      onChange={handleFileUpload}
                      disabled={creating}
                      multiple
                      style={{ display: 'none' }}
                      accept=".fastq,.fasta,.fq,.fa,.gz"
                    />
                  </label>
                </div>

                {loadingDataTree ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading candidate files...</p>
                ) : (
                  <div style={{ marginBottom: '1rem' }}>
                    <div style={sharedRequirementCardStyle}>
                      {getCombinedSelectableFiles().map(file => {
                        const isSelected = recommendationFileIds.includes(file.id)
                        return (
                          <button
                            key={`rec-file-${file.id}`}
                            type="button"
                            onClick={() => handleRecommendationFileToggle(file.id)}
                            className={isSelected ? 'btn-primary' : 'btn-secondary'}
                            style={{ padding: '0.4rem 0.75rem' }}
                            title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                          >
                            {file.filename}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleGenerateRecommendations}
                  className="btn-primary"
                  disabled={loadingRecommendations || selectedIntentIds.length === 0 || recommendationFileIds.length === 0}
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
                  setPersistedReviewPipelinePreview(null)
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
                            setPersistedReviewPipelinePreview(null)
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
                    {pipelineRequirements.tools.length > 0 ? pipelineRequirements.tools.map(toolId => {
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

          {currentLevel === 4 && (
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
                <label>Pipeline Files</label>
                <div className="builder-section-card">
                  <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                    Choose the files you want available for this pipeline. In the next step you will assign them to the explicit tool blocks.
                  </p>

                  {renderFileSourceControls()}

                  {loadingDataTree ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                  ) : combinedSelectableFiles.length === 0 ? (
                    <p style={{ color: '#666', fontStyle: 'italic', margin: 0 }}>
                      No files available yet. Upload files now, then map them to pipeline tool blocks in the next step.
                    </p>
                  ) : (
                    <div className="builder-file-chip-grid">
                      {combinedSelectableFiles.map((file) => renderSelectableFileChip(file, 'pipeline-file'))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {selectionMode === 'tools' && (
              <div className="form-group">
                <label>Input Files</label>
                <div className="builder-section-card">
                  <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                    Add or review the files you want available. In the next step, you will assign them into named tool blocks.
                  </p>

                  {renderFileSourceControls()}

                  {loadingDataTree ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                  ) : combinedSelectableFiles.length === 0 ? (
                    <p style={{ color: '#666', fontStyle: 'italic', margin: 0 }}>
                      No input files available yet. Upload files here, then map them to tool blocks in the next step.
                    </p>
                  ) : (
                    <div className="builder-file-chip-grid">
                      {combinedSelectableFiles.map((file) => renderSelectableFileChip(file, 'tool-file'))}
                    </div>
                  )}
                </div>
              </div>
            )}
              </>
            )}

            {currentLevel === 3 && (
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
                      {combinedSelectableFiles.length > 0 && (
                        <div className="builder-section-card builder-input-file-context">
                          <p className="builder-card-kicker">Selected Files</p>
                      <div className="builder-file-chip-grid">
                            {combinedSelectableFiles.map((file) => renderSelectableFileChip(
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
                            {compatibleFiles.length === 0 ? (
                              <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                                No compatible files found. Upload files with formats: {inputReq.formats.join(', ').toUpperCase()}
                              </p>
                            ) : (
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
                            )}
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
                  {combinedSelectableFiles.length > 0 && (
                    <div className="builder-section-card builder-input-file-context">
                      <p className="builder-card-kicker">Selected Files</p>
                      <div className="builder-file-chip-grid">
                        {combinedSelectableFiles.map((file) => renderSelectableFileChip(
                          file,
                          'tool-context',
                          selectedLibraryFiles.some((item) => item.id === file.id)
                        ))}
                      </div>
                    </div>
                  )}

                  {combinedSelectableFiles.length === 0 ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>
                      No input files available yet. Go back and add files first, then connect them to the tool blocks here.
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
                        return (
                          <div key={block.id} className="builder-requirement-card builder-block-card">
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
                                    ) : compatibleFiles.length === 0 ? (
                                      <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem', margin: 0 }}>
                                        No compatible files found. Upload files with formats: {req.formats.join(', ').toUpperCase()}
                                        {req.filename_example ? ` and names like ${req.filename_example}` : ''}
                                      </p>
                                    ) : (
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
                                    )}
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

          {currentLevel === 5 && (
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
                    <p style={{ margin: '0 0 0.75rem', color: '#b91c1c', fontSize: '0.9rem' }}>
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
                        return (
                          <div key={`review-${block.id}`} className="builder-input-summary-row">
                            <strong>{inputBlockDisplayName(block.id, getManualInputBlockDefaultName(block))}</strong>
                            <span>
                              {mappedFileCount} file(s) | {block.requirements.length} requirement(s) for {block.toolReq.tool_name}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
          </div>

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
            {currentLevel < 5 ? (
              <button
                key={`builder-next-${currentLevel}`}
                type="button"
                className="btn-primary"
                disabled={
                  creating ||
                  (currentLevel === 1 && !canAdvanceFromLevelOne) ||
                  (currentLevel === 2 && !canAdvanceFromLevelTwo) ||
                  (currentLevel === 3 && !canAdvanceFromLevelThree) ||
                  (currentLevel === 4 && !canAdvanceFromLevelFour)
                }
                onClick={(event) => {
                  event.preventDefault()
                  goToNextLevel()
                }}
              >
                {currentLevel === 4 ? 'Review Job' : 'Continue'}
              </button>
            ) : (
              <button
                key="builder-submit"
                type="submit"
                className="btn-primary"
                disabled={creating}
              >
                {creating ? (submitStatus || 'Submitting job...') : 'Submit Job'}
              </button>
            )}
          </div>
        </form>
        </div>
      </div>
    </div>
  )
}
