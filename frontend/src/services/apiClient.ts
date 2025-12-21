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
    if (token) {
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
      clearToken()
      // Only redirect to login if we're not already on a public page
      // Public pages: /, /jobs, /pipelines, /community, /jobs/create, /pipelines/builder
      const publicPaths = ['/', '/jobs', '/pipelines', '/community', '/jobs/create', '/pipelines/builder']
      const currentPath = window.location.pathname
      const isPublicPath = publicPaths.some(path => currentPath === path || currentPath.startsWith(path + '/'))
      
      // Don't auto-redirect on public pages - let the component handle it
      if (!isPublicPath) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient
