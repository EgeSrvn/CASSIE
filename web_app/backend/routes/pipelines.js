const express = require('express')
const auth = require('../middleware/auth')
const Pipeline = require('../models/Pipeline')

const router = express.Router()

router.post('/', auth, async (req, res) => {
  try {
    const { name, description, nodes, edges } = req.body

    const pipeline = new Pipeline({
      userId: req.user._id,
      name,
      description,
      nodes,
      edges,
    })
    await pipeline.save()

    res.json({ message: 'Pipeline saved', pipeline })
  } catch (error) {
    res.status(500).json({ message: 'Failed to save pipeline', error: error.message })
  }
})

router.get('/', auth, async (req, res) => {
  try {
    const pipelines = await Pipeline.find({ userId: req.user._id })
    res.json(pipelines)
  } catch (error) {
    res.status(500).json({ message: 'Failed to fetch pipelines', error: error.message })
  }
})

module.exports = router

