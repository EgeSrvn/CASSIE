import apiClient from './apiClient'

const TOKEN_KEY = 'cassie_token'

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
}

export interface AuthResponse {
  access_token: string
  user: User
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

export const setToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token)
}

export const getToken = (): string | null => {
  return localStorage.getItem(TOKEN_KEY)
}

export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY)
}

export const logout = (): void => {
  clearToken()
}
