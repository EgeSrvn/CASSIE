const express = require('express')
const auth = require('../middleware/auth')
const Project = require('../models/Project')

const router = express.Router()

router.post('/configure', auth, async (req, res) => {
  try {
    const { cloudProvider, credentials, projectDetails, s3Paths } = req.body

    let project = await Project.findOne({ userId: req.user._id })
    
    if (project) {
      project.cloudProvider = cloudProvider
      project.credentials = credentials
      project.projectDetails = projectDetails
      project.s3Paths = s3Paths
      project.updatedAt = new Date()
      await project.save()
    } else {
      project = new Project({
        userId: req.user._id,
        cloudProvider,
        credentials,
        projectDetails,
        s3Paths,
      })
      await project.save()
    }

    res.json({ message: 'Configuration saved', project })
  } catch (error) {
    res.status(500).json({ message: 'Failed to save configuration', error: error.message })
  }
})

router.get('/current', auth, async (req, res) => {
  try {
    const project = await Project.findOne({ userId: req.user._id })
    res.json(project || {})
  } catch (error) {
    res.status(500).json({ message: 'Failed to fetch project', error: error.message })
  }
})

module.exports = router

