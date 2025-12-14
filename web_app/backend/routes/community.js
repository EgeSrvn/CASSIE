const express = require('express')
const auth = require('../middleware/auth')
const Workflow = require('../models/Workflow')

const router = express.Router()

router.get('/workflows', async (req, res) => {
  try {
    const workflows = await Workflow.find()
      .populate('author', 'email')
      .sort({ votes: -1, createdAt: -1 })
    res.json(workflows)
  } catch (error) {
    res.status(500).json({ message: 'Failed to fetch workflows', error: error.message })
  }
})

router.post('/workflows/:id/vote', auth, async (req, res) => {
  try {
    const workflow = await Workflow.findById(req.params.id)
    if (!workflow) {
      return res.status(404).json({ message: 'Workflow not found' })
    }

    if (workflow.voters.includes(req.user._id)) {
      return res.status(400).json({ message: 'Already voted' })
    }

    workflow.votes += 1
    workflow.voters.push(req.user._id)
    await workflow.save()

    res.json({ message: 'Vote recorded', workflow })
  } catch (error) {
    res.status(500).json({ message: 'Failed to vote', error: error.message })
  }
})

module.exports = router

