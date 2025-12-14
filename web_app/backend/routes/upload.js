const express = require('express')
const auth = require('../middleware/auth')
const { getPresignedUrl, uploadComplete } = require('../services/storage')

const router = express.Router()

router.post('/presigned-url', auth, async (req, res) => {
  try {
    const { filename, contentType } = req.body
    const userId = req.user._id.toString()
    
    const { url, key } = await getPresignedUrl(userId, filename, contentType)
    res.json({ url, key })
  } catch (error) {
    res.status(500).json({ message: 'Failed to generate presigned URL', error: error.message })
  }
})

router.post('/complete', auth, async (req, res) => {
  try {
    const { filename, s3Key } = req.body
    await uploadComplete(req.user._id, filename, s3Key)
    res.json({ message: 'Upload recorded' })
  } catch (error) {
    res.status(500).json({ message: 'Failed to record upload', error: error.message })
  }
})

module.exports = router

