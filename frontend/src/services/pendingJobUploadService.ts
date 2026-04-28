import { executeJob, getJob } from './jobService'
import { importGoogleDriveFileToJob, uploadFile } from './fileService'

export type PendingJobUploadFile = {
  tempId: number
  file: globalThis.File
  filename: string
  original_filename?: string
  size_bytes: number
  file_format: string | null
  uploaded_at: null
  created_at: string
  folderPath?: string
  staged_file_id?: number
  upload_status?: 'queued' | 'uploading' | 'uploaded' | 'failed'
  upload_progress?: number
  upload_error?: string
}

export type PendingGoogleDriveJobImportFile = {
  tempId: number
  googleFileId: string
  accessToken: string
  filename: string
  original_filename?: string
  size_bytes: number | null
  file_format: string | null
  mime_type?: string
  created_at: string
  folderPath?: string
  staged_file_id?: number
  upload_status?: 'queued' | 'uploading' | 'uploaded' | 'failed'
  upload_progress?: number
  upload_error?: string
}

export type JobUploadStage = 'queued' | 'uploading' | 'starting' | 'failed'

export type JobUploadStatus = {
  jobId: number
  stage: JobUploadStage
  message: string
  totalFiles: number
  uploadedFiles: number
  currentFileName?: string
  progress?: number
  error?: string
  updatedAt: number
}

export type PendingQueuedJobFile = {
  jobId: number
  filename: string
  size_bytes: number
  file_format: string | null
  created_at: string
}

type StoredUploadRecord = {
  id: string
  schemaVersion?: number
  source?: 'pc' | 'google-drive'
  jobId: number
  tempId: number
  filename: string
  original_filename?: string
  size_bytes: number
  lastModified?: number
  file_format: string | null
  created_at: string
  queueOrder: number
  fileBlob?: Blob
  googleFileId?: string
  googleAccessToken?: string
  mime_type?: string
  uploadSessionToken?: string
}

const DB_NAME = 'cassie-pending-job-uploads'
const DB_VERSION = 1
const STORE_NAME = 'upload_files'
const STATUS_STORAGE_KEY = 'cassie-pending-job-upload-status'
const UPLOAD_RECORD_SCHEMA_VERSION = 4
const TRANSIENT_UPLOAD_ATTEMPTS = 3
const TRANSIENT_UPLOAD_RETRY_DELAY_MS = 10000

const listeners = new Set<(jobId: number, status: JobUploadStatus | null) => void>()
let uploadProcessorStarted = false
let uploadInFlight = false
const inMemoryUploadRecords: StoredUploadRecord[] = []

const isBrowser = () => typeof window !== 'undefined'
const hasIndexedDb = () => typeof indexedDB !== 'undefined'

const readStatusMap = (): Record<string, JobUploadStatus> => {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STATUS_STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

const writeStatusMap = (statuses: Record<string, JobUploadStatus>) => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STATUS_STORAGE_KEY, JSON.stringify(statuses))
}

const emitStatus = (jobId: number, status: JobUploadStatus | null) => {
  listeners.forEach(listener => listener(jobId, status))
}

const setJobUploadStatus = (jobId: number, status: JobUploadStatus | null) => {
  const statuses = readStatusMap()
  if (status) {
    statuses[jobId.toString()] = status
  } else {
    delete statuses[jobId.toString()]
  }
  writeStatusMap(statuses)
  emitStatus(jobId, status)
}

export const getJobUploadStatus = (jobId: number): JobUploadStatus | null => {
  const statuses = readStatusMap()
  return statuses[jobId.toString()] || null
}

export const subscribeToJobUploadStatus = (
  listener: (jobId: number, status: JobUploadStatus | null) => void
) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

const openUploadDb = (): Promise<IDBDatabase> => {
  return new Promise((resolve, reject) => {
    if (!isBrowser() || !hasIndexedDb()) {
      reject(new Error('Browser storage is unavailable'))
      return
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' })
        store.createIndex('jobId', 'jobId', { unique: false })
        store.createIndex('queueOrder', 'queueOrder', { unique: false })
      }
    }

    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('Failed to open upload database'))
  })
}

