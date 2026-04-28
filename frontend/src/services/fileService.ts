import apiClient from './apiClient'

export const getUploadResponseTimeoutMs = (sizeBytes?: number | null): number => {
  const baseTimeoutMs = 5 * 60 * 1000
  const bytesPerGiB = 1024 * 1024 * 1024
  if (!sizeBytes || sizeBytes <= 0) {
    return baseTimeoutMs
  }

  const extraGiB = Math.ceil(sizeBytes / bytesPerGiB)
  return baseTimeoutMs + (extraGiB * 2 * 60 * 1000)
}

const extractApiErrorMessage = (errorData: any, fallback: string): string => {
  const candidate = (
    errorData?.message ||
    errorData?.detail ||
    errorData?.error?.message ||
    errorData?.error
  )

  return typeof candidate === 'string' && candidate.trim().length > 0
    ? candidate
    : fallback
}

export interface File {
  id: number
  job_id: number | null
  filename: string
  s3_key: string
  file_type: 'input' | 'output' | 'intermediate' | 'log'
  file_format?: string
  size_bytes: number
  checksum: string
  uploaded_at: string
  created_at: string
}

export interface StorageFileUpdatePayload {
  filename?: string
  file_format?: string
}

export interface FileListResponse {
  success: boolean
  data: File[]
  pagination?: {
    page: number
    per_page: number
    total: number
    total_pages: number
  }
}

export interface JobOutputsZipStatus {
  status: 'idle' | 'queued' | 'processing' | 'ready' | 'failed' | 'expired'
  download_url: string | null
  filename: string | null
  expires_in: number | null
  error: string | null
}

export const uploadFile = async (
  file: globalThis.File,
  jobId: number | null,
  fileType: 'input' | 'output' | 'intermediate' | 'log',
  fileFormat?: string,
  onProgress?: (progress: number) => void,
  authToken?: string,
  signal?: AbortSignal
): Promise<File> => {
  try {
    const formData = new FormData()
    formData.append('file', file)
    
    const params: any = { file_type: fileType }
    if (jobId !== null) params.job_id = jobId
    if (fileFormat) params.file_format = fileFormat
    
    const response = await apiClient.post<{ success: boolean; data: File; message?: string }>(
      '/api/storage/upload',
      formData,
      {
        params,
        headers: {
          'Content-Type': 'multipart/form-data',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        timeout: getUploadResponseTimeoutMs(file.size),
        signal,
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            onProgress(Math.min(percentCompleted, 100))
          }
        },
      }
    )
    
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to upload file')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      const message = (
        errorData.message ||
        errorData.detail ||
        errorData.error?.message ||
        errorData.error ||
        'Failed to upload file'
      )
      const uploadError = new Error(message) as Error & { status?: number; code?: string }
      uploadError.status = error.response.status
      uploadError.code = errorData.error?.code || errorData.code
      throw uploadError
    }
    if (error.code === 'ECONNABORTED') {
      throw new Error('Upload reached the server, but storage did not confirm in time. Please retry after checking that MinIO is healthy.')
    }
    throw error
  }
}

export interface StorageSummary {
  used_bytes: number
  max_storage_bytes: number
  remaining_bytes: number | null
  usage_ratio: number | null
  subscription_upgrade_available: boolean
  subscription_period: 'weekly' | string
}

export const getStorageSummary = async (): Promise<StorageSummary> => {
  const response = await apiClient.get<{ success: boolean; data: StorageSummary; message?: string }>('/api/storage/summary')
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to get storage summary')
}

export interface GoogleDriveJobImportPayload {
  file_id: string
  access_token: string
  filename: string
  mime_type?: string
  file_format?: string | null
}

export const importGoogleDriveFileToJob = async (
  jobId: number | null,
  payload: GoogleDriveJobImportPayload,
  authToken?: string,
  signal?: AbortSignal
): Promise<File> => {
  const params: { job_id?: number } = {}
  if (jobId !== null) {
    params.job_id = jobId
  }

  const response = await apiClient.post<{ success: boolean; data: File; message?: string }>(
    '/api/storage/import-google-drive',
    payload,
    {
      params,
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
      signal,
    }
  )

  if (response.data.success) {
    return response.data.data
  }

  throw new Error(response.data.message || 'Failed to import Google Drive file')
}

