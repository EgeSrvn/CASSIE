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
    description: 'Ways to reach the CASSIE team for platform support, onboarding help, and research collaboration.',
    sections: [
      {
        heading: 'General Support',
        body: [
          'For account, upload, pipeline, or job questions, contact the platform support desk during business hours. Include your job name, pipeline name, and a short description of what happened so the team can reproduce the issue quickly.',
          'A normal support request can cover login trouble, stalled uploads, failed runs, missing outputs, and questions about how to configure a workflow for a specific dataset.',
        ],
      },
      {
        heading: 'Research Collaboration',
        body: [
          'Collaboration requests are welcome for method evaluation, pipeline benchmarking, and teaching use cases. When reaching out, share your organism, sequencing data type, expected scale, and whether the work is exploratory, production, or educational.',
          'If your team needs a repeatable workflow for a lab or course, CASSIE can support saved pipelines, curated starter templates, and shared community examples.',
        ],
      },
      {
        heading: 'What To Include',
        body: [
          'The fastest support requests usually include the job ID, a screenshot of the page where the issue appeared, and a short note describing what you expected to happen instead.',
          'If the problem involves the forum or community area, include the post or pipeline title so moderators can find it quickly.',
        ],
      },
    ],
  },
  about: {
    title: 'About',
    description: 'An overview of what CASSIE is designed for and how the platform brings pipelines, jobs, and collaboration together.',
    sections: [
      {
        heading: 'Mission',
        body: [
          'CASSIE is a genomics workflow platform built to help researchers move from raw files to repeatable analyses without juggling disconnected tools, ad hoc scripts, and scattered execution environments.',
          'The platform is designed for students, researchers, and teams who need a guided way to build pipelines, launch jobs, compare results, and share useful workflow patterns with others.',
        ],
      },
      {
        heading: 'Platform Scope',
        body: [
          'CASSIE combines drag-and-drop pipeline design, step-by-step job configuration, shared community pipelines, discussion forums, and execution tracking in a single workspace.',
          'Instead of treating pipelines as static definitions, the platform keeps them connected to job inputs, compute selection, runtime estimates, outputs, and community feedback.',
        ],
      },
      {
        heading: 'Typical Workflows',
        body: [
          'Common use cases include read quality control, assembly, annotation transfer, and assembly evaluation. Pipelines can be built manually from supported tools or reused from saved and community-shared templates.',
          'The goal is to make routine analysis more reproducible while keeping enough flexibility for advanced users to tune stages, rename blocks, and document what each run was meant to do.',
        ],
      },
    ],
  },
  help: {
    title: 'Help',
    description: 'Practical guidance for common platform questions, troubleshooting steps, and first-line support.',
    sections: [
      {
        heading: 'Getting Unblocked',
        body: [
          'If a job does not start, first confirm that every required input block has at least one selected file, that a VM has been chosen, and that the review stage shows the expected pipeline before submission.',
          'If uploads appear complete but inputs are still missing, refresh the page and confirm that the selected files are attached to the correct input block rather than just present in the data library.',
        ],
      },
      {
        heading: 'Common Topics',
        body: [
          'For login or verification issues, check whether the account was registered with the correct email and whether the verification link has already expired. For community or forum issues, try reloading the page before reposting content.',
          'When a pipeline preview looks wrong, compare the renamed block labels, stage order, and result blocks in the builder with the review visualization to confirm the saved graph still matches the intended workflow.',
        ],
      },
      {
        heading: 'Where To Look Next',
        body: [
          'Use the tutorial page for a full guided walkthrough, the forum for workflow questions from other users, and the job details page when you need execution history, required inputs, or downloadable outputs.',
          'If a problem seems platform-wide rather than job-specific, contact support with the approximate time, the page involved, and any visible error text.',
        ],
      },
    ],
  },
  tutorial: {
    title: 'Tutorial',
    description: 'A guided walkthrough for new users learning the typical CASSIE workflow from account setup to results review.',
    sections: [
      {
        heading: 'Start Here',
        body: [
          'Begin by creating an account, verifying your email, and signing in. From there, upload a small set of test data or select existing files from the data library so you can see how input assignment works before running a larger job.',
          'Next, choose whether to configure a job manually from tools or start from a saved pipeline. Manual mode is useful for learning stage order, while saved pipelines are faster once your workflow is stable.',
        ],
      },
      {
        heading: 'Suggested Walkthroughs',
        body: [
          'A simple first exercise is to open the pipeline builder, add one input block, one or two tool blocks, and a result block, then rename each block so the review page is easy to interpret later.',
          'After that, create a job from the saved pipeline, select files explicitly for each input block, choose a VM, inspect the backend-generated review visualization, and submit the run.',
        ],
      },
      {
        heading: 'After Submission',
        body: [
          'Use the job details page to follow execution tracking, input requirements, and output availability. Once the run finishes, compare the result names with the pipeline result blocks to verify that your naming scheme is working as expected.',
          'When you discover a pipeline that works well, publish it to the community area, add context in the description, and join the forum if you want feedback or want to share why a particular configuration was successful.',
        ],
      },
    ],
  },
}