const withStore = async <T>(
  mode: IDBTransactionMode,
  handler: (store: IDBObjectStore) => Promise<T> | T
): Promise<T> => {
  const db = await openUploadDb()
  return new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, mode)
    const store = transaction.objectStore(STORE_NAME)
    let handlerResult: T

    transaction.oncomplete = () => {
      db.close()
      resolve(handlerResult)
    }
    transaction.onerror = () => {
      db.close()
      reject(transaction.error || new Error('Upload database transaction failed'))
    }
    transaction.onabort = () => {
      db.close()
      reject(transaction.error || new Error('Upload database transaction aborted'))
    }

    Promise.resolve(handler(store))
      .then(result => {
        handlerResult = result
      })
      .catch(error => {
        db.close()
        reject(error)
      })
  })
}

const requestToPromise = <T>(request: IDBRequest<T>): Promise<T> => {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'))
  })
}

const getAllUploadRecords = async (): Promise<StoredUploadRecord[]> => {
  if (!isBrowser() || !hasIndexedDb()) {
    return []
  }
  return withStore('readonly', async (store) => {
    const records = await requestToPromise(store.getAll())
    return (records as StoredUploadRecord[]).sort((a, b) => a.queueOrder - b.queueOrder)
  })
}

const getUploadRecordsForJob = async (jobId: number): Promise<StoredUploadRecord[]> => {
  const persistedRecords = await getAllUploadRecords()
  const memoryRecords = inMemoryUploadRecords.filter(record => record.jobId === jobId)
  return [...memoryRecords, ...persistedRecords].sort((a, b) => a.queueOrder - b.queueOrder)
}

export const getPendingJobUploadFiles = async (jobId: number): Promise<PendingQueuedJobFile[]> => {
  const records = await getUploadRecordsForJob(jobId)
  return records
    .sort((a, b) => a.queueOrder - b.queueOrder)
    .map(record => ({
      jobId: record.jobId,
      filename: record.filename,
      size_bytes: record.size_bytes,
      file_format: record.file_format,
      created_at: record.created_at,
    }))
}

const putUploadRecord = async (record: StoredUploadRecord) => {
  await withStore('readwrite', async (store) => {
    await requestToPromise(store.put(record))
  })
}

const deleteUploadRecord = async (recordId: string) => {
  const memoryIndex = inMemoryUploadRecords.findIndex(record => record.id === recordId)
  if (memoryIndex >= 0) {
    inMemoryUploadRecords.splice(memoryIndex, 1)
    return
  }

  if (!hasIndexedDb()) {
    return
  }

  await withStore('readwrite', async (store) => {
    await requestToPromise(store.delete(recordId))
  })
}

const deleteUploadRecordsForJob = async (jobId: number) => {
  const records = await getUploadRecordsForJob(jobId)
  await Promise.all(records.map(record => deleteUploadRecord(record.id)))
}

export const clearPendingJobUploads = async (jobId: number) => {
  await deleteUploadRecordsForJob(jobId)
  setJobUploadStatus(jobId, null)
}

const getFileFingerprint = (file: PendingJobUploadFile): string => (
  `pc:${file.file.name}:${file.size_bytes}:${file.file.lastModified}`
)

const getGoogleDriveFingerprint = (file: PendingGoogleDriveJobImportFile): string => (
  `google-drive:${file.googleFileId}:${file.filename}:${file.size_bytes || 0}`
)

const getRecordFingerprint = (record: StoredUploadRecord): string => {
  if (record.source === 'google-drive') {
    return `google-drive:${record.googleFileId || record.original_filename || record.filename}:${record.filename}:${record.size_bytes}`
  }

  return `pc:${record.original_filename || record.filename}:${record.size_bytes}:${record.lastModified || 0}`
}

const removeDuplicateUploadRecords = async (records: StoredUploadRecord[]): Promise<StoredUploadRecord[]> => {
  const seen = new Set<string>()
  const uniqueRecords: StoredUploadRecord[] = []

  for (const record of records) {
    const fingerprint = getRecordFingerprint(record)
    if (seen.has(fingerprint)) {
      await deleteUploadRecord(record.id)
      continue
    }

    seen.add(fingerprint)
    uniqueRecords.push(record)
  }

  return uniqueRecords
}

const isDeletedJobUploadError = (error: any): boolean => {
  const message = getUploadErrorMessage(error).toLowerCase()
  return getUploadErrorStatus(error) === 404 && (
    message.includes('job') ||
    message.includes('not found')
  )
}

const isJobAlreadyStartingOrStartedError = (error: any): boolean => {
  const message = getUploadErrorMessage(error).toLowerCase()
  return (
    message.includes('job must be in pending status') ||
    message.includes('active execution') ||
    message.includes('already running') ||
    message.includes('already started')
  )
}

