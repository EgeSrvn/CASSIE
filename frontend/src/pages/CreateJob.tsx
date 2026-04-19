import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { createJob, JobCreate, executeJob, estimateRuntime, getAvailableVMs, RuntimeEstimate, RuntimeInputAssignment, VM } from '../services/jobService'
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
import { getPipelines, Pipeline, getPipelineRequirements, PipelineRequirement, PipelineRequirements } from '../services/pipelineService'
import { getDataFileTree } from '../services/dataFileService'
import { FolderTreeItem, FileItem } from '../services/folderService'
import { getToken } from '../services/authService'
import { PendingJobUploadFile, enqueuePendingJobUploads } from '../services/pendingJobUploadService'
import Navigation from '../components/Navigation'
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

export default function CreateJob() {
  const location = useLocation()
  const [jobName, setJobName] = useState('')
  const isAuthenticated = !!getToken()
  const [selectionMode, setSelectionMode] = useState<'tools' | 'pipeline'>('tools')
  const [availableTools, setAvailableTools] = useState<Tool[]>([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [selectedTools, setSelectedTools] = useState<number[]>([]) // No tools selected by default
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [selectedPipelineId, setSelectedPipelineId] = useState<number | null>(null)
  const [loadingPipelines, setLoadingPipelines] = useState(false)
  const [pipelineRequirements, setPipelineRequirements] = useState<PipelineRequirements | null>(null)
  const [loadingRequirements, setLoadingRequirements] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string>('')
  const [dataFileTree, setDataFileTree] = useState<FolderTreeItem[]>([])
  const [loadingDataTree, setLoadingDataTree] = useState(false)
  const [pendingLocalFiles, setPendingLocalFiles] = useState<PendingJobUploadFile[]>([])
  const [submitStatus, setSubmitStatus] = useState<string>('')
  const [availableVMs, setAvailableVMs] = useState<VM[]>([])
  const [loadingVMs, setLoadingVMs] = useState(false)
  const [selectedVM, setSelectedVM] = useState<string>('')
  const [runtimeEstimate, setRuntimeEstimate] = useState<RuntimeEstimate | null>(null)
  const [loadingRuntimeEstimate, setLoadingRuntimeEstimate] = useState(false)
  const [runtimeEstimateError, setRuntimeEstimateError] = useState('')
  const [toolRequirements, setToolRequirements] = useState<ToolRequirementInfo[]>([])
  const [loadingToolRequirements, setLoadingToolRequirements] = useState(false)
  const [toolFileMappings, setToolFileMappings] = useState<Record<string, Record<string, number[]>>>({}) // Maps tool_index -> requirement_type -> file_id[]
  const [pipelineInputMappings, setPipelineInputMappings] = useState<Record<string, number[]>>({})
  const [requirementSourceSelections, setRequirementSourceSelections] = useState<Record<string, 'external' | 'upstream'>>({})
  const [recommendationIntents, setRecommendationIntents] = useState<RecommendationIntent[]>([])
  const [selectedIntentIds, setSelectedIntentIds] = useState<string[]>([])
  const [recommendationFileIds, setRecommendationFileIds] = useState<number[]>([])
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationOption[]>([])
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [appliedRecommendationFileIds, setAppliedRecommendationFileIds] = useState<number[] | null>(null)
  const [priorityGroups, setPriorityGroups] = useState<PriorityGroup[]>([])
  const [openPriorityGroups, setOpenPriorityGroups] = useState<number[]>([0])
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false)
  const navigate = useNavigate()
  const sharedRequirementCardStyle = {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.5rem',
    padding: '1rem',
    border: '1px solid #e5e7eb',
    borderRadius: '4px',
    backgroundColor: 'white',
  }
  const selectedVMDetails = availableVMs.find(vm => vm.name === selectedVM) || null
  const selectedPipeline = useMemo(
    () => pipelines.find((pipeline) => pipeline.id === selectedPipelineId) || null,
    [pipelines, selectedPipelineId]
  )

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
  }, [selectedVM, selectionMode, selectedPipelineId, selectedTools, toolFileMappings, pendingLocalFiles, dataFileTree])

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
          setToolFileMappings({})
          setPipelineInputMappings({})
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
      setToolFileMappings({})
      setPipelineInputMappings({})
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

  // Fetch available VMs on component mount
  useEffect(() => {
    const fetchVMs = async () => {
      try {
        setLoadingVMs(true)
        const vms = await getAvailableVMs()
        setAvailableVMs(vms)
        // Auto-select first VM if available
        if (vms.length > 0 && !selectedVM) {
          setSelectedVM(vms[0].name)
        }
      } catch (err: any) {
        console.error('Failed to load VMs:', err)
        // If not authenticated, don't redirect - let user configure without VMs
        if (err.response?.status === 401 && !isAuthenticated) {
          setAvailableVMs([])
        }
      } finally {
        setLoadingVMs(false)
      }
    }
    fetchVMs()
    const intervalId = window.setInterval(fetchVMs, 5000)
    return () => window.clearInterval(intervalId)
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
      const nodes = Array.isArray(selectedPipeline.nodes) ? selectedPipeline.nodes : []
      const edges = Array.isArray(selectedPipeline.edges) ? selectedPipeline.edges : []
      return computePipelinePriorityGroups(nodes as any[], edges as any[])
    }
    if (selectionMode === 'tools' && activeToolRequirementCards.length > 0 && selectedToolIds.length > 0) {
      return computeManualPriorityGroups(activeToolRequirementCards, selectedToolIds)
    }
    return []
  }, [activeToolRequirementCards, selectedPipeline, selectedToolIds, selectionMode])
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
  }, [selectionMode, appliedRecommendationFileIds, toolRequirements, pendingLocalFiles, dataFileTree])

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

  const getRequirementSelectionKey = (toolReq: ToolRequirementInfo, req: ToolRequirement): string => (
    req.requirement_id || `${toolReq.tool_index}:${req.type}`
  )

  const getRequirementSource = (toolReq: ToolRequirementInfo, req: ToolRequirement): 'external' | 'upstream' => {
    const key = getRequirementSelectionKey(toolReq, req)
    return requirementSourceSelections[key] || req.default_source || (req.is_intermediate ? 'upstream' : 'external')
  }

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

    return [...pendingFilesAsItems, ...libraryFiles]
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

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || [])
    if (selectedFiles.length === 0) return

    try {
      setError('')
      setPendingLocalFiles(prev => {
        const existingKeys = new Set(prev.map(file => `${file.filename}:${file.size_bytes}:${file.file.lastModified}`))
        const additions = selectedFiles
          .filter(file => !existingKeys.has(`${file.name}:${file.size}:${file.lastModified}`))
          .map((file, index) => ({
            tempId: -(Date.now() + index + Math.floor(Math.random() * 1000)),
            file,
            filename: file.name,
            size_bytes: file.size,
            file_format: inferFileFormat(file.name),
            uploaded_at: null,
            created_at: new Date().toISOString(),
            folderPath: 'Selected Files',
          }))

        return [...additions, ...prev]
      })
      e.target.value = '' // Reset input
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Failed to select file')
    }
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    
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
              missingRequirements.push(`${toolReq.tool_name}: ${req.label}`)
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
        .map((inputReq) => inputReq.label)

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

    try {
      setCreating(true)
      setSubmitStatus('Creating job...')
      
      // Create job with tool selection or pipeline and input files
      const jobData: JobCreate = {
        name: jobName,
        vm_name: selectedVM || undefined
      }
      
      const existingLibraryFileIds = uploadedFileIds.filter(id => id > 0)
      const pendingFileIds = Array.from(new Set(uploadedFileIds.filter(id => id < 0)))
      const expectedTotalInputFiles = existingLibraryFileIds.length + pendingFileIds.length

      // Only include already-uploaded library files at create time
      if (existingLibraryFileIds.length > 0) {
        jobData.input_file_ids = existingLibraryFileIds
      }
      if (pendingFileIds.length > 0) {
        jobData.pending_upload_count = pendingFileIds.length
        jobData.expected_total_input_files = expectedTotalInputFiles
      }

      const inputSourceOverrides = selectionMode === 'tools'
        ? activeToolRequirementCards.flatMap((toolReq) =>
            toolReq.requirements
              .filter((req) => (req.available_sources || []).length > 1)
              .map((req) => ({
                tool_id: toolReq.tool_id,
                requirement_type: req.type,
                source: getRequirementSource(toolReq, req),
              }))
          )
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

      if (job && job.id && pendingFileIds.length > 0) {
        const pendingFilesToUpload = pendingLocalFiles.filter(file => pendingFileIds.includes(file.tempId))
        setSubmitStatus('Queueing selected files...')
        await enqueuePendingJobUploads(job.id, pendingFilesToUpload, job.upload_session_token)
        navigate(`/jobs/${job.id}`)
        return
      }
      
      // Auto-execute the job after creation
      if (job && job.id) {
        try {
          setSubmitStatus('Starting job...')
          await executeJob(job.id)
        } catch (executeErr: any) {
          console.error('Failed to auto-execute job:', executeErr)
          // Don't show error to user, just log it - job was created successfully
          // Navigate to job details so user can see the job and execute manually if needed
        }
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

        <div className="form-container">
        {error && <div className="error-message">{error}</div>}

        <form onSubmit={handleSubmit}>
          {submitStatus && (
            <div style={{ marginBottom: '1rem', padding: '0.75rem 1rem', borderRadius: '6px', backgroundColor: '#eff6ff', color: '#1d4ed8' }}>
              {submitStatus}
            </div>
          )}

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
              <div style={{ marginTop: '0.75rem', padding: '0.875rem 1rem', borderRadius: '8px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
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
            {(loadingRuntimeEstimate || runtimeEstimate || runtimeEstimateError) && (
              <div className="runtime-estimate-card">
                <div className="runtime-estimate-header">
                  <strong>Predicted Job Estimate</strong>
                  <span>Deterministic model</span>
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
          </div>

          {selectionMode === 'tools' && (
            <div className="form-group">
              <label>Intent-Based Suggestions</label>
              <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
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
                        style={{ padding: '1rem', border: '1px solid #dbeafe', borderRadius: '8px', backgroundColor: '#fff' }}
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
                        onClick={() => setSelectedPipelineId(pipeline.id)}
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
              {loadingRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading requirements...</p>
              ) : pipelineRequirements ? (
                <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
                  <p style={{ marginBottom: '0.75rem', color: '#666', fontSize: '0.875rem' }}>
                    This saved pipeline will run with its existing graph. You only need to provide files for the explicit input blocks in the pipeline.
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

            {selectionMode === 'pipeline' && selectedPipelineId && (
              <div className="form-group">
                <label>Pipeline Inputs *</label>
                {loadingRequirements ? (
                  <p style={{ color: '#666', fontStyle: 'italic' }}>Loading pipeline inputs...</p>
                ) : (
                  <div>
                    <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                      Each explicit input block in the saved pipeline needs a file assignment here.
                    </p>

                    <div style={{ marginBottom: '1.5rem' }}>
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
                    </div>

                    {loadingDataTree ? (
                      <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                    ) : pipelineInputRequirements.length === 0 ? (
                      <p style={{ color: '#666', fontStyle: 'italic' }}>
                        This pipeline does not expose any external input blocks.
                      </p>
                    ) : (
                      pipelineInputRequirements.map((inputReq: PipelineRequirement) => {
                        const inputKey = inputReq.id || inputReq.label
                        const mappedFileIds = pipelineInputMappings[inputKey] || []
                        const compatibleFiles = getCombinedSelectableFiles().filter(file => fileMatchesRequirement(file, inputReq))

                        return (
                          <div key={inputKey} style={{ marginBottom: '1.5rem', padding: '1.25rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
                            <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                              <strong>{inputReq.label}</strong>
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
                              <div style={sharedRequirementCardStyle}>
                                {compatibleFiles.map((file) => {
                                  const isSelected = mappedFileIds.includes(file.id)
                                  const isPendingLocalFile = file.id < 0
                                  return (
                                    <button
                                      key={`pipeline-input-${inputKey}-${file.id}`}
                                      type="button"
                                      onClick={() => handlePipelineInputMapping(inputKey, file.id)}
                                      disabled={creating}
                                      style={{
                                        padding: '0.5rem 1rem',
                                        borderRadius: '4px',
                                        border: `2px solid ${isSelected ? '#27548A' : (isPendingLocalFile ? '#DDA853' : '#d9c8a4')}`,
                                        backgroundColor: isSelected ? '#f1e5cf' : (isPendingLocalFile ? '#fbf1d9' : '#F5EEDC'),
                                        color: isSelected ? '#183B4E' : '#374151',
                                        cursor: creating ? 'not-allowed' : 'pointer',
                                        fontSize: '0.875rem',
                                        fontWeight: isSelected ? '600' : '400',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                        whiteSpace: 'nowrap',
                                        transition: 'all 0.2s ease'
                                      }}
                                      title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                                    >
                                      {isSelected && <span>✓</span>}
                                      <span>{file.filename}</span>
                                      {file.folderPath && (
                                        <span style={{ color: '#6b7280', fontSize: '0.75rem' }}>
                                          ({file.folderPath})
                                        </span>
                                      )}
                                    </button>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Tool Input Requirements Section */}
          {selectionMode === 'tools' && activeToolRequirementCards.length > 0 && (
            <div className="form-group">
              <label>Tool Input Requirements *</label>
              {loadingToolRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading tool requirements...</p>
              ) : activeToolRequirementCards.length > 0 ? (
                <div>
                  <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                    Each tool requires specific input files. Map files from your data library or upload new files.
                    Intermediate inputs (from previous tools) are automatically handled.
                  </p>
                  
                  {/* File Upload Section */}
                  <div style={{ marginBottom: '1.5rem' }}>
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
                  </div>

                  {loadingDataTree ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                  ) : (() => {
                    const combinedFiles = getCombinedSelectableFiles()
                    
                    return activeToolRequirementCards.map((toolReq) => {
                      const toolKey = toolReq.tool_index.toString()
                      return (
                        <div key={toolReq.tool_index} style={{ marginBottom: '2rem', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
                          <div style={{ marginBottom: '1rem' }}>
                            <h3 style={{ margin: 0, fontSize: '1.125rem', fontWeight: '600', color: '#111827' }}>
                              {toolReq.tool_name}
                            </h3>
                            <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#6b7280' }}>
                              {toolReq.description || `Tool type: ${toolReq.tool_type}`}
                            </p>
                          </div>
                          
                          {toolReq.requirements.length === 0 ? (
                            <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                              This tool doesn't require any input files (all inputs come from previous tools).
                            </p>
                          ) : (
                            toolReq.requirements.map((req) => {
                              const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
                              const selectedCount = mappedFileIds.length
                              const requirementSource = getRequirementSource(toolReq, req)
                              // Filter files that match the requirement format
                              const compatibleFiles = combinedFiles.filter(file => fileMatchesRequirement(file, req))
                              
                              return (
                                <div key={req.type} style={{ marginBottom: '1.5rem' }}>
                                  <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <strong>{req.label}</strong>
                                    <span style={{ color: '#666', fontSize: '0.875rem' }}>
                                      ({req.formats.join(', ').toUpperCase()})
                                    </span>
                                    {(req.available_sources || []).length > 1 ? (
                                      <div style={{ display: 'inline-flex', gap: '0.4rem', marginLeft: '0.5rem' }}>
                                        <button
                                          type="button"
                                          className={requirementSource === 'upstream' ? 'btn-primary' : 'btn-secondary'}
                                          style={{ padding: '0.25rem 0.55rem', fontSize: '0.75rem' }}
                                          onClick={() => handleRequirementSourceChange(toolReq, req, 'upstream')}
                                        >
                                          Use {req.source_tool || 'upstream output'}
                                        </button>
                                        <button
                                          type="button"
                                          className={requirementSource === 'external' ? 'btn-primary' : 'btn-secondary'}
                                          style={{ padding: '0.25rem 0.55rem', fontSize: '0.75rem' }}
                                          onClick={() => handleRequirementSourceChange(toolReq, req, 'external')}
                                        >
                                          Use uploaded input
                                        </button>
                                      </div>
                                    ) : null}
                                    {requirementSource === 'upstream' ? (
                                      <span style={{ 
                                        marginLeft: '0.5rem', 
                                        padding: '0.25rem 0.5rem',
                                        backgroundColor: '#dbeafe',
                                        color: '#1e40af',
                                        fontSize: '0.75rem',
                                        borderRadius: '4px',
                                        fontWeight: '500'
                                      }}>
                                        ⚡ Intermediate (from {req.source_tool})
                                      </span>
                                    ) : selectedCount > 0 ? (
                                      <span style={{ marginLeft: '0.5rem', color: '#16a34a', fontSize: '0.875rem', fontWeight: '500' }}>
                                        ✓ {selectedCount} file{selectedCount !== 1 ? 's' : ''} selected
                                      </span>
                                    ) : (
                                      <span style={{ marginLeft: '0.5rem', color: '#f59e0b', fontSize: '0.875rem', fontWeight: '500' }}>
                                        ⚠ Required (select at least one)
                                      </span>
                                    )}
                                  </div>
                                  {requirementSource !== 'upstream' && req.validation_message ? (
                                    <p style={{ margin: '0 0 0.75rem 0', color: '#6b7280', fontSize: '0.8rem', lineHeight: 1.5 }}>
                                      {req.validation_message}
                                      {req.filename_example ? ` Example: ${req.filename_example}` : ''}
                                    </p>
                                  ) : null}
                                  
                                  {requirementSource === 'upstream' ? (
                                    <p style={{ color: '#6b7280', fontStyle: 'italic', fontSize: '0.875rem', padding: '0.5rem', backgroundColor: '#eff6ff', borderRadius: '4px' }}>
                                      This input will be automatically provided by {req.source_tool}. No file selection needed.
                                    </p>
                                  ) : compatibleFiles.length === 0 ? (
                                    <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                                      No compatible files found. Upload files with formats: {req.formats.join(', ').toUpperCase()}
                                      {req.filename_example ? ` and names like ${req.filename_example}` : ''}
                                    </p>
                                  ) : (
                                    <div style={sharedRequirementCardStyle}>
                                      {compatibleFiles.map((file) => {
                                        const isSelected = mappedFileIds.includes(file.id)
                                        const isPendingLocalFile = file.id < 0
                                        return (
                                          <button
                                            key={file.id}
                                            type="button"
                                            onClick={() => handleToolFileMapping(toolReq.tool_index, req.type, file.id)}
                                            disabled={creating}
                                            style={{
                                              padding: '0.5rem 1rem',
                                              borderRadius: '4px',
                                              border: `2px solid ${isSelected ? '#27548A' : (isPendingLocalFile ? '#DDA853' : '#d9c8a4')}`,
                                              backgroundColor: isSelected ? '#f1e5cf' : (isPendingLocalFile ? '#fbf1d9' : '#F5EEDC'),
                                              color: isSelected ? '#183B4E' : '#374151',
                                              cursor: creating ? 'not-allowed' : 'pointer',
                                              fontSize: '0.875rem',
                                              fontWeight: isSelected ? '600' : '400',
                                              display: 'flex',
                                              alignItems: 'center',
                                              gap: '0.5rem',
                                              whiteSpace: 'nowrap',
                                              transition: 'all 0.2s ease'
                                            }}
                                            title={file.folderPath ? `${file.folderPath}/${file.filename}` : file.filename}
                                          >
                                            {isSelected && <span>✓</span>}
                                            <span>{file.filename}</span>
                                            {file.folderPath && (
                                              <span style={{ color: '#6b7280', fontSize: '0.75rem' }}>
                                                ({file.folderPath})
                                              </span>
                                            )}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  )}
                                </div>
                              )
                            })
                          )}
                        </div>
                      )
                    })
                  })()}
                </div>
              ) : (
                <p style={{ color: '#666', fontStyle: 'italic' }}>
                  Select tools above to see their input requirements.
                </p>
              )}
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
              onClick={() => navigate('/')}
              className="btn-secondary"
              disabled={creating}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={creating}
            >
              {creating ? (submitStatus || 'Creating job...') : 'Create Job'}
            </button>
          </div>
        </form>
        </div>
      </div>
    </div>
  )
}
