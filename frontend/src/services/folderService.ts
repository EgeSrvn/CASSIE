import apiClient from './apiClient'

export interface Folder {
  id: number
  user_id: number
  name: string
  parent_folder_id: number | null
  path: string
  created_at: string
  updated_at: string
}

export interface FolderCreate {
  name: string
  parent_folder_id?: number | null
}

export interface FolderUpdate {
  name?: string
  parent_folder_id?: number | null
}

export interface FolderTreeItem extends Folder {
  children: FolderTreeItem[]
  files: FileItem[]
}

export interface FileItem {
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

export const getFolders = async (parentId?: number | null): Promise<Folder[]> => {
  const params = parentId !== undefined ? { parent_id: parentId } : {}
  const response = await apiClient.get('/api/folders', { params })
  return response.data.data
}

export const getFolderTree = async (): Promise<FolderTreeItem[]> => {
  const response = await apiClient.get('/api/folders', { params: { tree: true } })
  return response.data.data
}

export const getFolder = async (folderId: number): Promise<Folder> => {
  const response = await apiClient.get(`/api/folders/${folderId}`)
  return response.data.data
}

export const createFolder = async (data: FolderCreate): Promise<Folder> => {
  const response = await apiClient.post('/api/folders', data)
  return response.data.data
}

export const updateFolder = async (folderId: number, data: FolderUpdate): Promise<Folder> => {
  const response = await apiClient.put(`/api/folders/${folderId}`, data)
  return response.data.data
}

export const deleteFolder = async (folderId: number): Promise<void> => {
  await apiClient.delete(`/api/folders/${folderId}`)
}