const isTransientUploadError = (error: any): boolean => {
  const status = getUploadErrorStatus(error)
  if (!status) {
    return true
  }
  return [408, 409, 425, 429, 500, 502, 503, 504].includes(status)
}

const wait = (milliseconds: number) => new Promise(resolve => window.setTimeout(resolve, milliseconds))

const getUploadErrorStatus = (error: any): number | undefined => {
  return error?.status || error?.response?.status
}

const getUploadErrorMessage = (error: any): string => {
  const responseData = error?.response?.data
  return String(
    error?.message ||
    responseData?.message ||
    responseData?.detail ||
    responseData?.error?.message ||
    responseData?.error ||
    ''
  )
}

const queuedJobStillExists = async (jobId: number, uploadSessionToken?: string): Promise<boolean> => {
  try {
    await getJob(jobId, uploadSessionToken)
    return true
  } catch (error: any) {
    if (getUploadErrorStatus(error) === 404) {
      return false
    }
    throw error
  }
}

const jobHasLeftPendingState = async (jobId: number, uploadSessionToken?: string): Promise<boolean> => {
  const job = await getJob(jobId, uploadSessionToken)
  return job.status !== 'pending'
}

const buildUploadStatus = (
  jobId: number,
  stage: JobUploadStage,
  message: string,
  totalFiles: number,
  uploadedFiles: number,
  extras?: Partial<JobUploadStatus>
): JobUploadStatus => ({
  jobId,
  stage,
  message,
  totalFiles,
  uploadedFiles,
  updatedAt: Date.now(),
  ...extras,
})

const resetInterruptedUploadsToQueued = async () => {
  if (!hasIndexedDb()) {
    return
  }

  const statuses = readStatusMap()
  const allRecords = await getAllUploadRecords()
  const currentRecords = allRecords.filter(record => record.schemaVersion === UPLOAD_RECORD_SCHEMA_VERSION)
  const legacyRecords = allRecords.filter(record => record.schemaVersion !== UPLOAD_RECORD_SCHEMA_VERSION)

  await Promise.all(legacyRecords.map(record => deleteUploadRecord(record.id)))

  const jobsWithQueuedFiles = new Set(currentRecords.map(record => record.jobId))

  Object.values(statuses).forEach(status => {
    if (!jobsWithQueuedFiles.has(status.jobId)) {
      setJobUploadStatus(status.jobId, null)
      return
    }

    if (status.stage === 'uploading' || status.stage === 'starting' || status.stage === 'failed') {
      const remainingFiles = currentRecords.filter(record => record.jobId === status.jobId)
      const totalFiles = Math.max(status.totalFiles, remainingFiles.length + status.uploadedFiles)
      setJobUploadStatus(
        status.jobId,
        buildUploadStatus(
          status.jobId,
          'queued',
          `Resuming upload queue (${status.uploadedFiles}/${totalFiles})...`,
          totalFiles,
          status.uploadedFiles
        )
      )
    }
  })
}

