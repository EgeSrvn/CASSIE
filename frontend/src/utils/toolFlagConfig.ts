import type { EditableFlagDefinition, ToolRequirement } from '../services/toolService'

export type FlagValue = string | number | boolean

const buildExternalRequirement = (
  type: string,
  label: string,
  formats: string[],
  overrides: Partial<ToolRequirement> = {}
): ToolRequirement => ({
  type,
  label,
  formats,
  is_intermediate: false,
  available_sources: ['external'],
  default_source: 'external',
  ...overrides,
})

export const buildDefaultFlagValues = (flagDefinitions: EditableFlagDefinition[]) =>
  flagDefinitions.reduce<Record<string, FlagValue>>((acc, flag) => {
    if (!flag.key) {
      return acc
    }
    acc[flag.key] = (flag.default as FlagValue) ?? (flag.type === 'boolean' ? false : '')
    return acc
  }, {})

export const normalizeDraftFlagValues = (
  flagDefinitions: EditableFlagDefinition[],
  draftValues: Record<string, FlagValue>
) => {
  const normalized = buildDefaultFlagValues(flagDefinitions)
  const errors: Record<string, string> = {}

  flagDefinitions.forEach((flag) => {
    const raw = draftValues[flag.key] ?? normalized[flag.key]

    try {
      if (flag.type === 'boolean') {
        normalized[flag.key] = Boolean(raw)
        return
      }

      const stringValue = String(raw ?? '').trim()
      const effectiveString = stringValue === '' ? String(flag.default ?? '') : stringValue

      if (flag.type === 'integer') {
        if (effectiveString === '') {
          normalized[flag.key] = Number(flag.default ?? 0)
          return
        }
        const parsed = Number.parseInt(effectiveString, 10)
        if (Number.isNaN(parsed)) {
          throw new Error('Enter a whole number.')
        }
        if (typeof flag.min === 'number' && parsed < flag.min) {
          throw new Error(`Enter a value of at least ${flag.min}.`)
        }
        if (typeof flag.max === 'number' && parsed > flag.max) {
          throw new Error(`Enter a value of at most ${flag.max}.`)
        }
        normalized[flag.key] = parsed
        return
      }

      if (flag.type === 'number') {
        if (effectiveString === '') {
          normalized[flag.key] = Number(flag.default ?? 0)
          return
        }
        const parsed = Number.parseFloat(effectiveString)
        if (Number.isNaN(parsed)) {
          throw new Error('Enter a numeric value.')
        }
        if (typeof flag.min === 'number' && parsed < flag.min) {
          throw new Error(`Enter a value of at least ${flag.min}.`)
        }
        if (typeof flag.max === 'number' && parsed > flag.max) {
          throw new Error(`Enter a value of at most ${flag.max}.`)
        }
        normalized[flag.key] = parsed
        return
      }

      if (flag.type === 'select') {
        const options = new Set((flag.options || []).map((option) => option.value))
        if (options.size > 0 && !options.has(effectiveString)) {
          throw new Error('Choose one of the available options.')
        }
        normalized[flag.key] = effectiveString
        return
      }

      if (flag.pattern && effectiveString) {
        const regex = new RegExp(flag.pattern)
        if (!regex.test(effectiveString)) {
          throw new Error(flag.error_message || 'Invalid value.')
        }
      }
      normalized[flag.key] = effectiveString
    } catch (error) {
      errors[flag.key] = error instanceof Error ? error.message : 'Invalid value.'
    }
  })

  return { normalized, errors }
}

export const hasCustomizedFlagValues = (
  flagDefinitions: EditableFlagDefinition[],
  flagValues?: Record<string, FlagValue>
) => {
  const defaults = buildDefaultFlagValues(flagDefinitions)
  return flagDefinitions.some((flag) => {
    const currentValue = flagValues?.[flag.key] ?? defaults[flag.key]
    return String(currentValue) !== String(defaults[flag.key])
  })
}

