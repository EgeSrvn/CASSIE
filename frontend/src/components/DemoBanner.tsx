import { isDemoToken } from '../services/authService'

export function DemoBanner() {
  if (!isDemoToken()) return null

  return (
    <div
      role="status"
      style={{
        background: '#fffbeb',
        borderBottom: '1px solid #f59e0b',
        padding: '0.5rem 1rem',
        fontSize: '0.825rem',
        color: '#92400e',
        textAlign: 'center',
        lineHeight: 1.4,
      }}
    >
      <strong>Demo Mode</strong> — Only synthetic/mock datasets are available. Uploads, sharing, and community
      features are disabled. Session outputs are temporary.
    </div>
  )
}
