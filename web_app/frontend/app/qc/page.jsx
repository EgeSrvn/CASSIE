'use client'

import { useSearchParams } from 'next/navigation'
import Link from 'next/link'

export default function QCPage() {
  const params = useSearchParams()
  const rawReport = params.get('report')
  const report = rawReport ? decodeURIComponent(rawReport) : null
  const rawFolder = params.get('folder')
  const folder = rawFolder ? decodeURIComponent(rawFolder).replace(/\/+$/, '') : null
  // Always build an absolute public URL (Next.js serves from /public)
  const basePath = folder ? `/${folder.replace(/^\/+/, '')}` : null

  // Known FastQC SVG outputs we expect in the provided folder
  const fastqcSvgs = basePath
    ? [
        { file: 'per_sequence_gc_content.svg', label: 'Per-sequence GC Content' },
        { file: 'duplication_levels.svg', label: 'Duplication Levels' },
        { file: 'per_sequence_quality.svg', label: 'Per-sequence Quality Scores' },
        { file: 'per_base_n_content.svg', label: 'Per-base N Content' },
        { file: 'per_tile_quality.svg', label: 'Per-tile Quality Scores' },
        { file: 'per_base_quality.svg', label: 'Per-base Quality Scores' },
        { file: 'sequence_length_distribution.svg', label: 'Sequence Length Distribution' },
        { file: 'per_base_sequence_content.svg', label: 'Per-base Sequence Content' },
      ]
    : []

  // If a folder is provided, render a structured FastQC summary from SVGs
  if (basePath) {
    const firstPlot = fastqcSvgs[0]?.file
    const firstPlotHref = firstPlot ? `${basePath}/${firstPlot}` : null
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Quality Control Summary</h1>
          <div className="flex gap-2">
            <Link href="/jobs" className="btn-ghost">
              Back to Jobs
            </Link>
          </div>
        </div>

        <p className="text-gray-600 mb-6">
        </p>

        <div className="grid gap-6 md:grid-cols-2">
          {fastqcSvgs.map(({ file, label }) => {
            const imgSrc = `${basePath}/${file}`
            return (
            <div key={file} className="card">
              <h2 className="text-lg font-semibold text-primary-blue mb-3">{label}</h2>
              <div className="border border-gray-200 rounded bg-white overflow-hidden">
                <img
                  src={imgSrc}
                  alt={label}
                  className="w-full h-auto"
                />
              </div>
              <p className="mt-2 text-xs text-gray-500 break-all">
                Source: {imgSrc}
              </p>
            </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (!report) {
    return (
      <div className="container mx-auto px-4 py-12">
        <h1 className="text-2xl font-bold mb-4">Quality Control Viewer</h1>
        <p className="text-gray-600">No report specified. Pass a <code>?report=/path/to/report.html</code> query parameter.</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Quality Control Viewer</h1>
        <div className="flex gap-2">
          <a href={report} target="_blank" rel="noopener" className="btn-secondary">Open raw report</a>
          <Link href="/community" className="btn-ghost">Back to Community</Link>
        </div>
      </div>
      <div style={{ height: '80vh', border: '1px solid #e5e7eb' }}>
        <iframe src={report} width="100%" height="100%" title="QC Report" frameBorder="0" />
      </div>
    </div>
  )
}
