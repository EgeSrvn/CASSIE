import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import Navigation from '../components/Navigation'
import { depositCashBalance, getProfile, User } from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import '../styles/globals.css'

const formatUsd = (value?: number | null): string => `$${Number(value || 0).toFixed(2)}`

const formatCardNumber = (value: string): string => (
  value.replace(/\D/g, '').slice(0, 19).replace(/(.{4})/g, '$1 ').trim()
)

const getCardProvider = (value: string): string => {
  const digits = value.replace(/\D/g, '')
  if (/^4/.test(digits)) {
    return 'Visa'
  }
  if (/^(5[1-5]|2[2-7])/.test(digits)) {
    return 'Mastercard'
  }
  if (/^3[47]/.test(digits)) {
    return 'American Express'
  }
  if (/^(6011|65|64[4-9])/.test(digits)) {
    return 'Discover'
  }
  if (/^35/.test(digits)) {
    return 'JCB'
  }
  if (/^3(?:0[0-5]|[68])/.test(digits)) {
    return 'Diners Club'
  }
  if (/^62/.test(digits)) {
    return 'UnionPay'
  }
  return digits ? 'Card' : 'Provider'
}

const formatExpiry = (value: string): string => {
  const digits = value.replace(/\D/g, '').slice(0, 4)
  if (digits.length <= 2) {
    return digits
  }
  return `${digits.slice(0, 2)}/${digits.slice(2)}`
}

const passesLuhn = (digits: string): boolean => {
  let sum = 0
  let shouldDouble = false
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    let value = Number(digits[index])
    if (shouldDouble) {
      value *= 2
      if (value > 9) {
        value -= 9
      }
    }
    sum += value
    shouldDouble = !shouldDouble
  }
  return sum > 0 && sum % 10 === 0
}

const isValidExpiry = (expiry: string): boolean => {
  const [monthText, yearText] = expiry.split('/')
  const month = Number(monthText)
  const year = Number(`20${yearText}`)
  if (!monthText || !yearText || month < 1 || month > 12) {
    return false
  }
  const expiryDate = new Date(year, month, 0, 23, 59, 59)
  return expiryDate >= new Date()
}

