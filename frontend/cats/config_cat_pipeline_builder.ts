import damatImage from '../images/damat.jpeg'
import type { CatCornerConfig } from './types'

export const configCatPipelineBuilder: CatCornerConfig = {
  title: 'Damat the Architect',
  description: 'Build the workflow visually by placing inputs, tools, checkpoints, and result blocks into a valid flow.',
  detailText: 'Connect data in a way that matches the real analysis path, use the three-dot menu on each tool block to edit or copy its settings, and save only after every branch leads to a meaningful result block.',
  mediaSrc: damatImage,
  mediaAlt: 'Pipeline builder guide cat',
}
