import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import apiClient from '../services/apiClient'

export interface AppConfig {
  demo_mode_enabled: boolean
  demo_code_length: number
}

const DEFAULT_CONFIG: AppConfig = {
  demo_mode_enabled: false,
  demo_code_length: 12,
}

const AppConfigContext = createContext<AppConfig>(DEFAULT_CONFIG)

export function AppConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG)

  useEffect(() => {
    apiClient
      .get<{ success: boolean; data: AppConfig }>('/api/config/public')
      .then((res) => {
        if (res.data?.success && res.data.data) {
          setConfig(res.data.data)
        }
      })
      .catch(() => {
        // Fail silently — safe defaults mean demo mode stays off
      })
  }, [])

  return <AppConfigContext.Provider value={config}>{children}</AppConfigContext.Provider>
}

export function useAppConfig(): AppConfig {
  return useContext(AppConfigContext)
}
