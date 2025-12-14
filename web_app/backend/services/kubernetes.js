const k8s = require('@kubernetes/client-node')

const kc = new k8s.KubeConfig()
kc.loadFromDefault()

const k8sApi = kc.makeApiClient(k8s.BatchV1Api)
const coreApi = kc.makeApiClient(k8s.CoreV1Api)

const createJob = async (job, project) => {
  const jobManifest = {
    apiVersion: 'batch/v1',
    kind: 'Job',
    metadata: {
      name: `cassie-job-${job._id}`,
      labels: {
        app: 'cassie',
        jobId: job._id.toString(),
      },
    },
    spec: {
      template: {
        metadata: {
          labels: {
            app: 'cassie',
            jobId: job._id.toString(),
          },
        },
        spec: {
          containers: [
            {
              name: 'nextflow-runner',
              image: 'nextflow/nextflow:latest',
              command: ['/bin/sh', '-c'],
              args: [
                `nextflow run ${project.projectDetails.pipeline} -with-kubernetes`,
              ],
              env: [
                {
                  name: 'AWS_ACCESS_KEY_ID',
                  value: project.credentials.accessKey,
                },
                {
                  name: 'AWS_SECRET_ACCESS_KEY',
                  value: project.credentials.secretKey,
                },
              ],
              volumeMounts: [
                {
                  name: 's3-mount',
                  mountPath: '/data',
                },
              ],
            },
          ],
          volumes: [
            {
              name: 's3-mount',
              // S3 FUSE mount configuration would go here
            },
          ],
          restartPolicy: 'Never',
        },
      },
      backoffLimit: 3,
    },
  }

  try {
    const response = await k8sApi.createNamespacedJob('default', jobManifest)
    return response.body
  } catch (error) {
    console.error('Failed to create Kubernetes job:', error)
    throw error
  }
}

module.exports = {
  createJob,
}

