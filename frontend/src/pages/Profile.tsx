import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Navigation from '../components/Navigation'
import TrashIcon from '../components/TrashIcon'
import {
  CommunityEntry,
  ProfileUpdateRequest,
  User,
  confirmAccountDeletion,
  getProfile,
  getPublicProfile,
  requestAccountDeletionCode,
  updateProfile,
  uploadProfileAvatar,
} from '../services/authService'
import { extractApiErrorMessage } from '../services/apiClient'
import { getPasswordRequirementText, validatePasswordComplexity } from '../utils/passwordValidation'
import '../styles/globals.css'

const emptyForm: ProfileUpdateRequest = {
  email: '',
  display_name: '',
  bio: '',
  affiliation: '',
  job_title: '',
  location: '',
  website_url: '',
  current_password: '',
  new_password: '',
  login_two_factor_enabled: false,
  job_notifications_enabled: false,
}

export default function Profile() {
  const navigate = useNavigate()
  const { userId } = useParams()
  const isPublicProfile = Boolean(userId)
  const [profile, setProfile] = useState<User | null>(null)
  const [communityEntries, setCommunityEntries] = useState<CommunityEntry[]>([])
  const [formData, setFormData] = useState<ProfileUpdateRequest>(emptyForm)
  const [isEditing, setIsEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deletingAccount, setDeletingAccount] = useState(false)
  const [requestingDeletionCode, setRequestingDeletionCode] = useState(false)
  const [deletionCodeSent, setDeletionCodeSent] = useState(false)
  const [deletionCode, setDeletionCode] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [isPasswordEditing, setIsPasswordEditing] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)
  const editSectionRef = useRef<HTMLElement | null>(null)
  const passwordSectionRef = useRef<HTMLElement | null>(null)

  const avatarPreviewUrl = useMemo(() => {
    if (!avatarFile) return null
    return URL.createObjectURL(avatarFile)
  }, [avatarFile])

  useEffect(() => {
    return () => {
      if (avatarPreviewUrl) {
        URL.revokeObjectURL(avatarPreviewUrl)
      }
    }
  }, [avatarPreviewUrl])

  useEffect(() => {
    void loadProfile()
  }, [userId])

  const loadProfile = async () => {
    try {
      setLoading(true)
      setError('')
      setSuccess('')
      setIsEditing(false)
      setIsPasswordEditing(false)

      const data = isPublicProfile ? await getPublicProfile(Number(userId)) : await getProfile()
      const loadedUser = data.user as User

      setProfile(loadedUser)
      setCommunityEntries(data.community_entries)
      setFormData(
        isPublicProfile
          ? emptyForm
          : {
              email: loadedUser.email || '',
              display_name: loadedUser.display_name || '',
              bio: loadedUser.bio || '',
              affiliation: loadedUser.affiliation || '',
              job_title: loadedUser.job_title || '',
              location: loadedUser.location || '',
              website_url: loadedUser.website_url || '',
              current_password: '',
              new_password: '',
              login_two_factor_enabled: loadedUser.login_two_factor_enabled || false,
              job_notifications_enabled: loadedUser.job_notifications_enabled || false,
            }
      )
      setAvatarFile(null)
      setConfirmNewPassword('')
    } catch (err: any) {
      const message = extractApiErrorMessage(err, 'Failed to load profile')
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (field: keyof ProfileUpdateRequest, value: string) => {
    setFormData((current) => ({ ...current, [field]: value }))
  }

  const handleToggle = (field: 'login_two_factor_enabled' | 'job_notifications_enabled', checked: boolean) => {
    setFormData((current) => ({ ...current, [field]: checked }))
  }

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = e.target.files?.[0] || null
    setAvatarFile(nextFile)
  }

  const handleToggleEdit = () => {
    setIsEditing((current) => {
      const next = !current
      if (next) {
        setIsPasswordEditing(false)
        window.setTimeout(() => {
          editSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 50)
      }
      return next
    })
  }

  const handleTogglePasswordEdit = () => {
    setIsPasswordEditing((current) => {
      const next = !current
      if (next) {
        setIsEditing(false)
        window.setTimeout(() => {
          passwordSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 50)
      }
      return next
    })
  }

  const handleRequestDeletionCode = async () => {
    try {
      setRequestingDeletionCode(true)
      setError('')
      await requestAccountDeletionCode()
      setDeletionCodeSent(true)
      setSuccess('Deletion verification code sent to your email.')
    } catch (err: any) {
      const message = extractApiErrorMessage(err, 'Failed to request account deletion code')
      setError(message)
    } finally {
      setRequestingDeletionCode(false)
    }
  }

  const handleDeleteAccount = async () => {
    try {
      setDeletingAccount(true)
      setError('')
      await confirmAccountDeletion(deletionCode)
      navigate('/')
    } catch (err: any) {
      const message = extractApiErrorMessage(err, 'Failed to delete account')
      setError(message)
    } finally {
      setDeletingAccount(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const emailChanged = (formData.email || '').trim() !== (profile?.email || '').trim()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      let updated = await updateProfile(formData)
      if (avatarFile) {
        updated = await uploadProfileAvatar(avatarFile)
      }
      setProfile(updated)
      setSuccess(
        emailChanged
          ? 'Profile updated. Your new email must be verified again, so login 2FA and job notification emails were turned off for now.'
          : 'Profile updated successfully.'
      )
      setIsEditing(false)
      setAvatarFile(null)
      window.dispatchEvent(new Event('auth-change'))
    } catch (err: any) {
      const message = extractApiErrorMessage(err, 'Failed to update profile')
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const passwordFailures = validatePasswordComplexity(formData.new_password || '')
    if (passwordFailures.length > 0) {
      setError(`New password must include: ${passwordFailures.join(', ')}.`)
      return
    }
    if (!confirmNewPassword.trim()) {
      setError('Please confirm your new password.')
      return
    }
    if ((formData.new_password || '') !== confirmNewPassword) {
      setError('New passwords do not match.')
      return
    }

    setSavingPassword(true)
    setError('')
    setSuccess('')
    try {
      await updateProfile({
        current_password: formData.current_password || '',
        new_password: formData.new_password || '',
      })
      setSuccess('Password updated successfully.')
      setIsPasswordEditing(false)
      setFormData((current) => ({
        ...current,
        current_password: '',
        new_password: '',
      }))
      setConfirmNewPassword('')
    } catch (err: any) {
      const message = extractApiErrorMessage(err, 'Failed to update password')
      setError(message)
    } finally {
      setSavingPassword(false)
    }
  }

  if (loading) {
    return (
      <div className="page-container">
        <Navigation />
        <div className="page-content">
          <div className="loading-state">Loading profile...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content profile-page">
        <section className="feature-hero">
          <div className="profile-summary-card">
            {!isPublicProfile && (
              <div className="profile-summary-actions">
                <button
                  type="button"
                  className="profile-edit-button"
                  onClick={handleToggleEdit}
                  aria-label={isEditing ? 'Close profile editor' : 'Edit profile'}
                  title={isEditing ? 'Close profile editor' : 'Edit profile'}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path
                      d="M3 17.25V21h3.75L17.8 9.94l-3.75-3.75L3 17.25zm2.92 2.33H5v-.92l9.06-9.06.92.92L5.92 19.58zM19.71 6.04a1 1 0 0 0 0-1.41l-.34-.34a1 1 0 0 0-1.41 0l-1.06 1.06 1.75 1.75 1.06-1.06z"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <button
                  type="button"
                  className="btn-secondary profile-password-toggle"
                  onClick={handleTogglePasswordEdit}
                >
                  {isPasswordEditing ? 'Close Password' : 'Change Password'}
                </button>
              </div>
            )}
            <div className="profile-avatar-shell">
              {avatarPreviewUrl || profile?.avatar_url ? (
                <img className="profile-avatar" src={avatarPreviewUrl || profile?.avatar_url || ''} alt={profile?.username || 'profile'} />
              ) : (
                <div className="profile-avatar profile-avatar-fallback">
                  {(profile?.display_name || profile?.username || 'U').slice(0, 1).toUpperCase()}
                </div>
              )}
            </div>
            <div className="profile-summary-heading">
              <h2>{profile?.display_name || profile?.username}</h2>
              <p>@{profile?.username}</p>
            </div>
            <div className="profile-mini-meta">
              <span>{profile?.job_title || 'Researcher'}</span>
              <span>{profile?.affiliation || 'Independent'}</span>
              <span>{communityEntries.length} shared pipeline{communityEntries.length === 1 ? '' : 's'}</span>
            </div>
            <div className="profile-summary-bio">
              <p>{profile?.bio || 'No bio added yet.'}</p>
            </div>
            <div className="profile-summary-info-grid">
              <div className="profile-summary-info-item">
                <span className="profile-info-label">Location</span>
                <strong>{profile?.location || 'Not set'}</strong>
              </div>
              <div className="profile-summary-info-item">
                <span className="profile-info-label">Website</span>
                {profile?.website_url ? (
                  <a href={profile.website_url} target="_blank" rel="noreferrer" className="profile-info-link">
                    {profile.website_url}
                  </a>
                ) : (
                  <strong>Not set</strong>
                )}
              </div>
              <div className="profile-summary-info-item">
                <span className="profile-info-label">Affiliation</span>
                <strong>{profile?.affiliation || 'Not set'}</strong>
              </div>
            </div>
          </div>
        </section>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="success-message">{success}</div>}

        <section className="card profile-community-card profile-community-main">
          <div className="section-heading">
            <h2>{isPublicProfile ? 'Published Community Pipelines' : 'Community Entries'}</h2>
            <p>
              {isPublicProfile
                ? 'Read-only profile view for pipelines this researcher shared with the community catalog.'
                : 'The pipelines you have posted to the community catalog.'}
            </p>
          </div>

          {communityEntries.length === 0 ? (
            <div className="empty-state compact-empty">
              <p>{isPublicProfile ? 'This user has not shared any pipelines yet.' : 'You have not shared any pipelines yet.'}</p>
            </div>
          ) : (
            <div className="profile-entry-list profile-entry-list-main">
              {communityEntries.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className="profile-entry-card"
                  onClick={() => navigate(`/pipelines/builder/${entry.id}`)}
                >
                  <div className="profile-entry-topline">
                    <span className="entry-badge">Shared Pipeline</span>
                    <span>{entry.saved_at ? new Date(entry.saved_at).toLocaleDateString() : ''}</span>
                  </div>
                  <h3>{entry.name}</h3>
                  <p>{entry.description || 'No description provided.'}</p>
                </button>
              ))}
            </div>
          )}
        </section>

        {!isPublicProfile && isEditing && (
          <section ref={editSectionRef} className="card profile-form-card">
            <div className="section-heading">
              <h2>Profile Details</h2>
              <p>Visible information, account basics, and notification settings.</p>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="profile-form-grid">
                <div className="form-group">
                  <label htmlFor="display_name">Display Name</label>
                  <input
                    id="display_name"
                    value={formData.display_name || ''}
                    onChange={(e) => handleChange('display_name', e.target.value)}
                    placeholder="How you want to appear publicly"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    type="email"
                    value={formData.email || ''}
                    onChange={(e) => handleChange('email', e.target.value)}
                    placeholder="name@example.com"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="job_title">Role / Title</label>
                  <input
                    id="job_title"
                    value={formData.job_title || ''}
                    onChange={(e) => handleChange('job_title', e.target.value)}
                    placeholder="Bioinformatics Engineer, PhD Student..."
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="affiliation">Affiliation</label>
                  <input
                    id="affiliation"
                    value={formData.affiliation || ''}
                    onChange={(e) => handleChange('affiliation', e.target.value)}
                    placeholder="Lab, university, company, or team"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="location">Location</label>
                  <input
                    id="location"
                    value={formData.location || ''}
                    onChange={(e) => handleChange('location', e.target.value)}
                    placeholder="City, country, or remote"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="website_url">Website</label>
                  <input
                    id="website_url"
                    value={formData.website_url || ''}
                    onChange={(e) => handleChange('website_url', e.target.value)}
                    placeholder="https://..."
                  />
                </div>

                <div className="form-group profile-form-wide">
                  <label htmlFor="avatar_upload">Profile Picture</label>
                  <input
                    id="avatar_upload"
                    type="file"
                    accept="image/png,image/jpeg,image/jpg,image/gif,image/webp,image/svg+xml"
                    onChange={handleAvatarChange}
                  />
                  <small style={{ color: 'var(--text-light)' }}>
                    Upload PNG, JPEG, GIF, WEBP, or SVG up to 5 MB.
                  </small>
                </div>

                <div className="form-group profile-form-wide">
                  <label htmlFor="bio">Bio</label>
                  <textarea
                    id="bio"
                    rows={5}
                    value={formData.bio || ''}
                    onChange={(e) => handleChange('bio', e.target.value)}
                    placeholder="Tell the community what you work on, what genomes or workflows interest you, and what others should know."
                  />
                </div>

                <div className="profile-settings-block profile-form-wide">
                  <h3>Security & Notifications</h3>
                  <p className="profile-settings-copy">
                    These options use your verified email address to protect sign-in and keep you updated on long-running jobs.
                  </p>
                  <div className="profile-settings-list">
                    <label className="profile-setting-toggle">
                      <input
                        type="checkbox"
                        checked={Boolean(formData.login_two_factor_enabled)}
                        onChange={(e) => handleToggle('login_two_factor_enabled', e.target.checked)}
                      />
                      <span>
                        <strong>Require a code every time I log in</strong>
                        <small>Email a one-time sign-in code after your password is accepted.</small>
                      </span>
                    </label>
                    <label className="profile-setting-toggle">
                      <input
                        type="checkbox"
                        checked={Boolean(formData.job_notifications_enabled)}
                        onChange={(e) => handleToggle('job_notifications_enabled', e.target.checked)}
                      />
                      <span>
                        <strong>Send me job emails</strong>
                        <small>Notify me when a job finishes successfully or pauses at a checkpoint.</small>
                      </span>
                    </label>
                  </div>
                  {!profile?.email_verified && (
                    <small className="profile-settings-warning">
                      Verify your email before enabling login 2FA or job notification emails.
                    </small>
                  )}
                </div>
              </div>

              <div className="button-row" style={{ marginTop: '1.5rem' }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? 'Saving Profile...' : 'Save Changes'}
                </button>
                <button
                  className="btn-secondary"
                  type="button"
                  onClick={() => {
                    setIsEditing(false)
                    setConfirmNewPassword('')
                  }}
                >
                  Cancel
                </button>
                <button className="btn-secondary" type="button" onClick={() => navigate('/')}>
                  Back To Home
                </button>
              </div>
            </form>

            <div className="profile-danger-zone">
              <h3>Delete Account</h3>
              <p>Permanently remove your account and its associated data. A verification code will be sent to your email before deletion is allowed.</p>
              <div className="button-row profile-code-actions">
                <button className="btn-secondary profile-danger-button" type="button" onClick={handleRequestDeletionCode} disabled={requestingDeletionCode || deletingAccount}>
                  {requestingDeletionCode ? 'Sending Code...' : (deletionCodeSent ? 'Resend Delete Code' : 'Send Delete Code')}
                </button>
              </div>
              {deletionCodeSent && (
                <div className="profile-delete-confirmation">
                  <div className="form-group">
                    <label htmlFor="delete_account_code">Deletion Verification Code</label>
                    <input
                      id="delete_account_code"
                      value={deletionCode}
                      onChange={(e) => setDeletionCode(e.target.value)}
                      placeholder="Enter the emailed code"
                      disabled={deletingAccount}
                    />
                  </div>
                  <button className="btn-secondary profile-danger-button" type="button" onClick={handleDeleteAccount} disabled={deletingAccount || !deletionCode.trim()}>
                    <TrashIcon />
                    {deletingAccount ? 'Deleting Account...' : 'Confirm Delete Account'}
                  </button>
                </div>
              )}
            </div>
          </section>
        )}

        {!isPublicProfile && isPasswordEditing && (
          <section ref={passwordSectionRef} className="card profile-form-card profile-password-card">
            <div className="section-heading">
              <h2>Change Password</h2>
              <p>Update only your sign-in password. Your public profile details stay unchanged.</p>
            </div>

            <form onSubmit={handlePasswordSubmit}>
              <div className="profile-form-grid">
                <div className="form-group">
                  <label htmlFor="current_password">Current Password</label>
                  <input
                    id="current_password"
                    type="password"
                    value={formData.current_password || ''}
                    onChange={(e) => handleChange('current_password', e.target.value)}
                    placeholder="Enter your current password"
                    required
                    disabled={savingPassword}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="new_password">New Password</label>
                  <input
                    id="new_password"
                    type="password"
                    minLength={8}
                    value={formData.new_password || ''}
                    onChange={(e) => handleChange('new_password', e.target.value)}
                    placeholder="Choose a stronger password"
                    required
                    disabled={savingPassword}
                  />
                  <small>{getPasswordRequirementText()}.</small>
                </div>
                <div className="form-group">
                  <label htmlFor="confirm_new_password">Confirm New Password</label>
                  <input
                    id="confirm_new_password"
                    type="password"
                    minLength={8}
                    value={confirmNewPassword}
                    onChange={(e) => setConfirmNewPassword(e.target.value)}
                    placeholder="Re-enter your new password"
                    required
                    disabled={savingPassword}
                  />
                  {!!((formData.new_password || '').trim() || confirmNewPassword.trim()) &&
                    (formData.new_password || '') !== confirmNewPassword && (
                      <small style={{ color: '#b91c1c' }}>New passwords must match.</small>
                    )}
                </div>
              </div>

              <div className="button-row" style={{ marginTop: '1.5rem' }}>
                <button className="btn-primary" type="submit" disabled={savingPassword}>
                  {savingPassword ? 'Updating Password...' : 'Update Password'}
                </button>
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={savingPassword}
                  onClick={() => {
                    setIsPasswordEditing(false)
                    setFormData((current) => ({ ...current, current_password: '', new_password: '' }))
                    setConfirmNewPassword('')
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          </section>
        )}
      </div>
    </div>
  )
}
