import apiClient from './apiClient'

export interface Workflow {
  id: number
  name: string
  description?: string
  workflow_type: 'predefined' | 'custom' | 'template'
  is_public: boolean
  is_active: boolean
}

export interface WorkflowListResponse {
  success: boolean
  data: Workflow[]
}

// For now, we'll use a simple approach - get workflows from a list endpoint
// If that doesn't exist, we'll hardcode the workflow ID
export const getWorkflows = async (): Promise<Workflow[]> => {
  try {
    const response = await apiClient.get<WorkflowListResponse>('/api/workflows')
    if (response.data.success) {
      return response.data.data
    }
  } catch (error) {
    console.warn('Workflows endpoint not available, using default workflow')
  }
  
  // Fallback: return default workflow (ID 2 from database)
  return [
    {
      id: 2,
      name: 'FastQC Quality Control',
      description: 'FastQC quality control pipeline for sequencing data',
      workflow_type: 'predefined' as const,
      is_public: true,
      is_active: true,
    }
  ]
}

