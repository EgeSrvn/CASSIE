import apiClient from './apiClient'
import { getUploadResponseTimeoutMs } from './fileService'
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
  
  const response = await apiClient.post('/api/data-files/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    timeout: getUploadResponseTimeoutMs(file.size),
    signal,
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(Math.min(percentCompleted, 100))
      }
    },
  })
  return response.data.data
}

interface DirectUploadPrepareResponse {
  upload_url: string
  s3_key: string
  filename: string
  expires_in: number
}

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
    }
  )

  if (!prepareResponse.data.success) {
    throw new Error(prepareResponse.data.message || 'Failed to prepare direct upload')
  }

  const prepared = prepareResponse.data.data
  await axios.put(prepared.upload_url, file, {
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
    },
    timeout: getUploadResponseTimeoutMs(file.size),
    signal,
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
        onProgress(Math.min(percentCompleted, 100))
      }
    },
  })

  const completeResponse = await apiClient.post<{ success: boolean; data: DataFile; message?: string }>(
    '/api/data-files/direct-upload/complete',
    {
      filename: prepared.filename,
      s3_key: prepared.s3_key,
      size_bytes: file.size,
      folder_id: folderId ?? null,
      file_format: fileFormat || null,
    }
  )

  if (completeResponse.data.success) {
    return completeResponse.data.data
  }

  throw new Error(completeResponse.data.message || 'Failed to complete direct upload')
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
