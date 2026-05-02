import apiClient, { extractApiErrorMessage } from './apiClient'

const TOKEN_KEY = 'cassie_token'
const USER_KEY = 'cassie_user'
const AUTH_CHANGE_EVENT = 'auth-change'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  invitation_code: string
}

export interface User {
  id: number
  username: string
  email: string
  email_verified?: boolean
  login_two_factor_enabled?: boolean
  job_notifications_enabled?: boolean
  display_name?: string | null
  bio?: string | null
  affiliation?: string | null
  job_title?: string | null
  location?: string | null
  website_url?: string | null
  avatar_url?: string | null
  cash_balance_usd?: number
  cash_reserved_usd?: number
  cash_available_usd?: number
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

export interface LoginTwoFactorChallenge {
  username: string
  email: string
  two_factor_required: boolean
  verification_preview_code?: string | null
  expires_in_minutes: number
}

export type LoginResult = AuthResponse | LoginTwoFactorChallenge

export interface AuthError extends Error {
  verificationEmail?: string
  verificationRequired?: boolean
}

export interface VerificationChallenge {
  email: string
  verification_required: boolean
  verification_preview_code?: string | null
  expires_in_minutes: number
}

export interface PasswordResetChallenge {
  email: string
  reset_preview_code?: string | null
  expires_in_minutes: number
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
  login_two_factor_enabled?: boolean
  job_notifications_enabled?: boolean
}

const normalizeProfilePayload = (payload: ProfileUpdateRequest): ProfileUpdateRequest => {
  const normalized: ProfileUpdateRequest = {}
  ;(Object.entries(payload) as Array<[keyof ProfileUpdateRequest, string | boolean | undefined]>).forEach(([key, value]) => {
    if (typeof value === 'boolean') {
      Object.assign(normalized, { [key]: value })
      return
    }
    if (typeof value !== 'string') {
      return
    }
    Object.assign(normalized, { [key]: value.trim() })
  })
  return normalized
}

const storeAuthenticatedSession = (user: User, accessToken: string) => {
  setStoredUser(user)
  setToken(accessToken)
}

export const login = async (credentials: LoginRequest): Promise<LoginResult> => {
  try {
    const response = await apiClient.post<{
      success: boolean
      data: { access_token?: string; token_type?: string; user?: User } & Partial<LoginTwoFactorChallenge>
      message?: string
    }>('/api/auth/login', credentials)
    if (response.data.success && response.data.data.access_token && response.data.data.user) {
      storeAuthenticatedSession(response.data.data.user, response.data.data.access_token)
      return {
        access_token: response.data.data.access_token,
        user: response.data.data.user
      }
    }
    if (response.data.success && response.data.data.two_factor_required) {
      return response.data.data as LoginTwoFactorChallenge
    }
    throw new Error(response.data.message || 'Login failed')
  } catch (error: any) {
    const loginError = new Error(extractApiErrorMessage(error, 'Login failed: Network error or server unavailable')) as AuthError
    const responseData = error?.response?.data
    const errorDetails = responseData?.error?.details
    if (error?.response?.status === 403 && errorDetails?.verification_required && typeof errorDetails?.email === 'string') {
      loginError.verificationRequired = true
      loginError.verificationEmail = errorDetails.email
    }
    throw loginError
  }
}

export const confirmLoginTwoFactor = async (username: string, code: string): Promise<AuthResponse> => {
  const response = await apiClient.post<{ success: boolean; data: { access_token: string; token_type: string; user: User }; message?: string }>(
    '/api/auth/login/2fa/confirm',
    { username, code }
  )
  if (response.data.success && response.data.data.access_token && response.data.data.user) {
    storeAuthenticatedSession(response.data.data.user, response.data.data.access_token)
    return {
      access_token: response.data.data.access_token,
      user: response.data.data.user,
    }
  }
  throw new Error(response.data.message || 'Failed to confirm login code')
}

export const resendLoginTwoFactor = async (username: string): Promise<LoginTwoFactorChallenge> => {
  const response = await apiClient.post<{ success: boolean; data: LoginTwoFactorChallenge; message?: string }>(
    '/api/auth/login/2fa/resend',
    { username }
  )
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to resend login code')
}

export const register = async (userData: RegisterRequest): Promise<VerificationChallenge> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: VerificationChallenge; message?: string }>('/api/auth/register', userData)
    if (response.data.success) {
      return response.data.data
    }
    throw new Error(response.data.message || 'Registration failed')
  } catch (error: any) {
    throw new Error(extractApiErrorMessage(error, 'Registration failed: Network error or server unavailable'))
  }
}

