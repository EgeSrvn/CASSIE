'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

const analyses = [
  'Read Quality (FastQC)',
  'Genomic Property Estimation (GenomeScope2)',
  'Assembly (Spades)',
  'Quality Assessment for Assembly (QUAST)',
]

export default function Configure() {
  const router = useRouter()
  const [projectName, setProjectName] = useState('')
  const [notes, setNotes] = useState('')
  const [selectedAnalyses, setSelectedAnalyses] = useState([])
  const [files, setFiles] = useState([])

  const handleAnalysisToggle = (analysis) => {
    setSelectedAnalyses(prev =>
      prev.includes(analysis)
        ? prev.filter(a => a !== analysis)
        : [...prev, analysis]
    )
  }

  const handleFileSelect = (e) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files))
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    localStorage.setItem(
      'configuration',
      JSON.stringify({
        projectName,
        notes,
        analyses: selectedAnalyses,
        files: files.map(f => f.name),
      })
    )
    alert('Configuration captured locally for this template app.')
  }

  const handleSubmitJob = (e) => {
    e.preventDefault()
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    if (!user) {
      alert('You must be logged in to submit a job')
      router.push('/login')
      return
    }

    const jobsObj = JSON.parse(localStorage.getItem('jobs') || '{}')
    const owner = user.email
    const userJobs = jobsObj[owner] || []
    const newJob = {
      id: Date.now().toString(),
      name: projectName || `Job ${userJobs.length + 1}`,
      pipeline: projectName,
      analyses: selectedAnalyses,
      files: files.map(f => f.name),
      createdAt: new Date().toISOString(),
      status: 'pending',
      owner,
    }
    jobsObj[owner] = [...userJobs, newJob]
    localStorage.setItem('jobs', JSON.stringify(jobsObj))
    router.push('/jobs')
  }

  return (
    <div className="container mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-primary-blue mb-8">
        Project Configuration
      </h1>

      <form onSubmit={handleSubmit} className="space-y-8">
        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-4">
            Project Basics
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-gray-700 font-medium mb-2">
                Project Name
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                placeholder="e.g., Atlantic salmon assembly"
                required
              />
            </div>
            <div>
              <label className="block text-gray-700 font-medium mb-2">
                Notes
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                rows={4}
                placeholder="Add reminders or run parameters"
              />
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-4">
            Upload Data
          </h2>
          <p className="text-gray-600 mb-4">
            Accepted formats: FASTQ (.fastq, .fq), BAM/CRAM (.bam, .cram), FASTA (.fasta, .fa).
          </p>
          <label className="cursor-pointer btn-primary inline-block mb-4">
            <input
              type="file"
              accept=".fastq,.fq,.bam,.cram,.fasta,.fa"
              multiple
              className="hidden"
              onChange={handleFileSelect}
            />
            Select Files
          </label>
          {files.length > 0 && (
            <ul className="space-y-2">
              {files.map(file => (
                <li key={file.name} className="p-2 bg-gray-50 rounded border border-gray-200">
                  {file.name}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-4">
            Analyses
          </h2>
          <div className="grid md:grid-cols-2 gap-3">
            {analyses.map(analysis => (
              <label key={analysis} className="flex items-center">
                <input
                  type="checkbox"
                  checked={selectedAnalyses.includes(analysis)}
                  onChange={() => handleAnalysisToggle(analysis)}
                  className="mr-3"
                />
                <span>{analysis}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="flex gap-4">
          <button type="submit" className="btn-primary text-lg px-8 py-3">
            Save Draft
          </button>
          <button type="button" onClick={handleSubmitJob} className="btn-secondary text-lg px-8 py-3">
            Submit Job
          </button>
        </div>
      </form>
    </div>
  )
}

