import apiClient from './apiClient'

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

export const uploadFile = async (
  file: globalThis.File,
  jobId: number | null,
  fileType: 'input' | 'output' | 'intermediate' | 'log',
  fileFormat?: string,
  onProgress?: (progress: number) => void
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
        },
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            onProgress(percentCompleted)
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
    throw error
  }
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

export const downloadJobOutputsZip = async (jobId: number): Promise<void> => {
  try {
    const response = await apiClient.get(`/api/storage/jobs/${jobId}/download-zip`, {
      responseType: 'blob',
      timeout: 300000 // 5 minutes timeout for large ZIP files
    })
    
    // response.data is already a Blob when responseType is 'blob'
    const blob = response.data as Blob
    
    if (!(blob instanceof Blob)) {
      throw new Error('Invalid response: expected blob')
    }
    
    // Check if blob is actually an error response (JSON error in blob format)
    if (blob.type === 'application/json' || blob.size < 100) {
      const text = await blob.text()
      try {
        const errorData = JSON.parse(text)
        throw new Error(errorData.message || 'Failed to download ZIP')
      } catch {
        // If not JSON, might be empty or error message
        if (text.includes('error') || text.includes('Error')) {
          throw new Error(text)
        }
      }
    }
    
    // Extract filename from Content-Disposition header if available
    const contentDisposition = response.headers['content-disposition'] || response.headers['Content-Disposition']
    let filename = `job_${jobId}_outputs.zip`
    if (contentDisposition) {
      // Try different patterns for Content-Disposition parsing
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
    
    // Create a blob URL and trigger download
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    
    // Trigger download
    link.click()
    
    // Clean up
    setTimeout(() => {
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    }, 100)
  } catch (error: any) {
    console.error('ZIP download error:', error)
    // If blob download fails, try to show error message
    if (error.response?.data instanceof Blob) {
      // Try to read error message from blob
      const text = await error.response.data.text()
      try {
        const errorData = JSON.parse(text)
        alert(`Failed to download ZIP: ${errorData.message || 'Unknown error'}`)
      } catch {
        alert('Failed to download ZIP archive')
      }
    } else {
      alert(`Failed to download ZIP: ${error.message || 'Unknown error'}`)
    }
    throw error
  }
}