export const getCurrentUser = async (): Promise<User> => {
  const response = await apiClient.get<{ success: boolean; data: User }>('/api/auth/me')
  if (response.data.success) {
    setStoredUser(response.data.data)
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
    setStoredUser(response.data.data)
    return response.data.data
  }
  throw new Error('Failed to update profile')
}

export const depositCashBalance = async (amountUsd: number): Promise<User> => {
  const response = await apiClient.post<{ success: boolean; data: User }>(
    '/api/auth/profile/balance/deposit',
    { amount_usd: amountUsd }
  )
  if (response.data.success) {
    setStoredUser(response.data.data)
    return response.data.data
  }
  throw new Error('Failed to update cash balance')
}

export const requestAccountDeletionCode = async (): Promise<{ email: string; expires_in_minutes: number }> => {
  const response = await apiClient.post<{ success: boolean; data: { email: string; expires_in_minutes: number } }>(
    '/api/auth/profile/delete/request'
  )
  if (response.data.success) {
    return response.data.data
  }
  throw new Error('Failed to request account deletion code')
}

export const confirmAccountDeletion = async (code: string): Promise<void> => {
  const response = await apiClient.post<{ success: boolean }>('/api/auth/profile/delete/confirm', { code })
  if (!response.data.success) {
    throw new Error('Failed to delete profile')
  }
  clearToken()
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
    setStoredUser(response.data.data)
    return response.data.data
  }
  throw new Error('Failed to upload profile picture')
}

export const setToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token)
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

export const setStoredUser = (user: User | null): void => {
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_KEY)
  }
}

export const getStoredUser = (): User | null => {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) {
    return null
  }

  try {
    return JSON.parse(raw) as User
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
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
  localStorage.removeItem(USER_KEY)
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

export const logout = (): void => {
  clearToken()
}

export const notifyAuthChange = (): void => {
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT))
}

// ============================================================================
// Demo session helpers
// ============================================================================

export interface DemoAuthResponse {
  access_token: string
  token_type: string
  role: string
}

/**
 * Parse the JWT payload without verifying the signature.
 * Used only for reading non-sensitive claims (role, is_demo, exp).
 */
const _parseJwtPayload = (token: string): Record<string, unknown> | null => {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    return JSON.parse(atob(padded)) as Record<string, unknown>
  } catch {
    return null
  }
}

/**
 * Returns true if the stored (or provided) token is a demo session token.
 * Backend is the authoritative source — this is for UI gating only.
 */
export const isDemoToken = (token: string | null = getToken()): boolean => {
  if (!token) return false
  const payload = _parseJwtPayload(token)
  return payload?.is_demo === true && payload?.token_type === 'demo_session'
}

/**
 * Submit a demo code and store the resulting demo session token.
 * On success the `auth-change` event is dispatched so UI updates.
 */
export const demoLogin = async (code: string): Promise<DemoAuthResponse> => {
  try {
    const response = await apiClient.post<{ success: boolean; data: DemoAuthResponse; message?: string }>(
      '/api/demo/validate-code',
      { code }
    )
    if (response.data.success && response.data.data.access_token) {
      setToken(response.data.data.access_token)
      return response.data.data
    }
    throw new Error(response.data.message || 'Invalid or expired demo code.')
  } catch (error: any) {
    throw new Error(extractApiErrorMessage(error, 'Invalid or expired demo code.'))
  }
}

export const requestEmailVerification = async (email: string): Promise<VerificationChallenge> => {
  const response = await apiClient.post<{ success: boolean; data: VerificationChallenge; message?: string }>('/api/auth/verify-email/request', { email })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to request verification code')
}

export const confirmEmailVerification = async (email: string, code: string): Promise<User | null> => {
  const response = await apiClient.post<{ success: boolean; data: { user?: User | null }; message?: string }>('/api/auth/verify-email/confirm', {
    email,
    code,
  })
  if (response.data.success) {
    return response.data.data.user || null
  }
  throw new Error(response.data.message || 'Failed to verify email')
}

export const requestPasswordReset = async (email: string): Promise<PasswordResetChallenge> => {
  const response = await apiClient.post<{ success: boolean; data: PasswordResetChallenge; message?: string }>('/api/auth/forgot-password/request', { email })
  if (response.data.success) {
    return response.data.data
  }
  throw new Error(response.data.message || 'Failed to request password reset')
}

export const resetPasswordWithCode = async (email: string, code: string, newPassword: string): Promise<void> => {
  const response = await apiClient.post<{ success: boolean; message?: string }>('/api/auth/forgot-password/reset', {
    email,
    code,
    new_password: newPassword,
  })
  if (!response.data.success) {
    throw new Error(response.data.message || 'Failed to reset password')
  }
}
