import apiClient from './apiClient'

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
  fileFormat?: string
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
    }
  })
  return response.data.data
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
