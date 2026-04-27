export interface StaticPageContent {
  title: string
  description: string
  sections: Array<{
    heading: string
    body: string[]
  }>
}

export const STATIC_PAGES: Record<string, StaticPageContent> = {
  about: {
    title: 'About',
    description: '',
    sections: [
      {
        heading: 'About',
        body: [
          'CASSIE is a genomics workflow platform built to help researchers move from raw files to repeatable analyses without juggling disconnected tools, ad hoc scripts, and scattered execution environments.',
          'The platform combines drag-and-drop pipeline design, step-by-step job configuration, community-shared workflows, discussion spaces, and execution tracking in one workspace.',
          'Common use cases include read quality control, assembly, annotation transfer, and assembly evaluation, with enough flexibility for advanced users to tune tool settings, rename blocks, and shape reusable workflows.',
        ],
      },
      {
        heading: 'Contact',
        body: [
          'For account, upload, pipeline, or job questions, contact platform support with the job ID, the page involved, and a short description of what happened so the issue can be reproduced quickly.',
          'Collaboration requests are welcome for benchmarking, teaching use cases, and workflow evaluation. Include your organism, sequencing data type, and expected project scale when reaching out.',
        ],
      },
    ],
  },
  faq: {
    title: 'FAQ',
    description: '',
    sections: [
      {
        heading: 'How do I get a job to start correctly?',
        body: [
          'Make sure every required input block has at least one selected file, that a VM has been chosen, and that the review stage shows the expected pipeline before submission.',
          'If uploads appear complete but inputs are still missing, refresh the page and confirm that the selected files are attached to the correct tool or pipeline block rather than only sitting in the storage library.',
        ],
      },
      {
        heading: 'What should I check if a pipeline preview looks wrong?',
        body: [
          'Compare the renamed block labels, stage order, and result blocks in the builder with the review visualization to confirm the saved graph still matches the workflow you intended to run.',
          'If a saved pipeline was edited earlier, reopen it in the builder and verify that each input, tool, checkpoint, and result block is still connected in the way you expect.',
        ],
      },
      {
        heading: 'Where should I look when something fails?',
        body: [
          'Use the job details page for execution tracking, live stage status, logs, required inputs, and output availability. That page should be the first stop for run-specific problems.',
          'If the issue looks platform-wide rather than job-specific, gather the visible error text, the affected page, and the approximate time, then contact support with that information.',
        ],
      },
    ],
  },
}
