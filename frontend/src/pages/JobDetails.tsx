import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getJob,
  Job,
  JobExecution,
  JobPipelineVisualization,
  executeJob,
  getJobExecutions,
  getJobPipelineVisualization,
  getAvailableVMs,
  VM,
  cancelJob,
  retryJob,
} from '../services/jobService'
import {
  getFiles,
  File,
  downloadFile,
  getFileViewUrl,
  requestJobOutputsZip,
  getJobOutputsZipStatus,
  openJobOutputsZipLink,
  JobOutputsZipStatus,
} from '../services/fileService'
import { getPipelineRequirements, PipelineRequirements } from '../services/pipelineService'
import {
  getJobUploadStatus,
  JobUploadStatus,
  PendingQueuedJobFile,
  clearPendingJobUploads,
  getPendingJobUploadFiles,
  startPendingJobUploadProcessor,
  subscribeToJobUploadStatus
} from '../services/pendingJobUploadService'
import { formatDurationClock, formatLocalDateTime } from '../utils/dateTime'
import Navigation from '../components/Navigation'
import PipelineVisualization from '../components/PipelineVisualization'
import '../styles/globals.css'

const formatVmCpu = (cpuMillis: number): string => `${(cpuMillis / 1000).toFixed(2)} cores`
const formatVmMemory = (memoryMib: number): string => `${(memoryMib / 1024).toFixed(2)} GiB`
const formatVmStorage = (storageMib: number): string => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'
const formatVmSlots = (vm: VM): string => `${vm.available_job_slots}/${vm.max_jobs} jobs available`

type JobDetailTab = 'information' | 'pipeline' | 'tracking' | 'resources' | 'inputs' | 'outputs'

const JOB_DETAIL_TABS: Array<{ id: JobDetailTab; label: string; description: string }> = [
  { id: 'information', label: 'Job Information', description: 'Overview, status, selected VM, and launch actions.' },
  { id: 'pipeline', label: 'Pipeline Visualization', description: 'Stage map of how the job will flow from inputs to outputs.' },
  { id: 'tracking', label: 'Execution Tracking', description: 'Per-run history, stage progress, and execution timing.' },
  { id: 'resources', label: 'Active Resource Usage', description: 'Live CPU, memory, and storage use against VM capacity.' },
  { id: 'inputs', label: 'Input Files', description: 'Files queued or attached to this job before execution.' },
  { id: 'outputs', label: 'Output Files', description: 'Generated artifacts, previews, and ZIP export actions.' },
]

