import apiClient from './apiClient'

export interface EditableFlagOption {
  label: string
  value: string
}

export interface EditableFlagDefinition {
  key: string
  label: string
  description?: string
  type: 'string' | 'integer' | 'number' | 'boolean' | 'select'
  default?: string | number | boolean
  placeholder?: string
  example?: string
  min?: number
  max?: number
  pattern?: string
  error_message?: string
  options?: EditableFlagOption[]
}

export interface Tool {
  id: number
  tool_id?: string
  name: string
  description: string
  type: string
  enabled: boolean
  editable_flags?: EditableFlagDefinition[]
  default_flag_values?: Record<string, string | number | boolean>
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
    {
      id: 4,
      tool_id: 'METASPADES',
      name: 'metaSPAdes',
      description: 'Metagenome assembly from paired short reads',
      type: 'transform',
      enabled: true,
    },
    {
      id: 5,
      tool_id: 'HIFIASM',
      name: 'Hifiasm',
      description: 'HiFi long-read genome assembly',
      type: 'transform',
      enabled: true,
    },
    {
      id: 6,
      tool_id: 'VERKKO',
      name: 'Verkko',
      description: 'Telomere-to-telomere long-read assembly pipeline',
      type: 'transform',
      enabled: true,
    },
    {
      id: 7,
      tool_id: 'LIFTOFF',
      name: 'Liftoff',
      description: 'Lift annotations from a reference genome to a target assembly',
      type: 'annotation',
      enabled: true,
    },
    {
      id: 8,
      tool_id: 'CAT',
      name: 'CAT',
      description: 'Comparative Annotation Toolkit on HAL alignments',
      type: 'annotation',
      enabled: true,
    },
    {
      id: 9,
      tool_id: 'BUSCO',
      name: 'BUSCO',
      description: 'Assembly completeness assessment using conserved orthologs',
      type: 'qc',
      enabled: true,
    },
    {
      id: 10,
      tool_id: 'MERQURY',
      name: 'Merqury',
      description: 'Reference-free k-mer-based assembly evaluation',
      type: 'qc',
      enabled: true,
    },
  ]
}

export interface ToolRequirement {
  requirement_id?: string
  type: string
  label: string
  formats: string[]
  is_intermediate?: boolean
  source_tool?: string
  available_sources?: Array<'external' | 'upstream'>
  default_source?: 'external' | 'upstream'
  filename_pattern?: string
  filename_example?: string
  validation_message?: string
  input_behavior?: string
}

export interface ToolRequirementInfo {
  tool_index: number
  tool_id: string
  tool_name: string
  tool_type: string
  description?: string
  tool_config?: Record<string, string | number | boolean>
  requirements: ToolRequirement[]
}

export interface ToolRequirementsResponse {
  success: boolean
  data: ToolRequirementInfo[]
  message?: string
}

export interface RecommendationIntent {
  id: string
  label: string
  description: string
  tags: string[]
}

export interface RecommendationFileSummary {
  filename: string
  file_format?: string | null
}

export interface RecommendationOption {
  id: string
  title: string
  summary: string
  intent_ids: string[]
  tool_ids: string[]
  tool_indices: number[]
  tool_names: string[]
  missing_inputs: string[]
  assumptions: string[]
  rationale: string[]
  tags: string[]
  score: number
}

export interface RecommendationResponseData {
  intents: RecommendationIntent[]
  detected_inputs: {
    fastq_count: number
    fasta_count: number
    annotation_count?: number
    hal_count?: number
    meryl_count?: number
    txt_count?: number
    has_fastq: boolean
    has_paired_fastq: boolean
    has_fasta: boolean
    has_sequence?: boolean
    has_annotation?: boolean
    has_hal?: boolean
    has_meryl?: boolean
    has_txt?: boolean
  }
  pipeline_options: RecommendationOption[]
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

export const getRecommendationIntents = async (): Promise<RecommendationIntent[]> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: RecommendationIntent[]; message?: string }>(
      '/api/tools/recommendation-intents'
    )
    if (response.data.success && response.data.data) {
      return response.data.data
    }
    return []
  } catch (error) {
    console.error('Failed to get recommendation intents:', error)
    return []
  }
}

export const getPipelineRecommendations = async (
  intentIds: string[],
  files: RecommendationFileSummary[]
): Promise<RecommendationResponseData | null> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: RecommendationResponseData; message?: string }>(
      '/api/tools/recommendations',
      {
        intent_ids: intentIds,
        files,
      }
    )
    if (response.data.success && response.data.data) {
      return response.data.data
    }
    return null
  } catch (error) {
    console.error('Failed to get pipeline recommendations:', error)
    return null
  }
}
