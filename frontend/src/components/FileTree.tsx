import { useState } from 'react'
import { FolderTreeItem, FileItem } from '../services/folderService'
import TrashIcon from './TrashIcon'
import '../styles/FileTree.css'

interface FileTreeProps {
  tree: FolderTreeItem[]
  selectedFiles: Set<number>
  onFileSelect: (fileId: number, selected: boolean) => void
  showCheckboxes?: boolean
  selectedFolderId?: number | null
  onFolderSelect?: (folderId: number | null) => void
  onFolderDelete?: (folderId: number) => void
  showDeleteButtons?: boolean
}

export default function FileTree({
  tree,
  selectedFiles,
  onFileSelect,
  showCheckboxes = true,
  selectedFolderId,
  onFolderSelect,
  onFolderDelete,
  showDeleteButtons = false
}: FileTreeProps) {
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(new Set())

  const toggleFolder = (folderId: number) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(folderId)) {
      newExpanded.delete(folderId)
    } else {
      newExpanded.add(folderId)
    }
    setExpandedFolders(newExpanded)
  }

  const renderFolder = (folder: FolderTreeItem, level: number = 0) => {
    const isExpanded = expandedFolders.has(folder.id)
    const hasChildren = folder.children.length > 0 || folder.files.length > 0
    const isSelected = selectedFolderId === folder.id

    const handleFolderClick = (e: React.MouseEvent) => {
      e.stopPropagation()
      // Select folder (for viewing contents)
      // Don't deselect if already selected - just toggle expansion
      if (onFolderSelect) {
        if (isSelected) {
          // If already selected, just toggle expansion, don't deselect
          if (hasChildren) {
            toggleFolder(folder.id)
          }
        } else {
          // Select the folder
          onFolderSelect(folder.id)
          // Also toggle expansion if it has children
          if (hasChildren) {
            toggleFolder(folder.id)
          }
        }
      } else {
        // If no onFolderSelect callback, just toggle expansion
        if (hasChildren) {
          toggleFolder(folder.id)
        }
      }
    }

    const handleDeleteClick = (e: React.MouseEvent) => {
      e.stopPropagation()
      if (onFolderDelete) {
        onFolderDelete(folder.id)
      }
    }

    return (
      <div key={folder.id} className="file-tree-item">
        <div
          className={`file-tree-folder ${isExpanded ? 'expanded' : ''} ${isSelected ? 'selected' : ''}`}
          style={{ paddingLeft: `${level * 20}px` }}
          onClick={handleFolderClick}
        >
          <span className="file-tree-icon">
            {hasChildren ? (isExpanded ? '📂' : '📁') : '📁'}
          </span>
          <span className="file-tree-name">{folder.name}</span>
          {showDeleteButtons && onFolderDelete && (
            <button
              className="file-tree-delete-btn"
              onClick={handleDeleteClick}
              title="Delete folder and all contents"
              aria-label={`Delete folder ${folder.name}`}
            >
              <TrashIcon />
            </button>
          )}
        </div>

        {isExpanded && (
          <div className="file-tree-children">
            {folder.children.map((child) => renderFolder(child, level + 1))}
            {folder.files.map((file) => renderFile(file, level + 1))}
          </div>
        )}
      </div>
    )
  }

  const renderFile = (file: FileItem, level: number = 0) => {
    const isSelected = selectedFiles.has(file.id)
    const fileIcon = getFileIcon(file.file_format || '')

    return (
      <div
        key={file.id}
        className={`file-tree-file ${isSelected ? 'selected' : ''}`}
        style={{ paddingLeft: `${level * 20}px` }}
        onClick={() => showCheckboxes && onFileSelect(file.id, !isSelected)}
      >
        {showCheckboxes && (
          <input
            type="checkbox"
            checked={isSelected}
            onChange={(e) => onFileSelect(file.id, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
        )}
        <span className="file-tree-icon">{fileIcon}</span>
        <span className="file-tree-name">{file.filename}</span>
        {file.size_bytes && (
          <span className="file-tree-size">
            {formatFileSize(file.size_bytes)}
          </span>
        )}
      </div>
    )
  }

  const getFileIcon = (format: string): string => {
    const formatLower = format.toLowerCase()
    if (formatLower.includes('fastq')) return '🧬'
    if (formatLower.includes('fasta')) return '📄'
    if (formatLower.includes('sam') || formatLower.includes('bam')) return '📊'
    return '📄'
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
  }

  return (
    <div className="file-tree">
      {tree.length === 0 ? (
        <div className="file-tree-empty">No folders or files</div>
      ) : (
        tree.map((folder) => renderFolder(folder))
      )}
    </div>
  )
}
