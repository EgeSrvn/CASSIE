const AWS = require('aws-sdk')
const { Storage } = require('@google-cloud/storage')
const { BlobServiceClient } = require('@azure/storage-blob')

const getStorageClient = (provider, credentials) => {
  switch (provider) {
    case 'aws':
      return new AWS.S3({
        accessKeyId: credentials.accessKey,
        secretAccessKey: credentials.secretKey,
        region: credentials.region || 'us-east-1',
      })
    case 'gcp':
      return new Storage({
        projectId: credentials.projectId,
        keyFilename: credentials.keyFile,
      })
    case 'azure':
      return BlobServiceClient.fromConnectionString(
        `DefaultEndpointsProtocol=https;AccountName=${credentials.accountName};AccountKey=${credentials.accountKey};EndpointSuffix=core.windows.net`
      )
    default:
      throw new Error('Unsupported cloud provider')
  }
}

const getPresignedUrl = async (userId, filename, contentType) => {
  // For now, use default AWS config from env
  // In production, this should use user's project credentials
  const s3 = new AWS.S3({
    accessKeyId: process.env.AWS_ACCESS_KEY_ID,
    secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
    region: process.env.AWS_REGION || 'us-east-1',
  })

  const key = `uploads/${userId}/${Date.now()}-${filename}`
  const bucket = process.env.AWS_S3_BUCKET || 'cassie-uploads'

  const url = await s3.getSignedUrlPromise('putObject', {
    Bucket: bucket,
    Key: key,
    ContentType: contentType,
    Expires: 3600, // 1 hour
  })

  return { url, key }
}

const uploadComplete = async (userId, filename, s3Key) => {
  // Record upload in database if needed
  // This could be stored in a File model
  return true
}

module.exports = {
  getStorageClient,
  getPresignedUrl,
  uploadComplete,
}

