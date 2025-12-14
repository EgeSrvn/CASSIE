const k8s = require('@kubernetes/client-node')
const { createJob } = require('./kubernetes')
const { createEC2Instance } = require('./cloudInstances')

const submitJob = async (job, project) => {
  try {
    // Update job status
    job.status = 'running'
    job.startedAt = new Date()
    await job.save()

    // Create Kubernetes job or EC2 instance based on project config
    if (project.cloudProvider === 'aws') {
      // Create EC2 instance for the job
      const instanceId = await createEC2Instance(job, project)
      job.metadata = { instanceId }
      await job.save()
    } else {
      // Create Kubernetes job
      await createJob(job, project)
    }

    // In a real implementation, this would:
    // 1. Create compute resources (EC2/K8s)
    // 2. Mount S3/GCS/Azure storage
    // 3. Run Nextflow pipeline
    // 4. Monitor progress
    // 5. Clean up resources when done
  } catch (error) {
    job.status = 'failed'
    await job.save()
    throw error
  }
}

module.exports = {
  submitJob,
}

