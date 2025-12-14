const mongoose = require('mongoose')

const projectSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
  },
  cloudProvider: {
    type: String,
    enum: ['aws', 'gcp', 'azure'],
    required: true,
  },
  credentials: {
    type: mongoose.Schema.Types.Mixed,
    required: true,
  },
  projectDetails: {
    genomeSize: String,
    ploidy: String,
    knownGenomeSize: Boolean,
    dataTypes: [String],
    analyses: [String],
  },
  s3Paths: {
    type: mongoose.Schema.Types.Mixed,
    default: {},
  },
  createdAt: {
    type: Date,
    default: Date.now,
  },
  updatedAt: {
    type: Date,
    default: Date.now,
  },
})

module.exports = mongoose.model('Project', projectSchema)

