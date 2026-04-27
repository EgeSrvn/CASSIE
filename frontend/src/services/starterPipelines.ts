export interface StarterPipelineTemplate {
  id: string
  name: string
  description: string
  nodes: any[]
  edges: any[]
}

export const STARTER_PIPELINE_TEMPLATES: StarterPipelineTemplate[] = [
  {
    id: 'fastqc-qc',
    name: 'FastQC Quality Check',
    description: 'A simple starter pipeline to inspect read quality before downstream analysis.',
    nodes: [
      {
        id: '1',
        type: 'fastqInput',
        data: { label: 'FASTQ Input 1', description: ['One FASTQ file'] },
        position: { x: 80, y: 160 }
      },
      {
        id: '2',
        type: 'fastqInput',
        data: { label: 'FASTQ Input 2', description: ['Optional second FASTQ file'] },
        position: { x: 80, y: 280 }
      },
      {
        id: '3',
        type: 'tool',
        data: { label: 'Read Quality (FastQC)', description: ['Input: FASTQ', 'Output: QC reports'] },
        position: { x: 340, y: 160 }
      },
      {
        id: '4',
        type: 'result',
        data: { label: 'FastQC Results' },
        position: { x: 620, y: 160 }
      }
    ],
    edges: [
      { id: 'e1-3', source: '1', target: '3', type: 'smoothstep' },
      { id: 'e2-3', source: '2', target: '3', type: 'smoothstep' },
      { id: 'e3-4', source: '3', target: '4', type: 'smoothstep' }
    ]
  },
  {
    id: 'assembly-quast',
    name: 'Assembly and QUAST',
    description: 'Assemble paired-end reads with SPAdes and assess the resulting assembly with QUAST.',
    nodes: [
      {
        id: '1',
        type: 'fastqInput',
        data: { label: 'FASTQ Input R1', description: ['Forward reads'] },
        position: { x: 60, y: 120 }
      },
      {
        id: '2',
        type: 'fastqInput',
        data: { label: 'FASTQ Input R2', description: ['Reverse reads'] },
        position: { x: 60, y: 240 }
      },
      {
        id: '3',
        type: 'fastaInput',
        data: { label: 'Reference FASTA', description: ['Reference genome'] },
        position: { x: 60, y: 360 }
      },
      {
        id: '4',
        type: 'tool',
        data: { label: 'Assembly (Spades)', description: ['Input: paired reads', 'Output: contigs/scaffolds'] },
        position: { x: 320, y: 120 }
      },
      {
        id: '5',
        type: 'tool',
        data: { label: 'Quality Assessment for Assembly (QUAST)', description: ['Input: assembly + reference', 'Output: assembly metrics'] },
        position: { x: 650, y: 180 }
      },
      {
        id: '6',
        type: 'result',
        data: { label: 'SPAdes Results' },
        position: { x: 650, y: 40 }
      },
      {
        id: '7',
        type: 'result',
        data: { label: 'QUAST Results' },
        position: { x: 970, y: 180 }
      }
    ],
    edges: [
      { id: 'e1-4', source: '1', target: '4', type: 'smoothstep' },
      { id: 'e2-4', source: '2', target: '4', type: 'smoothstep' },
      { id: 'e3-5', source: '3', target: '5', type: 'smoothstep' },
      { id: 'e4-5', source: '4', target: '5', type: 'smoothstep' },
      { id: 'e4-6', source: '4', target: '6', type: 'smoothstep' },
      { id: 'e5-7', source: '5', target: '7', type: 'smoothstep' }
    ]
  },
  {
    id: 'qc-assembly-quast',
    name: 'QC to Assembly Report',
    description: 'Run read QC, assemble reads, then generate a final assembly quality report.',
    nodes: [
      {
        id: '1',
        type: 'fastqInput',
        data: { label: 'FASTQ Input R1', description: ['Forward reads'] },
        position: { x: 60, y: 100 }
      },
      {
        id: '2',
        type: 'fastqInput',
        data: { label: 'FASTQ Input R2', description: ['Reverse reads'] },
        position: { x: 60, y: 240 }
      },
      {
        id: '3',
        type: 'fastaInput',
        data: { label: 'Reference FASTA', description: ['Reference genome'] },
        position: { x: 60, y: 380 }
      },
      {
        id: '4',
        type: 'tool',
        data: { label: 'Read Quality (FastQC)', description: ['Input: FASTQ', 'Output: QC reports'] },
        position: { x: 300, y: 60 }
      },
      {
        id: '5',
        type: 'tool',
        data: { label: 'Assembly (Spades)', description: ['Input: paired reads', 'Output: contigs/scaffolds'] },
        position: { x: 320, y: 240 }
      },
      {
        id: '6',
        type: 'tool',
        data: { label: 'Quality Assessment for Assembly (QUAST)', description: ['Input: assembly + reference', 'Output: assembly metrics'] },
        position: { x: 620, y: 180 }
      },
      {
        id: '7',
        type: 'result',
        data: { label: 'FastQC Results' },
        position: { x: 620, y: 40 }
      },
      {
        id: '8',
        type: 'result',
        data: { label: 'SPAdes Results' },
        position: { x: 620, y: 300 }
      },
      {
        id: '9',
        type: 'result',
        data: { label: 'QUAST Results' },
        position: { x: 920, y: 180 }
      }
    ],
    edges: [
      { id: 'e1-4', source: '1', target: '4', type: 'smoothstep' },
      { id: 'e2-4', source: '2', target: '4', type: 'smoothstep' },
      { id: 'e1-5', source: '1', target: '5', type: 'smoothstep' },
      { id: 'e2-5', source: '2', target: '5', type: 'smoothstep' },
      { id: 'e3-6', source: '3', target: '6', type: 'smoothstep' },
      { id: 'e4-7', source: '4', target: '7', type: 'smoothstep' },
      { id: 'e5-6', source: '5', target: '6', type: 'smoothstep' },
      { id: 'e5-8', source: '5', target: '8', type: 'smoothstep' },
      { id: 'e6-9', source: '6', target: '9', type: 'smoothstep' }
    ]
  },
  {
    id: 'cat-hal-annotation',
    name: 'CAT from HAL',
    description: 'Run Comparative Annotation Toolkit from a HAL alignment, reference annotation, and reference genome name text file.',
    nodes: [
      {
        id: '1',
        type: 'input',
        data: { label: 'HAL Alignment Input', description: ['Whole-genome HAL alignment', 'Used by CAT'] },
        position: { x: 60, y: 120 }
      },
      {
        id: '2',
        type: 'input',
        data: { label: 'Reference Annotation Input', description: ['Reference annotation in GFF3 or GTF', 'Used by CAT'] },
        position: { x: 60, y: 240 }
      },
      {
        id: '3',
        type: 'input',
        data: { label: 'Reference Genome Name Input', description: ['Plain text file containing the HAL reference genome name', 'Used by CAT'] },
        position: { x: 60, y: 360 }
      },
      {
        id: '4',
        type: 'tool',
        data: { label: 'Comparative Annotation Toolkit (CAT)', description: ['Input: HAL alignment + reference annotation + reference genome name', 'Output: comparative annotations'] },
        position: { x: 370, y: 220 }
      },
      {
        id: '5',
        type: 'result',
        data: { label: 'CAT Results' },
        position: { x: 700, y: 220 }
      }
    ],
    edges: [
      { id: 'e1-4', source: '1', target: '4', type: 'smoothstep' },
      { id: 'e2-4', source: '2', target: '4', type: 'smoothstep' },
      { id: 'e3-4', source: '3', target: '4', type: 'smoothstep' },
      { id: 'e4-5', source: '4', target: '5', type: 'smoothstep' }
    ]
  },
  {
    id: 'merqury-evaluation',
    name: 'Merqury Evaluation',
    description: 'Evaluate an assembly with Merqury using an assembly FASTA and a read-derived Meryl database archive.',
    nodes: [
      {
        id: '1',
        type: 'fastaInput',
        data: { label: 'Assembly FASTA', description: ['Assembly or genome FASTA', 'Used by Merqury'] },
        position: { x: 60, y: 160 }
      },
      {
        id: '2',
        type: 'input',
        data: { label: 'Meryl Archive Input', description: ['Upload a .meryl.tar.gz or .meryl.tgz archive', 'Used by Merqury'] },
        position: { x: 60, y: 300 }
      },
      {
        id: '3',
        type: 'tool',
        data: { label: 'Assembly k-mer Evaluation (Merqury)', description: ['Input: assembly FASTA + Meryl archive', 'Output: k-mer completeness and QV reports'] },
        position: { x: 360, y: 220 }
      },
      {
        id: '4',
        type: 'result',
        data: { label: 'Merqury Results' },
        position: { x: 700, y: 220 }
      }
    ],
    edges: [
      { id: 'e1-3', source: '1', target: '3', type: 'smoothstep' },
      { id: 'e2-3', source: '2', target: '3', type: 'smoothstep' },
      { id: 'e3-4', source: '3', target: '4', type: 'smoothstep' }
    ]
  }
]
