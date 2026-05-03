/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GENERAL_ACCESS_PASSWORD?: string
  readonly VITE_GOOGLE_DRIVE_CLIENT_ID?: string
  readonly VITE_GOOGLE_DRIVE_API_KEY?: string
  readonly VITE_GOOGLE_DRIVE_APP_ID?: string
}

interface Window {
  google?: any
  gapi?: any
}
