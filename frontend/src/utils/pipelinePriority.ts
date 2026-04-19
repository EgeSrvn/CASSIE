import type { ToolRequirementInfo } from '../services/toolService'

export interface PriorityGroupItem {
  id: string
  label: string
  toolId?: string
  nodeId?: string
  stageId?: string
  priorityOrder: number
  selected?: boolean
}

export interface PriorityGroup {
  priority: number
  title: string
  items: PriorityGroupItem[]
}

type GenericNode = {
  id?: string
  type?: string
  data?: {
    label?: string
    toolId?: string
    priorityOrder?: number
    prioritySelected?: boolean
  }
}

type GenericEdge = {
  source?: string
  target?: string
}

const isToolNode = (node: GenericNode) => String(node.type || '').trim().toLowerCase() === 'tool'

export const computePipelinePriorityGroups = (rawNodes: GenericNode[], rawEdges: GenericEdge[]): PriorityGroup[] => {
  const toolNodes = rawNodes.filter(isToolNode).filter((node): node is Required<Pick<GenericNode, 'id'>> & GenericNode => Boolean(node.id))
  const nodeIds = new Set(toolNodes.map((node) => String(node.id)))
  const dependencies = new Map<string, Set<string>>()
  const dependents = new Map<string, Set<string>>()
  const levels = new Map<string, number>()
  const inputPositions = new Map<string, number>()

  toolNodes.forEach((node, index) => {
    const nodeId = String(node.id)
    dependencies.set(nodeId, new Set())
    dependents.set(nodeId, new Set())
    levels.set(nodeId, 0)
    inputPositions.set(nodeId, index)
  })

  rawEdges.forEach((edge) => {
    const source = String(edge.source || '')
    const target = String(edge.target || '')
    if (!nodeIds.has(source) || !nodeIds.has(target)) {
      return
    }
    dependencies.get(target)?.add(source)
    dependents.get(source)?.add(target)
  })

  const inDegree = new Map<string, number>()
  nodeIds.forEach((nodeId) => inDegree.set(nodeId, dependencies.get(nodeId)?.size || 0))
  const queue = Array.from(nodeIds)
    .filter((nodeId) => (inDegree.get(nodeId) || 0) === 0)
    .sort((a, b) => (inputPositions.get(a) || 0) - (inputPositions.get(b) || 0))

  while (queue.length > 0) {
    const nodeId = queue.shift() as string
    const currentLevel = levels.get(nodeId) || 0
    Array.from(dependents.get(nodeId) || [])
      .sort((a, b) => (inputPositions.get(a) || 0) - (inputPositions.get(b) || 0))
      .forEach((dependentId) => {
        levels.set(dependentId, Math.max(levels.get(dependentId) || 0, currentLevel + 1))
        inDegree.set(dependentId, (inDegree.get(dependentId) || 0) - 1)
        if ((inDegree.get(dependentId) || 0) === 0) {
          queue.push(dependentId)
        }
      })
  }

  const grouped = new Map<number, PriorityGroupItem[]>()
  toolNodes.forEach((node) => {
    const nodeId = String(node.id)
    const priority = levels.get(nodeId) || 0
    const current = grouped.get(priority) || []
    current.push({
      id: nodeId,
      nodeId,
      toolId: node.data?.toolId,
      label: String(node.data?.label || 'Tool'),
      priorityOrder: Number.isFinite(Number(node.data?.priorityOrder))
        ? Number(node.data?.priorityOrder)
        : current.length,
      selected:
        Boolean(node.data?.prioritySelected) ||
        (Number.isFinite(Number(node.data?.priorityOrder)) && Number(node.data?.priorityOrder) < 10_000),
    })
    grouped.set(priority, current)
  })

  return Array.from(grouped.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([priority, items]) => ({
      priority,
      title: `Priority Set ${priority + 1}`,
      items: items
        .slice()
        .sort((left, right) =>
          left.priorityOrder - right.priorityOrder ||
          (inputPositions.get(left.id) || 0) - (inputPositions.get(right.id) || 0) ||
          left.label.localeCompare(right.label)
        ),
    }))
}

