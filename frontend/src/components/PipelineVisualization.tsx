import { useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Node,
  Edge,
  Position,
  ReactFlowInstance,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  JobPipelineBlock,
  JobPipelineConnection,
  JobPipelineVisualization,
} from '../services/jobService'

const LockedPipelineNode = ({ data }: { data: any }) => (
  <div style={{ position: 'relative' }}>
    <Handle
      type="target"
      position={Position.Left}
      isConnectable={false}
      style={{ opacity: 0, width: 8, height: 8 }}
    />
    <div
      style={{
        minWidth: 220,
        maxWidth: 260,
        border: `1px solid ${data.borderColor}`,
        borderRadius: 14,
        background: data.backgroundColor,
        boxShadow: '0 10px 24px rgba(15, 23, 42, 0.08)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '0.65rem 0.85rem',
          background: data.headerColor,
          color: '#F5EEDC',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.75rem',
        }}
      >
        <div style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          {data.kindLabel}
        </div>
        <div
          style={{
            fontSize: '0.72rem',
            fontWeight: 700,
            textTransform: 'uppercase',
            padding: '0.15rem 0.45rem',
            borderRadius: 999,
            background: 'rgba(255,255,255,0.18)',
          }}
        >
          {data.statusLabel}
        </div>
      </div>
      <div style={{ padding: '0.85rem' }}>
        <div style={{ fontWeight: 700, color: '#183B4E', marginBottom: '0.4rem', lineHeight: 1.3 }}>
          {data.label}
        </div>
        {data.stageLabel && (
          <div style={{ fontSize: '0.78rem', color: '#475569', marginBottom: '0.35rem' }}>
            {data.stageLabel}
          </div>
        )}
        {data.metaLine && (
          <div style={{ fontSize: '0.8rem', color: '#334155', marginBottom: data.description ? '0.45rem' : 0 }}>
            {data.metaLine}
          </div>
        )}
        {data.description && (
          <div style={{ fontSize: '0.8rem', color: '#475569', lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
            {data.description}
          </div>
        )}
      </div>
    </div>
    <Handle
      type="source"
      position={Position.Right}
      isConnectable={false}
      style={{ opacity: 0, width: 8, height: 8 }}
    />
  </div>
)

const jobPipelineNodeTypes = {
  lockedPipelineNode: LockedPipelineNode,
}

const getPipelineBlockTone = (status: JobPipelineBlock['status']) => {
  switch (status) {
    case 'finished':
      return {
        border: '#b9c9b4',
        background: '#eef3e8',
      }
    case 'working':
      return {
        border: '#6d89ac',
        background: '#ecf1f6',
      }
    case 'failed':
      return {
        border: '#fca5a5',
        background: '#fef2f2',
      }
    default:
      return {
        border: '#d9c7a5',
        background: '#F5EEDC',
      }
  }
}

const formatPipelineBlockStatus = (status: JobPipelineBlock['status']) => {
  switch (status) {
    case 'working':
      return 'working'
    case 'finished':
      return 'finished'
    case 'failed':
      return 'failed'
    default:
      return 'waiting'
  }
}

const buildPipelineFlow = (jobPipeline: JobPipelineVisualization | null) => {
  if (!jobPipeline || jobPipeline.blocks.length === 0) {
    return { nodes: [] as Node[], edges: [] as Edge[] }
  }

  const connections = Array.isArray(jobPipeline.connections) ? jobPipeline.connections : []
  const stageTopPadding = 140
  const stageVerticalGap = 360
  const stageHorizontalGap = 520
  const inputHorizontalGap = 420
  const outputHorizontalGap = 420
  const leftPadding = 520
  const outputColumnGap = 320
  const stageCollisionGap = 260
  const ioCollisionGap = 220
  const blocksById = new Map(jobPipeline.blocks.map((block) => [block.id, block]))
  const stageBlocks = jobPipeline.blocks.filter((block) => block.column === 'stage')
  const inputBlocks = jobPipeline.blocks.filter((block) => block.column === 'input')
  const outputBlocks = jobPipeline.blocks.filter((block) => block.column === 'output')
  const stageIds = new Set(stageBlocks.map((block) => block.id))
  const dependencyConnections = connections.filter(
    (connection) =>
      connection.kind === 'dependency' &&
      stageIds.has(connection.source) &&
      stageIds.has(connection.target)
  )
  const incomingStageIds = new Map<string, string[]>()
  const outgoingStageIds = new Map<string, string[]>()
  stageBlocks.forEach((block) => {
    incomingStageIds.set(block.id, [])
    outgoingStageIds.set(block.id, [])
  })
  dependencyConnections.forEach((connection) => {
    incomingStageIds.set(connection.target, [...(incomingStageIds.get(connection.target) || []), connection.source])
    outgoingStageIds.set(connection.source, [...(outgoingStageIds.get(connection.source) || []), connection.target])
  })

  const stageOrder = [...stageBlocks]
    .sort((left, right) => {
      const leftStage = left.stage_number ?? left.row ?? Number.MAX_SAFE_INTEGER
      const rightStage = right.stage_number ?? right.row ?? Number.MAX_SAFE_INTEGER
      return leftStage - rightStage || left.label.localeCompare(right.label)
    })
    .map((block) => block.id)

  const inDegree = new Map<string, number>()
  stageOrder.forEach((stageId) => {
    inDegree.set(stageId, (incomingStageIds.get(stageId) || []).length)
  })

  const readyQueue = stageOrder.filter((stageId) => (inDegree.get(stageId) || 0) === 0)
  const topoStageIds: string[] = []
  while (readyQueue.length > 0) {
    const stageId = readyQueue.shift()!
    topoStageIds.push(stageId)
    ;(outgoingStageIds.get(stageId) || []).forEach((targetId) => {
      const nextDegree = (inDegree.get(targetId) || 0) - 1
      inDegree.set(targetId, nextDegree)
      if (nextDegree === 0) {
        readyQueue.push(targetId)
        readyQueue.sort((left, right) => stageOrder.indexOf(left) - stageOrder.indexOf(right))
      }
    })
  }
  if (topoStageIds.length < stageOrder.length) {
    stageOrder.forEach((stageId) => {
      if (!topoStageIds.includes(stageId)) {
        topoStageIds.push(stageId)
      }
    })
  }

  const stageLevelById = new Map<string, number>()
  topoStageIds.forEach((stageId) => {
    const parentLevels = (incomingStageIds.get(stageId) || []).map((sourceId) => stageLevelById.get(sourceId) || 0)
    stageLevelById.set(stageId, parentLevels.length > 0 ? Math.max(...parentLevels) + 1 : 0)
  })

  const stageXById = new Map<string, number>()
  topoStageIds.forEach((stageId) => {
    stageXById.set(stageId, leftPadding + ((stageLevelById.get(stageId) || 0) * stageHorizontalGap))
  })

  const placeColumn = (
    ids: string[],
    desiredYById: Map<string, number>,
    gap: number
  ): Map<string, number> => {
    const sortedIds = [...ids].sort((left, right) => {
      const leftDesired = desiredYById.get(left) ?? stageTopPadding
      const rightDesired = desiredYById.get(right) ?? stageTopPadding
      const leftBlock = blocksById.get(left)
      const rightBlock = blocksById.get(right)
      const leftStage = leftBlock?.stage_number ?? leftBlock?.row ?? Number.MAX_SAFE_INTEGER
      const rightStage = rightBlock?.stage_number ?? rightBlock?.row ?? Number.MAX_SAFE_INTEGER
      return leftDesired - rightDesired || leftStage - rightStage || left.localeCompare(right)
    })

    const positionById = new Map<string, number>()
    let currentY = stageTopPadding - gap
    sortedIds.forEach((id) => {
      const desiredY = desiredYById.get(id) ?? stageTopPadding
      const y = Math.max(desiredY, currentY + gap)
      positionById.set(id, y)
      currentY = y
    })
    return positionById
  }

  const globallySeparateNodes = (
    positions: Map<string, { x: number; y: number }>,
    gapFor: (id: string) => number
  ) => {
    const nodes = Array.from(positions.entries())
    for (let iteration = 0; iteration < 6; iteration += 1) {
      let changed = false
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const [leftId, leftPos] = nodes[i]
          const [rightId, rightPos] = nodes[j]
          const dx = Math.abs(leftPos.x - rightPos.x)
          const minHorizontalClearance = 300
          if (dx > minHorizontalClearance) {
            continue
          }

          const requiredGap = Math.max(gapFor(leftId), gapFor(rightId))
          const dy = Math.abs(leftPos.y - rightPos.y)
          if (dy >= requiredGap) {
            continue
          }

          const push = (requiredGap - dy) / 2 + 8
          if (leftPos.y <= rightPos.y) {
            leftPos.y -= push
            rightPos.y += push
          } else {
            leftPos.y += push
            rightPos.y -= push
          }
          changed = true
        }
      }
      if (!changed) {
        break
      }
    }
  }

  const stageYById = new Map<string, number>()
  const stageLevels = [...new Set(topoStageIds.map((stageId) => stageLevelById.get(stageId) || 0))].sort((a, b) => a - b)
  stageLevels.forEach((level) => {
    const idsAtLevel = topoStageIds.filter((stageId) => (stageLevelById.get(stageId) || 0) === level)
    const desiredYById = new Map<string, number>()
    idsAtLevel.forEach((stageId, index) => {
      const parentYs = (incomingStageIds.get(stageId) || [])
        .map((sourceId) => stageYById.get(sourceId))
        .filter((value): value is number => typeof value === 'number')
      if (parentYs.length > 0) {
        desiredYById.set(stageId, parentYs.reduce((sum, value) => sum + value, 0) / parentYs.length)
      } else {
        desiredYById.set(stageId, stageTopPadding + (index * stageVerticalGap))
      }
    })
    const placed = placeColumn(idsAtLevel, desiredYById, stageVerticalGap)
    placed.forEach((y, id) => {
      stageYById.set(id, y)
    })
  })

  const inputConnections = connections.filter(
    (connection) =>
      connection.kind === 'input' &&
      inputBlocks.some((block) => block.id === connection.source) &&
      stageIds.has(connection.target)
  )
  const inputConsumerIds = new Map<string, string[]>()
  inputBlocks.forEach((block) => inputConsumerIds.set(block.id, []))
  inputConnections.forEach((connection) => {
    inputConsumerIds.set(connection.source, [...(inputConsumerIds.get(connection.source) || []), connection.target])
  })
  const stageInputIds = new Map<string, string[]>()
  stageBlocks.forEach((block) => stageInputIds.set(block.id, []))
  inputConnections.forEach((connection) => {
    stageInputIds.set(connection.target, [...(stageInputIds.get(connection.target) || []), connection.source])
  })
  stageInputIds.forEach((ids, stageId) => {
    ids.sort((left, right) => {
      const leftBlock = blocksById.get(left)
      const rightBlock = blocksById.get(right)
      const leftName = leftBlock?.filenames?.[0] || leftBlock?.label || left
      const rightName = rightBlock?.filenames?.[0] || rightBlock?.label || right
      return leftName.localeCompare(rightName)
    })
    stageInputIds.set(stageId, ids)
  })

  const stageInputOffset = (stageId: string, inputId: string): number => {
    const ids = stageInputIds.get(stageId) || []
    const index = ids.indexOf(inputId)
    if (index === -1) {
      return 0
    }

    const hasDependencyInputs = (incomingStageIds.get(stageId) || []).length > 0
    if (ids.length === 1) {
      return hasDependencyInputs ? ioCollisionGap * 0.7 : 0
    }

    const centered = (index - ((ids.length - 1) / 2)) * ioCollisionGap
    if (!hasDependencyInputs) {
      return centered
    }

    const sign = centered >= 0 ? 1 : -1
    return centered + (sign * ioCollisionGap * 0.45)
  }

  const sharedInputColumnX = leftPadding - inputHorizontalGap
  const inputDesiredYById = new Map<string, number>()
  inputBlocks.forEach((block, index) => {
    const consumerIds = inputConsumerIds.get(block.id) || []
    const consumerYs = consumerIds
      .map((stageId) => stageYById.get(stageId))
      .filter((value): value is number => typeof value === 'number')
    inputDesiredYById.set(
      block.id,
      consumerYs.length > 0
        ? consumerIds.reduce((sum, stageId) => {
            const stageY = stageYById.get(stageId)
            return sum + ((stageY ?? stageTopPadding) + stageInputOffset(stageId, block.id))
          }, 0) / consumerIds.length
        : stageTopPadding + (index * stageVerticalGap)
    )
  })

  const inputPositionById = new Map<string, number>()
  const inputXById = new Map<string, number>()
  const inputIds = inputBlocks.map((block) => block.id)
  const placedInputs = placeColumn(inputIds, inputDesiredYById, ioCollisionGap)
  inputIds.forEach((id) => {
    inputXById.set(id, sharedInputColumnX)
  })
  placedInputs.forEach((y, id) => {
    inputPositionById.set(id, y)
  })

  const outputIncomingStageIds = new Map<string, string[]>()
  const outputOutgoingStageIds = new Map<string, string[]>()
  outputBlocks.forEach((block) => {
    outputIncomingStageIds.set(block.id, [])
    outputOutgoingStageIds.set(block.id, [])
  })
  connections.forEach((connection) => {
    if (outputIncomingStageIds.has(connection.target) && stageIds.has(connection.source)) {
      outputIncomingStageIds.set(connection.target, [...(outputIncomingStageIds.get(connection.target) || []), connection.source])
    }
    if (outputOutgoingStageIds.has(connection.source) && stageIds.has(connection.target)) {
      outputOutgoingStageIds.set(connection.source, [...(outputOutgoingStageIds.get(connection.source) || []), connection.target])
    }
  })

  const outputBaseXById = new Map<string, number>()
  const outputDesiredYById = new Map<string, number>()
  outputBlocks.forEach((block, index) => {
    const relatedStageId = block.related_stage_id ? `stage:${block.related_stage_id}` : ''
    const producerStageId = outputIncomingStageIds.get(block.id)?.[0] || relatedStageId
    const stageX = stageXById.get(producerStageId)
    const stageY = stageYById.get(producerStageId)
    const consumerStageXs = (outputOutgoingStageIds.get(block.id) || [])
      .map((stageId) => stageXById.get(stageId))
      .filter((value): value is number => typeof value === 'number')
    const consumerStageYs = (outputOutgoingStageIds.get(block.id) || [])
      .map((stageId) => stageYById.get(stageId))
      .filter((value): value is number => typeof value === 'number')
    outputBaseXById.set(
      block.id,
      typeof stageX === 'number' && consumerStageXs.length > 0
        ? stageX + Math.max(220, (Math.min(...consumerStageXs) - stageX) / 2)
        : typeof stageX === 'number'
          ? stageX + outputHorizontalGap
          : leftPadding + (stageLevels.length * stageHorizontalGap) + outputHorizontalGap
    )
    outputDesiredYById.set(
      block.id,
      typeof stageY === 'number' && consumerStageYs.length > 0
        ? (stageY + consumerStageYs.reduce((sum, value) => sum + value, 0)) / (consumerStageYs.length + 1)
        : typeof stageY === 'number'
          ? stageY
          : stageTopPadding + (index * stageVerticalGap)
    )
  })

  const outputPositionById = new Map<string, number>()
  const outputXById = new Map<string, number>()
  const outputColumns = [...new Set(outputBlocks.map((block) => outputBaseXById.get(block.id) ?? (leftPadding + outputHorizontalGap)))].sort((a, b) => a - b)
  outputColumns.forEach((columnX, columnIndex) => {
    const idsInColumn = outputBlocks
      .filter((block) => (outputBaseXById.get(block.id) ?? (leftPadding + outputHorizontalGap)) === columnX)
      .map((block) => block.id)
    const sparseColumnX = columnX + (columnIndex * outputColumnGap)
    idsInColumn.forEach((id) => {
      outputXById.set(id, sparseColumnX)
    })
    const placed = placeColumn(idsInColumn, outputDesiredYById, ioCollisionGap)
    placed.forEach((y, id) => {
      outputPositionById.set(id, y)
    })
  })

  const provisionalPositions = new Map<string, { x: number; y: number }>()
  jobPipeline.blocks.forEach((block, index) => {
    provisionalPositions.set(block.id, {
      x: block.column === 'input'
        ? (inputXById.get(block.id) ?? (leftPadding - inputHorizontalGap))
        : block.column === 'output'
          ? (outputXById.get(block.id) ?? (leftPadding + outputHorizontalGap))
          : (stageXById.get(block.id) ?? leftPadding),
      y: block.column === 'input'
        ? (inputPositionById.get(block.id) ?? stageTopPadding)
        : block.column === 'output'
          ? (outputPositionById.get(block.id) ?? (stageTopPadding + (index * stageVerticalGap)))
          : (stageYById.get(block.id) ?? (stageTopPadding + (index * stageVerticalGap))),
    })
  })

  globallySeparateNodes(provisionalPositions, (id) => {
    const block = blocksById.get(id)
    if (!block) {
      return stageCollisionGap
    }
    return block.column === 'stage' ? stageCollisionGap : ioCollisionGap
  })

  const nodes: Node[] = jobPipeline.blocks.map((block, index) => {
    const tone = getPipelineBlockTone(block.status)
    const kindLabel = block.kind === 'tool'
      ? 'Tool'
      : block.kind === 'checkpoint'
        ? 'Checkpoint'
        : block.kind === 'input'
          ? 'Input'
          : 'Output'
    const metaParts: string[] = []
    if (block.formats && block.formats.length > 0) {
      metaParts.push(block.formats.join(', ').toUpperCase())
    }
    if (block.kind === 'input' && block.filenames && block.filenames.length > 0) {
      metaParts.push(`${block.filenames.length} file${block.filenames.length === 1 ? '' : 's'}`)
      metaParts.push(block.filenames[0] + (block.filenames.length > 1 ? ` +${block.filenames.length - 1}` : ''))
    } else if (block.filenames && block.filenames.length > 0) {
      metaParts.push(block.filenames.slice(0, 2).join(', ') + (block.filenames.length > 2 ? ` +${block.filenames.length - 2}` : ''))
    }

    const displayDescription = block.kind === 'input'
      ? undefined
      : block.description || undefined

    return {
      id: block.id,
      type: 'lockedPipelineNode',
      position: {
        x: provisionalPositions.get(block.id)?.x ?? leftPadding,
        y: provisionalPositions.get(block.id)?.y ?? (stageTopPadding + (index * stageVerticalGap)),
      },
      draggable: false,
      selectable: false,
      data: {
        label: block.label,
        description: displayDescription,
        kindLabel,
        statusLabel: formatPipelineBlockStatus(block.status),
        stageLabel: typeof block.stage_number === 'number' ? `Stage ${block.stage_number}` : '',
        metaLine: metaParts.join(' | '),
        borderColor: tone.border,
        backgroundColor: tone.background,
        headerColor: block.kind === 'checkpoint'
          ? '#183B4E'
          : block.kind === 'input'
            ? '#183B4E'
            : block.kind === 'output'
              ? '#DDA853'
              : '#27548A',
      },
      sourcePosition: block.column === 'output' ? undefined : Position.Right,
      targetPosition: block.column === 'input' ? undefined : Position.Left,
    } as Node
  })

  const edges: Edge[] = connections
    .filter((connection) => blocksById.has(connection.source) && blocksById.has(connection.target))
    .map((connection: JobPipelineConnection) => {
      const targetBlock = blocksById.get(connection.target)
      const isAnimated = targetBlock?.status === 'working'
      const edgeColor = connection.kind === 'output'
        ? '#DDA853'
        : connection.kind === 'artifact'
          ? '#183B4E'
          : connection.kind === 'dependency'
            ? '#27548A'
            : '#183B4E'

      return {
        id: connection.id,
        source: connection.source,
        target: connection.target,
        type: 'smoothstep',
        animated: isAnimated,
        label: connection.label || undefined,
        labelStyle: {
          fill: '#334155',
          fontSize: 11,
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: '#F5EEDC',
          fillOpacity: 0.9,
        },
        labelBgPadding: [6, 3],
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
        style: {
          stroke: edgeColor,
          strokeWidth: connection.kind === 'input' ? 1.6 : 1.8,
          strokeDasharray: connection.kind === 'artifact' ? '6 4' : undefined,
        },
      } as Edge
    })

  return {
    nodes,
    edges,
  }
}

