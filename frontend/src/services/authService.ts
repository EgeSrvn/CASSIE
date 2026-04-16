import apiClient from './apiClient'

const TOKEN_KEY = 'cassie_token'
const AUTH_CHANGE_EVENT = 'auth-change'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface User {
  id: number
  username: string
  email: string
  display_name?: string | null
  bio?: string | null
  affiliation?: string | null
  job_title?: string | null
  location?: string | null
  website_url?: string | null
  avatar_url?: string | null
  bucket_name?: string
  created_at?: string
  updated_at?: string
}

export interface PublicProfileUser {
  id: number
  username: string
  display_name?: string | null
  bio?: string | null
  affiliation?: string | null
  job_title?: string | null
  location?: string | null
  website_url?: string | null
  avatar_url?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface AuthResponse {
  access_token: string
  user: User
}

export interface CommunityEntry {
  id: number
  name: string
  description?: string | null
  saved_at?: string | null
  is_shared: boolean
}

export interface ProfileResponse {
  user: User | PublicProfileUser
  community_entries: CommunityEntry[]
  is_public_profile?: boolean
}

export interface ProfileUpdateRequest {
  email?: string
  display_name?: string
  bio?: string
  affiliation?: string
  job_title?: string
  location?: string
  website_url?: string
  current_password?: string
  new_password?: string
}

const normalizeProfilePayload = (payload: ProfileUpdateRequest): ProfileUpdateRequest => {
  const normalized: ProfileUpdateRequest = {}
  ;(Object.entries(payload) as Array<[keyof ProfileUpdateRequest, string | undefined]>).forEach(([key, value]) => {
    if (typeof value !== 'string') {
      return
    }
    normalized[key] = value.trim()
  })
  return normalized
}

export const login = async (credentials: LoginRequest): Promise<AuthResponse> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: { access_token: string; token_type: string; user: User }; message?: string }>('/api/auth/login', credentials)
    if (response.data.success && response.data.data.access_token) {
      setToken(response.data.data.access_token)
      return {
        access_token: response.data.data.access_token,
        user: response.data.data.user
      }
    }
    throw new Error(response.data.message || 'Login failed')
  } catch (error: any) {
    // Extract error message from response
    if (error.response?.data) {
      const errorData = error.response.data
      const errorMessage = errorData.message || errorData.detail || errorData.error || 'Login failed'
      throw new Error(errorMessage)
    }
    if (error.message) {
      throw error
    }
    throw new Error('Login failed: Network error or server unavailable')
  }
}

export const register = async (userData: RegisterRequest): Promise<AuthResponse> => {
  try {
    // Register doesn't return a token, need to login after
    const response = await apiClient.post<{ success: boolean; data: User; message?: string }>('/api/auth/register', userData)
    if (response.data.success) {
      // Auto-login after registration
      return login({ username: userData.username, password: userData.password })
    }
    throw new Error(response.data.message || 'Registration failed')
  } catch (error: any) {
    // Extract error message from response
    if (error.response?.data) {
      const errorData = error.response.data
      const errorMessage = errorData.message || errorData.detail || errorData.error || 'Registration failed'
      throw new Error(errorMessage)
    }
    if (error.message) {
      throw error
    }
    throw new Error('Registration failed: Network error or server unavailable')
  }
}

export const getCurrentUser = async (): Promise<User> => {
  const response = await apiClient.get<{ success: boolean; data: User }>('/api/auth/me')
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to get user')
}

export const getProfile = async (): Promise<ProfileResponse> => {
  const response = await apiClient.get<{ success: boolean; data: ProfileResponse }>('/api/auth/profile')
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to get profile')
}

export const getPublicProfile = async (userId: number): Promise<ProfileResponse> => {
  const response = await apiClient.get<{ success: boolean; data: ProfileResponse }>(`/api/auth/profile/${userId}`)
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to get public profile')
}

export const updateProfile = async (payload: ProfileUpdateRequest): Promise<User> => {
  const response = await apiClient.put<{ success: boolean; data: User }>('/api/auth/profile', normalizeProfilePayload(payload))
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to update profile')
}

export const uploadProfileAvatar = async (file: File): Promise<User> => {
  const formData = new FormData()
  formData.append('file', file)

  const response = await apiClient.post<{ success: boolean; data: User }>('/api/auth/profile/avatar', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to upload profile picture')
}

export const setToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token)
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

export const getToken = (): string | null => {
  return localStorage.getItem(TOKEN_KEY)
}

export const isTokenExpired = (token: string | null = getToken()): boolean => {
  if (!token) {
    return true
  }

  try {
    const payloadBase64 = token.split('.')[1]
    if (!payloadBase64) {
      return true
    }

    const normalized = payloadBase64.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const payload = JSON.parse(atob(padded)) as { exp?: number }

    if (typeof payload.exp !== 'number') {
      return false
    }

    return payload.exp <= Math.floor(Date.now() / 1000)
  } catch {
    return true
  }
}

export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY)
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

export const logout = (): void => {
  clearToken()
}

export const notifyAuthChange = (): void => {
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}
