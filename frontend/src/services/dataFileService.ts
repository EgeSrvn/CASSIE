import apiClient from './apiClient'
import { createUploadActivityWatchdog } from './fileService'
import axios from 'axios'

export interface DataFile {
  id: number
  filename: string
  s3_key: string
  file_type: string
  file_format: string | null
  size_bytes: number | null
  checksum: string | null
  uploaded_at: string | null
  created_at: string
}

export const getDataFiles = async (folderId?: number | null): Promise<DataFile[]> => {
  const params = folderId !== undefined ? { folder_id: folderId } : {}
  const response = await apiClient.get('/api/data-files', { params })
  return response.data.data
}

export const getDataFileTree = async (): Promise<any[]> => {
  const response = await apiClient.get('/api/data-files/tree')
  return response.data.data
}

export const getDataFile = async (fileId: number): Promise<DataFile> => {
  const response = await apiClient.get(`/api/data-files/${fileId}`)
  return response.data.data
}

export const uploadDataFile = async (
  file: File,
  folderId?: number | null,
  fileFormat?: string,
  onProgress?: (progress: number) => void,
  signal?: AbortSignal
): Promise<DataFile> => {
  const formData = new FormData()
  formData.append('file', file)
  if (folderId !== undefined && folderId !== null) {
    formData.append('folder_id', folderId.toString())
  }
  if (fileFormat) {
    formData.append('file_format', fileFormat)
  }
  
  const watchdog = createUploadActivityWatchdog(signal)
  try {
    const response = await apiClient.post('/api/data-files/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      },
      timeout: 0,
      signal: watchdog.signal,
      onUploadProgress: (progressEvent) => {
        watchdog.markProgress(progressEvent.loaded)
        if (onProgress && progressEvent.total) {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(Math.min(percentCompleted, 100))
        }
      },
    })
    return response.data.data
  } catch (error: any) {
    if (watchdog.timedOut()) {
      throw new Error('Upload timed out after 5 minutes without transfer progress')
    }
    throw error
  } finally {
    watchdog.cleanup()
  }
}

interface DirectUploadBaseResponse {
  s3_key: string
  filename: string
  expires_in: number
}

interface DirectUploadSinglePrepareResponse extends DirectUploadBaseResponse {
  upload_strategy: 'single'
  upload_url: string
}

interface DirectUploadMultipartPrepareResponse extends DirectUploadBaseResponse {
  upload_strategy: 'multipart'
  upload_id: string
  part_size_bytes: number
  part_count: number
}

type DirectUploadPrepareResponse =
  | DirectUploadSinglePrepareResponse
  | DirectUploadMultipartPrepareResponse

interface DirectUploadPartUrlResponse {
  upload_url: string
  part_number: number
  expires_in: number
}

interface CompletedMultipartPart {
  part_number: number
  etag: string
}

const delay = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    const onAbort = () => {
      window.clearTimeout(timer)
      reject(new DOMException('Upload cancelled', 'AbortError'))
    }

    if (signal) {
      if (signal.aborted) {
        onAbort()
        return
      }
      signal.addEventListener('abort', onAbort, { once: true })
    }
  })

