import firuzanImage from '../images/firuzan.png'
import type { CatCornerConfig } from './types'

const jobBuilderCats: Record<number, CatCornerConfig> = {
  1: {
    title: 'Planner Cat',
    description: 'Start by naming the run and choosing whether you want a saved pipeline, manual tools, or a recommended workflow.',
    detailText: 'This step decides the overall shape of the job. Pick the pipeline or tool path that matches your analysis goal before moving on to file mapping and compute choices.',
    mediaSrc: firuzanImage,
    mediaAlt: 'Job builder planning cat',
  },
  2: {
    title: 'Input Cat',
    description: 'Add or choose files here, rename them if needed, and map each selected file to the correct tool block.',
    detailText: 'This is the file-assignment step. Make sure every required tool block has the right input file before continuing, especially paired reads, references, and annotation files.',
    mediaSrc: firuzanImage,
    mediaAlt: 'Job builder input cat',
  },
  3: {
    title: 'Resource Cat',
    description: 'Choose the VM that should run the job and adjust same-priority execution order if resources may become tight.',
    detailText: 'This step is about scheduling. Pick a VM with enough available capacity, then decide which tools at the same priority level should be favored first when they cannot all run at once.',
    mediaSrc: firuzanImage,
    mediaAlt: 'Job builder resource cat',
  },
  4: {
    title: 'Review Cat',
    description: 'Review the whole run one last time before starting it.',
    detailText: 'Check the pipeline preview, mapped inputs, VM choice, estimated runtime, and estimated cost here. If everything looks correct, submit the job and let CASSIE continue from the job details page.',
    mediaSrc: firuzanImage,
    mediaAlt: 'Job builder review cat',
  },
}

export const getCreateJobCatConfig = (level: number): CatCornerConfig => (
  jobBuilderCats[level] || jobBuilderCats[1]
)
