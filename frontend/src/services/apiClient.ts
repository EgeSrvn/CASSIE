import axios, { AxiosInstance, AxiosError } from 'axios'
import { getToken, clearToken } from './authService'

// Use relative URLs to leverage Vite proxy, or use environment variable
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const extractApiErrorMessage = (error: any, fallback: string): string => {
  const responseData = error?.response?.data
  const detailErrors = responseData?.error?.details?.errors
  if (Array.isArray(detailErrors) && detailErrors.length > 0) {
    const firstError = detailErrors[0]
    const field = typeof firstError?.field === 'string'
      ? firstError.field.split('.').pop()?.replace(/_/g, ' ')
      : ''
    const message = typeof firstError?.message === 'string' ? firstError.message : ''
    if (field && message) {
      return `${field.charAt(0).toUpperCase()}${field.slice(1)}: ${message}`
    }
    if (message) {
      return message
    }
  }
  if (typeof responseData?.error?.message === 'string' && responseData.error.message.trim()) {
    return responseData.error.message
  }
  if (typeof responseData?.message === 'string' && responseData.message.trim()) {
    return responseData.message
  }
  if (typeof responseData?.detail === 'string' && responseData.detail.trim()) {
    return responseData.detail
  }
  if (typeof error?.message === 'string' && error.message.trim()) {
    return error.message
  }
  return fallback
}

// Add token to requests
apiClient.interceptors.request.use(
  (config) => {
    const token = getToken()
    const hasExplicitAuthorization = !!config.headers?.Authorization
    if (token && !hasExplicitAuthorization) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Handle 401 errors (unauthorized)
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      const hadToken = !!getToken()
      const requestUrl = `${error.config?.url || ''}`
      const isLoginRequest = requestUrl.includes('/api/auth/login')
      const isRegisterRequest = requestUrl.includes('/api/auth/register')

      if (hadToken && !isLoginRequest && !isRegisterRequest) {
        clearToken()
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient
