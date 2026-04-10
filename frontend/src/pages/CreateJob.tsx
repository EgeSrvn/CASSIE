import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { createJob, JobCreate, executeJob, getAvailableVMs, VM } from '../services/jobService'
import { getAvailableTools, Tool, getToolRequirements, ToolRequirementInfo } from '../services/toolService'
import { getPipelines, Pipeline, getPipelineRequirements, PipelineRequirements, PipelineRequirement } from '../services/pipelineService'
import { getDataFileTree } from '../services/dataFileService'
import { FolderTreeItem, FileItem } from '../services/folderService'
import { getToken } from '../services/authService'
import { PendingJobUploadFile, enqueuePendingJobUploads } from '../services/pendingJobUploadService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

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
  const [fileMappings, setFileMappings] = useState<Record<string, number>>({}) // Maps requirement type to file ID
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
  const navigate = useNavigate()

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
          // Reset file mappings when pipeline changes
          setFileMappings({})
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
      setFileMappings({})
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

  // Fetch tool requirements when tools are selected
  useEffect(() => {
    if (selectionMode === 'tools' && selectedTools.length > 0) {
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
  }, [selectedTools, selectionMode])

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

  const handleFileMapping = (requirementType: string, fileId: number) => {
    setFileMappings(prev => {
      const currentFileId = prev[requirementType]
      // Toggle: if clicking the same file, unmap it
      if (currentFileId === fileId) {
        const newMappings = { ...prev }
        delete newMappings[requirementType]
        return newMappings
      } else {
        return {
          ...prev,
          [requirementType]: fileId
        }
      }
    })
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
    if (lower.endsWith('.txt')) return 'txt'
    if (lower.endsWith('.html')) return 'html'
    return null
  }

  const isMappedFileId = (fileId: unknown): fileId is number => (
    typeof fileId === 'number' && Number.isFinite(fileId)
  )

  const getPipelineRequirementKey = (req: PipelineRequirement) => `${req.type}:${req.label}`

  const getPipelineRequirementTools = (req: PipelineRequirement): string[] => {
    if (req.used_by && req.used_by.length > 0) return req.used_by

    if (req.type === 'forward_reads' || req.type === 'reverse_reads') return ['SPAdes']
    if (req.type === 'assembly' || req.type === 'reference') return ['QUAST']
    if (req.type === 'reads') {
      const tools: string[] = []
      if (pipelineRequirements?.has_fastqc) tools.push('FastQC')
      if (pipelineRequirements?.has_genomescope2) tools.push('GenomeScope2')
      return tools.length > 0 ? tools : ['Read-based tools']
    }
    return ['Selected pipeline']
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

    // For tools mode, validate that all non-intermediate requirements have files mapped
    if (selectionMode === 'tools') {
      const missingRequirements: string[] = []
      toolRequirements.forEach(toolReq => {
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

    // Get file IDs from data library
    let uploadedFileIds: number[] = []
    
    if (selectionMode === 'pipeline' && pipelineRequirements) {
      // Use mapped files from requirements
      uploadedFileIds = pipelineRequirements.input_requirements
        .map(req => fileMappings[getPipelineRequirementKey(req)])
        .filter(isMappedFileId)
      
      // Validate that all pipeline requirements are mapped
      if (pipelineRequirements.input_requirements.length > 0) {
        const missingRequirements = pipelineRequirements.input_requirements.filter(
          req => !isMappedFileId(fileMappings[getPipelineRequirementKey(req)])
        )
        if (missingRequirements.length > 0) {
          setError(`Please map files for all required inputs: ${missingRequirements.map(r => r.label).join(', ')}`)
          return
        }
      }
      // For pipelines, if there are no requirements, it's valid to have no files
    } else {
      // For tools mode, collect all mapped files from tool requirements
      const fileIdSet = new Set<number>()
      toolRequirements.forEach(toolReq => {
        toolReq.requirements.forEach(req => {
          if (!req.is_intermediate) {
            const toolKey = toolReq.tool_index.toString()
            const mappedFileIds = toolFileMappings[toolKey]?.[req.type] || []
            mappedFileIds.forEach(fileId => fileIdSet.add(fileId))
          }
        })
      })
      uploadedFileIds = Array.from(fileIdSet)
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

      // Only include already-uploaded library files at create time
      if (existingLibraryFileIds.length > 0) {
        jobData.input_file_ids = existingLibraryFileIds
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
        await enqueuePendingJobUploads(job.id, pendingFilesToUpload)
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
                    {vm.display_name}
                  </option>
                ))}
              </select>
            )}
            <small style={{ color: '#666', display: 'block', marginTop: '0.25rem' }}>
              Select the virtual machine where this job will be executed
            </small>
          </div>

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
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '1rem' }}>
                    {pipelines.map((pipeline) => (
                      <div
                        key={pipeline.id}
                        onClick={() => setSelectedPipelineId(pipeline.id)}
                        style={{
                          padding: '1rem',
                          border: `2px solid ${selectedPipelineId === pipeline.id ? '#2563eb' : '#e5e7eb'}`,
                          borderRadius: '8px',
                          cursor: 'pointer',
                          backgroundColor: selectedPipelineId === pipeline.id ? '#eff6ff' : 'white',
                        }}
                      >
                        <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem', fontWeight: '600' }}>{pipeline.name}</h3>
                        {pipeline.description && (
                          <p style={{ margin: '0', fontSize: '0.875rem', color: '#6b7280' }}>{pipeline.description}</p>
                        )}
                      </div>
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
              <label>Pipeline Input Requirements *</label>
              {loadingRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading requirements...</p>
              ) : pipelineRequirements && pipelineRequirements.input_requirements.length > 0 ? (
                <div className="pipeline-requirements-container">
                  <p style={{ marginBottom: '1rem', color: '#666', fontSize: '0.875rem' }}>
                    This pipeline requires the following input files. Map each requirement to a file from your data library or upload new files:
                  </p>
                  
                  {/* File Upload Section for Pipeline */}
                  <div style={{ marginBottom: '1rem' }}>
                    <label className="btn-secondary" style={{ cursor: 'pointer', display: 'inline-block' }}>
                      Select New File(s)
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
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                  ) : (() => {
                    const combinedFiles = getCombinedSelectableFiles()
                    
                    return pipelineRequirements.input_requirements.map((req: PipelineRequirement) => {
                      const requirementKey = getPipelineRequirementKey(req)
                      const mappedFileId = fileMappings[requirementKey]
                      const toolNames = getPipelineRequirementTools(req)
                      // Filter files that match the requirement format
                      const compatibleFiles = combinedFiles.filter(file => 
                        req.formats.some(format => 
                          file.filename.toLowerCase().endsWith(`.${format}`) || 
                          file.filename.toLowerCase().endsWith(`.${format}.gz`)
                        )
                      )
                      
                      return (
                        <div key={requirementKey} style={{ marginBottom: '1.5rem' }}>
                          <div style={{ marginBottom: '0.75rem' }}>
                            <strong>{req.label}</strong>
                            <span style={{ marginLeft: '0.5rem', color: '#666', fontSize: '0.875rem' }}>
                              ({req.formats.join(', ').toUpperCase()})
                            </span>
                            <span style={{ marginLeft: '0.5rem', color: '#475569', fontSize: '0.875rem' }}>
                              Used by: {toolNames.join(', ')}
                            </span>
                            {isMappedFileId(mappedFileId) && (
                              <span style={{ marginLeft: '0.5rem', color: '#16a34a', fontSize: '0.875rem', fontWeight: '500' }}>
                                ✓ File selected
                              </span>
                            )}
                          </div>
                          {compatibleFiles.length === 0 ? (
                            <p style={{ color: '#666', fontStyle: 'italic', fontSize: '0.875rem' }}>
                              No compatible files found. Upload files with formats: {req.formats.join(', ').toUpperCase()}
                            </p>
                          ) : (
                            <div style={{ 
                              display: 'flex', 
                              flexWrap: 'wrap', 
                              gap: '0.5rem',
                              padding: '1rem',
                              border: '1px solid #ddd',
                              borderRadius: '4px',
                              backgroundColor: '#f9fafb'
                            }}>
                              {compatibleFiles.map((file) => {
                                const isSelected = mappedFileId === file.id
                                return (
                                  <button
                                    key={file.id}
                                    type="button"
                                    onClick={() => handleFileMapping(requirementKey, file.id)}
                                    disabled={creating}
                                    style={{
                                      padding: '0.5rem 1rem',
                                      borderRadius: '4px',
                                      border: `2px solid ${isSelected ? '#2563eb' : '#e5e7eb'}`,
                                      backgroundColor: isSelected ? '#eff6ff' : 'white',
                                      color: isSelected ? '#2563eb' : '#374151',
                                      cursor: creating ? 'not-allowed' : 'pointer',
                                      fontSize: '0.875rem',
                                      fontWeight: isSelected ? '600' : '400',
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: '0.5rem',
                                      whiteSpace: 'nowrap'
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
                  })()}
                </div>
              ) : pipelineRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>
                  This pipeline doesn't require any input files (or all inputs come from previous tools).
                </p>
              ) : null}
            </div>
          )}

          {/* Tool Input Requirements Section - Only for tools mode */}
          {selectionMode === 'tools' && selectedTools.length > 0 && (
            <div className="form-group">
              <label>Tool Input Requirements *</label>
              {loadingToolRequirements ? (
                <p style={{ color: '#666', fontStyle: 'italic' }}>Loading tool requirements...</p>
              ) : toolRequirements.length > 0 ? (
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
                        accept=".fastq,.fasta,.fq,.fa,.gz"
                      />
                    </label>
                  </div>

                  {loadingDataTree ? (
                    <p style={{ color: '#666', fontStyle: 'italic' }}>Loading data library...</p>
                  ) : (() => {
                    const combinedFiles = getCombinedSelectableFiles()
                    
                    return toolRequirements.map((toolReq) => {
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
                              const compatibleFiles = combinedFiles.filter(file => 
                                req.formats.some(format => 
                                  file.filename.toLowerCase().endsWith(`.${format}`) || 
                                  file.filename.toLowerCase().endsWith(`.${format}.gz`)
                                )
                              )
                              
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
                                    <div style={{ 
                                      display: 'flex', 
                                      flexWrap: 'wrap', 
                                      gap: '0.5rem',
                                      padding: '1rem',
                                      border: '1px solid #e5e7eb',
                                      borderRadius: '4px',
                                      backgroundColor: 'white'
                                    }}>
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
