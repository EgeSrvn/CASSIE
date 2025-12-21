import apiClient from './apiClient'

export interface Job {
  id: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  workflow_id: number
  pipeline_config_id?: number
  pipeline_id?: number
  assembler?: string
  data_types?: string[]
  cloud_provider?: string
  vm_name?: string
  created_at: string
  updated_at: string
}

export interface JobCreate {
  name: string
  workflow_id?: number // Optional, will be created dynamically from tools
  tool_indices?: number[] // Tool indices to use (e.g., [0] for FastQC)
  pipeline_id?: number // Optional saved pipeline ID (visual pipeline builder)
  pipeline_config_id?: number
  assembler?: string
  data_types?: string[]
  cloud_provider?: string
  vm_name?: string // Virtual machine name for execution (e.g., 'vm1', 'vm2')
  input_file_ids?: number[] // Pre-uploaded file IDs to associate with this job
}

export interface JobListResponse {
  success: boolean
  data: Job[]
  pagination?: {
    page: number
    per_page: number
    total: number
    total_pages: number
  }
}

export const createJob = async (jobData: JobCreate): Promise<Job> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: Job; message?: string }>('/api/jobs', jobData)
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to create job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(errorData.message || errorData.detail || errorData.error || 'Failed to create job')
    }
    throw error
  }
}

export const getJobs = async (status?: string, page: number = 1): Promise<JobListResponse> => {
  const params: any = { page, per_page: 20 }
  if (status) params.status = status
  
  const response = await apiClient.get<JobListResponse>('/api/jobs', { params })
  return response.data
}

export const getJob = async (jobId: number): Promise<Job> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: Job; message?: string }>(`/api/jobs/${jobId}`)
    if (response.data && response.data.success) {
      return response.data.data
    }
    throw new Error(response.data?.message || 'Failed to get job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(errorData.message || errorData.detail || errorData.error || 'Failed to get job')
    }
    throw error
  }
}

export const deleteJob = async (jobId: number): Promise<void> => {
  await apiClient.delete(`/api/jobs/${jobId}`)
}

export const executeJob = async (jobId: number): Promise<void> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: any; message?: string }>(`/api/jobs/${jobId}/execute`)
    if (!response.data.success) {
      throw new Error(response.data.message || 'Failed to execute job')
    }
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(errorData.message || errorData.detail || errorData.error || 'Failed to execute job')
    }
    throw error
  }
}

export const addFilesToJob = async (
  jobId: number, 
  fileIds?: number[], 
  fileMappings?: Record<string, number>
): Promise<Job> => {
  try {
    const requestBody: { file_ids?: number[]; file_mappings?: Record<string, number> } = {}
    if (fileMappings) {
      requestBody.file_mappings = fileMappings
    } else if (fileIds) {
      requestBody.file_ids = fileIds
    } else {
      throw new Error('Either fileIds or fileMappings must be provided')
    }

    const response = await apiClient.post<{ success: boolean; data: Job; message?: string }>(
      `/api/jobs/${jobId}/files`,
      requestBody
    )
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to add files to job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(errorData.message || errorData.detail || errorData.error || 'Failed to add files to job')
    }
    throw error
  }
}

export interface VM {
  name: string
  display_name: string
}

export const getAvailableVMs = async (): Promise<VM[]> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: VM[]; message?: string }>('/api/jobs/vms')
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to get available VMs')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(errorData.message || errorData.detail || errorData.error || 'Failed to get available VMs')
    }
    throw error
  }
}

