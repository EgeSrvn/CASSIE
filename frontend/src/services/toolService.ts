import apiClient from './apiClient'

export interface Tool {
  id: number
  tool_id?: string
  name: string
  description: string
  type: string
  enabled: boolean
}

export interface ToolListResponse {
  success: boolean
  data: Tool[]
  message?: string
}

/**
 * Get list of available tools from the backend.
 * Falls back to a default list if the API is unavailable.
 */
export const getAvailableTools = async (): Promise<Tool[]> => {
  try {
    const response = await apiClient.get<ToolListResponse>('/api/tools')
    if (response.data.success && response.data.data) {
      return response.data.data
    }
  } catch (error) {
    console.warn('Tools endpoint not available, using fallback list', error)
  }
  
  // Fallback: return default tool list
  return [
    {
      id: 0,
      tool_id: 'FASTQC',
      name: 'FastQC',
      description: 'Quality control for raw sequence data',
      type: 'qc',
      enabled: true,
    },
    {
      id: 1,
      tool_id: 'SPADES',
      name: 'SPAdes',
      description: 'Genome assembler',
      type: 'transform',
      enabled: true,
    },
    {
      id: 2,
      tool_id: 'QUAST',
      name: 'QUAST',
      description: 'Assembly quality assessment',
      type: 'qc',
      enabled: true,
    },
    {
      id: 3,
      tool_id: 'GENOMESCOPE2',
      name: 'GenomeScope2',
      description: 'Reference-free profiling',
      type: 'qc',
      enabled: true,
    },
  ]
}

export interface ToolRequirement {
  type: string
  label: string
  formats: string[]
  is_intermediate?: boolean
  source_tool?: string
}

export interface ToolRequirementInfo {
  tool_index: number
  tool_id: string
  tool_name: string
  tool_type: string
  description?: string
  requirements: ToolRequirement[]
}

export interface ToolRequirementsResponse {
  success: boolean
  data: ToolRequirementInfo[]
  message?: string
}

/**
 * Get input requirements for specified tools.
 */
export const getToolRequirements = async (toolIndices: number[]): Promise<ToolRequirementInfo[]> => {
  try {
    if (toolIndices.length === 0) {
      return []
    }
    const indicesStr = toolIndices.join(',')
    const response = await apiClient.get<ToolRequirementsResponse>(`/api/tools/requirements?tool_indices=${indicesStr}`)
    if (response.data.success && response.data.data) {
      return response.data.data
    }
    return []
  } catch (error) {
    console.error('Failed to get tool requirements:', error)
    return []
  }
}
