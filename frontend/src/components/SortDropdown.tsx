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
}

export default function SortDropdown({ id, label, value, options, onChange }: SortDropdownProps) {
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
      <label id={`${id}-label`}>{label}</label>
      <div className="system-dropdown">
        <button
          type="button"
          className="system-dropdown-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-labelledby={`${id}-label ${id}-button`}
          id={`${id}-button`}
          onClick={() => setOpen((current) => !current)}
        >
          <span>{selectedOption?.label || 'Sort'}</span>
          <span className="system-dropdown-caret" aria-hidden="true">{'\u2304'}</span>
        </button>
        {open && (
          <div className="system-dropdown-menu" role="listbox" aria-labelledby={`${id}-label`}>
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
