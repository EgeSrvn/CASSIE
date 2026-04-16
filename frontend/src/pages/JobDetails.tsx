import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getJob, Job, JobExecution, executeJob, getJobExecutions, getAvailableVMs, VM } from '../services/jobService'
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
  getPendingJobUploadFiles,
  startPendingJobUploadProcessor,
  subscribeToJobUploadStatus
} from '../services/pendingJobUploadService'
import { formatDurationClock, formatLocalDateTime } from '../utils/dateTime'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

const formatVmCpu = (cpuMillis: number): string => `${(cpuMillis / 1000).toFixed(2)} cores`
const formatVmMemory = (memoryMib: number): string => `${(memoryMib / 1024).toFixed(2)} GiB`
const formatVmStorage = (storageMib: number): string => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'
const formatVmSlots = (vm: VM): string => `${vm.available_job_slots}/${vm.max_jobs} jobs available`

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

  useEffect(() => {
    if (jobId) {
      loadJob()
      loadFiles()
      loadExecutions()
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
      }
    })
  }, [jobId])

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
  const outputFiles = (files || []).filter(f => f && f.file_type === 'output')
  const visibleInputCount = inputFiles.length + pendingQueuedFiles.length
  const selectedVMDetails = job?.vm_name ? availableVMs.find(vm => vm.name === job.vm_name) || null : null
  const latestExecution = executions.length > 0 ? executions[0] : null
  const latestQueuePosition = (
    latestExecution?.status === 'pending' &&
    String(latestExecution.parameters_used?.queue_state || '').trim().toLowerCase() === 'waiting_for_vm_slot' &&
    typeof latestExecution.parameters_used?.queue_position === 'number'
  ) ? latestExecution.parameters_used.queue_position : null

  const fileMatchesRequirement = (
    filename: string,
    formats: string[],
    declaredFormat?: string | null
  ): boolean => {
    const lowerName = filename.toLowerCase()
    const normalizedDeclaredFormat = (declaredFormat || '').toLowerCase()
    return formats.some(format => {
      const normalizedFormat = format.toLowerCase()
      return (
        normalizedDeclaredFormat === normalizedFormat ||
        lowerName.endsWith(`.${normalizedFormat}`) ||
        lowerName.endsWith(`.${normalizedFormat}.gz`)
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
      if (filename.includes('fastqc')) {
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'status-completed'
      case 'running': return 'status-running'
      case 'failed': return 'status-failed'
      case 'pending': return 'status-pending'
      case 'waiting_for_dependencies': return 'status-pending'
      case 'waiting_for_resources': return 'status-pending'
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
    if (stage.status === 'waiting_for_dependencies') return `Waiting for previous tools before: ${toolName}`
    if (stage.status === 'pending') return `Next Tool: ${toolName}`
    if (stage.status === 'failed') return `Failed Tool: ${toolName}`
    if (stage.status === 'completed' && execution.status === 'completed') return `Last Completed Tool: ${toolName}`
    return `Tool: ${toolName}`
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
          <button onClick={() => navigate('/dashboard')} className="btn-primary">
            Back to Dashboard
          </button>
        </div>
      </div>
    )
  }

  // Check if required files are present
  const canExecute = (() => {
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
            <button onClick={() => { loadJob(); loadFiles(); loadExecutions(); }} className="btn-secondary">
              Refresh
            </button>
            <button onClick={() => navigate('/dashboard')} className="btn-secondary">
              Back to Dashboard
            </button>
          </div>
        </header>

        {error && <div className="error-message">{error}</div>}
        <div className="job-details-container">
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
                        backgroundColor: jobUploadStatus.stage === 'failed' ? '#fee2e2' : '#dbeafe',
                        color: jobUploadStatus.stage === 'failed' ? '#b91c1c' : '#1d4ed8',
                      }}
                    >
                      {jobUploadStatus.stage === 'starting'
                        ? 'Starting job'
                        : `Uploading files (${jobUploadStatus.uploadedFiles}/${jobUploadStatus.totalFiles})`}
                    </span>
                  )}
                </div>
                {job.status === 'pending' && (
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
                        {executing ? 'Executing...' : 'Execute Job'}
                      </button>
                    )}
                    {!jobUploadStatus && !canExecute && getExecuteButtonMessage() && (
                      <span style={{ display: 'inline-block', marginTop: '10px', color: '#f59e0b', fontSize: '0.875rem' }}>
                        {getExecuteButtonMessage()}
                      </span>
                    )}
                  </>
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
                <div style={{ gridColumn: '1 / -1', color: '#b91c1c' }}>
                  <strong>Upload error:</strong> {jobUploadStatus.error}
                </div>
              )}
              {job.data_types && job.data_types.length > 0 && (
                <div><strong>Data Types:</strong> {job.data_types.join(', ')}</div>
              )}
            </div>
            {selectedVMDetails && (
              <div style={{ marginTop: '1rem', padding: '0.875rem 1rem', borderRadius: '8px', backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
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

                  return (
                    <div
                      key={execution.id}
                      style={{
                        padding: '1rem',
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        backgroundColor: '#fff'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
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
                        <div style={{ marginBottom: '0.5rem', color: '#475569', fontSize: '0.9rem' }}>
                          Started: {formatLocalDateTime(execution.started_at)}
                          {execution.completed_at ? ` | Completed: ${formatLocalDateTime(execution.completed_at)}` : ''}
                        </div>
                      )}

                      {currentStageLabel && (
                        <div
                          style={{
                            marginBottom: '0.75rem',
                            padding: '0.75rem',
                            borderRadius: '6px',
                            backgroundColor: '#eff6ff',
                            color: '#1e3a8a',
                            border: '1px solid #bfdbfe',
                            fontSize: '0.95rem'
                          }}
                        >
                          <strong>Current Progress:</strong> {currentStageLabel}
                        </div>
                      )}

                      {execution.error_message && (
                        <div className="error-message" style={{ marginBottom: '0.75rem' }}>
                          {execution.error_message}
                        </div>
                      )}

                      {stages.length > 0 && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                          {stages.map((stage) => (
                            <div
                              key={`${execution.id}-${stage.stage_number}-${stage.tool_id}`}
                              style={{
                                padding: '0.75rem',
                                borderRadius: '6px',
                                backgroundColor: '#f8fafc',
                                border: '1px solid #e2e8f0'
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
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
                                <div style={{ marginTop: '0.5rem', fontSize: '0.9rem', color: '#64748b' }}>
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

          <div className="detail-section">
            <h2>Input Files</h2>
            
            {/* Show pipeline requirements if job has a pipeline_id */}
            {job.pipeline_id && (
              <div style={{ marginBottom: '1.5rem', padding: '1rem', backgroundColor: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                <h3 style={{ marginTop: 0, marginBottom: '0.75rem', fontSize: '1rem', fontWeight: '600' }}>
                  Pipeline Input Requirements
                </h3>
                {loadingRequirements ? (
                  <p style={{ color: '#64748b', fontSize: '0.875rem' }}>Loading requirements...</p>
                ) : pipelineRequirements ? (
                  pipelineRequirements.input_requirements.length > 0 ? (
                    <>
                      <p style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.875rem' }}>
                        This pipeline requires the following input files:
                      </p>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {pipelineRequirements.input_requirements.map((req) => {
                          // Check if this requirement is already satisfied by existing files
                          const isSatisfied = inputFiles.some(f => {
                            return fileMatchesRequirement(f.filename, req.formats, f.file_format)
                          })
                          const isPending = !isSatisfied && pendingQueuedFiles.some(file =>
                            fileMatchesRequirement(file.filename, req.formats, file.file_format)
                          )
                          
                          const borderColor = isSatisfied ? '#86efac' : (isPending ? '#93c5fd' : '#e2e8f0')
                          const bgColor = isSatisfied ? '#dcfce7' : (isPending ? '#eff6ff' : '#fff')
                          return (
                            <div key={req.type} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.5rem', backgroundColor: bgColor, borderRadius: '4px', border: `1px solid ${borderColor}` }}>
                              <div style={{ flex: 1 }}>
                                <strong>{req.label}</strong>
                                <span style={{ marginLeft: '0.5rem', color: '#64748b', fontSize: '0.875rem' }}>
                                  ({req.formats.join(', ').toUpperCase()})
                                </span>
                                <span style={{ marginLeft: '0.5rem', color: '#475569', fontSize: '0.875rem' }}>
                                  Used by: {getPipelineRequirementTools(req).join(', ')}
                                </span>
                                {isSatisfied && (
                                  <span style={{ marginLeft: '0.5rem', color: '#16a34a', fontSize: '0.875rem' }}>✓ Satisfied</span>
                                )}
                                {isPending && (
                                  <span style={{ marginLeft: '0.5rem', color: '#2563eb', fontSize: '0.875rem' }}>Uploading</span>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </>
                  ) : (
                    <p style={{ color: '#64748b', fontSize: '0.875rem' }}>
                      This pipeline does not require any specific input files.
                    </p>
                  )
                ) : (
                  <p style={{ color: '#f59e0b', fontSize: '0.875rem' }}>
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
                  <p>Output files will appear here when the job completes.</p>
                )}
              </div>
            ) : (
              <>
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
                          backgroundColor: 'white',
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
        </div>
      </div>
    </div>
  )
}
