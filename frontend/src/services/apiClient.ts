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
