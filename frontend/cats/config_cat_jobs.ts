import latteImage from '../images/latte.jpeg'
import type { CatCornerConfig } from './types'

export const configCatJobs: CatCornerConfig = {
  title: 'Latte the Tracker',
  description: 'This page helps you follow each run from queued state to outputs, logs, and final status.',
  detailText: 'Open a job to review its pipeline, watch execution tracking, inspect live stage progress, and download outputs or logs after each tool finishes.',
  mediaSrc: latteImage,
  mediaAlt: 'CASSIE cat mascot',
}
