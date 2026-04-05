import apiClient from './apiClient'

export interface Pipeline {
  id: number
  user_id: number
  name: string
  description?: string
  nodes: any
  edges: any
  saved_at: string
  is_shared?: boolean
}

export interface PipelineCreate {
  name: string
  description?: string
  nodes: any
  edges: any
}

export interface PipelineUpdate {
  name?: string
  description?: string
  nodes?: any
  edges?: any
}

export interface PipelineListResponse {
  success: boolean
  data: Pipeline[]
  message?: string
}

export interface PipelineResponse {
  success: boolean
  data: Pipeline
  message?: string
}

export const getPipelines = async (): Promise<Pipeline[]> => {
  const response = await apiClient.get<PipelineListResponse>('/api/pipelines')
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch pipelines')
}

export const getPipeline = async (id: number): Promise<Pipeline> => {
  const response = await apiClient.get<PipelineResponse>(`/api/pipelines/${id}`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch pipeline')
}

export const createPipeline = async (data: PipelineCreate): Promise<Pipeline> => {
  const response = await apiClient.post<PipelineResponse>('/api/pipelines', data)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to create pipeline')
}

export const updatePipeline = async (id: number, data: PipelineUpdate): Promise<Pipeline> => {
  const response = await apiClient.put<PipelineResponse>(`/api/pipelines/${id}`, data)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to update pipeline')
}

export const deletePipeline = async (id: number): Promise<void> => {
  const response = await apiClient.delete(`/api/pipelines/${id}`)
  if (!response.data.success) {
    throw new Error(response.data.message || 'Failed to delete pipeline')
  }
}

export interface PipelineRequirement {
  type: string
  label: string
  formats: string[]
}

export interface PipelineRequirements {
  input_requirements: PipelineRequirement[]
  tools: string[]
  has_spades: boolean
  has_quast: boolean
  has_fastqc: boolean
  has_genomescope2: boolean
}

export const getPipelineRequirements = async (id: number): Promise<PipelineRequirements> => {
  const response = await apiClient.get<{ success: boolean; data: PipelineRequirements; message?: string }>(`/api/pipelines/${id}/requirements`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch pipeline requirements')
}

export const getSharedPipelines = async (): Promise<Pipeline[]> => {
  const response = await apiClient.get<PipelineListResponse>('/api/pipelines/shared')
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch shared pipelines')
}

export const sharePipeline = async (id: number): Promise<Pipeline> => {
  const response = await apiClient.post<PipelineResponse>(`/api/pipelines/${id}/share`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to share pipeline')
}

export const unsharePipeline = async (id: number): Promise<Pipeline> => {
  const response = await apiClient.post<PipelineResponse>(`/api/pipelines/${id}/unshare`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to unshare pipeline')
}