export const resolveToolRequirementsForFlags = (
  toolId: string,
  baseRequirements: ToolRequirement[],
  flagValues?: Record<string, FlagValue>
): ToolRequirement[] => {
  const normalizedToolId = String(toolId || '').trim().toUpperCase()
  const requirementsByType = new Map(
    baseRequirements.map((requirement) => [String(requirement.type || '').trim().toLowerCase(), requirement])
  )
  const getExistingRequirement = (type: string): ToolRequirement | undefined => (
    requirementsByType.get(type.trim().toLowerCase())
  )
  const cloneRequirement = (
    type: string,
    label: string,
    formats: string[],
    overrides: Partial<ToolRequirement> = {}
  ): ToolRequirement => {
    const existing = getExistingRequirement(type)
    if (existing) {
      return {
        ...existing,
        type,
        label,
        formats,
        ...overrides,
      }
    }
    return buildExternalRequirement(type, label, formats, overrides)
  }

  if (normalizedToolId === 'FASTQC') {
    return baseRequirements.map((requirement) => {
      if (String(requirement.type || '').trim().toLowerCase() !== 'reads') {
        return requirement
      }
      if (!Boolean(flagValues?.casava)) {
        return requirement
      }
      return {
        ...requirement,
        filename_pattern: '.+_L\\d{3}_(?:R?[12])_\\d{3}\\.(?:fastq|fq)(?:\\.gz)?$',
        filename_example: 'sample_L001_R1_001.fastq.gz',
        validation_message: 'CASAVA mode expects filenames like sample_L001_R1_001.fastq.gz.',
        input_behavior: 'casava',
      }
    })
  }

  if (normalizedToolId === 'SPADES') {
    const inputMode = String(flagValues?.input_mode || 'paired_end').trim().toLowerCase()
    const longReadSupport = String(flagValues?.long_read_support || 'none').trim().toLowerCase()
    const resolvedRequirements: ToolRequirement[] = []

    if (inputMode === 'interlaced') {
      resolvedRequirements.push(
        cloneRequirement('interlaced_reads', 'Interlaced Paired Reads', ['fastq'], { input_behavior: 'single-file' })
      )
    } else if (inputMode === 'single_end') {
      resolvedRequirements.push(
        cloneRequirement('single_reads', 'Single-End Reads', ['fastq'], { input_behavior: 'multiple' })
      )
    } else {
      resolvedRequirements.push(
        cloneRequirement('forward_reads', 'Forward Reads (R1)', ['fastq'], { input_behavior: 'paired-r1' }),
        cloneRequirement('reverse_reads', 'Reverse Reads (R2)', ['fastq'], { input_behavior: 'paired-r2' }),
      )
    }

    if (longReadSupport === 'pacbio') {
      resolvedRequirements.push(
        cloneRequirement('pacbio_reads', 'PacBio Long Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    } else if (longReadSupport === 'nanopore') {
      resolvedRequirements.push(
        cloneRequirement('nanopore_reads', 'Nanopore Long Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    }

    return resolvedRequirements
  }

  if (normalizedToolId === 'METASPADES') {
    const shortReadMode = String(flagValues?.short_read_mode || 'paired_end').trim().toLowerCase()
    const longReadSupport = String(flagValues?.long_read_support || 'none').trim().toLowerCase()
    const resolvedRequirements: ToolRequirement[] = []

    if (shortReadMode === 'interlaced') {
      resolvedRequirements.push(
        cloneRequirement('interlaced_reads', 'Interlaced Paired Reads', ['fastq'], { input_behavior: 'single-file' })
      )
    } else {
      resolvedRequirements.push(
        cloneRequirement('forward_reads', 'Forward Reads (R1)', ['fastq'], { input_behavior: 'paired-r1' }),
        cloneRequirement('reverse_reads', 'Reverse Reads (R2)', ['fastq'], { input_behavior: 'paired-r2' }),
      )
    }

    if (longReadSupport === 'pacbio') {
      resolvedRequirements.push(
        cloneRequirement('pacbio_reads', 'PacBio Long Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    } else if (longReadSupport === 'nanopore') {
      resolvedRequirements.push(
        cloneRequirement('nanopore_reads', 'Nanopore Long Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    }

    return resolvedRequirements
  }

  if (normalizedToolId === 'HIFIASM') {
    const mode = String(flagValues?.mode || 'hifi').trim().toLowerCase()

    if (mode === 'ont') {
      return [
        cloneRequirement('ont_reads', 'ONT Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' }),
      ]
    }

    const resolvedRequirements: ToolRequirement[] = [
      cloneRequirement('hifi_reads', 'HiFi Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' }),
    ]

    if (mode === 'hifi_hic') {
      resolvedRequirements.push(
        cloneRequirement('hic_forward_reads', 'Hi-C Reads (R1)', ['fastq'], { input_behavior: 'paired-r1' }),
        cloneRequirement('hic_reverse_reads', 'Hi-C Reads (R2)', ['fastq'], { input_behavior: 'paired-r2' }),
      )
    } else if (mode === 'hifi_ul') {
      resolvedRequirements.push(
        cloneRequirement('ul_reads', 'Ultra-Long ONT Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    }

    return resolvedRequirements
  }

  if (normalizedToolId === 'VERKKO') {
    const resolvedRequirements: ToolRequirement[] = [
      cloneRequirement('hifi_reads', 'HiFi Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' }),
    ]

    if (Boolean(flagValues?.include_nano)) {
      resolvedRequirements.push(
        cloneRequirement('nanopore_reads', 'Nanopore Reads', ['fastq', 'fasta'], { input_behavior: 'multiple' })
      )
    }
    if (Boolean(flagValues?.include_hic)) {
      resolvedRequirements.push(
        cloneRequirement('hic_forward_reads', 'Hi-C Reads (R1)', ['fastq'], { input_behavior: 'paired-r1' }),
        cloneRequirement('hic_reverse_reads', 'Hi-C Reads (R2)', ['fastq'], { input_behavior: 'paired-r2' }),
      )
    }
    if (Boolean(flagValues?.use_hap_kmers)) {
      resolvedRequirements.push(
        cloneRequirement('haplotype_kmers', 'Haplotype K-mer Database', ['meryl'], { input_behavior: 'single-file' })
      )
    }
    if (Boolean(flagValues?.reference_guided)) {
      resolvedRequirements.push(
        cloneRequirement('reference_genome', 'Reference Genome (FASTA)', ['fasta'], { input_behavior: 'single-file' })
      )
    }

    return resolvedRequirements
  }

  return baseRequirements
}
