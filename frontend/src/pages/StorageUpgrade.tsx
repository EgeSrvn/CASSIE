import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import { getStoredUser, notifyAuthChange, setStoredUser } from '../services/authService'
import { purchaseStorageUpgrade } from '../services/fileService'
import { extractApiErrorMessage } from '../services/apiClient'
import storageUpgradeConfig from '../../storage_upgrade_plans.json'
import '../styles/globals.css'
import './Storage.css'

interface StorageUpgradePlan {
  id: string
  name: string
  additional_gb: number
  weekly_price: number
}

const formatCurrency = (amount: number, currency: string) => (
  new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(amount)
)

export default function StorageUpgrade() {
  const navigate = useNavigate()
  const [submittingPlanId, setSubmittingPlanId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const currency = storageUpgradeConfig.currency || 'USD'
  const billingInterval = storageUpgradeConfig.billing_interval || 'week'
  const plans = storageUpgradeConfig.plans as StorageUpgradePlan[]

  const handlePurchase = async (plan: StorageUpgradePlan) => {
    try {
      setSubmittingPlanId(plan.id)
      setError('')
      setSuccess('')
      const result = await purchaseStorageUpgrade(plan.id)
      if (result.user) {
        const currentUser = getStoredUser()
        if (currentUser) {
          setStoredUser({
            ...currentUser,
            cash_balance_usd: result.user.cash_balance_usd,
            cash_reserved_usd: result.user.cash_reserved_usd,
            cash_available_usd: result.user.cash_available_usd,
          })
          notifyAuthChange()
        }
      }
      setSuccess(
        `${plan.name} purchased successfully. Your storage increased by ${plan.additional_gb} GB.`
      )
      window.dispatchEvent(new Event('storage-library-change'))
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to purchase storage upgrade'))
    } finally {
      setSubmittingPlanId(null)
    }
  }

  return (
    <div className="page-container storage-page">
      <Navigation />
      <main className="storage-content storage-upgrade-page">
        <header className="storage-header">
          <div>
            <p className="storage-kicker">Weekly storage upgrades</p>
            <h1>Upgrade Storage</h1>
            <p>Add more space for larger datasets and active projects.</p>
          </div>
          <button type="button" className="btn-secondary" onClick={() => navigate('/storage')}>
            Back To Storage
          </button>
        </header>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}

        <section className="storage-upgrade-grid">
          {plans.map((plan) => (
            <article key={plan.id} className="storage-upgrade-card">
              <div>
                <p className="storage-kicker">{plan.name}</p>
                <h2>+{plan.additional_gb} GB</h2>
                <p>Additional cloud storage for uploads, imports, and reusable job inputs.</p>
              </div>
              <div className="storage-upgrade-price">
                <strong>{formatCurrency(plan.weekly_price, currency)}</strong>
                <span>per {billingInterval}</span>
              </div>
              <div className="storage-upgrade-actions">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={submittingPlanId === plan.id}
                  onClick={() => handlePurchase(plan)}
                >
                  {submittingPlanId === plan.id ? 'Purchasing...' : 'Buy Upgrade'}
                </button>
                <button type="button" className="btn-secondary" onClick={() => navigate('/balance')}>
                  Add Balance
                </button>
              </div>
            </article>
          ))}
        </section>
      </main>
    </div>
  )
}
