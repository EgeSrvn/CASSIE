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
        type: 'inputNode',
        data: { label: 'Input Data', description: ['FASTQ reads'] },
        position: { x: 80, y: 160 }
      },
      {
        id: '2',
        type: 'tool',
        data: { label: 'Read Quality (FastQC)', description: ['Input: FASTQ/FASTA', 'Output: QC reports'] },
        position: { x: 340, y: 160 }
      },
      {
        id: '3',
        type: 'end',
        data: { label: 'Results' },
        position: { x: 620, y: 160 }
      }
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2', type: 'smoothstep' },
      { id: 'e2-3', source: '2', target: '3', type: 'smoothstep' }
    ]
  },
  {
    id: 'assembly-quast',
    name: 'Assembly and QUAST',
    description: 'Assemble paired-end reads with SPAdes and assess the resulting assembly with QUAST.',
    nodes: [
      {
        id: '1',
        type: 'inputNode',
        data: { label: 'Input Data', description: ['Paired FASTQ reads', 'Reference FASTA'] },
        position: { x: 60, y: 180 }
      },
      {
        id: '2',
        type: 'tool',
        data: { label: 'Assembly (Spades)', description: ['Input: paired reads', 'Output: contigs/scaffolds'] },
        position: { x: 320, y: 120 }
      },
      {
        id: '3',
        type: 'tool',
        data: { label: 'Quality Assessment for Assembly (QUAST)', description: ['Input: assembly + reference', 'Output: assembly metrics'] },
        position: { x: 620, y: 120 }
      },
      {
        id: '4',
        type: 'end',
        data: { label: 'Results' },
        position: { x: 920, y: 120 }
      }
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2', type: 'smoothstep' },
      { id: 'e2-3', source: '2', target: '3', type: 'smoothstep' },
      { id: 'e3-4', source: '3', target: '4', type: 'smoothstep' }
    ]
  },
  {
    id: 'qc-assembly-quast',
    name: 'QC to Assembly Report',
    description: 'Run read QC, assemble reads, then generate a final assembly quality report.',
    nodes: [
      {
        id: '1',
        type: 'inputNode',
        data: { label: 'Input Data', description: ['Paired FASTQ reads', 'Reference FASTA'] },
        position: { x: 60, y: 180 }
      },
      {
        id: '2',
        type: 'tool',
        data: { label: 'Read Quality (FastQC)', description: ['Input: FASTQ/FASTA', 'Output: QC reports'] },
        position: { x: 300, y: 60 }
      },
      {
        id: '3',
        type: 'tool',
        data: { label: 'Assembly (Spades)', description: ['Input: paired reads', 'Output: contigs/scaffolds'] },
        position: { x: 320, y: 240 }
      },
      {
        id: '4',
        type: 'tool',
        data: { label: 'Quality Assessment for Assembly (QUAST)', description: ['Input: assembly + reference', 'Output: assembly metrics'] },
        position: { x: 620, y: 180 }
      },
      {
        id: '5',
        type: 'end',
        data: { label: 'Results' },
        position: { x: 920, y: 180 }
      }
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2', type: 'smoothstep' },
      { id: 'e1-3', source: '1', target: '3', type: 'smoothstep' },
      { id: 'e3-4', source: '3', target: '4', type: 'smoothstep' },
      { id: 'e4-5', source: '4', target: '5', type: 'smoothstep' }
    ]
  }
]
