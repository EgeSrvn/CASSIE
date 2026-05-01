import apiClient from './apiClient'

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
  execution_preferences?: Record<string, unknown>
  vm_name?: string
  estimated_price_usd?: number
  max_charge_usd?: number
  actual_price_charged_usd?: number | null
  balance_reserved_at?: string | null
  balance_charged_at?: string | null
  interactive_outputs_enabled?: boolean
  upload_session_token?: string
  pending_upload_count?: number
  expected_total_input_files?: number
  created_at: string
  updated_at: string
}

export interface JobExecutionStage {
  stage_id?: string
  stage_number: number
  tool_id: string
  tool_name: string
  kubernetes_job_name?: string
  pod_name?: string
  dependency_stage_ids?: string[]
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  started_at?: string
  completed_at?: string
  output_count?: number
  error?: string
  resource_profile?: string
  threads?: number
  cpu_limit_millis?: number
  memory_limit_mib?: number
  storage_limit_mib?: number
  live_cpu_millis?: number | null
  live_memory_mib?: number | null
  live_metrics_error?: string | null
  live_tool_logs?: string | null
  live_init_logs?: string | null
  pod_phase?: string | null
  live_pods?: Array<{
    pod_name: string
    pod_phase?: string | null
    containers?: Array<{
      name: string
      state?: string | null
      ready?: boolean
      restart_count?: number
      live_cpu_millis?: number | null
      live_memory_mib?: number | null
      live_metrics_error?: string | null
    }>
  }> | null
}

export interface JobExecution {
  id: number
  job_id: number
  execution_number: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  nextflow_run_id?: string | null
  work_dir?: string | null
  output_dir?: string | null
  process_id?: number | null
  tool_versions?: Record<string, string> | null
  parameters_used?: {
    backend?: string
    namespace?: string
    workflow_id?: number
    tool_sequence?: string[]
    queue_state?: string
    queue_position?: number | null
    stages?: JobExecutionStage[]
    [key: string]: unknown
  } | null
  error_message?: string | null
  started_at?: string | null
  completed_at?: string | null
  created_at: string
}

export interface JobPipelineBlock {
  id: string
  kind: 'input' | 'tool' | 'checkpoint' | 'output'
  column: 'input' | 'stage' | 'output'
  row: number
  label: string
  status: 'waiting' | 'working' | 'finished' | 'failed'
  raw_status?: string
  stage_id?: string
  stage_number?: number
  tool_id?: string | null
  dependency_stage_ids?: string[]
  produced_type?: string | null
  related_stage_id?: string | null
  consumer_stage_ids?: string[]
  formats?: string[]
  filenames?: string[]
  description?: string | null
}

export interface JobPipelineConnection {
  id: string
  source: string
  target: string
  kind: 'input' | 'dependency' | 'output' | 'artifact'
  label?: string | null
}

export interface JobPipelineVisualization {
  job_id: number
  workflow_id: number
  latest_execution_id?: number | null
  blocks: JobPipelineBlock[]
  connections?: JobPipelineConnection[]
}

export interface PipelinePlanPreviewInput {
  id?: number
  binding_id?: string
  tool_id?: string
  requirement_type?: string
  label?: string
  filename: string
  file_format?: string | null
  size_bytes?: number
  s3_key?: string
  source?: string
}

export interface PipelinePlanPreviewRequest {
  tool_indices?: number[]
  pipeline_id?: number
  input_file_ids?: number[]
  planned_inputs?: PipelinePlanPreviewInput[]
  execution_preferences?: Record<string, unknown>
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
  execution_preferences?: Record<string, unknown>
  vm_name?: string // Virtual machine name for execution (e.g., 'vm1', 'vm2')
  input_file_ids?: number[] // Data library file IDs to associate with this job
  staged_input_file_ids?: number[] // Staged storage file IDs to associate with this job
  pending_upload_count?: number
  expected_total_input_files?: number
  estimated_price_usd?: number
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
      throw new Error(extractApiErrorMessage(errorData, 'Failed to create job'))
    }
    throw error
  }
}

export const getJobs = async (status?: string, page: number = 1, perPage: number = 20): Promise<JobListResponse> => {
  const params: any = { page, per_page: perPage }
  if (status) params.status = status
  
  const response = await apiClient.get<JobListResponse>('/api/jobs', { params })
  return response.data
}

export const getJob = async (jobId: number, authToken?: string): Promise<Job> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: Job; message?: string }>(`/api/jobs/${jobId}`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
    })
    if (response.data && response.data.success) {
      return response.data.data
    }
    throw new Error(response.data?.message || 'Failed to get job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to get job'))
    }
    throw error
  }
}

export const getJobExecutions = async (jobId: number): Promise<JobExecution[]> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: JobExecution[]; message?: string }>(
      `/api/jobs/${jobId}/executions`
    )
    if (response.data && response.data.success) {
      return response.data.data
    }
    throw new Error(response.data?.message || 'Failed to get job executions')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to get job executions'))
    }
    throw error
  }
}

