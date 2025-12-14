'use client'

import { useState } from 'react'
import axios from 'axios'

export default function Configure() {
  const [cloudProvider, setCloudProvider] = useState('aws')
  const [credentials, setCredentials] = useState({
    aws: { accessKey: '', secretKey: '', region: 'us-east-1' },
    gcp: { projectId: '', keyFile: '' },
    azure: { accountName: '', accountKey: '' }
  })
  const [projectDetails, setProjectDetails] = useState({
    genomeSize: '',
    ploidy: '',
    knownGenomeSize: false,
    dataTypes: [] as string[],
    analyses: [] as string[]
  })
  const [s3Paths, setS3Paths] = useState<Record<string, string>>({})

  const dataTypes = [
    'Illumina / MGI',
    'PacBio CLR',
    'PacBio CCS/HiFi',
    'Oxford Nanopore',
    'BioNano',
    'StrandSeq',
    'HiC',
    'Linked reads (10x, UST, etc.)'
  ]

  const analyses = [
    'Read QC',
    'Genome size estimation',
    'Heterozygosity estimation',
    'Repeat content analysis',
    'Assembly',
    'Scaffolding',
    'Error correction',
    'Gap filling',
    'Gene annotation',
    'RepeatMasker',
    'SEDEF/BISER',
    'BUSCO',
    'QUAST',
    'mrCaNaVaR'
  ]

  const handleDataTypeToggle = (type: string) => {
    setProjectDetails(prev => ({
      ...prev,
      dataTypes: prev.dataTypes.includes(type)
        ? prev.dataTypes.filter(t => t !== type)
        : [...prev.dataTypes, type]
    }))
  }

  const handleAnalysisToggle = (analysis: string) => {
    setProjectDetails(prev => ({
      ...prev,
      analyses: prev.analyses.includes(analysis)
        ? prev.analyses.filter(a => a !== analysis)
        : [...prev.analyses, analysis]
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const token = localStorage.getItem('token')
    
    try {
      await axios.post(
        `${process.env.NEXT_PUBLIC_API_URL}/api/projects/configure`,
        {
          cloudProvider,
          credentials: credentials[cloudProvider as keyof typeof credentials],
          projectDetails,
          s3Paths
        },
        { headers: { Authorization: `Bearer ${token}` } }
      )
      alert('Configuration saved successfully!')
    } catch (err: any) {
      alert(err.response?.data?.message || 'Failed to save configuration')
    }
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-primary-blue mb-8">
        Project Configuration
      </h1>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Cloud Provider Selection */}
        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-4">
            Cloud Provider
          </h2>
          <div className="flex gap-4">
            {['aws', 'gcp', 'azure'].map(provider => (
              <label key={provider} className="flex items-center">
                <input
                  type="radio"
                  name="cloudProvider"
                  value={provider}
                  checked={cloudProvider === provider}
                  onChange={(e) => setCloudProvider(e.target.value)}
                  className="mr-2"
                />
                <span className="text-lg">{provider.toUpperCase()}</span>
              </label>
            ))}
          </div>

          {/* AWS Credentials */}
          {cloudProvider === 'aws' && (
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  AWS Access Key ID
                </label>
                <input
                  type="text"
                  value={credentials.aws.accessKey}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    aws: { ...prev.aws, accessKey: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  AWS Secret Access Key
                </label>
                <input
                  type="password"
                  value={credentials.aws.secretKey}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    aws: { ...prev.aws, secretKey: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Region
                </label>
                <input
                  type="text"
                  value={credentials.aws.region}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    aws: { ...prev.aws, region: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
            </div>
          )}

          {/* GCP Credentials */}
          {cloudProvider === 'gcp' && (
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  GCP Project ID
                </label>
                <input
                  type="text"
                  value={credentials.gcp.projectId}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    gcp: { ...prev.gcp, projectId: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Service Account Key File (JSON)
                </label>
                <textarea
                  value={credentials.gcp.keyFile}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    gcp: { ...prev.gcp, keyFile: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                  rows={4}
                />
              </div>
            </div>
          )}

          {/* Azure Credentials */}
          {cloudProvider === 'azure' && (
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Azure Storage Account Name
                </label>
                <input
                  type="text"
                  value={credentials.azure.accountName}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    azure: { ...prev.azure, accountName: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Azure Storage Account Key
                </label>
                <input
                  type="password"
                  value={credentials.azure.accountKey}
                  onChange={(e) => setCredentials(prev => ({
                    ...prev,
                    azure: { ...prev.azure, accountKey: e.target.value }
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
            </div>
          )}
        </div>

        {/* Project Details */}
        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-4">
            Project Details
          </h2>
          
          <div className="mb-4">
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={projectDetails.knownGenomeSize}
                onChange={(e) => setProjectDetails(prev => ({
                  ...prev,
                  knownGenomeSize: e.target.checked
                }))}
                className="mr-2"
              />
              <span>I know the genome size and ploidy</span>
            </label>
          </div>

          {projectDetails.knownGenomeSize && (
            <div className="space-y-4 mb-4">
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Genome Size (bp)
                </label>
                <input
                  type="number"
                  value={projectDetails.genomeSize}
                  onChange={(e) => setProjectDetails(prev => ({
                    ...prev,
                    genomeSize: e.target.value
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
              <div>
                <label className="block text-gray-700 font-medium mb-2">
                  Ploidy
                </label>
                <input
                  type="number"
                  value={projectDetails.ploidy}
                  onChange={(e) => setProjectDetails(prev => ({
                    ...prev,
                    ploidy: e.target.value
                  }))}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
            </div>
          )}

          <div className="mb-4">
            <h3 className="text-lg font-semibold mb-3">Data Types</h3>
            <div className="grid md:grid-cols-2 gap-2">
              {dataTypes.map(type => (
                <label key={type} className="flex items-center">
                  <input
                    type="checkbox"
                    checked={projectDetails.dataTypes.includes(type)}
                    onChange={() => handleDataTypeToggle(type)}
                    className="mr-2"
                  />
                  <span>{type}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <h3 className="text-lg font-semibold mb-3">S3/Storage Paths</h3>
            {projectDetails.dataTypes.map(type => (
              <div key={type} className="mb-2">
                <label className="block text-gray-700 font-medium mb-1">
                  {type} Path
                </label>
                <input
                  type="text"
                  value={s3Paths[type] || ''}
                  onChange={(e) => setS3Paths(prev => ({
                    ...prev,
                    [type]: e.target.value
                  }))}
                  placeholder={`s3://bucket/path/to/${type.toLowerCase().replace(/\s+/g, '-')}/`}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>
            ))}
          </div>

          <div>
            <h3 className="text-lg font-semibold mb-3">Analyses to Perform</h3>
            <div className="grid md:grid-cols-2 gap-2">
              {analyses.map(analysis => (
                <label key={analysis} className="flex items-center">
                  <input
                    type="checkbox"
                    checked={projectDetails.analyses.includes(analysis)}
                    onChange={() => handleAnalysisToggle(analysis)}
                    className="mr-2"
                  />
                  <span>{analysis}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <button type="submit" className="btn-primary text-lg px-8 py-3">
          Save Configuration
        </button>
      </form>
    </div>
  )
}

