import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import { getStoredUser, notifyAuthChange, setStoredUser } from '../services/authService'
import { cancelStorageUpgrade, getStorageSummary, purchaseStorageUpgrade, StorageSummary } from '../services/fileService'
import { extractApiErrorMessage } from '../services/apiClient'
import storageUpgradeConfig from '../../../config/storage_upgrade_plans.json'
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
  const [summary, setSummary] = useState<StorageSummary | null>(null)
  const [loadingSummary, setLoadingSummary] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const currency = storageUpgradeConfig.currency || 'USD'
  const billingInterval = storageUpgradeConfig.billing_interval || 'week'
  const plans = storageUpgradeConfig.plans as StorageUpgradePlan[]
  const activePlanId = summary?.active_subscription?.plan_id || null

  useEffect(() => {
    const loadSummary = async () => {
      try {
        setLoadingSummary(true)
        const nextSummary = await getStorageSummary()
        setSummary(nextSummary)
      } catch (err: any) {
        setError(extractApiErrorMessage(err, 'Failed to load storage subscription'))
      } finally {
        setLoadingSummary(false)
      }
    }

    void loadSummary()
  }, [])

  const activePlanName = useMemo(() => {
    if (!summary?.active_subscription) {
      return 'Default storage'
    }
    return `${summary.active_subscription.plan_name} (+${summary.active_subscription.additional_gb} GB)`
  }, [summary])

  const handlePurchase = async (plan: StorageUpgradePlan) => {
    try {
      setSubmittingPlanId(plan.id)
      setError('')
      setSuccess('')
      const result = await purchaseStorageUpgrade(plan.id)
      setSummary(result.storage)
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
        activePlanId === plan.id
          ? `${plan.name} remains your active storage plan.`
          : `${plan.name} is now your active storage plan.`
      )
      window.dispatchEvent(new Event('storage-library-change'))
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to purchase storage upgrade'))
    } finally {
      setSubmittingPlanId(null)
    }
  }

  const handleCancelSubscription = async () => {
    try {
      setSubmittingPlanId('cancel')
      setError('')
      setSuccess('')
      const result = await cancelStorageUpgrade()
      setSummary(result.storage)
      setSuccess('Your active storage subscription has been cancelled. Default storage is active now.')
      window.dispatchEvent(new Event('storage-library-change'))
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to cancel storage subscription'))
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
            <article
              key={plan.id}
              className={`storage-upgrade-card ${activePlanId === plan.id ? 'storage-upgrade-card-active' : ''}`}
            >
              <div>
                <p className="storage-kicker">{plan.name}</p>
                <h2>+{plan.additional_gb} GB</h2>
                <p>Additional cloud storage for uploads, imports, and reusable job inputs.</p>
                <p className="storage-upgrade-status-copy">
                  {activePlanId === plan.id ? 'Current active subscription' : 'Available to activate'}
                </p>
              </div>
              <div className="storage-upgrade-price">
                <strong>{formatCurrency(plan.weekly_price, currency)}</strong>
                <span>per {billingInterval}</span>
              </div>
              <div className="storage-upgrade-actions">
                <button type="button" className="btn-secondary" onClick={() => navigate('/balance')}>
                  Add Balance
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={submittingPlanId === plan.id}
                  onClick={() => handlePurchase(plan)}
                >
                  {submittingPlanId === plan.id
                    ? (activePlanId === plan.id ? 'Refreshing...' : 'Switching...')
                    : (activePlanId === plan.id ? 'Keep Current Plan' : 'Switch To This Plan')}
                </button>
              </div>
            </article>
          ))}
        </section>

        <section className="storage-upgrade-summary-card">
          <div>
            <p className="storage-kicker">Current subscription</p>
            <h2>{loadingSummary ? 'Loading...' : activePlanName}</h2>
            <p>
              {summary?.active_subscription
                ? `Your plan renews on the normal ${billingInterval} billing cycle and replaces the previous add-on.`
                : 'You are currently using the default included storage plan.'}
            </p>
            {summary?.active_subscription && (
              <button
                type="button"
                className="btn-soft-cancel"
                disabled={submittingPlanId === 'cancel'}
                onClick={handleCancelSubscription}
              >
                {submittingPlanId === 'cancel' ? 'Cancelling...' : 'Cancel Active Subscription'}
              </button>
            )}
          </div>
          {summary && (
            <div className="storage-upgrade-summary-metrics">
              <span>{(summary.used_bytes / (1024 * 1024 * 1024)).toFixed(2)} GB used</span>
              <span>{(summary.max_storage_bytes / (1024 * 1024 * 1024)).toFixed(2)} GB total</span>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