const processUploadQueue = async () => {
  if (uploadInFlight || !isBrowser()) return
  uploadInFlight = true

  try {
    while (true) {
      const persistedRecords = await getAllUploadRecords()
      const allRecords = [...inMemoryUploadRecords, ...persistedRecords].sort((a, b) => a.queueOrder - b.queueOrder)
      if (allRecords.length === 0) break

      const nextRecord = allRecords[0]
      const jobId = nextRecord.jobId
      const rawJobRecords = allRecords.filter(record => record.jobId === jobId).sort((a, b) => a.queueOrder - b.queueOrder)
      const jobRecords = await removeDuplicateUploadRecords(rawJobRecords)
      if (jobRecords.length === 0) {
        setJobUploadStatus(jobId, null)
        continue
      }
      const currentStatus = getJobUploadStatus(jobId)
      const totalFiles = currentStatus?.totalFiles || jobRecords.length
      let uploadedFiles = currentStatus?.uploadedFiles || 0

      try {
        const uploadSessionToken = jobRecords.find(record => record.uploadSessionToken)?.uploadSessionToken
        const jobExists = await queuedJobStillExists(jobId, uploadSessionToken)
        if (!jobExists) {
          await deleteUploadRecordsForJob(jobId)
          setJobUploadStatus(jobId, null)
          continue
        }
      } catch (error: any) {
        setJobUploadStatus(
          jobId,
          buildUploadStatus(
            jobId,
            'failed',
            'Could not verify job before upload',
            totalFiles,
            uploadedFiles,
            {
              error: getUploadErrorMessage(error) || 'Failed to verify job before upload',
            }
          )
        )
        return
      }

      let shouldContinueQueue = false

      for (const record of jobRecords) {
        const filePosition = uploadedFiles + 1
        const transferLabel = record.source === 'google-drive' ? 'Importing Google Drive files' : 'Uploading selected files'
        const transferMessage = `${transferLabel} (${filePosition}/${totalFiles}): ${record.filename}`
        setJobUploadStatus(
          jobId,
          buildUploadStatus(
            jobId,
            'uploading',
            transferMessage,
            totalFiles,
            uploadedFiles,
            {
              currentFileName: record.filename,
              progress: 0,
            }
          )
        )

        let uploadSucceeded = false
        let lastUploadError: any = null

        for (let attempt = 1; attempt <= TRANSIENT_UPLOAD_ATTEMPTS; attempt += 1) {
          try {
            if (record.source === 'google-drive') {
              if (!record.googleFileId || !record.googleAccessToken) {
                throw new Error(`Missing Google Drive import information for ${record.filename}`)
              }

              await importGoogleDriveFileToJob(
                jobId,
                {
                  file_id: record.googleFileId,
                  access_token: record.googleAccessToken,
                  filename: record.filename,
                  mime_type: record.mime_type,
                  file_format: record.file_format,
                },
                record.uploadSessionToken
              )

              setJobUploadStatus(
                jobId,
                buildUploadStatus(
                  jobId,
                  'uploading',
                  transferMessage,
                  totalFiles,
                  uploadedFiles,
                  {
                    currentFileName: record.filename,
                    progress: 100,
                  }
                )
              )
            } else {
              if (!record.fileBlob) {
                throw new Error(`Missing browser upload data for ${record.filename}`)
              }

              const restoredFile = new globalThis.File(
                [record.fileBlob],
                record.filename,
                { type: record.fileBlob.type || 'application/octet-stream' }
              )

              await uploadFile(
                restoredFile,
                jobId,
                'input',
                record.file_format || undefined,
                (progress) => {
                  setJobUploadStatus(
                    jobId,
                    buildUploadStatus(
                      jobId,
                      'uploading',
                      transferMessage,
                      totalFiles,
                      uploadedFiles,
                      {
                        currentFileName: record.filename,
                        progress,
                      }
                    )
                  )
                },
                record.uploadSessionToken
              )

              setJobUploadStatus(
                jobId,
                buildUploadStatus(
                  jobId,
                  'uploading',
                  transferMessage,
                  totalFiles,
                  uploadedFiles,
                  {
                    currentFileName: record.filename,
                    progress: 100,
                  }
                )
              )
            }

            uploadSucceeded = true
            break
          } catch (error: any) {
            lastUploadError = error
            if (isDeletedJobUploadError(error)) {
              break
            }

            try {
              const uploadSessionToken = jobRecords.find(item => item.uploadSessionToken)?.uploadSessionToken
              if (await jobHasLeftPendingState(jobId, uploadSessionToken)) {
                await deleteUploadRecord(record.id)
                setJobUploadStatus(jobId, null)
                shouldContinueQueue = true
                uploadSucceeded = true
                break
              }
            } catch {
              // If the follow-up check also fails, fall through to retry handling.
            }

            if (attempt < TRANSIENT_UPLOAD_ATTEMPTS && isTransientUploadError(error)) {
              setJobUploadStatus(
                jobId,
                buildUploadStatus(
                  jobId,
                  'queued',
                  `Upload is taking longer than expected. Retrying ${record.filename} (${attempt + 1}/3)...`,
                  totalFiles,
                  uploadedFiles,
                  {
                    currentFileName: record.filename,
                    progress: undefined,
                  }
                )
              )
              await wait(attempt * 2500)
              continue
            }

            break
          }
        }

        if (!uploadSucceeded && isTransientUploadError(lastUploadError)) {
          setJobUploadStatus(
            jobId,
            buildUploadStatus(
              jobId,
              'queued',
              `Upload is taking longer than expected. Retrying ${record.filename} automatically...`,
              totalFiles,
              uploadedFiles,
              {
                currentFileName: record.filename,
                progress: undefined,
              }
            )
          )
          await wait(TRANSIENT_UPLOAD_RETRY_DELAY_MS)
          shouldContinueQueue = true
          break
        }

        if (uploadSucceeded) {
          const remainingRecords = await getUploadRecordsForJob(jobId)
          if (remainingRecords.some(item => item.id === record.id)) {
            await deleteUploadRecord(record.id)
          }
          uploadedFiles += 1
        } else {
          const error = lastUploadError
          if (isDeletedJobUploadError(error)) {
            await deleteUploadRecordsForJob(jobId)
            setJobUploadStatus(jobId, null)
            shouldContinueQueue = true
            break
          }

          setJobUploadStatus(
            jobId,
            buildUploadStatus(
              jobId,
              'failed',
              `Upload paused: ${record.filename}`,
              totalFiles,
              uploadedFiles,
              {
                currentFileName: record.filename,
                error: getUploadErrorMessage(error) || 'Upload is taking longer than expected. Refreshing the page will resume it.',
              }
            )
          )
          return
        }
      }

      if (shouldContinueQueue) {
        continue
      }

      setJobUploadStatus(
        jobId,
        buildUploadStatus(
          jobId,
          'starting',
          'Starting job...',
          totalFiles,
          uploadedFiles
        )
      )

      try {
        const uploadSessionToken = jobRecords.find(record => record.uploadSessionToken)?.uploadSessionToken
        if (await jobHasLeftPendingState(jobId, uploadSessionToken)) {
          setJobUploadStatus(jobId, null)
          continue
        }

        await executeJob(jobId, uploadSessionToken)
        setJobUploadStatus(jobId, null)
      } catch (error: any) {
        if (isJobAlreadyStartingOrStartedError(error)) {
          try {
            const uploadSessionToken = jobRecords.find(record => record.uploadSessionToken)?.uploadSessionToken
            if (await jobHasLeftPendingState(jobId, uploadSessionToken)) {
              setJobUploadStatus(jobId, null)
              continue
            }
          } catch (followUpError: any) {
            setJobUploadStatus(
              jobId,
              buildUploadStatus(
                jobId,
                'failed',
                'Failed to confirm job start after upload',
                totalFiles,
                uploadedFiles,
                {
                  error: getUploadErrorMessage(followUpError) || getUploadErrorMessage(error) || 'Failed to confirm job start after upload',
                }
              )
            )
            return
          }
        }

        setJobUploadStatus(
          jobId,
          buildUploadStatus(
            jobId,
            'failed',
            'Failed to start job after upload',
            totalFiles,
            uploadedFiles,
            {
              error: error?.message || 'Failed to start job after upload',
            }
          )
        )
        return
      }
    }
  } finally {
    uploadInFlight = false
  }
}

