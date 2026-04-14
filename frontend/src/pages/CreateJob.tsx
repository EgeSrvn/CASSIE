import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { createJob, JobCreate, executeJob, getAvailableVMs, VM } from '../services/jobService'
import {
  getAvailableTools,
  Tool,
  getToolRequirements,
  ToolRequirementInfo,
  getRecommendationIntents,
  getPipelineRecommendations,
  RecommendationIntent,
  RecommendationOption,
} from '../services/toolService'
import { getPipelines, Pipeline, getPipelineRequirements, PipelineRequirements } from '../services/pipelineService'
import { getDataFileTree } from '../services/dataFileService'
import { FolderTreeItem, FileItem } from '../services/folderService'
import { getToken } from '../services/authService'
import { PendingJobUploadFile, enqueuePendingJobUploads } from '../services/pendingJobUploadService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

const formatVmCpu = (cpuMillis: number): string => `${(cpuMillis / 1000).toFixed(2)} cores`
const formatVmMemory = (memoryMib: number): string => `${(memoryMib / 1024).toFixed(2)} GiB`
const formatVmStorage = (storageMib: number): string => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'
const formatVmSlots = (vm: VM): string => `${vm.available_job_slots}/${vm.max_jobs} jobs available`

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
  const [toolRequirements, setToolRequirements] = useState<ToolRequirementInfo[]>([])
  const [loadingToolRequirements, setLoadingToolRequirements] = useState(false)
  const [toolFileMappings, setToolFileMappings] = useState<Record<string, Record<string, number[]>>>({}) // Maps tool_index -> requirement_type -> file_id[]
  const [recommendationIntents, setRecommendationIntents] = useState<RecommendationIntent[]>([])
  const [selectedIntentIds, setSelectedIntentIds] = useState<string[]>([])
  const [recommendationFileIds, setRecommendationFileIds] = useState<number[]>([])
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationOption[]>([])
  const [loadingRecommendations, setLoadingRecommendations] = useState(false)
  const [appliedRecommendationFileIds, setAppliedRecommendationFileIds] = useState<number[] | null>(null)
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

  const handleIntentToggle = (intentId: string) => {
    setSelectedIntentIds(prev => (
      prev.includes(intentId)
        ? prev.filter(id => id !== intentId)
        : [...prev, intentId]
    ))
  }

  const activeToolRequirementCards = selectionMode === 'pipeline'
    ? (pipelineRequirements?.tool_requirements || [])
    : toolRequirements

  // Fetch tool requirements when tools are selected
  useEffect(() => {
    if (selectionMode === 'pipeline') {
      setToolRequirements(pipelineRequirements?.tool_requirements || [])
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
  }, [selectionMode, selectedTools, pipelineRequirements])

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
    requirement: { formats: string[] }
  ): boolean => {
    const normalizedFormats = new Set(normalizeFileFormats(file))
    return requirement.formats.some(format => normalizedFormats.has(format.toLowerCase()))
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
    if ((selectionMode === 'tools' && selectedTools.length > 0) || (selectionMode === 'pipeline' && activeToolRequirementCards.length > 0)) {
      const missingRequirements: string[] = []
      activeToolRequirementCards.forEach(toolReq => {
        toolReq.requirements.forEach(req => {
          if (!req.is_intermediate) {
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

    if (selectionMode === 'pipeline' && !selectedPipelineId) {
      setError('Please select a pipeline')
      return
    }

    // Collect all mapped files from visible tool requirements
    const fileIdSet = new Set<number>()
    activeToolRequirementCards.forEach(toolReq => {
      toolReq.requirements.forEach(req => {
        if (!req.is_intermediate) {
          const toolKey = toolReq.tool_index.toString()
          const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
          mappedFileIds.forEach(fileId => fileIdSet.add(fileId))
        }
      })
    })
    const uploadedFileIds = Array.from(fileIdSet)

    if (selectionMode === 'pipeline' && activeToolRequirementCards.length === 0) {
      setError('The selected pipeline has no supported tools available for job creation')
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

      if (selectionMode === 'pipeline') {
        if (!selectedPipelineId) {
          setError('Please select a pipeline')
          setCreating(false)
          return
        }
        jobData.pipeline_id = selectedPipelineId
      } else {
        if (selectedTools.length === 0) {
          setError('Please select at least one tool')
          setCreating(false)
          return
        }
        jobData.tool_indices = selectedTools
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
              <label>Pipeline Tools</label>
              {loadingRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading requirements...</p>
              ) : pipelineRequirements ? (
                <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#f9fafb' }}>
                  <p style={{ marginBottom: '0.75rem', color: '#666', fontSize: '0.875rem' }}>
                    This pipeline will use the same tool/input configuration flow as normal tool selection.
                  </p>
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

          {/* Tool Input Requirements Section */}
          {activeToolRequirementCards.length > 0 && (
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
                              // Filter files that match the requirement format
                              const compatibleFiles = combinedFiles.filter(file => fileMatchesRequirement(file, req))
                              
                              return (
                                <div key={req.type} style={{ marginBottom: '1.5rem' }}>
                                  <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <strong>{req.label}</strong>
                                    <span style={{ color: '#666', fontSize: '0.875rem' }}>
                                      ({req.formats.join(', ').toUpperCase()})
                                    </span>
                                    {req.is_intermediate ? (
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
                                  
                                  {req.is_intermediate ? (
                                    <p style={{ color: '#6b7280', fontStyle: 'italic', fontSize: '0.875rem', padding: '0.5rem', backgroundColor: '#eff6ff', borderRadius: '4px' }}>
                                      This input will be automatically provided by {req.source_tool}. No file selection needed.
                                    </p>
                                  ) : compatibleFiles.length === 0 ? (
                                    <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                                      No compatible files found. Upload files with formats: {req.formats.join(', ').toUpperCase()}
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
                                              border: `2px solid ${isSelected ? '#2563eb' : (isPendingLocalFile ? '#3b82f6' : '#e5e7eb')}`,
                                              backgroundColor: isSelected ? '#eff6ff' : (isPendingLocalFile ? '#f0f9ff' : 'white'),
                                              color: isSelected ? '#2563eb' : '#374151',
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