export const getJobPipelineVisualization = async (jobId: number): Promise<JobPipelineVisualization> => {
  try {
    const response = await apiClient.get<{ success: boolean; data: JobPipelineVisualization; message?: string }>(
      `/api/jobs/${jobId}/pipeline-visualization`
    )
    if (response.data && response.data.success) {
      return response.data.data
    }
    throw new Error(response.data?.message || 'Failed to get job pipeline visualization')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to get job pipeline visualization'))
    }
    throw error
  }
}

export const previewPipelinePlan = async (request: PipelinePlanPreviewRequest): Promise<JobPipelineVisualization> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: JobPipelineVisualization; message?: string }>(
      '/api/jobs/pipeline-plan-preview',
      request
    )
    if (response.data && response.data.success) {
      return response.data.data
    }
    throw new Error(response.data?.message || 'Failed to preview pipeline plan')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to preview pipeline plan'))
    }
    throw error
  }
}

export const deleteJob = async (jobId: number): Promise<void> => {
  await apiClient.delete(`/api/jobs/${jobId}`)
}

export interface JobUpdate {
  name?: string
  assembler?: string
  data_types?: string[]
  cloud_provider?: string
  execution_preferences?: Record<string, unknown>
  vm_name?: string
}

export const updateJob = async (jobId: number, jobData: JobUpdate): Promise<Job> => {
  try {
    const response = await apiClient.put<{ success: boolean; data: Job; message?: string }>(
      `/api/jobs/${jobId}`,
      jobData
    )
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to update job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to update job'))
    }
    throw error
  }
}

export interface CancelJobResult {
  job?: Job | null
  cancelled_executions: number
  kubernetes_cleanup?: {
    namespace?: string | null
    deleted_stage_jobs?: string[]
    errors?: string[]
  }
}

export const cancelJob = async (jobId: number): Promise<CancelJobResult> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: CancelJobResult; message?: string }>(
      `/api/jobs/${jobId}/cancel`
    )
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to cancel job')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to cancel job'))
    }
    throw error
  }
}

export const retryJob = async (jobId: number, jobData: JobUpdate): Promise<Job> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: Job; message?: string }>(
      `/api/jobs/${jobId}/retry`,
      jobData
    )
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to prepare job retry')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to prepare job retry'))
    }
    throw error
  }
}

export interface ExecuteJobResult {
  job_id: number
  status: 'pending' | 'running'
  queue_position?: number | null
  message: string
}

export const executeJob = async (jobId: number, authToken?: string): Promise<ExecuteJobResult> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: any; message?: string }>(
      `/api/jobs/${jobId}/execute`,
      undefined,
      {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
      }
    )
    if (!response.data.success) {
      throw new Error(response.data.message || 'Failed to execute job')
    }
    return response.data.data as ExecuteJobResult
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to execute job'))
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
      throw new Error(extractApiErrorMessage(errorData, 'Failed to add files to job'))
    }
    throw error
  }
}

export interface VM {
  name: string
  display_name: string
  max_jobs: number
  max_pods: number
  running_jobs: number
  active_jobs?: number
  available_job_slots: number
  available_cpu_millis: number
  available_memory_mib: number
  available_storage_mib: number
}

export interface RuntimeEstimate {
  model_type: string
  vm_name: string
  vm_display_name: string
  partition_factor: number
  vm_price_per_minute: number
  total_input_size_mib: number
  estimated_runtime_seconds: number
  estimated_runtime_minutes: number
  estimated_runtime_hours: number
  estimated_price_usd: number
  fixed_overhead_minutes: number
  execution_shape: string
  tool_breakdown: Array<{
    tool_id: string
    tool_name: string
    base_minutes: number
    input_size_mib: number
    input_size_bytes?: number
    input_suffixes?: string[]
    size_factor: number
    compression_factor?: number
    adjusted_minutes: number
  }>
  assumptions: string[]
}

export interface RuntimeInputAssignment {
  tool_id: string
  requirement_type: string
  total_input_size_mib: number
  compressed_input_size_mib?: number
  file_formats?: string[]
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
      throw new Error(extractApiErrorMessage(errorData, 'Failed to get available VMs'))
    }
    throw error
  }
}

export const estimateRuntime = async (payload: { tool_indices?: number[]; pipeline_id?: number; vm_name?: string; input_assignments?: RuntimeInputAssignment[] }): Promise<RuntimeEstimate> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: RuntimeEstimate; message?: string }>('/api/estimator/runtime', payload)
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Failed to estimate runtime')
  } catch (error: any) {
    if (error.response?.data) {
      const errorData = error.response.data
      throw new Error(extractApiErrorMessage(errorData, 'Failed to estimate runtime'))
    }
    throw error
  }
}