export const startPendingJobUploadProcessor = async () => {
  if (!isBrowser()) return

  if (!uploadProcessorStarted) {
    uploadProcessorStarted = true
    if (hasIndexedDb()) {
      await resetInterruptedUploadsToQueued()
    }
  }

  void processUploadQueue()
}

export const enqueuePendingJobInputUploads = async (
  jobId: number,
  files: PendingJobUploadFile[],
  googleDriveFiles: PendingGoogleDriveJobImportFile[] = [],
  uploadSessionToken?: string
) => {
  const uniqueFiles = files.filter((file, index, allFiles) => {
    const key = getFileFingerprint(file)
    return allFiles.findIndex(candidate => (
      getFileFingerprint(candidate) === key
    )) === index
  })
  const uniqueGoogleDriveFiles = googleDriveFiles.filter((file, index, allFiles) => {
    const key = getGoogleDriveFingerprint(file)
    return allFiles.findIndex(candidate => (
      getGoogleDriveFingerprint(candidate) === key
    )) === index
  })

  // Job IDs can restart when the local database is reset, while IndexedDB survives.
  // Clear stale browser-side records for this job ID before enqueueing the current selection.
  await deleteUploadRecordsForJob(jobId)

  const baseOrder = Date.now()

  for (let index = 0; index < uniqueFiles.length; index++) {
    const file = uniqueFiles[index]
    await putUploadRecord({
      id: `${jobId}:${encodeURIComponent(getFileFingerprint(file))}`,
      schemaVersion: UPLOAD_RECORD_SCHEMA_VERSION,
      source: 'pc',
      jobId,
      tempId: file.tempId,
      filename: file.filename,
      original_filename: file.original_filename || file.file.name,
      size_bytes: file.size_bytes,
      lastModified: file.file.lastModified,
      file_format: file.file_format,
      created_at: file.created_at,
      queueOrder: baseOrder + index,
      fileBlob: file.file,
      uploadSessionToken,
    })
  }

  for (let index = 0; index < uniqueGoogleDriveFiles.length; index++) {
    const file = uniqueGoogleDriveFiles[index]
    await putUploadRecord({
      id: `${jobId}:${encodeURIComponent(getGoogleDriveFingerprint(file))}`,
      schemaVersion: UPLOAD_RECORD_SCHEMA_VERSION,
      source: 'google-drive',
      jobId,
      tempId: file.tempId,
      filename: file.filename,
      original_filename: file.original_filename || file.filename,
      size_bytes: file.size_bytes || 0,
      file_format: file.file_format,
      created_at: file.created_at,
      queueOrder: baseOrder + uniqueFiles.length + index,
      googleFileId: file.googleFileId,
      googleAccessToken: file.accessToken,
      mime_type: file.mime_type,
      uploadSessionToken,
    })
  }

  const totalQueuedFiles = uniqueFiles.length + uniqueGoogleDriveFiles.length

  setJobUploadStatus(
    jobId,
    buildUploadStatus(
      jobId,
      'queued',
      `Waiting to upload ${totalQueuedFiles} selected file${totalQueuedFiles !== 1 ? 's' : ''}...`,
      totalQueuedFiles,
      0
    )
  )
}

