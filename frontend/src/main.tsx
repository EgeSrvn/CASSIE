import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'
import cassieLogo from '../images/cassie_logo.png'

const ensureFavicon = () => {
  if (typeof document === 'undefined') {
    return
  }

  let favicon = document.querySelector("link[rel='icon']") as HTMLLinkElement | null
  if (!favicon) {
    favicon = document.createElement('link')
    favicon.rel = 'icon'
    document.head.appendChild(favicon)
  }

  favicon.type = 'image/png'
  favicon.href = cassieLogo
}

ensureFavicon()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
