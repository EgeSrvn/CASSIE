import { useEffect, useRef, useState } from 'react'

export interface SortDropdownOption {
  value: string
  label: string
}

interface SortDropdownProps {
  id: string
  label: string
  value: string
  options: SortDropdownOption[]
  onChange: (value: string) => void
  hideLabel?: boolean
}

export default function SortDropdown({ id, label, value, options, onChange, hideLabel = false }: SortDropdownProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const selectedOption = options.find((option) => option.value === value) || options[0]

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [])

  return (
    <div className={`community-sort-controls ${open ? 'system-dropdown-open' : ''}`} ref={containerRef}>
      {!hideLabel && <label id={`${id}-label`}>{label}</label>}
      <div className="system-dropdown">
        <button
          type="button"
          className="system-dropdown-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-labelledby={hideLabel ? undefined : `${id}-label ${id}-button`}
          aria-label={hideLabel ? label : undefined}
          id={`${id}-button`}
          onClick={() => setOpen((current) => !current)}
        >
          <span>{selectedOption?.label || 'Sort'}</span>
          <span className="system-dropdown-caret" aria-hidden="true">▾</span>
        </button>
        {open && (
          <div
            className="system-dropdown-menu"
            role="listbox"
            aria-labelledby={hideLabel ? undefined : `${id}-label`}
            aria-label={hideLabel ? label : undefined}
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`system-dropdown-option ${option.value === value ? 'active' : ''}`}
                role="option"
                aria-selected={option.value === value}
                onClick={() => {
                  onChange(option.value)
                  setOpen(false)
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