interface PipelineVisualizationProps {
  pipeline: JobPipelineVisualization | null
  emptyMessage: string
  description?: string
  height?: string
  minHeight?: number
}

export default function PipelineVisualization({
  pipeline,
  emptyMessage,
  description,
  height = 'min(70vh, 720px)',
  minHeight = 420,
}: PipelineVisualizationProps) {
  const flow = useMemo(() => buildPipelineFlow(pipeline), [pipeline])
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null)
  const flowSignature = useMemo(
    () => `${flow.nodes.map((node) => node.id).join('|')}::${flow.edges.map((edge) => edge.id).join('|')}`,
    [flow.edges, flow.nodes]
  )

  useEffect(() => {
    if (!reactFlowInstance || flow.nodes.length === 0) {
      return
    }

    const frameId = window.requestAnimationFrame(() => {
      reactFlowInstance.fitView({
        padding: 0.18,
        includeHiddenNodes: true,
      })
    })

    return () => window.cancelAnimationFrame(frameId)
  }, [flow.edges, flow.nodes, reactFlowInstance])

  if (!pipeline || flow.nodes.length === 0) {
    return (
      <div className="empty-state">
        <p>{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
      {description && (
        <div style={{ color: '#3e4e59', fontSize: '0.92rem' }}>
          {description}
        </div>
      )}
      <div
        style={{
          height,
          minHeight,
          borderRadius: 18,
          overflow: 'hidden',
          border: '1px solid #d9c7a5',
          background: 'linear-gradient(180deg, #f8f1e2 0%, #f5eedc 100%)',
        }}
      >
        <ReactFlow
          key={flowSignature}
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={jobPipelineNodeTypes}
          onInit={setReactFlowInstance}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnDoubleClick={false}
          panOnDrag
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{
            type: 'smoothstep',
          }}
        >
          <Background color="#d9c7a5" gap={20} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  )
}
