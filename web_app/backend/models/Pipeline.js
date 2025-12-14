const mongoose = require('mongoose')

const pipelineSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
  },
  name: {
    type: String,
    required: true,
  },
  description: String,
  nodes: {
    type: mongoose.Schema.Types.Mixed,
    required: true,
  },
  edges: {
    type: mongoose.Schema.Types.Mixed,
    required: true,
  },
  nextflowScript: String,
  isPublic: {
    type: Boolean,
    default: false,
  },
  createdAt: {
    type: Date,
    default: Date.now,
  },
})

module.exports = mongoose.model('Pipeline', pipelineSchema)

