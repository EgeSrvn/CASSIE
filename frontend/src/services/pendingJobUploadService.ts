import { executeJob } from './jobService'
import { uploadFile } from './fileService'

export type PendingJobUploadFile = {
  tempId: number
  file: globalThis.File
  filename: string
  size_bytes: number
  file_format: string | null
  uploaded_at: null
  created_at: string
  folderPath?: string
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

type StoredUploadRecord = {
  id: string
  jobId: number
  tempId: number
  filename: string
  size_bytes: number
  file_format: string | null
  created_at: string
  queueOrder: number
  fileBlob: Blob
}

const DB_NAME = 'cassie-pending-job-uploads'
const DB_VERSION = 1
const STORE_NAME = 'upload_files'
const STATUS_STORAGE_KEY = 'cassie-pending-job-upload-status'

const listeners = new Set<(jobId: number, status: JobUploadStatus | null) => void>()
let uploadProcessorStarted = false
let uploadInFlight = false

const isBrowser = () => typeof window !== 'undefined' && typeof indexedDB !== 'undefined'

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
    if (!isBrowser()) {
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
  return withStore('readonly', async (store) => {
    const records = await requestToPromise(store.getAll())
    return (records as StoredUploadRecord[]).sort((a, b) => a.queueOrder - b.queueOrder)
  })
}

const getUploadRecordsForJob = async (jobId: number): Promise<StoredUploadRecord[]> => {
  const allRecords = await getAllUploadRecords()
  return allRecords.filter(record => record.jobId === jobId)
}

const putUploadRecord = async (record: StoredUploadRecord) => {
  await withStore('readwrite', async (store) => {
    await requestToPromise(store.put(record))
  })
}

const deleteUploadRecord = async (recordId: string) => {
  await withStore('readwrite', async (store) => {
    await requestToPromise(store.delete(recordId))
  })
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
  const statuses = readStatusMap()
  const allRecords = await getAllUploadRecords()
  const jobsWithQueuedFiles = new Set(allRecords.map(record => record.jobId))

  Object.values(statuses).forEach(status => {
    if (!jobsWithQueuedFiles.has(status.jobId)) {
      setJobUploadStatus(status.jobId, null)
      return
    }

    if (status.stage === 'uploading' || status.stage === 'starting') {
      const remainingFiles = allRecords.filter(record => record.jobId === status.jobId)
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
      const allRecords = await getAllUploadRecords()
      if (allRecords.length === 0) break

      const nextRecord = allRecords[0]
      const jobId = nextRecord.jobId
      const jobRecords = allRecords.filter(record => record.jobId === jobId).sort((a, b) => a.queueOrder - b.queueOrder)
      const currentStatus = getJobUploadStatus(jobId)
      const totalFiles = currentStatus?.totalFiles || jobRecords.length
      let uploadedFiles = currentStatus?.uploadedFiles || 0

      for (const record of jobRecords) {
        const filePosition = uploadedFiles + 1
        setJobUploadStatus(
          jobId,
          buildUploadStatus(
            jobId,
            'uploading',
            `Uploading selected files (${filePosition}/${totalFiles}): ${record.filename}`,
            totalFiles,
            uploadedFiles,
            {
              currentFileName: record.filename,
              progress: 0,
            }
          )
        )

        try {
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
                  `Uploading selected files (${filePosition}/${totalFiles}): ${record.filename}`,
                  totalFiles,
                  uploadedFiles,
                  {
                    currentFileName: record.filename,
                    progress,
                  }
                )
              )
            }
          )

          await deleteUploadRecord(record.id)
          uploadedFiles += 1
        } catch (error: any) {
          setJobUploadStatus(
            jobId,
            buildUploadStatus(
              jobId,
              'failed',
              `Upload failed: ${record.filename}`,
              totalFiles,
              uploadedFiles,
              {
                currentFileName: record.filename,
                error: error?.message || 'Failed to upload selected file',
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
          'starting',
          'Starting job...',
          totalFiles,
          uploadedFiles
        )
      )

      try {
        await executeJob(jobId)
        setJobUploadStatus(jobId, null)
      } catch (error: any) {
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
  if (uploadProcessorStarted || !isBrowser()) return
  uploadProcessorStarted = true
  await resetInterruptedUploadsToQueued()
  void processUploadQueue()
}

export const enqueuePendingJobUploads = async (jobId: number, files: PendingJobUploadFile[]) => {
  const existingRecords = await getUploadRecordsForJob(jobId)
  const baseOrder = existingRecords.length > 0
    ? Math.max(...existingRecords.map(record => record.queueOrder)) + 1
    : Date.now()

  for (let index = 0; index < files.length; index++) {
    const file = files[index]
    await putUploadRecord({
      id: `${jobId}:${file.tempId}`,
      jobId,
      tempId: file.tempId,
      filename: file.filename,
      size_bytes: file.size_bytes,
      file_format: file.file_format,
      created_at: file.created_at,
      queueOrder: baseOrder + index,
      fileBlob: file.file,
    })
  }

  setJobUploadStatus(
    jobId,
    buildUploadStatus(
      jobId,
      'queued',
      `Waiting to upload ${files.length} selected file${files.length !== 1 ? 's' : ''}...`,
      files.length,
      0
    )
  )

  await startPendingJobUploadProcessor()
  void processUploadQueue()
}
