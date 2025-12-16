'use client'

import { useState, useEffect } from 'react'
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
  const [estimatedTime, setEstimatedTime] = useState(null)
  const [estimatedPrice, setEstimatedPrice] = useState(null)
  const [selectedAnalyses, setSelectedAnalyses] = useState([])
  const [files, setFiles] = useState([])

  // Simple estimation rules (client-side): time per file per analysis and a size factor
  const ANALYSIS_CONFIG = {
    'Read Quality (FastQC)': { timePerFile: 0.1 },
    'Genomic Property Estimation (GenomeScope2)': { timePerFile: 0.5 },
    'Assembly (Spades)': { timePerFile: 2.0 },
    'Quality Assessment for Assembly (QUAST)': { timePerFile: 0.5 },
  }
  const RATE_PER_HOUR = 5.0 // USD per hour

  const formatPrice = (p) => {
    if (p == null) return null
    const n = Number(p)
    if (!Number.isFinite(n)) return null
    return `$${n.toFixed(2)}`
  }

  const formatTime = (t) => {
    if (t == null) return null
    const n = Number(t)
    if (!Number.isFinite(n)) return null
    return `${n} hr${n !== 1 ? 's' : ''}`
  }

  const formatBytes = (bytes) => {
    if (bytes == null) return ''
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let i = 0
    let n = Number(bytes) || 0
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
    return `${Math.round(n * 10) / 10} ${units[i]}`
  }

  useEffect(() => {
    // Recompute estimates when files or analyses change
    const compute = () => {
      const fileCount = Math.max(files.length, 1) // assume at least one file if analyses selected
      const totalBytes = files.reduce((s, f) => s + (f.size || 0), 0)
      const sizeGB = totalBytes / 1e9

      let time = 0
      selectedAnalyses.forEach(a => {
        const cfg = ANALYSIS_CONFIG[a] || { timePerFile: 0.5 }
        time += cfg.timePerFile * fileCount
      })

      // Add a size factor only when a real file is present
      if (files.length > 0) {
        time += sizeGB * 2 // 2 hours per GB
      }

      // If no analyses selected and no files, clear estimates
      if (selectedAnalyses.length === 0 && files.length === 0) {
        setEstimatedTime(null)
        setEstimatedPrice(null)
        return
      }

      const timeRounded = Math.round(time * 100) / 100
      const priceRounded = Math.round(timeRounded * RATE_PER_HOUR * 100) / 100
      setEstimatedTime(timeRounded)
      setEstimatedPrice(priceRounded)
    }

    compute()
  }, [files, selectedAnalyses])

  const handleAnalysisToggle = (analysis) => {
    setSelectedAnalyses(prev =>
      prev.includes(analysis)
        ? prev.filter(a => a !== analysis)
        : [...prev, analysis]
    )
  }

  const handleFileSelect = (e) => {
    if (e.target.files) {
      const newFiles = Array.from(e.target.files)
      // Merge new files with existing, avoiding duplicates by name
      const existing = files.slice()
      const combined = [...existing, ...newFiles].reduce((acc, f) => {
        const name = f.name || String(f)
        if (!acc.some(x => x.name === name)) acc.push(f)
        return acc
      }, [])
      setFiles(combined)
    }
  }

  const removeFile = (name) => {
    setFiles(prev => prev.filter(f => f.name !== name))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    localStorage.setItem(
      'configuration',
      JSON.stringify({
        projectName,
        notes,
        estimatedTime,
        estimatedPrice,
        analyses: selectedAnalyses,
        files: files.map(f => ({ name: f.name, size: f.size || null })),
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
      notes,
      estimatedTime: estimatedTime ? Number(estimatedTime) : null,
      estimatedPrice: estimatedPrice ? Number(estimatedPrice) : null,
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
            <>
              <ul className="space-y-2">
                {files.map(file => (
                  <li key={file.name} className="p-2 bg-gray-50 rounded border border-gray-200 flex justify-between items-center">
                    <div>
                      <div className="font-medium">{file.name}</div>
                      <div className="text-sm text-gray-500">{formatBytes(file.size)}</div>
                    </div>
                    <button type="button" onClick={() => removeFile(file.name)} className="text-sm text-red-500">Remove</button>
                  </li>
                ))}
              </ul>
              <p className="text-sm text-gray-500 mt-2">Total: {files.length} file(s), {formatBytes(files.reduce((s, f) => s + (f.size || 0), 0))}</p>
            </>
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

        <div className="flex items-center gap-4">
          <div className="flex gap-4">
            <button type="submit" className="btn-primary text-lg px-8 py-3">
              Save Draft
            </button>
            <button type="button" onClick={handleSubmitJob} className="btn-secondary text-lg px-8 py-3">
              Submit Job
            </button>
          </div>

          <div className="ml-auto text-right">
            <p className="text-sm text-gray-600">
              Estimated Time: <strong>{formatTime(estimatedTime) || '—'}</strong>
            </p>
            <p className="text-sm text-gray-600">
              Estimated Price: <strong>{formatPrice(estimatedPrice) || '—'}</strong>
            </p>
          </div>
        </div>
      </form>
    </div>
  )
}

