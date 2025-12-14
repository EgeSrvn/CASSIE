const AWS = require('aws-sdk')
const { Compute } = require('@google-cloud/compute')
const { ComputeManagementClient } = require('@azure/arm-compute')

const createEC2Instance = async (job, project) => {
  const ec2 = new AWS.EC2({
    accessKeyId: project.credentials.accessKey,
    secretAccessKey: project.credentials.secretKey,
    region: project.credentials.region || 'us-east-1',
  })

  const userData = `
#!/bin/bash
# Install dependencies
apt-get update
apt-get install -y docker.io s3fs

# Mount S3 bucket
echo "${project.credentials.accessKey}:${project.credentials.secretKey}" > /etc/passwd-s3fs
chmod 600 /etc/passwd-s3fs
s3fs ${process.env.AWS_S3_BUCKET} /mnt/s3 -o passwd_file=/etc/passwd-s3fs

# Run Nextflow pipeline
docker run -v /mnt/s3:/data nextflow/nextflow:latest \
  nextflow run ${job.pipeline} -work-dir /data/work
`

  const params = {
    ImageId: 'ami-0c55b159cbfafe1f0', // Amazon Linux 2
    MinCount: 1,
    MaxCount: 1,
    InstanceType: 't3.xlarge',
    UserData: Buffer.from(userData).toString('base64'),
    IamInstanceProfile: {
      Name: 'cassie-instance-profile', // Should have S3 access
    },
    TagSpecifications: [
      {
        ResourceType: 'instance',
        Tags: [
          { Key: 'Name', Value: `cassie-job-${job._id}` },
          { Key: 'JobId', Value: job._id.toString() },
        ],
      },
    ],
  }

  try {
    const result = await ec2.runInstances(params).promise()
    const instanceId = result.Instances[0].InstanceId
    
    // Set up termination when job completes (via CloudWatch or monitoring)
    // This is a simplified version - in production, you'd want proper monitoring
    
    return instanceId
  } catch (error) {
    console.error('Failed to create EC2 instance:', error)
    throw error
  }
}

const terminateEC2Instance = async (instanceId, credentials) => {
  const ec2 = new AWS.EC2({
    accessKeyId: credentials.accessKey,
    secretAccessKey: credentials.secretKey,
    region: credentials.region || 'us-east-1',
  })

  try {
    await ec2.terminateInstances({ InstanceIds: [instanceId] }).promise()
  } catch (error) {
    console.error('Failed to terminate EC2 instance:', error)
    throw error
  }
}

module.exports = {
  createEC2Instance,
  terminateEC2Instance,
}

