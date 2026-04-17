import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Navigation from '../components/Navigation'
import { createForumThread, uploadForumThreadImages } from '../services/forumService'
import { extractApiErrorMessage } from '../services/apiClient'
import '../styles/globals.css'

const MAX_FORUM_IMAGES = 4

export default function ForumComposer() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [images, setImages] = useState<File[]>([])
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')

  const imagePreviews = useMemo(
    () => images.map((file) => ({ file, url: URL.createObjectURL(file) })),
    [images]
  )

  useEffect(() => {
    return () => {
      imagePreviews.forEach(({ url }) => URL.revokeObjectURL(url))
    }
  }, [imagePreviews])

  const handleImageChange = (nextFiles: FileList | null) => {
    const selectedFiles = Array.from(nextFiles || [])
    if (selectedFiles.length > MAX_FORUM_IMAGES) {
      setError(`You can attach up to ${MAX_FORUM_IMAGES} images per post.`)
      return
    }
    setError('')
    setImages(selectedFiles)
  }

  const handlePublish = async (e: FormEvent) => {
    e.preventDefault()
    try {
      setPublishing(true)
      setError('')
      const createdThread = await createForumThread({ title, body })
      if (images.length > 0) {
        await uploadForumThreadImages(createdThread.id, images)
      }
      navigate(`/forum/${createdThread.id}`)
    } catch (err: any) {
      setError(extractApiErrorMessage(err, 'Failed to publish forum discussion'))
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="page-container">
      <Navigation />
      <div className="page-content forum-page">
        <section className="card forum-composer-page-card">
          <div className="section-heading">
            <h2>Create a New Discussion</h2>
            <p>Write the main question here, add optional images, then publish the post.</p>
          </div>
          {error && <div className="error-message">{error}</div>}
          <form className="forum-form" onSubmit={handlePublish}>
            <div className="form-group">
              <label htmlFor="forum-discussion-title">Title</label>
              <input
                id="forum-discussion-title"
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Summarize your question clearly"
              />
            </div>
            <div className="form-group">
              <label htmlFor="forum-discussion-body">Post Body</label>
              <textarea
                id="forum-discussion-body"
                rows={10}
                value={body}
                maxLength={8000}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Describe the problem, what you tried, and the context others need."
              />
            </div>
            <div className="form-group">
              <label htmlFor="forum-images">Images</label>
              <input
                id="forum-images"
                type="file"
                accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
                multiple
                onChange={(e) => handleImageChange(e.target.files)}
              />
              <small>Up to 4 images per discussion.</small>
            </div>
            {imagePreviews.length > 0 && (
              <div className="forum-image-preview-grid">
                {imagePreviews.map(({ file, url }) => (
                  <div key={file.name + file.size} className="forum-image-preview-card">
                    <img src={url} alt={file.name} className="forum-image-preview" />
                    <span>{file.name}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="button-row">
              <button type="submit" className="btn-primary" disabled={publishing}>
                {publishing ? 'Publishing...' : 'Publish Post'}
              </button>
              <button type="button" className="btn-secondary" onClick={() => navigate('/forum')}>
                Cancel
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  )
}