export const applyPipelinePriorityGroupOrder = (
  rawNodes: GenericNode[],
  _groupPriority: number,
  allGroupNodeIds: string[],
  selectedNodeIds: string[],
  orderedNodeIds: string[],
): GenericNode[] => {
  const orderMap = new Map(orderedNodeIds.map((nodeId, index) => [String(nodeId), index]))
  const groupNodeIds = new Set(allGroupNodeIds.map(String))
  const selectedNodeIdSet = new Set(selectedNodeIds.map(String))

  return rawNodes.map((node) => {
    const nodeId = String(node.id || '')
    if (!groupNodeIds.has(nodeId)) {
      return node
    }
    return {
      ...node,
      data: {
        ...(node.data || {}),
        prioritySelected: selectedNodeIdSet.has(nodeId),
        priorityOrder: selectedNodeIdSet.has(nodeId)
          ? (orderMap.get(nodeId) ?? _groupPriority)
          : 10_000,
      },
    }
  })
}

export const buildPipelineExecutionPreferences = (groups: PriorityGroup[]) => ({
  pipeline_priority_groups: groups
    .map((group) => ({
      priority: group.priority,
      ordered_node_ids: group.items
        .filter((item) => item.selected)
        .map((item) => item.nodeId || item.id),
    }))
    .filter((group) => group.ordered_node_ids.length > 0),
})

export const computeManualPriorityGroups = (
  requirements: ToolRequirementInfo[],
  selectedToolIds: string[],
): PriorityGroup[] => {
  const cardByToolId = new Map<string, ToolRequirementInfo>()
  const toolIdByName = new Map<string, string>()
  requirements.forEach((card) => {
    cardByToolId.set(card.tool_id, card)
    toolIdByName.set(card.tool_name, card.tool_id)
  })

  const selectedPosition = new Map<string, number>()
  selectedToolIds.forEach((toolId, index) => selectedPosition.set(toolId, index))

  const dependencies = new Map<string, Set<string>>()
  const dependents = new Map<string, Set<string>>()
  const levels = new Map<string, number>()

  selectedToolIds.forEach((toolId) => {
    dependencies.set(toolId, new Set())
    dependents.set(toolId, new Set())
    levels.set(toolId, 0)
  })

  requirements.forEach((card) => {
    if (!dependencies.has(card.tool_id)) {
      return
    }
    card.requirements.forEach((requirement) => {
      const sourceToolId = toolIdByName.get(String(requirement.source_tool || ''))
      if (!sourceToolId || sourceToolId === card.tool_id || !dependencies.has(sourceToolId)) {
        return
      }
      dependencies.get(card.tool_id)?.add(sourceToolId)
      dependents.get(sourceToolId)?.add(card.tool_id)
    })
  })

  const inDegree = new Map<string, number>()
  selectedToolIds.forEach((toolId) => inDegree.set(toolId, dependencies.get(toolId)?.size || 0))
  const queue = selectedToolIds
    .filter((toolId) => (inDegree.get(toolId) || 0) === 0)
    .sort((a, b) => (selectedPosition.get(a) || 0) - (selectedPosition.get(b) || 0))

  while (queue.length > 0) {
    const toolId = queue.shift() as string
    const currentLevel = levels.get(toolId) || 0
    Array.from(dependents.get(toolId) || [])
      .sort((a, b) => (selectedPosition.get(a) || 0) - (selectedPosition.get(b) || 0))
      .forEach((dependentId) => {
        levels.set(dependentId, Math.max(levels.get(dependentId) || 0, currentLevel + 1))
        inDegree.set(dependentId, (inDegree.get(dependentId) || 0) - 1)
        if ((inDegree.get(dependentId) || 0) === 0) {
          queue.push(dependentId)
        }
      })
  }

  const grouped = new Map<number, PriorityGroupItem[]>()
  selectedToolIds.forEach((toolId) => {
    const card = cardByToolId.get(toolId)
    if (!card) {
      return
    }
    const priority = levels.get(toolId) || 0
    const current = grouped.get(priority) || []
    current.push({
      id: toolId,
      toolId,
      label: card.tool_name,
      priorityOrder: selectedPosition.get(toolId) || current.length,
      selected: false,
    })
    grouped.set(priority, current)
  })

  return Array.from(grouped.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([priority, items]) => ({
      priority,
      title: `Priority Set ${priority + 1}`,
      items: items
        .slice()
        .sort((left, right) =>
          left.priorityOrder - right.priorityOrder ||
          (selectedPosition.get(left.toolId || '') || 0) - (selectedPosition.get(right.toolId || '') || 0) ||
          left.label.localeCompare(right.label)
        ),
    }))
}

export const buildManualExecutionPreferences = (groups: PriorityGroup[]) => ({
  manual_priority_groups: groups
    .map((group) => ({
      priority: group.priority,
      ordered_tool_ids: group.items
        .filter((item) => item.selected)
        .map((item) => item.toolId || item.id),
    }))
    .filter((group) => group.ordered_tool_ids.length > 0),
})