export const getFiles = async (jobId?: number, fileType?: string, page: number = 1, perPage: number = 100): Promise<FileListResponse> => {
  const params: any = { page, per_page: perPage }
  if (jobId) params.job_id = jobId
  if (fileType) params.file_type = fileType
  
  const response = await apiClient.get<FileListResponse>('/api/storage/files', { params })
  return response.data
}

export const getFile = async (fileId: number): Promise<File> => {
  const response = await apiClient.get<{ success: boolean; data: File }>(`/api/storage/files/${fileId}`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to get file')
}

export const downloadFile = async (fileId: number): Promise<void> => {
  try {
    const response = await apiClient.get(`/api/storage/files/${fileId}/download`, {
      responseType: 'blob'
    })
    
    // Get filename from Content-Disposition header
    const contentDisposition = response.headers['content-disposition'] || response.headers['Content-Disposition']
    let filename = `file_${fileId}`
    if (contentDisposition) {
      const patterns = [
        /filename\*?=['"]?([^'";\n]+)['"]?/i,
        /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/i,
        /filename=(.+)/i
      ]
      
      for (const pattern of patterns) {
        const match = contentDisposition.match(pattern)
        if (match && match[1]) {
          filename = decodeURIComponent(match[1].replace(/['"]/g, ''))
          break
        }
      }
    }
    
    // Create blob URL and trigger download
    const blob = response.data as Blob
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    
    // Clean up
    setTimeout(() => {
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    }, 100)
  } catch (error: any) {
    console.error('Download error:', error)
    if (error.response?.data instanceof Blob) {
      const text = await error.response.data.text()
      try {
        const errorData = JSON.parse(text)
        throw new Error(errorData.message || 'Failed to download file')
      } catch {
        throw new Error('Failed to download file')
      }
    }
    throw error
  }
}

export const getFileViewUrl = async (fileId: number): Promise<string> => {
  try {
    // Fetch file as blob using authenticated request
    const response = await apiClient.get(`/api/storage/files/${fileId}/view`, {
      responseType: 'blob'
    })
    
    // Create blob URL from the response
    const blob = response.data as Blob
    const blobUrl = window.URL.createObjectURL(blob)
    
    return blobUrl
  } catch (error: any) {
    console.error('Error getting file view URL:', error)
    throw error
  }
}

export const deleteFile = async (fileId: number): Promise<void> => {
  await apiClient.delete(`/api/storage/files/${fileId}`)
}

export const updateStorageFile = async (fileId: number, payload: StorageFileUpdatePayload): Promise<File> => {
  try {
    const response = await apiClient.put<{ success: boolean; data: File; message?: string }>(
      `/api/storage/files/${fileId}`,
      payload
    )
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to update file')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to update file'))
    }
    throw error
  }
}

export const requestJobOutputsZip = async (jobId: number): Promise<JobOutputsZipStatus> => {
  const response = await apiClient.post<{ success: boolean; data: JobOutputsZipStatus; message?: string }>(
    `/api/storage/jobs/${jobId}/download-zip`,
    null,
    {
      timeout: 15000
    }
  )

  if (response.data.success && response.data.data) {
    return response.data.data
  }

  throw new Error(response.data.message || 'Failed to start ZIP generation')
}

export const getJobOutputsZipStatus = async (jobId: number): Promise<JobOutputsZipStatus> => {
  const response = await apiClient.get<{ success: boolean; data: JobOutputsZipStatus; message?: string }>(
    `/api/storage/jobs/${jobId}/download-zip`,
    {
      params: { redirect: false }
    }
  )

  if (response.data.success && response.data.data) {
    return response.data.data
  }

  throw new Error(response.data.message || 'Failed to get ZIP download status')
}

export const openJobOutputsZipLink = (status: JobOutputsZipStatus, jobId: number): void => {
  if (!status.download_url) {
    throw new Error('ZIP download link is not ready yet')
  }

  const link = document.createElement('a')
  link.href = status.download_url
  link.download = status.filename || `job_${jobId}_outputs.zip`
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()

  setTimeout(() => {
    document.body.removeChild(link)
  }, 100)
}
