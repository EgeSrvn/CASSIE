import { useNavigate } from 'react-router-dom'
import Navigation from '../components/Navigation'
import storageUpgradeConfig from '../../../storage_upgrade_plans.json'
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
  const currency = storageUpgradeConfig.currency || 'USD'
  const billingInterval = storageUpgradeConfig.billing_interval || 'week'
  const plans = storageUpgradeConfig.plans as StorageUpgradePlan[]

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
              <button type="button" className="btn-primary" onClick={() => navigate('/balance')}>
                Continue To Balance
              </button>
            </article>
          ))}
        </section>
      </main>
    </div>
  )
}
