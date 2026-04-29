import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import {
  DataFile,
  deleteDataFile,
  downloadDataFile,
  getDataFileTree,
  importGoogleDriveDataFile,
} from '../services/dataFileService'
import {
  deleteFile,
  downloadFile,
  File as StorageJobFile,
  getFiles,
  getStorageSummary,
  StorageSummary,
} from '../services/fileService'
import { FolderTreeItem, FileItem } from '../services/folderService'
import { getJobs, Job } from '../services/jobService'
import {
  dismissStorageUpload,
  queueStorageUploads,
  StorageUploadItem,
  subscribeToStorageUploads,
} from '../services/storageUploadService'
import '../styles/globals.css'
import './Storage.css'

const GOOGLE_DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
const GOOGLE_API_SCRIPT_ID = 'cassie-google-api-script'
const GOOGLE_GSI_SCRIPT_ID = 'cassie-google-gsi-script'

type StorageTab = 'inputs' | 'outputs'
type InputLibraryRow = (FileItem & { folderPath?: string }) | StorageUploadItem

const formatBytes = (bytes?: number | null): string => {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

const formatUsagePercent = (ratio?: number | null): string => {
  if (ratio === null || ratio === undefined || ratio <= 0) return '0%'
  const percent = ratio * 100
  if (percent < 0.01) return '<0.01%'
  if (percent < 1) return `${percent.toFixed(2)}%`
  return `${percent.toFixed(1)}%`
}

const inferFileFormat = (filename: string): string | undefined => {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.fastq.gz')) return 'fastq.gz'
  if (lower.endsWith('.fq.gz')) return 'fq.gz'
  if (lower.endsWith('.fastq') || lower.endsWith('.fq')) return 'fastq'
  if (lower.endsWith('.fasta.gz')) return 'fasta.gz'
  if (lower.endsWith('.fa.gz')) return 'fa.gz'
  if (lower.endsWith('.fna.gz')) return 'fna.gz'
  if (lower.endsWith('.fasta') || lower.endsWith('.fa') || lower.endsWith('.fna')) return 'fasta'
  if (lower.endsWith('.gff3.gz')) return 'gff3.gz'
  if (lower.endsWith('.gff3')) return 'gff3'
  if (lower.endsWith('.gff.gz')) return 'gff.gz'
  if (lower.endsWith('.gff')) return 'gff'
  if (lower.endsWith('.gtf.gz')) return 'gtf.gz'
  if (lower.endsWith('.gtf')) return 'gtf'
  if (lower.endsWith('.hal.gz')) return 'hal.gz'
  if (lower.endsWith('.hal')) return 'hal'
  if (lower.endsWith('.gfa.gz')) return 'gfa.gz'
  if (lower.endsWith('.gfa')) return 'gfa'
  if (lower.endsWith('.json.gz')) return 'json.gz'
  if (lower.endsWith('.txt.gz')) return 'txt.gz'
  if (lower.endsWith('.csv.gz')) return 'csv.gz'
  if (lower.endsWith('.tsv.gz')) return 'tsv.gz'
  if (lower.endsWith('.csv')) return 'csv'
  if (lower.endsWith('.tsv')) return 'tsv'
  if (lower.endsWith('.json')) return 'json'
  if (lower.endsWith('.txt')) return 'txt'
  return undefined
}

const loadExternalScript = (id: string, src: string): Promise<void> => {
  const existing = document.getElementById(id) as HTMLScriptElement | null
  if (existing) {
    if (existing.dataset.loaded === 'true') return Promise.resolve()
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

const flattenFiles = (tree: FolderTreeItem[]): Array<FileItem & { folderPath?: string }> => {
  const files: Array<FileItem & { folderPath?: string }> = []
  const traverse = (folders: FolderTreeItem[], parentPath = '') => {
    folders.forEach((folder) => {
      const currentPath = parentPath ? `${parentPath}/${folder.name}` : folder.name
      folder.files?.forEach((file) => files.push({ ...file, folderPath: currentPath || 'Root' }))
      if (folder.children?.length) traverse(folder.children, currentPath)
    })
  }
  traverse(tree || [])
  return files
}

const formatStorageFileType = (file: StorageJobFile): string => {
  if (file.file_type === 'log') return 'LOG'
  return (file.file_format || file.file_type || 'unknown').toUpperCase()
}

const buildJobLabel = (job?: Job): string => {
  if (!job) return 'Unknown Job'
  const safeName = (job.name || '').trim()
  return safeName ? `${safeName} (#${job.id})` : `Job #${job.id}`
}

export default function Storage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [activeTab, setActiveTab] = useState<StorageTab>('inputs')
  const [summary, setSummary] = useState<StorageSummary | null>(null)
  const [dataTree, setDataTree] = useState<FolderTreeItem[]>([])
  const [jobFiles, setJobFiles] = useState<StorageJobFile[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [pendingFiles, setPendingFiles] = useState<StorageUploadItem[]>([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const inputFiles = useMemo(() => flattenFiles(dataTree), [dataTree])
  const visibleInputFiles = useMemo<InputLibraryRow[]>(() => [...pendingFiles, ...inputFiles], [inputFiles, pendingFiles])
  const outputFiles = useMemo(
    () => jobFiles.filter((file) => file.file_type === 'output' || file.file_type === 'log'),
    [jobFiles]
  )
  const jobLookup = useMemo(
    () => new Map(jobs.map((job) => [job.id, job])),
    [jobs]
  )
  const groupedOutputs = useMemo(() => {
    const groups = new Map<number, { job: Job | undefined; files: StorageJobFile[] }>()
    outputFiles.forEach((file) => {
      if (!file.job_id) return
      const current = groups.get(file.job_id) || { job: jobLookup.get(file.job_id), files: [] }
      current.job = jobLookup.get(file.job_id) || current.job
      current.files.push(file)
      groups.set(file.job_id, current)
    })

    return Array.from(groups.entries())
      .map(([jobId, group]) => ({
        jobId,
        job: group.job,
        files: [...group.files].sort((a, b) => {
          const aTime = new Date(a.created_at || a.uploaded_at || 0).getTime()
          const bTime = new Date(b.created_at || b.uploaded_at || 0).getTime()
          return bTime - aTime
        }),
      }))
      .sort((a, b) => {
        const aTime = a.job?.updated_at ? new Date(a.job.updated_at).getTime() : 0
        const bTime = b.job?.updated_at ? new Date(b.job.updated_at).getTime() : 0
        return bTime - aTime
      })
  }, [jobLookup, outputFiles])

  const usageRatio = summary?.usage_ratio ?? (
    summary?.max_storage_bytes ? summary.used_bytes / summary.max_storage_bytes : null
  )
  const usagePercent = usageRatio !== null && usageRatio !== undefined
    ? Math.min(usageRatio * 100, 100)
    : 0
  const usagePercentText = formatUsagePercent(usageRatio)

  const applyStorageDelta = (deltaBytes: number) => {
    if (!Number.isFinite(deltaBytes) || deltaBytes === 0) return
    setSummary((current) => {
      if (!current) return current
      const usedBytes = Math.max((current.used_bytes || 0) + deltaBytes, 0)
      const maxStorageBytes = current.max_storage_bytes || 0
      return {
        ...current,
        used_bytes: usedBytes,
        remaining_bytes: maxStorageBytes > 0 ? Math.max(maxStorageBytes - usedBytes, 0) : null,
        usage_ratio: maxStorageBytes > 0 ? usedBytes / maxStorageBytes : null,
      }
    })
  }

  const loadStorage = async (options?: { quiet?: boolean }) => {
    try {
      if (!options?.quiet) {
        setLoading(true)
      }
      setError('')
      const [nextSummary, nextTree, storageResponse, jobsResponse] = await Promise.all([
        getStorageSummary(),
        getDataFileTree(),
        getFiles(undefined, undefined, 1, 1000),
        getJobs(undefined, 1, 1000),
      ])
      setSummary(nextSummary)
      setDataTree(nextTree)
      setJobFiles(storageResponse.data || [])
      setJobs(jobsResponse.data || [])
    } catch (err: any) {
      setError(err?.response?.data?.message || err?.message || 'Failed to load storage')
    } finally {
      if (!options?.quiet) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    void loadStorage()
  }, [])

  useEffect(() => subscribeToStorageUploads((items) => {
    setPendingFiles(items)
  }), [])

  useEffect(() => {
    const handleStorageLibraryChange = (event: Event) => {
      const detail = (event as CustomEvent<{ deltaBytes?: number }>).detail
      if (detail?.deltaBytes) {
        applyStorageDelta(detail.deltaBytes)
      }
      void loadStorage({ quiet: true })
    }

    window.addEventListener('storage-library-change', handleStorageLibraryChange)
    return () => window.removeEventListener('storage-library-change', handleStorageLibraryChange)
  }, [])

  const updatePendingFile = (id: string, patch: Partial<StorageUploadItem>) => {
    setPendingFiles((current) => current.map((file) => (
      file.id === id ? { ...file, ...patch } : file
    )))
  }

  const handleLocalUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files || [])
    event.target.value = ''
    if (selectedFiles.length === 0) return

    try {
      setError('')
      setSuccess('')
      await queueStorageUploads(selectedFiles, inferFileFormat)
      setSuccess(`${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} queued`)
    } catch (err: any) {
      const message = err?.response?.data?.message || err?.message || 'Failed to upload file'
      setError(message)
    }
  }

  const openGoogleDrivePicker = async () => {
    const clientId = import.meta.env.VITE_GOOGLE_DRIVE_CLIENT_ID
    const apiKey = import.meta.env.VITE_GOOGLE_DRIVE_API_KEY
    const appId = import.meta.env.VITE_GOOGLE_DRIVE_APP_ID || clientId?.split('-')[0] || ''

    if (!clientId || !apiKey || !appId) {
      setError('Google Drive is not configured. Add the Google Drive client ID, API key, and app ID to enable imports.')
      return
    }

    try {
      setBusy(true)
      setError('')
      setSuccess('')
      await Promise.all([
        loadExternalScript(GOOGLE_API_SCRIPT_ID, 'https://apis.google.com/js/api.js'),
        loadExternalScript(GOOGLE_GSI_SCRIPT_ID, 'https://accounts.google.com/gsi/client'),
      ])

      const tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: clientId,
        scope: GOOGLE_DRIVE_SCOPE,
        callback: (tokenResponse: any) => {
          if (!tokenResponse?.access_token) {
            setBusy(false)
            setError('Google Drive sign-in did not return an access token')
            return
          }
          window.gapi.load('picker', {
            callback: () => {
              const picker = new window.google.picker.PickerBuilder()
                .setDeveloperKey(apiKey)
                .setAppId(appId)
                .setOAuthToken(tokenResponse.access_token)
                .addView(new window.google.picker.DocsView().setIncludeFolders(false))
                .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
                .setCallback(async (pickerData: any) => {
                  if (pickerData.action !== window.google.picker.Action.PICKED) {
                    setBusy(false)
                    return
                  }
                  const docs = pickerData.docs || []
                  const selectedAt = Date.now()
                  const pendingRows = docs.map((doc: any, index: number) => {
                    const filename = doc.name || `google-drive-${doc.id}`
                    const rawSize = doc.sizeBytes ?? doc.size
                    const parsedSize = rawSize !== undefined && rawSize !== null ? Number(rawSize) : null
                    return {
                      id: `gdrive-${selectedAt}-${index}-${doc.id}`,
                      filename,
                      size_bytes: typeof parsedSize === 'number' && Number.isFinite(parsedSize) ? parsedSize : null,
                      file_format: inferFileFormat(filename),
                      progress: null,
                      status: 'queued' as const,
                      created_at: new Date().toISOString(),
                    }
                  })
                  setPendingFiles((current) => [...pendingRows, ...current])
                  try {
                    for (let index = 0; index < docs.length; index += 1) {
                      const doc = docs[index]
                      const pendingRow = pendingRows[index]
                      const filename = doc.name || `google-drive-${doc.id}`
                      updatePendingFile(pendingRow.id, { status: 'confirming' })
                      const importedFile = await importGoogleDriveDataFile({
                        file_id: doc.id,
                        access_token: tokenResponse.access_token,
                        filename,
                        mime_type: doc.mimeType,
                        file_format: inferFileFormat(filename),
                      })
                      updatePendingFile(pendingRow.id, { status: 'ready', progress: 100 })
                      applyStorageDelta(importedFile.size_bytes || pendingRow.size_bytes || 0)
                      void loadStorage({ quiet: true })
                    }
                    setSuccess(`${docs.length} Google Drive file${docs.length === 1 ? '' : 's'} imported`)
                    await loadStorage()
                    setPendingFiles((current) => current.filter((file) => !pendingRows.some((row: StorageUploadItem) => row.id === file.id)))
                  } catch (err: any) {
                    const message = err?.response?.data?.message || err?.message || 'Failed to import Google Drive file'
                    setError(message)
                    setPendingFiles((current) => current.map((file) => (
                      pendingRows.some((row: StorageUploadItem) => row.id === file.id) && file.status !== 'ready'
                        ? { ...file, status: 'failed', error: message }
                        : file
                    )))
                  } finally {
                    setBusy(false)
                  }
                })
                .build()
              picker.setVisible(true)
            },
          })
        },
      })
      tokenClient.requestAccessToken({ prompt: 'consent' })
    } catch (err: any) {
      setBusy(false)
      setError(err?.message || 'Failed to open Google Drive')
    }
  }

  const handleDeleteInput = async (file: DataFile | FileItem) => {
    if (!confirm(`Delete ${file.filename}?`)) return
    try {
      setBusy(true)
      setError('')
      const deletedBytes = Number(file.size_bytes || 0)
      await deleteDataFile(file.id)
      applyStorageDelta(-deletedBytes)
      setSuccess('Input file deleted')
      await loadStorage({ quiet: true })
    } catch (err: any) {
      setError(err?.response?.data?.message || err?.message || 'Failed to delete file')
    } finally {
      setBusy(false)
    }
  }

  const handleDeleteOutput = async (file: StorageJobFile) => {
    if (!confirm(`Delete ${file.filename}?`)) return
    try {
      setBusy(true)
      setError('')
      const deletedBytes = Number(file.size_bytes || 0)
      await deleteFile(file.id)
      setJobFiles((current) => current.filter((currentFile) => currentFile.id !== file.id))
      applyStorageDelta(-deletedBytes)
      setSuccess('Output file deleted')
    } catch (err: any) {
      setError(err?.response?.data?.message || err?.message || 'Failed to delete output file')
    } finally {
      setBusy(false)
    }
  }

  const renderPendingInput = (file: StorageUploadItem) => {
    const progressLabel = file.status === 'failed'
      ? 'Not uploaded'
      : file.status === 'confirming'
        ? 'Waiting for confirmation'
        : file.progress !== null
          ? `${Math.round(file.progress)}%`
          : 'Preparing'
    const availabilityLabel = file.status === 'failed'
      ? 'Not available'
      : file.status === 'confirming'
        ? 'Bytes sent; not available until confirmed'
        : 'Not available yet'

    return (
      <article key={file.id} className="storage-file-row storage-file-row-pending">
        <div>
          <strong>{file.filename}</strong>
          <span>Pending Upload · {formatBytes(file.size_bytes)} · {(file.file_format || 'unknown').toUpperCase()}</span>
          <div className="storage-row-progress">
            <div className="storage-row-progress-header">
              <span>{progressLabel}</span>
              <span>{availabilityLabel}</span>
              {file.error && <span>{file.error}</span>}
            </div>
            {file.progress !== null && file.status !== 'confirming' && file.status !== 'failed' ? (
              <div className="storage-upload-progress">
                <span style={{ width: `${file.progress}%` }} />
              </div>
            ) : null}
            {file.status === 'confirming' && (
              <div className="storage-confirming-bar">
                <span />
              </div>
            )}
          </div>
        </div>
        <div className="storage-file-actions">
          {file.status === 'failed' ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => dismissStorageUpload(file.id)}
            >
              Dismiss
            </button>
          ) : (
            <span className="storage-status-pill">{progressLabel}</span>
          )}
        </div>
      </article>
    )
  }

  const renderInputLibraryFile = (file: FileItem & { folderPath?: string }) => (
    <article key={`input-${file.id}`} className="storage-file-row">
      <div>
        <strong>{file.filename}</strong>
        <span>{file.folderPath || 'Root'} · {formatBytes(file.size_bytes)} · {(file.file_format || 'unknown').toUpperCase()}</span>
      </div>
      <div className="storage-file-actions">
        <button type="button" className="btn-secondary" onClick={() => downloadDataFile(file.id)}>
          Download
        </button>
        <button type="button" className="btn-danger" disabled={busy} onClick={() => handleDeleteInput(file)}>
          Delete
        </button>
      </div>
    </article>
  )

  return (
    <div className="page-container storage-page">
      <Navigation />
      <main className="storage-content">
        <header className="storage-header">
          <div>
            <p className="storage-kicker">Data library</p>
            <h1>Storage</h1>
            <p>Manage reusable input files and job outputs in one place.</p>
          </div>
          <button type="button" className="btn-primary" onClick={() => navigate('/jobs/create')}>
            Create Job
          </button>
        </header>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}

        <section className="storage-usage-panel">
          <div className="storage-usage-main">
            <div>
              <strong>{formatBytes(summary?.used_bytes)} used</strong>
              <span> of {formatBytes(summary?.max_storage_bytes)} included storage</span>
            </div>
            <strong>{usagePercentText}</strong>
          </div>
          <div className="storage-meter" aria-label="Storage usage">
            <span style={{ width: `${usagePercent}%` }} />
          </div>
          <div className="storage-usage-footer">
            <span>{formatBytes(summary?.remaining_bytes)} remaining</span>
            <button type="button" className="btn-secondary storage-upgrade-link" onClick={() => navigate('/storage/upgrade')}>
              Weekly Storage Upgrades
            </button>
          </div>
        </section>

        <section className="storage-files-section">
          <div className="storage-section-heading">
            <div>
              <h2>Your Files</h2>
              <div className="storage-tab-strip" role="tablist" aria-label="Storage file categories">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'inputs'}
                  className={`storage-tab-button ${activeTab === 'inputs' ? 'active' : ''}`}
                  onClick={() => setActiveTab('inputs')}
                >
                  Input Files
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === 'outputs'}
                  className={`storage-tab-button ${activeTab === 'outputs' ? 'active' : ''}`}
                  onClick={() => setActiveTab('outputs')}
                >
                  Output Files
                </button>
              </div>
            </div>
            <button type="button" className="btn-secondary" disabled={loading || busy} onClick={() => loadStorage()}>
              Refresh
            </button>
          </div>

          {activeTab === 'inputs' && (
            <>
              <section className="storage-actions-panel">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleLocalUpload}
                  style={{ display: 'none' }}
                />
                <button type="button" className="btn-primary" disabled={busy} onClick={() => fileInputRef.current?.click()}>
                  Upload from Computer
                </button>
                <button type="button" className="btn-secondary" disabled={busy} onClick={openGoogleDrivePicker}>
                  Import from Google Drive
                </button>
              </section>

              {loading ? (
                <div className="loading-state">Loading storage...</div>
              ) : visibleInputFiles.length === 0 ? (
                <div className="empty-state">
                  <p>No stored inputs yet.</p>
                  <button type="button" className="btn-primary" onClick={() => fileInputRef.current?.click()}>
                    Upload First File
                  </button>
                </div>
              ) : (
                <div className="storage-file-list">
                  {visibleInputFiles.map((file) => (
                    'status' in file ? renderPendingInput(file) : renderInputLibraryFile(file)
                  ))}
                </div>
              )}
            </>
          )}

          {activeTab === 'outputs' && (
            loading ? (
              <div className="loading-state">Loading output files...</div>
            ) : groupedOutputs.length === 0 ? (
              <div className="empty-state">
                <p>No output files are stored yet.</p>
                <p className="empty-state-secondary">
                  Successful tool executions will appear here and stay grouped by job.
                </p>
              </div>
            ) : (
              <div className="storage-output-groups">
                {groupedOutputs.map((group) => (
                  <section key={`job-output-${group.jobId}`} className="storage-output-group">
                    <div className="storage-output-group-header">
                      <div>
                        <h3>{buildJobLabel(group.job)}</h3>
                        <p>
                          {group.job?.status ? `Status: ${group.job.status.toUpperCase()}` : 'Job details unavailable'} · {group.files.length} file{group.files.length === 1 ? '' : 's'}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => navigate(`/jobs/${group.jobId}`)}
                      >
                        Open Job
                      </button>
                    </div>
                    <div className="storage-file-list">
                      {group.files.map((file) => (
                        <article key={`output-${file.id}`} className="storage-file-row">
                          <div>
                            <strong>{file.filename}</strong>
                            <span>{formatBytes(file.size_bytes)} · {formatStorageFileType(file)}</span>
                          </div>
                          <div className="storage-file-actions">
                            <button type="button" className="btn-secondary" onClick={() => downloadFile(file.id)}>
                              Download
                            </button>
                            <button type="button" className="btn-danger" disabled={busy} onClick={() => handleDeleteOutput(file)}>
                              Delete
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )
          )}
        </section>
      </main>
    </div>
  )
}
