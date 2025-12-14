'use client'

import { useState } from 'react'
import axios from 'axios'

export default function Upload() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({})

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files))
    }
  }

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return

    setUploading(true)
    const token = localStorage.getItem('token')

    for (const file of selectedFiles) {
      try {
        // Get presigned URL
        const { data } = await axios.post(
          `${process.env.NEXT_PUBLIC_API_URL}/api/upload/presigned-url`,
          { filename: file.name, contentType: file.type },
          { headers: { Authorization: `Bearer ${token}` } }
        )

        // Upload to S3
        await axios.put(data.url, file, {
          headers: { 'Content-Type': file.type },
          onUploadProgress: (progressEvent) => {
            const percent = progressEvent.total
              ? Math.round((progressEvent.loaded * 100) / progressEvent.total)
              : 0
            setUploadProgress(prev => ({ ...prev, [file.name]: percent }))
          }
        })

        // Notify backend
        await axios.post(
          `${process.env.NEXT_PUBLIC_API_URL}/api/upload/complete`,
          { filename: file.name, s3Key: data.key },
          { headers: { Authorization: `Bearer ${token}` } }
        )
      } catch (error) {
        console.error(`Failed to upload ${file.name}:`, error)
      }
    }

    setUploading(false)
    setSelectedFiles([])
    setUploadProgress({})
    alert('Upload complete!')
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-primary-blue mb-8">
        Upload Genomic Data
      </h1>

      <div className="card max-w-3xl">
        <h2 className="text-2xl font-semibold text-primary-blue mb-4">
          Supported Formats
        </h2>
        <ul className="list-disc list-inside text-gray-700 mb-6 space-y-1">
          <li>Illumina / MGI (FASTQ)</li>
          <li>PacBio CLR / CCS / HiFi (FASTQ, BAM)</li>
          <li>Oxford Nanopore (FASTQ, FAST5)</li>
          <li>BioNano (CMAP, BNX)</li>
          <li>StrandSeq (BAM)</li>
          <li>HiC (FASTQ, Pairs)</li>
          <li>Linked reads (10x, UST) (FASTQ)</li>
          <li>RNAseq (FASTQ)</li>
        </ul>

        <div className="border-2 border-dashed border-primary-blue rounded-lg p-8 text-center mb-6">
          <input
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            id="file-input"
            accept=".fastq,.fq,.fastq.gz,.fq.gz,.bam,.bam.bai,.cmap,.bnx,.fast5,.pairs"
          />
          <label
            htmlFor="file-input"
            className="cursor-pointer btn-primary inline-block"
          >
            Select Files
          </label>
          {selectedFiles.length > 0 && (
            <p className="mt-4 text-gray-600">
              {selectedFiles.length} file(s) selected
            </p>
          )}
        </div>

        {selectedFiles.length > 0 && (
          <div className="mb-6">
            <h3 className="text-lg font-semibold mb-3">Selected Files</h3>
            <ul className="space-y-2">
              {selectedFiles.map((file, idx) => (
                <li key={idx} className="flex items-center justify-between p-3 bg-gray-50 rounded">
                  <span className="text-gray-700">{file.name}</span>
                  <span className="text-sm text-gray-500">
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                    {uploadProgress[file.name] !== undefined && (
                      <span className="ml-2">
                        ({uploadProgress[file.name]}%)
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={selectedFiles.length === 0 || uploading}
          className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {uploading ? 'Uploading...' : 'Upload to Cloud Storage'}
        </button>

        <div className="mt-6 p-4 bg-blue-50 rounded-lg">
          <p className="text-sm text-gray-600">
            <strong>Note:</strong> Files will be uploaded to your configured cloud storage
            (S3/GCS/Azure Blob). Large files may take some time to upload.
          </p>
        </div>
      </div>
    </div>
  )
}

