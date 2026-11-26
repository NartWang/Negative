import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Clock } from '../Icon'
import './style.css'

interface WarmTimePickerProps {
  value: string
  onChange: (value: string) => void
  label?: string
  className?: string
  modal?: boolean
  portalAbove?: boolean
}

const HOURS = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, '0'))
const MINUTES = Array.from({ length: 60 }, (_, index) => String(index).padStart(2, '0'))

export default function WarmTimePicker({
  value,
  onChange,
  label = '记录时间',
  className = '',
  modal = false,
  portalAbove = false,
}: WarmTimePickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selectedHourRef = useRef<HTMLButtonElement>(null)
  const selectedMinuteRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [anchorStyle, setAnchorStyle] = useState<CSSProperties>({})
  const [hour = '00', minute = '00'] = value.split(':')

  const togglePicker = () => {
    if (!open && portalAbove && rootRef.current) {
      const rect = rootRef.current.getBoundingClientRect()
      const width = Math.min(230, window.innerWidth - 32)
      setAnchorStyle({
        bottom: window.innerHeight - rect.top + 8,
        left: Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16)),
        width,
      })
    }
    setOpen(current => !current)
  }

  useEffect(() => {
    if (!open) return
    const closeWhenOutside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeWhenOutside)
    document.addEventListener('keydown', closeOnEscape)
    window.requestAnimationFrame(() => {
      selectedHourRef.current?.scrollIntoView?.({ block: 'center' })
      selectedMinuteRef.current?.scrollIntoView?.({ block: 'center' })
    })
    return () => {
      document.removeEventListener('pointerdown', closeWhenOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const popover = open ? (
    <div
      className={`warm-time-picker-popover ${modal ? 'is-modal' : ''} ${portalAbove ? 'is-portal-above' : ''}`}
      role="dialog"
      aria-label="选择时间"
      ref={popoverRef}
      style={portalAbove ? anchorStyle : undefined}
    >
      <div className="warm-time-picker-heading">
        <span>小时</span>
        <span>分钟</span>
      </div>
      <div className="warm-time-picker-columns">
        <div className="warm-time-picker-column" aria-label="选择小时">
          {HOURS.map(option => (
            <button
              key={option}
              ref={option === hour ? selectedHourRef : undefined}
              type="button"
              className={option === hour ? 'selected' : ''}
              aria-pressed={option === hour}
              onClick={() => onChange(`${option}:${minute}`)}
            >{option}</button>
          ))}
        </div>
        <div className="warm-time-picker-column" aria-label="选择分钟">
          {MINUTES.map(option => (
            <button
              key={option}
              ref={option === minute ? selectedMinuteRef : undefined}
              type="button"
              className={option === minute ? 'selected' : ''}
              aria-pressed={option === minute}
              onClick={() => onChange(`${hour}:${option}`)}
            >{option}</button>
          ))}
        </div>
      </div>
      <button type="button" className="warm-time-picker-done" onClick={() => setOpen(false)}>
        完成
      </button>
    </div>
  ) : null

  return (
    <div className={`warm-time-picker ${className}`} ref={rootRef}>
      <input
        className="warm-time-picker-native-value"
        type="text"
        aria-label={label}
        value={value}
        tabIndex={-1}
        onChange={event => onChange(event.target.value)}
      />
      <button
        type="button"
        className="warm-time-picker-trigger"
        aria-label={`选择${label}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={togglePicker}
      >
        <span>{value}</span>
        <Clock aria-hidden="true" />
      </button>
      {portalAbove && popover
        ? createPortal(popover, document.body)
        : modal && popover
        ? createPortal(
            <div className="warm-time-picker-modal-layer" onPointerDown={event => {
              if (event.target === event.currentTarget) setOpen(false)
            }}>
              {popover}
            </div>,
            document.body,
          )
        : popover}
    </div>
  )
}
