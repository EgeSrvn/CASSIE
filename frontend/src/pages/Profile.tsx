import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Navigation from '../components/Navigation'
import {
  CommunityEntry,
  ProfileUpdateRequest,
  User,
  getProfile,
  getPublicProfile,
  updateProfile,
  uploadProfileAvatar,
} from '../services/authService'
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
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [avatarFile, setAvatarFile] = useState<File | null>(null)

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
            }
      )
      setAvatarFile(null)
    } catch (err: any) {
      const message = err.response?.data?.message || err.message || 'Failed to load profile'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (field: keyof ProfileUpdateRequest, value: string) => {
    setFormData((current) => ({ ...current, [field]: value }))
  }

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = e.target.files?.[0] || null
    setAvatarFile(nextFile)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      let updated = await updateProfile(formData)
      if (avatarFile) {
        updated = await uploadProfileAvatar(avatarFile)
      }
      setProfile(updated)
      setSuccess('Profile updated successfully.')
      setIsEditing(false)
      setAvatarFile(null)
      setFormData((current) => ({
        ...current,
        current_password: '',
        new_password: '',
      }))
      window.dispatchEvent(new Event('auth-change'))
    } catch (err: any) {
      const message = err.response?.data?.message || err.message || 'Failed to update profile'
      setError(message)
    } finally {
      setSaving(false)
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
              <button
                type="button"
                className="profile-edit-button"
                onClick={() => setIsEditing((current) => !current)}
                aria-label={isEditing ? 'Close profile editor' : 'Edit profile'}
                title={isEditing ? 'Close profile editor' : 'Edit profile'}
              >
                ✎
              </button>
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
          <section className="card profile-form-card">
            <div className="section-heading">
              <h2>Profile Details</h2>
              <p>Visible information, account basics, and optional password change.</p>
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

                <div className="profile-password-block profile-form-wide">
                  <h3>Change Password</h3>
                  <div className="profile-form-grid">
                    <div className="form-group">
                      <label htmlFor="current_password">Current Password</label>
                      <input
                        id="current_password"
                        type="password"
                        value={formData.current_password || ''}
                        onChange={(e) => handleChange('current_password', e.target.value)}
                        placeholder="Required only if changing password"
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
                        placeholder="At least 8 characters"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="button-row" style={{ marginTop: '1.5rem' }}>
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? 'Saving Profile...' : 'Save Changes'}
                </button>
                <button className="btn-secondary" type="button" onClick={() => setIsEditing(false)}>
                  Cancel
                </button>
                <button className="btn-secondary" type="button" onClick={() => navigate('/dashboard')}>
                  Back To Dashboard
                </button>
              </div>
            </form>
          </section>
        )}
      </div>
    </div>
  )
}
