import Link from 'next/link'

export default function Home() {
  return (
    <div className="container mx-auto px-4 py-12">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold text-primary-blue mb-4">
          Cassie Genomics Platform
        </h1>
        <p className="text-xl text-gray-600 max-w-2xl mx-auto">
          Comprehensive genomic data analysis with multi-cloud support
        </p>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-3">
            Upload Data
          </h2>
          <p className="text-gray-600 mb-4">
            Upload your genomic data in various formats: Illumina, PacBio, ONT, HiC, and more.
          </p>
          <Link href="/upload" className="btn-primary inline-block">
            Upload Data
          </Link>
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-3">
            Configure Pipeline
          </h2>
          <p className="text-gray-600 mb-4">
            Set up your analysis pipeline with recommended workflows or create custom ones.
          </p>
          <Link href="/configure" className="btn-primary inline-block">
            Configure
          </Link>
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-3">
            View Jobs
          </h2>
          <p className="text-gray-600 mb-4">
            Monitor active jobs and access results from completed analyses.
          </p>
          <Link href="/jobs" className="btn-primary inline-block">
            View Jobs
          </Link>
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-3">
            Community
          </h2>
          <p className="text-gray-600 mb-4">
            Browse and share Nextflow workflows with the community.
          </p>
          <Link href="/community" className="btn-primary inline-block">
            Community
          </Link>
        </div>

        <div className="card">
          <h2 className="text-2xl font-semibold text-primary-blue mb-3">
            Pipeline Builder
          </h2>
          <p className="text-gray-600 mb-4">
            Visually create and customize your analysis pipelines.
          </p>
          <Link href="/builder" className="btn-primary inline-block">
            Build Pipeline
          </Link>
        </div>
      </div>

      <div className="card max-w-4xl mx-auto">
        <h2 className="text-2xl font-semibold text-primary-blue mb-4">
          Supported Analysis Types
        </h2>
        <ul className="grid md:grid-cols-2 gap-3 text-gray-700">
          <li>• Read QC (FastQC-like)</li>
          <li>• Genome size estimation</li>
          <li>• Heterozygosity estimation</li>
          <li>• Repeat content analysis</li>
          <li>• Assembly + Scaffolding</li>
          <li>• Error correction & Gap filling</li>
          <li>• Gene annotation</li>
          <li>• RepeatMasker</li>
          <li>• Segmental duplications (SEDEF/BISER)</li>
          <li>• Completeness analysis (BUSCO)</li>
          <li>• Assembly QC (QUAST)</li>
          <li>• mrCaNaVaR analysis</li>
        </ul>
      </div>
    </div>
  )
}

