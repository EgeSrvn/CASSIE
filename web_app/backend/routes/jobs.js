const express = require('express')
const auth = require('../middleware/auth')
const Job = require('../models/Job')
const Project = require('../models/Project')
const { submitJob } = require('../services/jobOrchestrator')

const router = express.Router()

router.get('/', auth, async (req, res) => {
  try {
    const jobs = await Job.find({ userId: req.user._id }).sort({ createdAt: -1 })
    res.json(jobs)
  } catch (error) {
    res.status(500).json({ message: 'Failed to fetch jobs', error: error.message })
  }
})

router.post('/', auth, async (req, res) => {
  try {
    const { name, pipeline, projectId } = req.body

    const project = await Project.findById(projectId || (await Project.findOne({ userId: req.user._id }))._id)
    if (!project) {
      return res.status(404).json({ message: 'Project not found' })
    }

    const job = new Job({
      userId: req.user._id,
      projectId: project._id,
      name,
      pipeline,
      status: 'pending',
    })
    await job.save()

    // Submit job to orchestrator
    await submitJob(job, project)

    res.json({ message: 'Job created', job })
  } catch (error) {
    res.status(500).json({ message: 'Failed to create job', error: error.message })
  }
})

router.get('/:id', auth, async (req, res) => {
  try {
    const job = await Job.findOne({ _id: req.params.id, userId: req.user._id })
    if (!job) {
      return res.status(404).json({ message: 'Job not found' })
    }
    res.json(job)
  } catch (error) {
    res.status(500).json({ message: 'Failed to fetch job', error: error.message })
  }
})

module.exports = router