export default function Balance() {
  const [profile, setProfile] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [checkoutOpen, setCheckoutOpen] = useState(false)
  const [amount, setAmount] = useState('')
  const [cardName, setCardName] = useState('')
  const [cardNumber, setCardNumber] = useState('')
  const [expiry, setExpiry] = useState('')
  const [cvc, setCvc] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const availableBalance = useMemo(
    () => Math.max(Number(profile?.cash_available_usd ?? profile?.cash_balance_usd ?? 0), 0),
    [profile?.cash_available_usd, profile?.cash_balance_usd]
  )
  const totalFunds = useMemo(
    () => availableBalance + Math.max(Number(profile?.cash_reserved_usd || 0), 0),
    [availableBalance, profile?.cash_reserved_usd]
  )
  const cardProvider = useMemo(() => getCardProvider(cardNumber), [cardNumber])

  useEffect(() => {
    const loadBalance = async () => {
      try {
        setLoading(true)
        setError('')
        const data = await getProfile()
        setProfile(data.user as User)
      } catch (err: any) {
        setError(extractApiErrorMessage(err, 'Failed to load balance'))
      } finally {
        setLoading(false)
      }
    }

    void loadBalance()
  }, [])

  const resetCardForm = () => {
    setAmount('')
    setCardName('')
    setCardNumber('')
    setExpiry('')
    setCvc('')
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const purchaseAmount = Number(amount)
    const cardDigits = cardNumber.replace(/\D/g, '')

    if (!Number.isFinite(purchaseAmount) || purchaseAmount <= 0) {
      setError('Enter an amount greater than zero.')
      return
    }
    if (!cardName.trim()) {
      setError('Enter the name on the card.')
      return
    }
    if (cardDigits.length < 13 || !passesLuhn(cardDigits)) {
      setError('Enter a valid card number.')
      return
    }
    if (!isValidExpiry(expiry)) {
      setError('Enter a valid expiration date.')
      return
    }
    if (!/^\d{3,4}$/.test(cvc)) {
      setError('Enter a valid security code.')
      return
    }

    try {
      setSubmitting(true)
      setError('')
      setSuccess('')
      const updatedUser = await depositCashBalance(purchaseAmount)
      setProfile(updatedUser)
      setCheckoutOpen(false)
      resetCardForm()
      setSuccess('Balance added. A confirmation email has been sent to your account email.')
      window.dispatchEvent(new Event('auth-change'))
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to add balance'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content balance-page">
        <section className="balance-header-card">
          <div>
            <p className="builder-level-kicker">Billing</p>
            <h1>Balance</h1>
            <p>Jobs move the reserved hold out of your balance before launch, then settle against actual runtime cost.</p>
          </div>
          <button type="button" className="btn-primary" onClick={() => setCheckoutOpen(true)}>
            Add Balance
          </button>
        </section>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}

        {loading ? (
          <div className="loading-state">Loading balance...</div>
        ) : (
          <section className="balance-summary-grid">
            <div className="balance-metric-card">
              <span>Available Balance</span>
              <strong>{formatUsd(profile?.cash_balance_usd)}</strong>
            </div>
            <div className="balance-metric-card">
              <span>Reserved Holds</span>
              <strong>{formatUsd(profile?.cash_reserved_usd)}</strong>
            </div>
            <div className="balance-metric-card">
              <span>Total Funds</span>
              <strong>{formatUsd(totalFunds)}</strong>
            </div>
          </section>
        )}

        {checkoutOpen && (
          <section className="balance-checkout-card">
            <div className="balance-card-preview" aria-hidden="true">
              <div className="balance-card-row">
                <span>CASSIE</span>
                <strong>{cardProvider}</strong>
              </div>
              <div className="balance-card-chip" />
              <div className="balance-card-number">{cardNumber || '0000 0000 0000 0000'}</div>
              <div className="balance-card-row">
                <span>
                  <small>Cardholder</small>
                  {cardName || 'CARDHOLDER'}
                </span>
                <span>
                  <small>Expires</small>
                  {expiry || 'MM/YY'}
                </span>
              </div>
            </div>

            <form className="balance-checkout-form" onSubmit={handleSubmit}>
              <div className="section-heading">
                <h2>Add Balance</h2>
                <p>Card details are used only for this checkout screen.</p>
              </div>
              <div className="balance-form-grid">
                <div className="form-group">
                  <label htmlFor="balance_amount">Amount</label>
                  <input
                    id="balance_amount"
                    type="number"
                    min="1"
                    step="0.01"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    placeholder="50.00"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="card_name">Name on Card</label>
                  <input
                    id="card_name"
                    value={cardName}
                    onChange={(event) => setCardName(event.target.value.toUpperCase())}
                    placeholder="ADA LOVELACE"
                  />
                </div>
                <div className="form-group balance-form-wide">
                  <label htmlFor="card_number">Card Number</label>
                  <input
                    id="card_number"
                    inputMode="numeric"
                    autoComplete="cc-number"
                    value={cardNumber}
                    onChange={(event) => setCardNumber(formatCardNumber(event.target.value))}
                    placeholder="4242 4242 4242 4242"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="card_expiry">Expiration</label>
                  <input
                    id="card_expiry"
                    inputMode="numeric"
                    autoComplete="cc-exp"
                    value={expiry}
                    onChange={(event) => setExpiry(formatExpiry(event.target.value))}
                    placeholder="MM/YY"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="card_cvc">CVC</label>
                  <input
                    id="card_cvc"
                    inputMode="numeric"
                    autoComplete="cc-csc"
                    value={cvc}
                    onChange={(event) => setCvc(event.target.value.replace(/\D/g, '').slice(0, 4))}
                    placeholder="123"
                  />
                </div>
              </div>
              <div className="balance-checkout-actions">
                <button type="button" className="btn-secondary" onClick={() => setCheckoutOpen(false)} disabled={submitting}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? 'Processing...' : `Pay ${formatUsd(Number(amount || 0))}`}
                </button>
              </div>
            </form>
          </section>
        )}
      </div>
    </div>
  )
}
