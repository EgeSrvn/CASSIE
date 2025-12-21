import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getJob, Job, executeJob } from '../services/jobService'
import { getFiles, File, downloadFile, downloadJobOutputsZip, getFileViewUrl } from '../services/fileService'
import { getPipelineRequirements, PipelineRequirements } from '../services/pipelineService'
import Navigation from '../components/Navigation'
import '../styles/globals.css'

export default function JobDetails() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<Job | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
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

  useEffect(() => {
    if (jobId) {
      loadJob()
      loadFiles()
    }
    // No auto-refresh - users can manually refresh if needed
  }, [jobId])

  // Load pipeline requirements if job has a pipeline_id
  useEffect(() => {
    if (job && job.pipeline_id) {
      console.log('Loading pipeline requirements for pipeline_id:', job.pipeline_id)
      const loadRequirements = async () => {
        try {
          setLoadingRequirements(true)
          const requirements = await getPipelineRequirements(job.pipeline_id!)
          console.log('Pipeline requirements loaded:', requirements)
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
      console.log('No pipeline_id found for job:', job?.id, 'pipeline_id:', job?.pipeline_id)
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

  // Compute files before early returns (will be empty arrays initially)
  const inputFiles = (files || []).filter(f => f && f.file_type === 'input')
  const outputFiles = (files || []).filter(f => f && f.file_type === 'output')

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
      } else if (filename.includes('spades') || filename.includes('contigs') || filename.includes('scaffolds')) {
        family = 'SPAdes'
      } else if (filename.includes('quast')) {
        family = 'QUAST'
      } else if (filename.includes('genomescope') || filename.includes('genomescope2')) {
        family = 'GenomeScope2'
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

  // Get viewable file types (images, HTML, PDF)
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
  }, [outputFiles.length, selectedOutputFamily])

  const currentFamilyFiles = selectedOutputFamily && outputGroups[selectedOutputFamily] ? outputGroups[selectedOutputFamily] : []
  const viewableFiles = currentFamilyFiles.filter(isViewable)
  
  // Update viewing file when index or family changes - MUST be before early returns
  useEffect(() => {
    if (!selectedOutputFamily || !outputGroups[selectedOutputFamily]) {
      setViewingFile(null)
      return
    }
    
    const familyFiles = outputGroups[selectedOutputFamily] || []
    const viewable = familyFiles.filter(isViewable)
    
    if (viewable.length > 0) {
      const validIndex = Math.max(0, Math.min(selectedOutputIndex, viewable.length - 1))
      const targetFile = viewable[validIndex]
      setViewingFile(prev => {
        if (!prev || prev.id !== targetFile.id) {
          return targetFile
        }
        return prev
      })
    } else {
      setViewingFile(null)
    }
  }, [selectedOutputIndex, selectedOutputFamily, outputFiles.length])
  
  // Load file URL when viewing file changes - MUST be before early returns
  useEffect(() => {
    if (!viewingFile || !isViewable(viewingFile)) {
      if (viewingFileUrlRef.current) {
        window.URL.revokeObjectURL(viewingFileUrlRef.current)
        viewingFileUrlRef.current = null
      }
      setViewingFileUrl(null)
      return
    }
    
    let cancelled = false
    
    // Load the file URL
    getFileViewUrl(viewingFile.id)
      .then(url => {
        if (cancelled) {
          window.URL.revokeObjectURL(url)
          return
        }
        
        // Revoke previous blob URL
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
    
    // Cleanup function
    return () => {
      cancelled = true
      // Don't revoke here - we want to keep the URL while component is mounted
    }
  }, [viewingFile?.id])
  
  // Cleanup blob URLs on unmount
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

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'status-completed'
      case 'running': return 'status-running'
      case 'failed': return 'status-failed'
      case 'pending': return 'status-pending'
      default: return ''
    }
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
    if (inputFiles.length === 0) return false
    
    // For pipeline-based jobs, check if all requirements are met
    if (pipelineRequirements && pipelineRequirements.input_requirements.length > 0) {
      return inputFiles.length >= pipelineRequirements.input_requirements.length
    }
    
    // For tool-based jobs, at least one file is required (already checked above)
    return true
  })()

  const getExecuteButtonMessage = () => {
    if (job.status !== 'pending') return null
    if (inputFiles.length === 0) {
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
            <button onClick={() => { loadJob(); loadFiles(); }} className="btn-secondary">
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
                <span className={`status-badge ${getStatusColor(job.status)}`}>
                  {job.status}
                </span>
                {job.status === 'pending' && (
                  <>
                    <button
                      onClick={async () => {
                        if (!jobId) return
                        try {
                          setExecuting(true)
                          setError('')
                          await executeJob(parseInt(jobId))
                          await loadJob()
                          await loadFiles() // Refresh files after execution
                          alert('Job execution started successfully!')
                        } catch (err: any) {
                          setError(err.message || 'Failed to execute job')
                        } finally {
                          setExecuting(false)
                        }
                      }}
                      disabled={executing || !canExecute}
                      className="btn-primary"
                      style={{ marginLeft: '10px' }}
                      title={getExecuteButtonMessage() || undefined}
                    >
                      {executing ? 'Executing...' : 'Execute Job'}
                    </button>
                    {!canExecute && getExecuteButtonMessage() && (
                      <span style={{ marginLeft: '10px', color: '#f59e0b', fontSize: '0.875rem' }}>
                        {getExecuteButtonMessage()}
                      </span>
                    )}
                  </>
                )}
              </div>
              <div><strong>Workflow ID:</strong> {job.workflow_id}</div>
              <div><strong>Created:</strong> {new Date(job.created_at).toLocaleString()}</div>
              <div><strong>Updated:</strong> {new Date(job.updated_at).toLocaleString()}</div>
              {job.data_types && job.data_types.length > 0 && (
                <div><strong>Data Types:</strong> {job.data_types.join(', ')}</div>
              )}
            </div>
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
                            // Check if any input file matches the requirement format
                            const fileName = f.filename.toLowerCase()
                            return req.formats.some(format => 
                              fileName.endsWith(`.${format}`) || fileName.endsWith(`.${format}.gz`)
                            )
                          })
                          
                          const borderColor = isSatisfied ? '#86efac' : '#e2e8f0'
                          const bgColor = isSatisfied ? '#dcfce7' : '#fff'
                          return (
                            <div key={req.type} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.5rem', backgroundColor: bgColor, borderRadius: '4px', border: `1px solid ${borderColor}` }}>
                              <div style={{ flex: 1 }}>
                                <strong>{req.label}</strong>
                                <span style={{ marginLeft: '0.5rem', color: '#64748b', fontSize: '0.875rem' }}>
                                  ({req.formats.join(', ').toUpperCase()})
                                </span>
                                {isSatisfied && (
                                  <span style={{ marginLeft: '0.5rem', color: '#16a34a', fontSize: '0.875rem' }}>✓ Satisfied</span>
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

              {inputFiles.length === 0 ? (
                <div className="empty-state">
                  <p>No input files configured. Files should be added during job creation.</p>
                  {job.status === 'pending' && (
                    <p style={{ marginTop: '0.5rem', color: '#666', fontSize: '0.875rem' }}>
                      To modify files, please create a new job with the desired configuration.
                    </p>
                  )}
                </div>
              ) : (
                <div className="file-list">
                  {inputFiles.map((file) => (
                    <div key={file.id} className="file-item">
                      <div className="file-info">
                        <strong>{file.filename}</strong>
                        <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                      </div>
                      <button
                        onClick={() => handleDownload(file)}
                        className="btn-secondary"
                      >
                        Download
                      </button>
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
                {outputFiles.length > 0 && (
                  <>
                    <button
                      onClick={() => setOutputFilesCollapsed(!outputFilesCollapsed)}
                      className="btn-secondary btn-collapse"
                      title={outputFilesCollapsed ? 'Expand files' : 'Collapse files'}
                    >
                      {outputFilesCollapsed ? '▶' : '▼'} {outputFilesCollapsed ? 'Expand' : 'Collapse'}
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await downloadJobOutputsZip(parseInt(jobId!))
                        } catch (err) {
                          console.error('Failed to download ZIP:', err)
                          alert('Failed to download ZIP archive')
                        }
                      }}
                      className="btn-primary"
                    >
                      📦 Download All as ZIP
                    </button>
                  </>
                )}
              </div>
            </div>
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
                {outputFilesCollapsed ? (
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
                    {outputFamilies.length > 1 && (
                      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                        {outputFamilies.map((family) => {
                          const familyViewableFiles = (outputGroups[family] || []).filter(isViewable)
                          return (
                            <button
                              key={family}
                              onClick={() => {
                                setSelectedOutputFamily(family)
                                setSelectedOutputIndex(0)
                                // Auto-select first viewable file if available
                                if (familyViewableFiles.length > 0) {
                                  setViewingFile(familyViewableFiles[0])
                                } else {
                                  setViewingFile(null)
                                }
                              }}
                              className={selectedOutputFamily === family ? 'btn-primary' : 'btn-secondary'}
                              style={{ padding: '0.5rem 1rem' }}
                            >
                              {family} ({outputGroups[family].length})
                            </button>
                          )
                        })}
                      </div>
                    )}

                    {/* Output Viewer */}
                    {currentViewingFile && isViewable(currentViewingFile) && (
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
                      {(selectedOutputFamily ? outputGroups[selectedOutputFamily] : outputFiles).map((file) => {
                        const canView = isViewable(file)
                        return (
                          <div key={file.id} className="file-item">
                            <div className="file-info">
                              <strong>{file.filename}</strong>
                              <span>{(file.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              {canView && (
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
                                  👁️ View
                                </button>
                              )}
                              <button
                                onClick={() => handleDownload(file)}
                                className="btn-primary"
                              >
                                Download
                              </button>
                            </div>
                          </div>
                        )
                      })}
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
