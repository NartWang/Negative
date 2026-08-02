import { ReactNode } from 'react'
import './style.css'

interface Props {
  illustration: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export default function EmptyState({ illustration, title, description, action }: Props) {
  return (
    <div className="empty-state slide-up">
      <div className="empty-illustration">{illustration}</div>
      <div className="empty-title">{title}</div>
      {description && <div className="empty-desc">{description}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  )
}
