import apiClient from './apiClient'

export interface ForumAuthor {
  id: number
  username: string
  display_name?: string | null
  affiliation?: string | null
  avatar_url?: string | null
}

export interface ForumCommentPreview {
  id: number
  author_name: string
  body: string
}

export interface ForumComment {
  id: number
  thread_id: number
  answer_id?: number | null
  parent_comment_id?: number | null
  user_id: number
  body: string
  image_urls: string[]
  created_at: string
  updated_at: string
  author: ForumAuthor
  parent_comment_preview?: ForumCommentPreview | null
  replies: ForumComment[]
}

export interface ForumThreadSummary {
  id: number
  user_id: number
  title: string
  body: string
  image_urls: string[]
  view_count: number
  answer_count: number
  comment_count: number
  created_at: string
  updated_at: string
  last_activity_at: string
  author: ForumAuthor
}

export interface ForumThreadDetail extends ForumThreadSummary {
  thread_comments: ForumComment[]
  answers: never[]
}

export interface ForumThreadList {
  items: ForumThreadSummary[]
  total: number
  page: number
  per_page: number
}

interface ForumApiResponse<T> {
  success: boolean
  data: T
  message?: string
}

export const listForumThreads = async (query = '', page = 1, perPage = 10): Promise<ForumThreadList> => {
  const response = await apiClient.get<ForumApiResponse<ForumThreadList>>('/api/forum', {
    params: {
      page,
      per_page: perPage,
      ...(query.trim() ? { q: query.trim() } : {}),
    },
  })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch forum threads')
}

export const getForumThread = async (threadId: number): Promise<ForumThreadDetail> => {
  const response = await apiClient.get<ForumApiResponse<ForumThreadDetail>>(`/api/forum/${threadId}`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to fetch forum thread')
}

export const createForumThread = async (payload: { title: string; body: string }): Promise<ForumThreadSummary> => {
  const response = await apiClient.post<ForumApiResponse<ForumThreadSummary>>('/api/forum', payload)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to create forum thread')
}

export const uploadForumThreadImages = async (threadId: number, files: File[]): Promise<ForumThreadSummary | null> => {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  const response = await apiClient.post<ForumApiResponse<ForumThreadSummary | null>>(`/api/forum/${threadId}/images`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to upload forum images')
}

export const createForumComment = async (
  threadId: number,
  payload: { body: string; parent_comment_id?: number }
): Promise<ForumComment> => {
  const response = await apiClient.post<ForumApiResponse<ForumComment>>(`/api/forum/${threadId}/comments`, payload)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to post comment')
}

export const uploadForumCommentImages = async (commentId: number, files: File[]): Promise<ForumComment | null> => {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  const response = await apiClient.post<ForumApiResponse<ForumComment | null>>(`/api/forum/comments/${commentId}/images`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to upload forum comment images')
}

export const deleteForumThread = async (threadId: number): Promise<void> => {
  const response = await apiClient.delete<ForumApiResponse<null>>(`/api/forum/${threadId}`)
  if (!response.data.success) {
    throw new Error(response.data.message || 'Failed to delete forum thread')
  }
}

export const deleteForumComment = async (commentId: number): Promise<void> => {
  const response = await apiClient.delete<ForumApiResponse<null>>(`/api/forum/comments/${commentId}`)
  if (!response.data.success) {
    throw new Error(response.data.message || 'Failed to delete forum comment')
  }
}