export const enqueuePendingJobUploads = async (
  jobId: number,
  files: PendingJobUploadFile[],
  uploadSessionToken?: string
) => {
  await enqueuePendingJobInputUploads(jobId, files, [], uploadSessionToken)
}

export const queuePendingJobInputUploadsInBackground = (
  jobId: number,
  files: PendingJobUploadFile[],
  googleDriveFiles: PendingGoogleDriveJobImportFile[] = [],
  uploadSessionToken?: string
) => {
  const totalFiles = files.length + googleDriveFiles.length

  setJobUploadStatus(
    jobId,
    buildUploadStatus(
      jobId,
      'queued',
      totalFiles > 0
        ? `Preparing ${totalFiles} selected file${totalFiles !== 1 ? 's' : ''} for upload...`
        : 'Preparing job upload queue...',
      totalFiles,
      0
    )
  )

  window.setTimeout(() => {
    void (async () => {
      try {
        const uniqueFiles = files.filter((file, index, allFiles) => {
          const key = getFileFingerprint(file)
          return allFiles.findIndex(candidate => (
            getFileFingerprint(candidate) === key
          )) === index
        })
        const uniqueGoogleDriveFiles = googleDriveFiles.filter((file, index, allFiles) => {
          const key = getGoogleDriveFingerprint(file)
          return allFiles.findIndex(candidate => (
            getGoogleDriveFingerprint(candidate) === key
          )) === index
        })

        const baseOrder = Date.now()
        uniqueFiles.forEach((file, index) => {
          inMemoryUploadRecords.push({
            id: `${jobId}:${encodeURIComponent(getFileFingerprint(file))}`,
            schemaVersion: UPLOAD_RECORD_SCHEMA_VERSION,
            source: 'pc',
            jobId,
            tempId: file.tempId,
            filename: file.filename,
            original_filename: file.original_filename || file.file.name,
            size_bytes: file.size_bytes,
            lastModified: file.file.lastModified,
            file_format: file.file_format,
            created_at: file.created_at,
            queueOrder: baseOrder + index,
            fileBlob: file.file,
            uploadSessionToken,
          })
        })

        uniqueGoogleDriveFiles.forEach((file, index) => {
          inMemoryUploadRecords.push({
            id: `${jobId}:${encodeURIComponent(getGoogleDriveFingerprint(file))}`,
            schemaVersion: UPLOAD_RECORD_SCHEMA_VERSION,
            source: 'google-drive',
            jobId,
            tempId: file.tempId,
            filename: file.filename,
            original_filename: file.original_filename || file.filename,
            size_bytes: file.size_bytes || 0,
            file_format: file.file_format,
            created_at: file.created_at,
            queueOrder: baseOrder + uniqueFiles.length + index,
            googleFileId: file.googleFileId,
            googleAccessToken: file.accessToken,
            mime_type: file.mime_type,
            uploadSessionToken,
          })
        })
        await startPendingJobUploadProcessor()
      } catch (error: any) {
        setJobUploadStatus(
          jobId,
          buildUploadStatus(
            jobId,
            'failed',
            'Failed to queue selected files',
            totalFiles,
            0,
            {
              error: getUploadErrorMessage(error) || 'Failed to queue selected files',
            }
          )
        )
      }
    })()
  }, 0)
}