export const directUploadDataFile = async (
  file: File,
  folderId?: number | null,
  fileFormat?: string,
  onProgress?: (progress: number) => void,
  signal?: AbortSignal
): Promise<DataFile> => {
  const prepareResponse = await apiClient.post<{ success: boolean; data: DirectUploadPrepareResponse; message?: string }>(
    '/api/data-files/direct-upload/prepare',
    {
      filename: file.name,
      size_bytes: file.size,
      folder_id: folderId ?? null,
      file_format: fileFormat || null,
      content_type: file.type || 'application/octet-stream',
    },
    { signal }
  )

  if (!prepareResponse.data.success) {
    throw new Error(prepareResponse.data.message || 'Failed to prepare direct upload')
  }

  const prepared = prepareResponse.data.data
  let completedParts: CompletedMultipartPart[] | undefined

  if (prepared.upload_strategy === 'single') {
    const watchdog = createUploadActivityWatchdog(signal)
    try {
      await axios.put(prepared.upload_url, file, {
        headers: {
          'Content-Type': file.type || 'application/octet-stream',
        },
        timeout: 0,
        signal: watchdog.signal,
        onUploadProgress: (progressEvent) => {
          watchdog.markProgress(progressEvent.loaded)
          if (onProgress && progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            onProgress(Math.min(percentCompleted, 100))
          }
        },
      })
    } catch (error: any) {
      if (watchdog.timedOut()) {
        throw new Error('Upload timed out after 5 minutes without transfer progress')
      }
      throw error
    } finally {
      watchdog.cleanup()
    }
  } else {
    completedParts = []
    const watchdog = createUploadActivityWatchdog(signal)
    let multipartFinished = false

    try {
      const partSize = Math.max(prepared.part_size_bytes, 5 * 1024 * 1024)
      const totalParts = Math.max(prepared.part_count, Math.ceil(file.size / partSize))
      let uploadedCommittedBytes = 0

      for (let partIndex = 0; partIndex < totalParts; partIndex += 1) {
        const partNumber = partIndex + 1
        const chunkStart = partIndex * partSize
        const chunkEnd = Math.min(file.size, chunkStart + partSize)
        const chunk = file.slice(chunkStart, chunkEnd)

        const partUrlResponse = await apiClient.post<{ success: boolean; data: DirectUploadPartUrlResponse; message?: string }>(
          '/api/data-files/direct-upload/part-url',
          {
            s3_key: prepared.s3_key,
            upload_id: prepared.upload_id,
            part_number: partNumber,
          },
          { signal: watchdog.signal }
        )

        if (!partUrlResponse.data.success) {
          throw new Error(partUrlResponse.data.message || `Failed to prepare multipart upload part ${partNumber}`)
        }

        let currentPartLoaded = 0
        const uploadResponse = await axios.put(partUrlResponse.data.data.upload_url, chunk, {
          headers: {
            'Content-Type': file.type || 'application/octet-stream',
          },
          timeout: 0,
          signal: watchdog.signal,
          onUploadProgress: (progressEvent) => {
            currentPartLoaded = Math.min(progressEvent.loaded || 0, chunk.size)
            const aggregateLoaded = uploadedCommittedBytes + currentPartLoaded
            watchdog.markProgress(aggregateLoaded)
            if (onProgress && file.size > 0) {
              const percentCompleted = Math.round((aggregateLoaded * 100) / file.size)
              onProgress(Math.min(percentCompleted, 99))
            }
          },
        })

        uploadedCommittedBytes += chunk.size
        watchdog.markProgress(uploadedCommittedBytes)

        const etagHeader = (uploadResponse.headers?.['etag'] || uploadResponse.headers?.['ETag']) as string | undefined
        const etag = String(etagHeader || '').replace(/"/g, '').trim()
        if (!etag) {
          throw new Error(`Storage did not return an ETag for uploaded part ${partNumber}`)
        }

        completedParts.push({
          part_number: partNumber,
          etag,
        })

        if (onProgress && file.size > 0) {
          const percentCompleted = Math.round((uploadedCommittedBytes * 100) / file.size)
          onProgress(Math.min(percentCompleted, 99))
        }
      }

      multipartFinished = true
    } catch (error: any) {
      if (!signal?.aborted && completedParts) {
        try {
          await apiClient.post(
            '/api/data-files/direct-upload/abort',
            {
              s3_key: prepared.s3_key,
              upload_id: prepared.upload_id,
            },
            { signal }
          )
        } catch {
          // Best-effort cleanup only; surfacing the original upload error is more useful.
        }
      }

      if (watchdog.timedOut()) {
        throw new Error('Upload timed out after 5 minutes without transfer progress')
      }
      throw error
    } finally {
      if (!multipartFinished && onProgress) {
        onProgress(0)
      }
      watchdog.cleanup()
    }
  }

  let lastCompleteError: any = null
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      const completeResponse = await apiClient.post<{ success: boolean; data: DataFile; message?: string }>(
        '/api/data-files/direct-upload/complete',
        {
          filename: prepared.filename,
          s3_key: prepared.s3_key,
          size_bytes: file.size,
          folder_id: folderId ?? null,
          file_format: fileFormat || null,
          upload_id: prepared.upload_strategy === 'multipart' ? prepared.upload_id : null,
          parts: prepared.upload_strategy === 'multipart' ? completedParts : null,
        },
        { signal }
      )

      if (completeResponse.data.success) {
        if (onProgress) {
          onProgress(100)
        }
        return completeResponse.data.data
      }

      lastCompleteError = new Error(completeResponse.data.message || 'Failed to complete direct upload')
    } catch (error) {
      lastCompleteError = error
    }

    await delay(attempt * 1000, signal)
  }

  throw lastCompleteError || new Error('Failed to complete direct upload')
}

export interface CloudImportPayload {
  source_url: string
  filename?: string
  folder_id?: number | null
  file_format?: string | null
}

export const importCloudDataFile = async (payload: CloudImportPayload): Promise<DataFile> => {
  const response = await apiClient.post('/api/data-files/import-cloud', payload)
  return response.data.data
}

export interface GoogleDriveImportPayload {
  file_id: string
  access_token: string
  filename?: string
  mime_type?: string
  folder_id?: number | null
  file_format?: string | null
}

export const importGoogleDriveDataFile = async (payload: GoogleDriveImportPayload): Promise<DataFile> => {
  const response = await apiClient.post('/api/data-files/import-google-drive', payload)
  return response.data.data
}

export const renameDataFile = async (fileId: number, newName: string): Promise<DataFile> => {
  const response = await apiClient.put(`/api/data-files/${fileId}/rename`, null, {
    params: { new_name: newName }
  })
  return response.data.data
}

export const moveDataFile = async (fileId: number, targetFolderId?: number | null): Promise<DataFile> => {
  const params = targetFolderId !== undefined ? { target_folder_id: targetFolderId } : {}
  const response = await apiClient.put(`/api/data-files/${fileId}/move`, null, { params })
  return response.data.data
}

export const deleteDataFile = async (fileId: number): Promise<void> => {
  await apiClient.delete(`/api/data-files/${fileId}`)
}

export const downloadDataFile = async (fileId: number): Promise<void> => {
  // Get the presigned URL from backend (with redirect=false)
  const response = await apiClient.get(`/api/data-files/${fileId}/download`, {
    params: { redirect: false }
  })
  
  if (response.data.success && response.data.data) {
    const { download_url, filename } = response.data.data
    
    // Create a link and trigger download
    const link = document.createElement('a')
    link.href = download_url
    link.download = filename
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    
    // Clean up
    setTimeout(() => {
      document.body.removeChild(link)
    }, 100)
  } else {
    throw new Error(response.data.message || 'Failed to get download URL')
  }
}
