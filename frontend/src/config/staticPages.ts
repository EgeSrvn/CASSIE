export interface StaticPageContent {
  title: string
  description: string
  sections: Array<{
    heading: string
    body: string[]
  }>
}

export const STATIC_PAGES: Record<string, StaticPageContent> = {
  contact: {
    title: 'Contact',
    description: 'How to reach the CASSIE team for support, questions, and collaboration.',
    sections: [
      {
        heading: 'General Support',
        body: [
          'Use this page for your primary support email address, help desk link, or contact form.',
          'You can also list expected response times here so users know what to expect.',
        ],
      },
      {
        heading: 'Research Collaboration',
        body: [
          'If CASSIE is part of a lab or research initiative, this section is a good place for collaboration inquiries.',
        ],
      },
    ],
  },
  about: {
    title: 'About',
    description: 'Overview of what CASSIE is for and the kind of genomics workflows it supports.',
    sections: [
      {
        heading: 'Mission',
        body: [
          'Describe why CASSIE exists, the problems it helps solve, and the users it is designed for.',
        ],
      },
      {
        heading: 'Platform Scope',
        body: [
          'This section can summarize jobs, pipelines, community sharing, and forum collaboration in one place.',
        ],
      },
    ],
  },
  help: {
    title: 'Help',
    description: 'Quick support guidance for common questions, platform issues, and onboarding steps.',
    sections: [
      {
        heading: 'Getting Unblocked',
        body: [
          'Add answers for account issues, upload problems, pipeline questions, and job troubleshooting here.',
        ],
      },
      {
        heading: 'Common Topics',
        body: [
          'This is a good place for short FAQ items or links to richer documentation and tutorials.',
        ],
      },
    ],
  },
  tutorial: {
    title: 'Tutorial',
    description: 'Step-by-step onboarding content for new users learning the CASSIE workflow.',
    sections: [
      {
        heading: 'Start Here',
        body: [
          'Outline the recommended first journey: register, verify email, upload data, build a pipeline, and launch a job.',
        ],
      },
      {
        heading: 'Suggested Walkthroughs',
        body: [
          'You can expand this page with guided examples for forum usage, community pipelines, and result downloads.',
        ],
      },
    ],
  },
}
