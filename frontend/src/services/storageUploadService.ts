import { directUploadDataFile } from './dataFileService'

export type StorageUploadStatus = 'queued' | 'uploading' | 'confirming' | 'ready' | 'failed'

export interface StorageUploadItem {
  id: string
  filename: string
  size_bytes: number | null
  file_format: string | null
  created_at: string
  folderPath?: string
  progress: number | null
  status: StorageUploadStatus
  error?: string
}

interface StorageUploadRecord extends StorageUploadItem {
  file: globalThis.File
  queueOrder: number
}

const listeners = new Set<(items: StorageUploadItem[]) => void>()
let processorStarted = false
let uploadInFlight = false
let records: StorageUploadRecord[] = []

const toItem = (record: StorageUploadRecord): StorageUploadItem => ({
  id: record.id,
  filename: record.filename,
  size_bytes: record.size_bytes,
  file_format: record.file_format,
  created_at: record.created_at,
  folderPath: record.folderPath,
  progress: record.progress,
  status: record.status,
  error: record.error,
})

const emit = () => {
  const items = records
    .slice()
    .sort((a, b) => a.queueOrder - b.queueOrder)
    .map(toItem)
  listeners.forEach((listener) => listener(items))
}

const updateRecord = (recordId: string, patch: Partial<StorageUploadRecord>): StorageUploadRecord | null => {
  let updatedRecord: StorageUploadRecord | null = null
  records = records.map((record) => {
    if (record.id !== recordId) return record
    updatedRecord = { ...record, ...patch }
    return updatedRecord
  })
  emit()
  return updatedRecord
}

const removeRecord = (recordId: string) => {
  records = records.filter((record) => record.id !== recordId)
  emit()
}

const runProcessor = async () => {
  if (uploadInFlight) return
  uploadInFlight = true

  try {
    while (true) {
      const record = records.find((item) => item.status !== 'ready' && item.status !== 'failed')
      if (!record) return

      updateRecord(record.id, { status: 'uploading', progress: 1, error: undefined })

      try {
        const uploadedFile = await directUploadDataFile(
          record.file,
          null,
          record.file_format || undefined,
          (progress) => {
            updateRecord(record.id, {
              progress,
              status: progress >= 100 ? 'confirming' : 'uploading',
            })
          }
        )
        updateRecord(record.id, { status: 'ready', progress: 100 })
        window.dispatchEvent(new CustomEvent('storage-library-change', {
          detail: {
            deltaBytes: uploadedFile.size_bytes ?? record.size_bytes ?? 0,
          },
        }))
        removeRecord(record.id)
      } catch (error: any) {
        updateRecord(record.id, {
          status: 'failed',
          error: error?.response?.data?.message || error?.message || 'Failed to upload file',
        })
      }
    }
  } finally {
    uploadInFlight = false
  }
}

export const queueStorageUploads = async (
  files: globalThis.File[],
  inferFileFormat: (filename: string) => string | undefined
) => {
  const selectedAt = Date.now()
  const nextRecords = files.map((file, index): StorageUploadRecord => ({
    id: `storage-${selectedAt}-${index}-${file.name}-${file.size}-${file.lastModified}`,
    filename: file.name,
    size_bytes: file.size,
    file_format: inferFileFormat(file.name) || null,
    created_at: new Date().toISOString(),
    folderPath: 'Selected Files',
    progress: 0,
    status: 'queued',
    file,
    queueOrder: selectedAt + index,
  }))

  records = [...nextRecords, ...records]
  emit()
  void runProcessor()
}

export const dismissStorageUpload = async (recordId: string) => {
  removeRecord(recordId)
}

export const getStorageUploadItems = () => records.map(toItem)

export const subscribeToStorageUploads = (listener: (items: StorageUploadItem[]) => void) => {
  listeners.add(listener)
  listener(getStorageUploadItems())
  return () => {
    listeners.delete(listener)
  }
}

export const startStorageUploadProcessor = async () => {
  if (processorStarted) return
  processorStarted = true
  emit()

  window.addEventListener('beforeunload', (event) => {
    if (!uploadInFlight) return
    event.preventDefault()
    event.returnValue = ''
  })
}