export default function JobDetails() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<Job | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [executions, setExecutions] = useState<JobExecution[]>([])
  const [outputFilesCollapsed, setOutputFilesCollapsed] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [pipelineRequirements, setPipelineRequirements] = useState<PipelineRequirements | null>(null)
  const [loadingRequirements, setLoadingRequirements] = useState(false)
  const [selectedOutputFamily, setSelectedOutputFamily] = useState<string | null>(null)
  const [selectedOutputIndex, setSelectedOutputIndex] = useState<number>(0)
  const [viewingFile, setViewingFile] = useState<File | null>(null)
  const [viewingFileUrl, setViewingFileUrl] = useState<string | null>(null)
  const [viewingTextContent, setViewingTextContent] = useState<string | null>(null)
  const viewingFileUrlRef = useRef<string | null>(null)
  const [htmlZoom, setHtmlZoom] = useState<number>(0.75)
  const [, setClockTick] = useState(0)
  const [jobUploadStatus, setJobUploadStatus] = useState<JobUploadStatus | null>(null)
  const [pendingQueuedFiles, setPendingQueuedFiles] = useState<PendingQueuedJobFile[]>([])
  const [availableVMs, setAvailableVMs] = useState<VM[]>([])
  const [zipPanelVisible, setZipPanelVisible] = useState(false)
  const [zipStatus, setZipStatus] = useState<JobOutputsZipStatus | null>(null)
  const [zipStatusError, setZipStatusError] = useState('')
  const [startingZipGeneration, setStartingZipGeneration] = useState(false)
  const [jobPipeline, setJobPipeline] = useState<JobPipelineVisualization | null>(null)
  const [activeTab, setActiveTab] = useState<JobDetailTab>('information')
  const [cancellingJob, setCancellingJob] = useState(false)
  const [preparingRetry, setPreparingRetry] = useState(false)
  const [retryName, setRetryName] = useState('')
  const [retryVM, setRetryVM] = useState('')

  useEffect(() => {
    if (jobId) {
      loadJob()
      loadFiles()
      loadExecutions()
      loadJobPipeline()
    }
    // No auto-refresh - users can manually refresh if needed
  }, [jobId])

  // Load pipeline requirements if job has a pipeline_id
  useEffect(() => {
    if (!job) {
      setPipelineRequirements(null)
      return
    }

    if (job.pipeline_id) {
      const loadRequirements = async () => {
        try {
          setLoadingRequirements(true)
          const requirements = await getPipelineRequirements(job.pipeline_id!)
          setPipelineRequirements(requirements)
        } catch (err) {
          console.error('Failed to load pipeline requirements:', err)
          setPipelineRequirements(null)
        } finally {
          setLoadingRequirements(false)
        }
      }
      loadRequirements()
    } else {
      setPipelineRequirements(null)
    }
  }, [job])

  useEffect(() => {
    if (!job) return
    setRetryName(job.name)
    setRetryVM(job.vm_name || '')
  }, [job?.id, job?.name, job?.vm_name])

  const loadJob = async () => {
    if (!jobId) return
    try {
      const jobData = await getJob(parseInt(jobId))
      setJob(jobData)
      setError('') // Clear any previous errors
    } catch (err: any) {
      console.error('Failed to load job:', err)
      const errorMsg = err.response?.data?.message || err.message || 'Failed to load job details'
      setError(errorMsg)
      setJob(null) // Ensure job is null so "Job not found" message shows
    } finally {
      setLoading(false)
    }
  }

  const loadFiles = async () => {
    if (!jobId) return
    try {
      // Fetch all files for this job (use large per_page to get all files)
      const response = await getFiles(parseInt(jobId), undefined, 1, 1000)
      setFiles(response.data || [])
    } catch (err) {
      console.error('Failed to load files:', err)
    }
  }

  const loadExecutions = async () => {
    if (!jobId) return
    try {
      const executionData = await getJobExecutions(parseInt(jobId))
      setExecutions(executionData)
    } catch (err) {
      console.error('Failed to load executions:', err)
    }
  }

  const loadJobPipeline = async () => {
    if (!jobId) return
    try {
      const visualization = await getJobPipelineVisualization(parseInt(jobId))
      setJobPipeline(visualization)
    } catch (err) {
      console.error('Failed to load job pipeline visualization:', err)
      setJobPipeline(null)
    }
  }

  const loadPendingQueuedFiles = async () => {
    if (!jobId) return
    try {
      const queuedFiles = await getPendingJobUploadFiles(parseInt(jobId))
      setPendingQueuedFiles(queuedFiles)
    } catch (err) {
      console.error('Failed to load pending queued files:', err)
    }
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockTick(value => value + 1)
    }, 1000)

    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!jobId) return

    const hasActiveExecution = job?.status === 'running' || executions.some(execution => execution.status === 'running')
    const hasQueuedExecution = executions.some(execution =>
      execution.status === 'pending' && String(execution.parameters_used?.queue_state || '').trim().toLowerCase() === 'waiting_for_vm_slot'
    )
    const hasActiveUpload = !!jobUploadStatus
    if (!hasActiveExecution && !hasQueuedExecution && !hasActiveUpload) return

    const poller = window.setInterval(() => {
      loadJob()
      loadFiles()
      loadExecutions()
      loadJobPipeline()
    }, 5000)

    return () => window.clearInterval(poller)
  }, [jobId, job?.status, executions, jobUploadStatus])

  useEffect(() => {
    if (!jobId) return

    const numericJobId = parseInt(jobId)
    setJobUploadStatus(getJobUploadStatus(numericJobId))
    void loadPendingQueuedFiles()
    void startPendingJobUploadProcessor()

    return subscribeToJobUploadStatus((changedJobId, status) => {
      if (changedJobId !== numericJobId) return
      setJobUploadStatus(status)
      void loadPendingQueuedFiles()
      if (!status) {
        void loadJob()
        void loadFiles()
        void loadExecutions()
        void loadJobPipeline()
      }
    })
  }, [jobId])

  useEffect(() => {
    if (!jobId || !jobUploadStatus || !job || job.status === 'pending') {
      return
    }

    void clearPendingJobUploads(parseInt(jobId))
  }, [jobId, job?.status, jobUploadStatus])

  useEffect(() => {
    const loadVMs = async () => {
      try {
        const vms = await getAvailableVMs()
        setAvailableVMs(vms)
      } catch (err) {
        console.error('Failed to load VMs:', err)
        setAvailableVMs([])
      }
    }

    void loadVMs()
  }, [])

  // Compute files before early returns (will be empty arrays initially)
  const inputFiles = (files || []).filter(f => f && f.file_type === 'input')
  const outputFiles = (files || []).filter(f => f && (f.file_type === 'output' || f.file_type === 'log'))
  const logFiles = outputFiles.filter((file) => file.file_type === 'log')
  const visibleInputCount = inputFiles.length + pendingQueuedFiles.length
  const selectedVMDetails = job?.vm_name ? availableVMs.find(vm => vm.name === job.vm_name) || null : null
  const latestExecution = executions.length > 0 ? executions[0] : null
  const activeTabDetails = JOB_DETAIL_TABS.find((tab) => tab.id === activeTab) || JOB_DETAIL_TABS[0]
  const hasWaitingCheckpoint = executions.some((execution) =>
    execution.status === 'running' &&
    (execution.parameters_used?.stages || []).some((stage) => stage.status === 'waiting_for_checkpoint')
  )
  const latestQueuePosition = (
    latestExecution?.status === 'pending' &&
    String(latestExecution.parameters_used?.queue_state || '').trim().toLowerCase() === 'waiting_for_vm_slot' &&
    typeof latestExecution.parameters_used?.queue_position === 'number'
  ) ? latestExecution.parameters_used.queue_position : null

  const activeStages = (latestExecution?.parameters_used?.stages || []).filter(stage => stage.status === 'running')
  const activeCpuMillis = activeStages.reduce((sum, stage) => {
    const stageCpu = typeof stage.cpu_limit_millis === 'number' && stage.cpu_limit_millis > 0
      ? stage.cpu_limit_millis
      : (stage.threads || 0) * 1000
    return sum + stageCpu
  }, 0)
  const activeMemoryMib = activeStages.reduce((sum, stage) => sum + (stage.memory_limit_mib || 0), 0)
  const activeStorageMib = activeStages.reduce((sum, stage) => sum + (stage.storage_limit_mib || 0), 0)
  const resourceLimits = {
    cpuMillis: selectedVMDetails?.available_cpu_millis || Math.max(activeCpuMillis, 0),
    memoryMib: selectedVMDetails?.available_memory_mib || Math.max(activeMemoryMib, 0),
    storageMib: selectedVMDetails?.available_storage_mib || Math.max(activeStorageMib, 0),
  }
  const resourcePercent = (used: number, limit: number): number => (
    limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  )

  const fileMatchesRequirement = (
    filename: string,
    formats: string[],
    declaredFormat?: string | null
  ): boolean => {
    const lowerName = filename.toLowerCase()
    const normalizedDeclaredFormat = (declaredFormat || '').toLowerCase()
    return formats.some(format => {
      const normalizedFormat = format.toLowerCase()
      const compressedFormat = normalizedFormat.endsWith('.gz') ? normalizedFormat : `${normalizedFormat}.gz`
      const baseFormat = normalizedFormat.replace(/\.gz$/, '')
      return (
        normalizedDeclaredFormat === normalizedFormat ||
        normalizedDeclaredFormat === compressedFormat ||
        normalizedDeclaredFormat === baseFormat ||
        lowerName.endsWith(`.${normalizedFormat}`) ||
        lowerName.endsWith(`.${compressedFormat}`) ||
        lowerName.endsWith(`.${baseFormat}`)
      )
    })
  }

  // Group output files by tool family
  const groupOutputsByFamily = (files: File[]) => {
    const groups: Record<string, File[]> = {}
    
    if (!files || files.length === 0) {
      return groups
    }
    
    files.forEach(file => {
      if (!file || !file.filename) return
      
      const filename = file.filename.toLowerCase()
      let family = 'Other'
      
      // Determine tool family based on filename patterns
      if (file.file_type === 'log') {
        family = 'Logs'
      } else if (filename.includes('fastqc')) {
        family = 'FastQC'
      } else if (filename.includes('metaspades')) {
        family = 'metaSPAdes'
      } else if (filename.includes('spades') || filename.includes('contigs') || filename.includes('scaffolds')) {
        family = 'SPAdes'
      } else if (filename.includes('hifiasm')) {
        family = 'Hifiasm'
      } else if (filename.includes('verkko')) {
        family = 'Verkko'
      } else if (filename.includes('quast')) {
        family = 'QUAST'
      } else if (filename.includes('genomescope') || filename.includes('genomescope2')) {
        family = 'GenomeScope2'
      } else if (filename.includes('liftoff')) {
        family = 'Liftoff'
      } else if (filename.includes('cat_') || filename.includes('/cat') || filename.includes('comparative')) {
        family = 'CAT'
      } else if (filename.includes('busco')) {
        family = 'BUSCO'
      } else if (filename.includes('merqury') || filename.includes('.qv')) {
        family = 'Merqury'
      }
      
      if (!groups[family]) {
        groups[family] = []
      }
      groups[family].push(file)
    })
    
    return groups
  }

  // Group outputs by family - compute directly to avoid dependency issues
  const outputGroups = outputFiles && outputFiles.length > 0 ? groupOutputsByFamily(outputFiles) : {}
  const outputFamilies = Object.keys(outputGroups).sort()
  const interactiveOutputsEnabled = job?.interactive_outputs_enabled !== false

  const isViewable = (file: File): boolean => {
    const filename = file.filename.toLowerCase()
    return filename.endsWith('.html') ||
           filename.endsWith('.txt') ||
           filename.endsWith('.log') ||
           filename.endsWith('.png') ||
           filename.endsWith('.jpg') ||
           filename.endsWith('.jpeg') ||
           filename.endsWith('.gif') ||
           filename.endsWith('.svg') ||
           filename.endsWith('.pdf')
  }

  // Initialize selected family and index - MUST be before early returns
  useEffect(() => {
    if (!interactiveOutputsEnabled) {
      setSelectedOutputFamily(null)
      setSelectedOutputIndex(0)
      setViewingFile(null)
      setZipPanelVisible(false)
      return
    }

    if (outputFiles && outputFiles.length > 0) {
      const families = Object.keys(groupOutputsByFamily(outputFiles)).sort()
      if (families.length > 0 && !selectedOutputFamily) {
        setSelectedOutputFamily(families[0])
        setSelectedOutputIndex(0)
      }
    } else if (selectedOutputFamily) {
      // Reset if no output files
      setSelectedOutputFamily(null)
      setSelectedOutputIndex(0)
    }
  }, [interactiveOutputsEnabled, outputFiles.length, selectedOutputFamily])

  const currentFamilyFiles = selectedOutputFamily && outputGroups[selectedOutputFamily] ? outputGroups[selectedOutputFamily] : []
  const viewableFiles = currentFamilyFiles.filter(isViewable)
  const inputFilesPendingUpload = job?.status === 'pending' && !!jobUploadStatus

  useEffect(() => {
    if (!interactiveOutputsEnabled) {
      setViewingFile(null)
      return
    }

    if (!selectedOutputFamily || !outputGroups[selectedOutputFamily]) {
      setViewingFile(null)
      return
    }

    const familyFiles = outputGroups[selectedOutputFamily] || []
    const viewable = familyFiles.filter(isViewable)

    if (viewable.length > 0) {
      const validIndex = Math.max(0, Math.min(selectedOutputIndex, viewable.length - 1))
      const targetFile = viewable[validIndex]
      setViewingFile(prev => (!prev || prev.id !== targetFile.id ? targetFile : prev))
    } else {
      setViewingFile(null)
    }
  }, [interactiveOutputsEnabled, selectedOutputIndex, selectedOutputFamily, outputFiles.length])

  useEffect(() => {
    if (!interactiveOutputsEnabled || !viewingFile || !isViewable(viewingFile)) {
      if (viewingFileUrlRef.current) {
        window.URL.revokeObjectURL(viewingFileUrlRef.current)
        viewingFileUrlRef.current = null
      }
      setViewingFileUrl(null)
      setViewingTextContent(null)
      return
    }

    let cancelled = false

    getFileViewUrl(viewingFile.id)
      .then(url => {
        if (cancelled) {
          window.URL.revokeObjectURL(url)
          return
        }
        if (viewingFileUrlRef.current) {
          window.URL.revokeObjectURL(viewingFileUrlRef.current)
        }
        viewingFileUrlRef.current = url
        setViewingFileUrl(url)
      })
      .catch(err => {
        console.error('Failed to load file view URL:', err)
        if (viewingFileUrlRef.current) {
          window.URL.revokeObjectURL(viewingFileUrlRef.current)
          viewingFileUrlRef.current = null
        }
        setViewingFileUrl(null)
        setViewingTextContent(null)
      })

    return () => {
      cancelled = true
    }
  }, [interactiveOutputsEnabled, viewingFile?.id])

  useEffect(() => {
    if (!jobId || !interactiveOutputsEnabled || !zipPanelVisible) return

    let cancelled = false

    const loadZipStatus = async () => {
      try {
        const status = await getJobOutputsZipStatus(parseInt(jobId))
        if (!cancelled) {
          setZipStatus(status)
          setZipStatusError('')
        }
      } catch (err: any) {
        if (!cancelled) {
          setZipStatusError(err.response?.data?.message || err.message || 'Failed to load ZIP status')
        }
      }
    }

    void loadZipStatus()

    const shouldPoll = zipStatus?.status === 'queued' || zipStatus?.status === 'processing' || zipStatus === null
    if (!shouldPoll) {
      return () => {
        cancelled = true
      }
    }

    const poller = window.setInterval(() => {
      void loadZipStatus()
    }, 3000)

    return () => {
      cancelled = true
      window.clearInterval(poller)
    }
  }, [jobId, interactiveOutputsEnabled, zipPanelVisible, zipStatus?.status])

  useEffect(() => {
    if (!viewingFileUrl || !viewingFile) {
      setViewingTextContent(null)
      return
    }

    const lowerName = viewingFile.filename.toLowerCase()
    if (!lowerName.endsWith('.txt') && !lowerName.endsWith('.log')) {
      setViewingTextContent(null)
      return
    }

    let cancelled = false
    fetch(viewingFileUrl)
      .then((response) => response.text())
      .then((text) => {
        if (!cancelled) {
          setViewingTextContent(text)
        }
      })
      .catch((err) => {
        console.error('Failed to load text preview:', err)
        if (!cancelled) {
          setViewingTextContent('Failed to load text preview.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [viewingFileUrl, viewingFile])

  useEffect(() => {
    return () => {
      if (viewingFileUrlRef.current) {
        window.URL.revokeObjectURL(viewingFileUrlRef.current)
        viewingFileUrlRef.current = null
      }
    }
  }, [])

  const currentViewingFile = viewingFile || (viewableFiles.length > 0 && selectedOutputIndex >= 0 && selectedOutputIndex < viewableFiles.length ? viewableFiles[selectedOutputIndex] : null)

  const handleDownload = async (file: File) => {
    try {
      await downloadFile(file.id)
    } catch (err: any) {
      console.error('Download error:', err)
      const errorMsg = err.message || 'Failed to download file'
      alert(`Failed to download file: ${errorMsg}`)
    }
  }

  const handlePrepareZip = async () => {
    if (!jobId) return

    try {
      setZipPanelVisible(true)
      setStartingZipGeneration(true)
      setZipStatusError('')
      const status = await requestJobOutputsZip(parseInt(jobId))
      setZipStatus(status)
    } catch (err: any) {
      console.error('Failed to start ZIP generation:', err)
      setZipStatusError(err.response?.data?.message || err.message || 'Failed to start ZIP generation')
    } finally {
      setStartingZipGeneration(false)
    }
  }

  const handleOpenZipLink = () => {
    if (!jobId || !zipStatus) return
    try {
      openJobOutputsZipLink(zipStatus, parseInt(jobId))
    } catch (err: any) {
      setZipStatusError(err.message || 'ZIP download link is not ready yet')
    }
  }

  const refreshJobData = async () => {
    await Promise.all([
      loadJob(),
      loadFiles(),
      loadExecutions(),
      loadJobPipeline(),
    ])
  }

  const handleCancelJob = async () => {
    if (!jobId || !job) return
    if (!confirm('Cancel this job? Running Kubernetes stages will be stopped, but the job record will stay here.')) return

    try {
      setCancellingJob(true)
      setError('')
      await cancelJob(parseInt(jobId))
      await clearPendingJobUploads(parseInt(jobId))
      await refreshJobData()
    } catch (err: any) {
      setError(err.message || 'Failed to cancel job')
    } finally {
      setCancellingJob(false)
    }
  }

  const handlePrepareRetry = async () => {
    if (!jobId) return

    try {
      setPreparingRetry(true)
      setError('')
      const updatedJob = await retryJob(parseInt(jobId), {
        name: retryName.trim() || job?.name,
        vm_name: retryVM || undefined,
      })
      setJob(updatedJob)
      await refreshJobData()
      setActiveTab('information')
    } catch (err: any) {
      setError(err.message || 'Failed to prepare job retry')
    } finally {
      setPreparingRetry(false)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'status-completed'
      case 'running': return 'status-running'
      case 'failed': return 'status-failed'
      case 'pending': return 'status-pending'
      case 'cancelled': return 'status-failed'
      case 'waiting_for_dependencies': return 'status-pending'
      case 'waiting_for_resources': return 'status-pending'
      case 'waiting_for_checkpoint': return 'status-pending'
      default: return ''
    }
  }

  const formatExecutionStatusLabel = (execution: JobExecution) => {
    const queueState = String(execution.parameters_used?.queue_state || '').trim().toLowerCase()
    const queuePosition = execution.parameters_used?.queue_position
    if (execution.status === 'pending' && queueState === 'waiting_for_vm_slot') {
      return typeof queuePosition === 'number' && queuePosition > 0
        ? `queued (#${queuePosition})`
        : 'queued'
    }
    return execution.status
  }

  const formatStageStatusLabel = (status: string) => {
    switch (status) {
      case 'waiting_for_dependencies':
        return 'waiting for dependencies'
      case 'waiting_for_resources':
        return 'waiting for resources'
      case 'waiting_for_checkpoint':
        return 'waiting for checkpoint'
      default:
        return status
    }
  }

  const getCurrentStage = (execution: JobExecution) => {
    const stages = execution.parameters_used?.stages || []
    const runningStage = stages.find(stage => stage.status === 'running')
    if (runningStage) return runningStage

    const resourceWaitingStage = stages.find(stage => stage.status === 'waiting_for_resources')
    if (resourceWaitingStage) return resourceWaitingStage

    const checkpointWaitingStage = stages.find(stage => stage.status === 'waiting_for_checkpoint')
    if (checkpointWaitingStage) return checkpointWaitingStage

    const dependencyWaitingStage = stages.find(stage => stage.status === 'waiting_for_dependencies')
    if (dependencyWaitingStage) return dependencyWaitingStage

    if (execution.status === 'running') {
      const pendingStage = stages.find(stage => stage.status === 'pending')
      if (pendingStage) return pendingStage
    }

    const failedStage = stages.find(stage => stage.status === 'failed')
    if (failedStage) return failedStage

    const completedStages = stages.filter(stage => stage.status === 'completed')
    return completedStages.length > 0 ? completedStages[completedStages.length - 1] : null
  }

  const getCurrentStageLabel = (execution: JobExecution) => {
    const stage = getCurrentStage(execution)
    if (!stage) {
      const queueState = String(execution.parameters_used?.queue_state || '').trim().toLowerCase()
      const queuePosition = execution.parameters_used?.queue_position
      if (execution.status === 'pending' && queueState === 'waiting_for_vm_slot') {
        return typeof queuePosition === 'number' && queuePosition > 0
          ? `Queued on ${job?.vm_name || 'selected VM'} at position ${queuePosition}`
          : 'Queued for the selected VM'
      }
      return null
    }

    const toolName = stage.tool_name || stage.tool_id
    if (stage.status === 'running') return `Current Tool: ${toolName}`
    if (stage.status === 'waiting_for_resources') return `Waiting for resources to run: ${toolName}`
    if (stage.status === 'waiting_for_checkpoint') return `Waiting for checkpoint resume before: ${toolName}`
    if (stage.status === 'waiting_for_dependencies') return `Waiting for previous tools before: ${toolName}`
    if (stage.status === 'pending') return `Next Tool: ${toolName}`
    if (stage.status === 'failed') return `Failed Tool: ${toolName}`
    if (stage.status === 'completed' && execution.status === 'completed') return `Last Completed Tool: ${toolName}`
    return `Tool: ${toolName}`
  }

  const getExecutionProgressPercent = (execution: JobExecution): number | null => {
    const stages = execution.parameters_used?.stages || []
    if (stages.length === 0) return null

    const completedStages = stages.filter(stage => stage.status === 'completed').length
    const activeStages = stages.filter(stage => (
      stage.status === 'running' ||
      stage.status === 'waiting_for_resources' ||
      stage.status === 'waiting_for_checkpoint'
    )).length
    const progressUnits = Math.min(stages.length, completedStages + (activeStages > 0 ? 0.5 : 0))
    return Math.round((progressUnits / stages.length) * 100)
  }

  const getPipelineRequirementTools = (req: { type: string; used_by?: string[] }): string[] => {
    if (req.used_by && req.used_by.length > 0) return req.used_by
    if (req.type === 'forward_reads' || req.type === 'reverse_reads') return ['SPAdes']
    if (req.type === 'assembly' || req.type === 'reference') return ['QUAST']
    if (req.type === 'annotation') return ['Liftoff', 'CAT']
    if (req.type === 'hal_alignment') return ['CAT']
    if (req.type === 'reference_annotation') return ['CAT']
    if (req.type === 'reference_genome_name') return ['CAT']
    if (req.type === 'read_kmer_db') return ['Merqury']
    if (req.type === 'target_genome' || req.type === 'reference_genome') return ['Liftoff']
    if (req.type === 'hifi_reads') return ['Hifiasm', 'Verkko']
    if (req.type === 'reads') {
      const tools: string[] = []
      if (pipelineRequirements?.has_fastqc) tools.push('FastQC')
      if (pipelineRequirements?.has_genomescope2) tools.push('GenomeScope2')
      return tools.length > 0 ? tools : ['Read-based tools']
    }
    return ['Selected pipeline']
  }

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <p>Loading job details...</p>
        </div>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <div className="error-message">Job not found</div>
          <button onClick={() => navigate('/')} className="btn-primary">
            Back to Home
          </button>
        </div>
      </div>
    )
  }

  // Check if required files are present
  const canExecute = (() => {
    if (hasWaitingCheckpoint) return true
    if (job.status !== 'pending') return false
    if (inputFilesPendingUpload) return false
    if (visibleInputCount === 0) return false
    
    // For pipeline-based jobs, check if all requirements are met
    if (pipelineRequirements && pipelineRequirements.input_requirements.length > 0) {
      return inputFiles.length >= pipelineRequirements.input_requirements.length
    }
    
    // For tool-based jobs, at least one file is required (already checked above)
    return true
  })()

  const getExecuteButtonMessage = () => {
    if (hasWaitingCheckpoint) {
      return 'Resume the branches currently waiting at checkpoint blocks.'
    }
    if (job.status !== 'pending') return null
    if (inputFilesPendingUpload) {
      return jobUploadStatus?.message || 'Selected files are still uploading for this job.'
    }
    if (visibleInputCount === 0) {
      return 'This job has no input files configured. Files must be added during job creation.'
    }
    if (pipelineRequirements && pipelineRequirements.input_requirements.length > 0) {
      const missing = pipelineRequirements.input_requirements.length - inputFiles.length
      if (missing > 0) {
        return `Missing ${missing} required file(s). This pipeline requires ${pipelineRequirements.input_requirements.length} input file(s).`
      }
    }
    return null
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content">
        <header className="page-header">
          <h1 className="page-title">Job Details: {job.name}</h1>
          <div className="header-actions">
            <button onClick={() => { loadJob(); loadFiles(); loadExecutions(); loadJobPipeline(); }} className="btn-secondary">
              Refresh
            </button>
            <button onClick={() => navigate('/')} className="btn-secondary">
              Back to Home
            </button>
          </div>
        </header>

        {error && <div className="error-message">{error}</div>}
        <div className="builder-stepper" style={{ marginBottom: '1.25rem' }}>
          {JOB_DETAIL_TABS.map((tab, index) => (
            <button
              key={tab.id}
              type="button"
              className={`builder-step ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="builder-step-number">{index + 1}</span>
              <span className="builder-step-copy">
                <strong>{tab.label}</strong>
                <small>{tab.description}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="builder-level-header">
          <div>
            <p className="builder-level-kicker">Stage {JOB_DETAIL_TABS.findIndex((tab) => tab.id === activeTabDetails.id) + 1}</p>
            <h2>{activeTabDetails.label}</h2>
          </div>
          <p>{activeTabDetails.description}</p>
        </div>
        <div className="job-details-container">
          {activeTab === 'information' && (
          <div className="detail-section">
            <h2>Job Information</h2>
            <div className="detail-grid">
              <div><strong>Job ID:</strong> {job.id}</div>
              <div><strong>Status:</strong> 
                <div className="status-line">
                  <span className={`status-badge ${getStatusColor(job.status)}`}>
                    {job.status}
                  </span>
                  {latestQueuePosition && (
                    <span
                      className="inline-upload-status"
                      style={{
                        backgroundColor: '#fef3c7',
                        color: '#92400e',
                      }}
                    >
                      Queued #{latestQueuePosition}
                    </span>
                  )}
                  {jobUploadStatus && (
                    <span
                      className="inline-upload-status"
                      style={{
                        backgroundColor: jobUploadStatus.stage === 'failed' ? '#f0ded8' : '#dbeafe',
                        color: jobUploadStatus.stage === 'failed' ? '#7c4036' : '#1d4ed8',
                      }}
                    >
                      {jobUploadStatus.stage === 'starting'
                        ? 'Starting job'
                        : `Uploading files (${jobUploadStatus.uploadedFiles}/${jobUploadStatus.totalFiles}, ${jobUploadStatus.progress || 0}%)`}
                    </span>
                  )}
                </div>
                {(job.status === 'pending' || hasWaitingCheckpoint) && (
                  <>
                    {!jobUploadStatus && (
                      <button
                        onClick={async () => {
                          if (!jobId) return
                          try {
                            setExecuting(true)
                            setError('')
                            const result = await executeJob(parseInt(jobId))
                            await loadJob()
                            await loadFiles() // Refresh files after execution
                            await loadExecutions()
                            await loadJobPipeline()
                            alert(result.message || 'Job execution started successfully!')
                          } catch (err: any) {
                            setError(err.message || 'Failed to execute job')
                          } finally {
                            setExecuting(false)
                          }
                        }}
                        disabled={executing || !canExecute}
                        className="btn-primary"
                        style={{ marginTop: '10px' }}
                        title={getExecuteButtonMessage() || undefined}
                      >
                        {executing ? 'Executing...' : hasWaitingCheckpoint ? 'Resume Checkpointed Branches' : 'Execute Job'}
                      </button>
                    )}
                    {!jobUploadStatus && !canExecute && getExecuteButtonMessage() && (
                      <span style={{ display: 'inline-block', marginTop: '10px', color: '#DDA853', fontSize: '0.875rem' }}>
                        {getExecuteButtonMessage()}
                      </span>
                    )}
                  </>
                )}
                {(job.status === 'pending' || job.status === 'running') && (
                  <button
                    onClick={handleCancelJob}
                    disabled={cancellingJob}
                    className="btn-secondary"
                    style={{ marginTop: '10px', marginLeft: '0.5rem' }}
                  >
                    {cancellingJob ? 'Cancelling...' : 'Cancel Job'}
                  </button>
                )}
              </div>
              <div><strong>Workflow ID:</strong> {job.workflow_id}</div>
              {job.vm_name && (
                <div>
                  <strong>Virtual Machine:</strong> {job.vm_name}
                  {selectedVMDetails ? ` (${formatVmSlots(selectedVMDetails)})` : ''}
                </div>
              )}
              <div><strong>Created:</strong> {formatLocalDateTime(job.created_at)}</div>
              <div><strong>Updated:</strong> {formatLocalDateTime(job.updated_at)}</div>
              {jobUploadStatus?.error && (
                <div style={{ gridColumn: '1 / -1', color: '#a94442' }}>
                  <strong>Upload error:</strong> {jobUploadStatus.error}
                </div>
              )}
              {job.data_types && job.data_types.length > 0 && (
                <div><strong>Data Types:</strong> {job.data_types.join(', ')}</div>
              )}
            </div>
            {(job.status === 'failed' || job.status === 'cancelled') && (
              <div style={{ marginTop: '1rem', padding: '1rem', borderRadius: '8px', border: '1px solid #d9c7a5', backgroundColor: '#fffaf0' }}>
                <h3 style={{ marginTop: 0 }}>Retry Settings</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem', alignItems: 'end' }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontWeight: 600 }}>
                    Job name
                    <input
                      type="text"
                      value={retryName}
                      onChange={(event) => setRetryName(event.target.value)}
                      maxLength={100}
                    />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontWeight: 600 }}>
                    Virtual machine
                    <select value={retryVM} onChange={(event) => setRetryVM(event.target.value)}>
                      <option value="">Default VM</option>
                      {availableVMs.map(vm => (
                        <option key={vm.name} value={vm.name}>
                          {vm.display_name} ({formatVmSlots(vm)})
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={handlePrepareRetry}
                    disabled={preparingRetry || !retryName.trim()}
                    className="btn-primary"
                  >
                    {preparingRetry ? 'Preparing...' : 'Prepare Retry'}
                  </button>
                </div>
                <p style={{ marginBottom: 0, color: '#64748b', fontSize: '0.9rem' }}>
                  This keeps the job record and execution history, changes the editable settings above, and returns the job to pending so you can run it again.
                </p>
              </div>
            )}
            {selectedVMDetails && (
              <div style={{ marginTop: '1rem', padding: '0.875rem 1rem', borderRadius: '8px', backgroundColor: '#f1e5cf', border: '1px solid #d9c7a5' }}>
                <div style={{ fontWeight: 600, color: '#183B4E', marginBottom: '0.35rem' }}>
                  Per-job resource limits for {selectedVMDetails.display_name}
                </div>
                <div style={{ color: '#3e4e59', fontSize: '0.95rem', lineHeight: 1.6 }}>
                  Available slots: {selectedVMDetails.available_job_slots}/{selectedVMDetails.max_jobs}
                  {' | '}
                  CPU: {formatVmCpu(selectedVMDetails.available_cpu_millis)}
                  {' | '}
                  Memory: {formatVmMemory(selectedVMDetails.available_memory_mib)}
                  {' | '}
                  Storage: {formatVmStorage(selectedVMDetails.available_storage_mib)}
                </div>
                <div style={{ color: '#786f63', fontSize: '0.875rem', marginTop: '0.35rem' }}>
                  Hard limit per job on this VM profile: total resources / number of VMs / max concurrent jobs on this VM.
                </div>
              </div>
            )}
          </div>
          )}

          {activeTab === 'pipeline' && (
          <div className="detail-section">
            <h2>Pipeline Visualization</h2>
            <PipelineVisualization
              pipeline={jobPipeline}
              emptyMessage="No pipeline blocks are available for this job yet."
              description="This locked flow is built from the resolved job workflow and the latest recorded execution state."
            />
          </div>
          )}

          {activeTab === 'tracking' && (
          <div className="detail-section">
            <h2>Execution Tracking</h2>
            {executions.length === 0 ? (
              <div className="empty-state">
                <p>No execution attempts recorded yet.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {executions.map((execution) => {
                  const stages = execution.parameters_used?.stages || []
                  const elapsed = formatDurationClock(execution.started_at, execution.completed_at)
                  const currentStageLabel = getCurrentStageLabel(execution)
                  const progressPercent = getExecutionProgressPercent(execution)

                  return (
                    <div key={execution.id} className="execution-card">
                      <div className="execution-card-header">
                        <div><strong>Execution #{execution.execution_number}</strong></div>
                        <div>
                          <strong>Status:</strong>{' '}
                          <span className={`status-badge ${getStatusColor(execution.status)}`}>
                            {formatExecutionStatusLabel(execution)}
                          </span>
                        </div>
                        {elapsed && <div><strong>Elapsed:</strong> {elapsed}</div>}
                      </div>

                      {execution.started_at && (
                        <div className="execution-card-meta">
                          Started: {formatLocalDateTime(execution.started_at)}
                          {execution.completed_at ? ` | Completed: ${formatLocalDateTime(execution.completed_at)}` : ''}
                        </div>
                      )}

                      {currentStageLabel && (
                        <div className="execution-progress-banner">
                          <strong>Current Progress:</strong> {currentStageLabel}
                          {progressPercent !== null && (
                            <div style={{ marginTop: '0.6rem' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.35rem' }}>
                                <span>{stages.filter(stage => stage.status === 'completed').length}/{stages.length} tool stages completed</span>
                                <strong>{progressPercent}%</strong>
                              </div>
                              <div style={{ height: '10px', borderRadius: '999px', backgroundColor: '#dbe5f0', overflow: 'hidden' }}>
                                <div style={{ width: `${progressPercent}%`, height: '100%', backgroundColor: '#2563eb' }} />
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {execution.error_message && (
                        <div className="error-message" style={{ marginBottom: '0.75rem' }}>
                          {execution.error_message}
                        </div>
                      )}

                      {stages.length > 0 && (
                        <div className="execution-stage-list">
                          {stages.map((stage) => (
                            <div key={`${execution.id}-${stage.stage_number}-${stage.tool_id}`} className="execution-stage-card">
                              <div className="execution-stage-header">
                                <div>
                                  <strong>Tool {stage.stage_number}:</strong> {stage.tool_name || stage.tool_id}
                                </div>
                                <div>
                                  <span className={`status-badge ${getStatusColor(stage.status)}`}>
                                    {formatStageStatusLabel(stage.status)}
                                  </span>
                                </div>
                              </div>

                              {stage.started_at && (
                                <div className="execution-stage-meta">
                                  Started: {formatLocalDateTime(stage.started_at)}
                                  {stage.completed_at ? ` | Completed: ${formatLocalDateTime(stage.completed_at)}` : ''}
                                  {formatDurationClock(stage.started_at, stage.completed_at) ? ` | Time: ${formatDurationClock(stage.started_at, stage.completed_at)}` : ''}
                                </div>
                              )}

                              {stage.error && (
                                <div className="error-message" style={{ marginTop: '0.75rem' }}>
                                  {stage.error}
                                </div>
                              )}

                              {(stage.live_tool_logs || stage.live_init_logs || ['pending', 'running', 'waiting_for_resources', 'waiting_for_dependencies'].includes(stage.status)) && (
                                <div style={{ marginTop: '0.85rem' }}>
                                  <strong style={{ display: 'block', marginBottom: '0.45rem' }}>Live Logs</strong>
                                  <pre
                                    style={{
                                      margin: 0,
                                      padding: '0.9rem 1rem',
                                      borderRadius: '10px',
                                      backgroundColor: '#183B4E',
                                      color: '#f8fafc',
                                      fontSize: '0.78rem',
                                      lineHeight: 1.55,
                                      whiteSpace: 'pre-wrap',
                                      wordBreak: 'break-word',
                                      maxHeight: '260px',
                                      overflow: 'auto',
                                    }}
                                  >
                                    {stage.live_tool_logs || stage.live_init_logs || (
                                      stage.pod_phase === 'Pending'
                                        ? 'Logs will appear after the Kubernetes container starts.'
                                        : 'Waiting for live logs...'
                                    )}
                                  </pre>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          )}

          {activeTab === 'resources' && (
          <div className="detail-section">
            <h2>Active Resource Usage</h2>
            <div className="builder-section-card" style={{ marginBottom: '1rem' }}>
              <p style={{ margin: '0 0 1rem', color: '#64748b' }}>
                This shows the resources currently allocated by running tool stages in this job, compared with this job's selected VM limit.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                {[
                  {
                    label: 'CPU',
                    used: activeCpuMillis,
                    limit: resourceLimits.cpuMillis,
                    display: `${formatVmCpu(activeCpuMillis)} / ${formatVmCpu(resourceLimits.cpuMillis)}`,
                  },
                  {
                    label: 'Memory',
                    used: activeMemoryMib,
                    limit: resourceLimits.memoryMib,
                    display: `${formatVmMemory(activeMemoryMib)} / ${formatVmMemory(resourceLimits.memoryMib)}`,
                  },
                  {
                    label: 'Storage',
                    used: activeStorageMib,
                    limit: resourceLimits.storageMib,
                    display: `${formatVmStorage(activeStorageMib)} / ${formatVmStorage(resourceLimits.storageMib)}`,
                  },
                ].map(resource => {
                  const percent = resourcePercent(resource.used, resource.limit)
                  return (
                    <div key={resource.label} style={{ padding: '1rem', borderRadius: '10px', border: '1px solid #e2d1ad', background: '#fffaf0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.6rem' }}>
                        <strong>{resource.label}</strong>
                        <span>{resource.display}</span>
                      </div>
                      <div style={{ height: '10px', borderRadius: '999px', backgroundColor: '#eadfca', overflow: 'hidden' }}>
                        <div style={{ width: `${percent}%`, height: '100%', backgroundColor: percent > 85 ? '#b6786d' : '#2563eb' }} />
                      </div>
                      <div style={{ marginTop: '0.4rem', color: '#64748b', fontSize: '0.875rem' }}>{percent}% allocated</div>
                    </div>
                  )
                })}
              </div>
            </div>

            {activeStages.length === 0 ? (
              <div className="empty-state">
                <p>No tool stage is actively running right now.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {activeStages.map(stage => (
                  <div key={`${stage.stage_id || stage.stage_number}-${stage.tool_id}`} style={{ padding: '0.875rem 1rem', borderRadius: '8px', border: '1px solid #e2e8f0', backgroundColor: '#f8fafc' }}>
                    <strong>{stage.tool_name || stage.tool_id}</strong>
                    <div style={{ marginTop: '0.35rem', color: '#475569' }}>
                      CPU: {formatVmCpu(stage.cpu_limit_millis || (stage.threads || 0) * 1000)}
                      {' | '}
                      Memory: {formatVmMemory(stage.memory_limit_mib || 0)}
                      {' | '}
                      Storage: {formatVmStorage(stage.storage_limit_mib || 0)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          )}

          {activeTab === 'inputs' && (
          <div className="detail-section">
            <h2>Input Files</h2>
            
            {/* Show pipeline requirements if job has a pipeline_id */}
            {job.pipeline_id && (
              <div className="pipeline-requirements-card">
                <h3 className="pipeline-requirements-title">
                  Pipeline Input Requirements
                </h3>
                {loadingRequirements ? (
                  <p className="pipeline-requirements-copy">Loading requirements...</p>
                ) : pipelineRequirements ? (
                  pipelineRequirements.input_requirements.length > 0 ? (
                    <>
                      <p className="pipeline-requirements-copy">
                        This pipeline requires the following input files:
                      </p>
                      <div className="pipeline-requirements-list">
                        {pipelineRequirements.input_requirements.map((req) => {
                          // Check if this requirement is already satisfied by existing files
                          const isSatisfied = inputFiles.some(f => {
                            return fileMatchesRequirement(f.filename, req.formats, f.file_format)
                          })
                          const isPending = !isSatisfied && pendingQueuedFiles.some(file =>
                            fileMatchesRequirement(file.filename, req.formats, file.file_format)
                          )

                          const stateClassName = isSatisfied
                            ? 'satisfied'
                            : isPending
                              ? 'pending'
                              : 'missing'
                          return (
                            <div key={req.type} className={`pipeline-requirement-item ${stateClassName}`}>
                              <div className="pipeline-requirement-main">
                                <strong>{req.label}</strong>
                                <span className="pipeline-requirement-formats">
                                  ({req.formats.join(', ').toUpperCase()})
                                </span>
                                <span className="pipeline-requirement-tools">
                                  Used by: {getPipelineRequirementTools(req).join(', ')}
                                </span>
                                {isSatisfied && (
                                  <span className="pipeline-requirement-status success">Satisfied</span>
                                )}
                                {isPending && (
                                  <span className="pipeline-requirement-status pending">Uploading</span>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  ) : (
                    <p className="pipeline-requirements-copy">
                      This pipeline does not require any specific input files.
                    </p>
                  )
                ) : (
                  <p className="pipeline-requirements-copy warning">
                    Failed to load pipeline requirements. Please refresh the page.
                  </p>
                )}
              </div>
            )}

              {visibleInputCount === 0 ? (
                <div className="empty-state">
                  <p>{inputFilesPendingUpload ? 'Selected files are being uploaded to this job now.' : 'No input files configured. Files should be added during job creation.'}</p>
                  {job.status === 'pending' && (
                    <p style={{ marginTop: '0.5rem', color: '#666', fontSize: '0.875rem' }}>
                      {inputFilesPendingUpload ? 'Execution will start automatically after the upload finishes.' : 'To modify files, please create a new job with the desired configuration.'}
                    </p>
                  )}
                </div>
              ) : (
                <div className="file-list">
                  {pendingQueuedFiles.map((file) => (
                    <div key={`pending-${file.jobId}-${file.filename}-${file.created_at}`} className="file-item">
                      <div className="file-info">
                        <strong>{file.filename}</strong>
                        <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                      </div>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          padding: '0.25rem 0.75rem',
                          borderRadius: '999px',
                          backgroundColor: '#dbeafe',
                          color: '#1d4ed8',
                          fontSize: '0.875rem',
                          fontWeight: 600,
                        }}
                      >
                        Pending upload
                      </span>
                    </div>
                  ))}
                  {inputFiles.map((file) => (
                    <div key={file.id} className="file-item">
                      <div className="file-info">
                        <strong>{file.filename}</strong>
                        <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
          </div>
          )}

          {activeTab === 'outputs' && (
          <div className="detail-section">
            <div className="section-header-with-action">
              <div className="section-header-left">
                <h2>Output Files</h2>
                {outputFiles.length > 0 && (
                  <span className="file-count-badge">{outputFiles.length} file{outputFiles.length !== 1 ? 's' : ''}</span>
                )}
              </div>
              <div className="section-header-actions">
                {outputFiles.length > 0 && interactiveOutputsEnabled && (
                  <>
                    <button
                      onClick={() => setOutputFilesCollapsed(!outputFilesCollapsed)}
                      className="btn-secondary btn-collapse"
                      title={outputFilesCollapsed ? 'Expand files' : 'Collapse files'}
                    >
                      {outputFilesCollapsed ? '▶' : '▼'} {outputFilesCollapsed ? 'Expand' : 'Collapse'}
                    </button>
                    <button
                      onClick={handlePrepareZip}
                      className="btn-primary"
                      disabled={startingZipGeneration}
                    >
                      {startingZipGeneration ? 'Preparing ZIP...' : '📦 Download All as ZIP'}
                    </button>
                  </>
                )}
              </div>
            </div>
            {interactiveOutputsEnabled && zipPanelVisible && outputFiles.length > 0 && (
              <div className="zip-download-panel">
                <div className="zip-download-panel-header">
                  <strong>ZIP Download</strong>
                  {zipStatus?.status && (
                    <span className={`zip-download-status zip-download-status-${zipStatus.status}`}>
                      {zipStatus.status === 'queued' && 'Queued'}
                      {zipStatus.status === 'processing' && 'Preparing archive'}
                      {zipStatus.status === 'ready' && 'Ready'}
                      {zipStatus.status === 'failed' && 'Failed'}
                      {zipStatus.status === 'expired' && 'Expired'}
                      {zipStatus.status === 'idle' && 'Not started'}
                    </span>
                  )}
                </div>
                {zipStatus?.status === 'ready' ? (
                  <div className="zip-download-panel-body">
                    <p>Your ZIP link is ready. It stays valid for 1 hour.</p>
                    <div className="zip-download-actions">
                      <button onClick={handleOpenZipLink} className="btn-primary">
                        Download ZIP
                      </button>
                      <button onClick={handlePrepareZip} className="btn-secondary">
                        Regenerate Link
                      </button>
                    </div>
                    {zipStatus.filename && (
                      <p className="zip-download-filename">{zipStatus.filename}</p>
                    )}
                  </div>
                ) : (
                  <div className="zip-download-panel-body">
                    <p>
                      {zipStatus?.status === 'failed' && (zipStatus.error || 'ZIP generation failed.')}
                      {zipStatus?.status === 'expired' && 'The previous ZIP link expired. Generate a fresh one when you need it.'}
                      {zipStatus?.status === 'queued' && 'The ZIP request was accepted. You can keep using the page while it is queued.'}
                      {zipStatus?.status === 'processing' && 'The ZIP archive is being created in the background.'}
                      {zipStatus?.status === 'idle' && 'ZIP generation has not started yet.'}
                      {!zipStatus && 'Starting ZIP generation...'}
                    </p>
                    <div className="zip-download-actions">
                      {(zipStatus?.status === 'failed' || zipStatus?.status === 'expired' || zipStatus?.status === 'idle') && (
                        <button onClick={handlePrepareZip} className="btn-primary" disabled={startingZipGeneration}>
                          {startingZipGeneration ? 'Preparing ZIP...' : 'Generate ZIP Link'}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                {zipStatusError && <p className="zip-download-error">{zipStatusError}</p>}
              </div>
            )}
            {outputFiles.length === 0 ? (
              <div className="empty-state">
                {job.status === 'completed' ? (
                  <p>No output files available yet.</p>
                ) : (
                  <p>Output files and per-tool logs will appear here as tools finish.</p>
                )}
              </div>
            ) : (
              <>
                {logFiles.length > 0 && (
                  <p style={{ marginBottom: '1rem', color: '#6b7280' }}>
                    Tool logs are included here as downloadable files alongside regular outputs.
                  </p>
                )}
                {interactiveOutputsEnabled && outputFilesCollapsed ? (
                  <div className="file-list-collapsed">
                    <div className="file-list-preview">
                      {outputFiles.slice(0, 3).map((file) => (
                        <div key={file.id} className="file-item-preview">
                          <div className="file-info">
                            <strong>{file.filename}</strong>
                            <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                          </div>
                        </div>
                      ))}
                      {outputFiles.length > 3 && (
                        <div className="file-list-more">
                          <p>... and {outputFiles.length - 3} more file{outputFiles.length - 3 !== 1 ? 's' : ''}</p>
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => setOutputFilesCollapsed(false)}
                      className="btn-secondary btn-expand-all"
                    >
                      Show all {outputFiles.length} files
                    </button>
                  </div>
                ) : (
                  <div>
                    {/* Output Family Tabs */}
                    {interactiveOutputsEnabled && outputFamilies.length > 1 && (
                      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                        {outputFamilies.map((family) => (
                          <button
                            key={family}
                            onClick={() => {
                              setSelectedOutputFamily(family)
                            }}
                            className={selectedOutputFamily === family ? 'btn-primary' : 'btn-secondary'}
                            style={{ padding: '0.5rem 1rem' }}
                          >
                            {family} ({outputGroups[family].length})
                          </button>
                        ))}
                      </div>
                    )}

                    {interactiveOutputsEnabled && currentViewingFile && isViewable(currentViewingFile) && (
                      <div style={{ 
                        marginBottom: '1.5rem', 
                        padding: '1rem', 
                        border: '1px solid #e5e7eb', 
                        borderRadius: '8px',
                        backgroundColor: '#f9fafb'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                          <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: '600' }}>
                            {currentViewingFile.filename}
                          </h3>
                          <div style={{ display: 'flex', gap: '0.5rem' }}>
                            {viewableFiles.length > 1 && (
                              <>
                                <button
                                  onClick={() => {
                                    const newIndex = selectedOutputIndex > 0 ? selectedOutputIndex - 1 : viewableFiles.length - 1
                                    setSelectedOutputIndex(newIndex)
                                    setViewingFile(viewableFiles[newIndex])
                                  }}
                                  className="btn-secondary"
                                  disabled={viewableFiles.length <= 1}
                                >
                                  ← Previous
                                </button>
                                <span style={{ padding: '0.5rem', fontSize: '0.875rem', color: '#666' }}>
                                  {selectedOutputIndex + 1} / {viewableFiles.length}
                                </span>
                                <button
                                  onClick={() => {
                                    const newIndex = selectedOutputIndex < viewableFiles.length - 1 ? selectedOutputIndex + 1 : 0
                                    setSelectedOutputIndex(newIndex)
                                    setViewingFile(viewableFiles[newIndex])
                                  }}
                                  className="btn-secondary"
                                  disabled={viewableFiles.length <= 1}
                                >
                                  Next →
                                </button>
                              </>
                            )}
                            {currentViewingFile.filename.toLowerCase().endsWith('.html') && (
                              <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', marginLeft: '0.5rem', padding: '0.25rem', border: '1px solid #ddd', borderRadius: '4px' }}>
                                <button
                                  onClick={() => setHtmlZoom(prev => Math.max(0.25, prev - 0.1))}
                                  className="btn-secondary"
                                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.875rem' }}
                                  title="Zoom out"
                                >
                                  −
                                </button>
                                <span style={{ padding: '0 0.5rem', fontSize: '0.875rem', color: '#666', minWidth: '3rem', textAlign: 'center' }}>
                                  {Math.round(htmlZoom * 100)}%
                                </span>
                                <button
                                  onClick={() => setHtmlZoom(prev => Math.min(2, prev + 0.1))}
                                  className="btn-secondary"
                                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.875rem' }}
                                  title="Zoom in"
                                >
                                  +
                                </button>
                                <button
                                  onClick={() => setHtmlZoom(0.75)}
                                  className="btn-secondary"
                                  style={{ padding: '0.25rem 0.5rem', fontSize: '0.875rem', marginLeft: '0.25rem' }}
                                  title="Reset zoom"
                                >
                                  Reset
                                </button>
                              </div>
                            )}
                            <button
                              onClick={() => handleDownload(currentViewingFile)}
                              className="btn-primary"
                            >
                              Download
                            </button>
                            <button
                              onClick={() => {
                                setViewingFile(null)
                                setSelectedOutputIndex(0)
                                setHtmlZoom(0.75)
                              }}
                              className="btn-secondary"
                            >
                              Close
                            </button>
                          </div>
                        </div>
                        <div style={{ 
                          border: '1px solid #ddd', 
                          borderRadius: '4px', 
                          overflow: 'hidden',
                          backgroundColor: '#F5EEDC',
                          display: 'flex',
                          justifyContent: 'center',
                          alignItems: 'flex-start'
                        }}>
                          {viewingFileUrl ? (
                            currentViewingFile.filename.toLowerCase().endsWith('.html') ? (
                              <div style={{ 
                                width: '100%',
                                height: '600px',
                                display: 'flex',
                                justifyContent: 'center',
                                alignItems: 'flex-start',
                                overflow: 'hidden'
                              }}>
                                <div style={{
                                  width: '80%',
                                  height: '100%',
                                  overflow: 'auto',
                                  position: 'relative',
                                  border: '1px solid #e5e7eb',
                                  borderRadius: '4px'
                                }}>
                                  <iframe
                                    src={viewingFileUrl}
                                    style={{ 
                                      width: `${100 / htmlZoom}%`, 
                                      height: `${100 / htmlZoom}%`, 
                                      border: 'none',
                                      transform: `scale(${htmlZoom})`,
                                      transformOrigin: 'top left',
                                      position: 'absolute',
                                      top: 0,
                                      left: 0
                                    }}
                                    title={currentViewingFile.filename}
                                  />
                                </div>
                              </div>
                            ) : currentViewingFile.filename.toLowerCase().match(/\.(txt|log)$/i) ? (
                              <div style={{
                                width: '100%',
                                maxHeight: '480px',
                                overflow: 'auto',
                                padding: '1rem',
                                backgroundColor: '#fffaf0'
                              }}>
                                <pre style={{
                                  margin: 0,
                                  whiteSpace: 'pre-wrap',
                                  wordBreak: 'break-word',
                                  fontFamily: 'Consolas, Monaco, monospace',
                                  fontSize: '0.9rem',
                                  lineHeight: 1.5,
                                  color: '#1f2937'
                                }}>
                                  {viewingTextContent ?? 'Loading text preview...'}
                                </pre>
                              </div>
                            ) : currentViewingFile.filename.toLowerCase().match(/\.(png|jpg|jpeg|gif|svg)$/i) ? (
                              <div style={{ 
                                maxHeight: '400px',
                                display: 'flex',
                                justifyContent: 'center',
                                alignItems: 'center',
                                overflow: 'hidden',
                                width: '100%'
                              }}>
                                <img
                                  src={viewingFileUrl}
                                  alt={currentViewingFile.filename}
                                  style={{ 
                                    maxWidth: '100%', 
                                    maxHeight: '400px',
                                    height: 'auto', 
                                    width: 'auto',
                                    display: 'block',
                                    objectFit: 'contain'
                                  }}
                                />
                              </div>
                            ) : currentViewingFile.filename.toLowerCase().endsWith('.pdf') ? (
                              <iframe
                                src={viewingFileUrl}
                                style={{ width: '100%', height: '400px', border: 'none', flexShrink: 0 }}
                                title={currentViewingFile.filename}
                              />
                            ) : null
                          ) : (
                            <div style={{ padding: '2rem', textAlign: 'center', color: '#666' }}>
                              Loading file...
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* File List */}
                    <div className="file-list">
                      {(interactiveOutputsEnabled && selectedOutputFamily ? outputGroups[selectedOutputFamily] : outputFiles).map((file) => (
                        <div key={file.id} className="file-item">
                          <div className="file-info">
                            <strong>{file.filename}</strong>
                            <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                          </div>
                          {interactiveOutputsEnabled && (
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              {isViewable(file) && (
                                <button
                                  onClick={() => {
                                    const familyFiles = selectedOutputFamily ? (outputGroups[selectedOutputFamily] || []) : outputFiles
                                    const viewableInFamily = familyFiles.filter(isViewable)
                                    const index = viewableInFamily.findIndex(f => f.id === file.id)
                                    if (index >= 0) {
                                      setSelectedOutputIndex(index)
                                      setViewingFile(viewableInFamily[index])
                                    } else {
                                      setSelectedOutputIndex(0)
                                      setViewingFile(viewableInFamily[0] || null)
                                    }
                                  }}
                                  className="btn-secondary"
                                >
                                  View
                                </button>
                              )}
                              <button
                                onClick={() => handleDownload(file)}
                                className="btn-primary"
                              >
                                Download
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
          )}
        </div>
      </div>
    </div>
  )
}
