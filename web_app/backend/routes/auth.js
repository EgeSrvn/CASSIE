const express = require('express')
const jwt = require('jsonwebtoken')
const User = require('../models/User')
const auth = require('../middleware/auth')

const router = express.Router()

router.post('/register', async (req, res) => {
  try {
    const { email, password } = req.body

    let user = await User.findOne({ email })
    if (user) {
      return res.status(400).json({ message: 'User already exists' })
    }

    user = new User({ email, password })
    await user.save()

    const token = jwt.sign(
      { userId: user._id },
      process.env.JWT_SECRET || 'your-secret-key',
      { expiresIn: '7d' }
    )

    res.json({ token, user: { id: user._id, email: user.email } })
  } catch (error) {
    res.status(500).json({ message: 'Server error', error: error.message })
  }
})

router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body

    const user = await User.findOne({ email })
    if (!user) {
      return res.status(400).json({ message: 'Invalid credentials' })
    }

    const isMatch = await user.comparePassword(password)
    if (!isMatch) {
      return res.status(400).json({ message: 'Invalid credentials' })
    }

    const token = jwt.sign(
      { userId: user._id },
      process.env.JWT_SECRET || 'your-secret-key',
      { expiresIn: '7d' }
    )

    res.json({ token, user: { id: user._id, email: user.email } })
  } catch (error) {
    res.status(500).json({ message: 'Server error', error: error.message })
  }
})

router.get('/me', auth, async (req, res) => {
  res.json({ id: req.user._id, email: req.user.email })
})

module.exports = router

