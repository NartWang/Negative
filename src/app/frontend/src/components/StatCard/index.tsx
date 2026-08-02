import './style.css'

interface Props {
  label: string
  value: string | number
  hint?: string
  icon?: string
}

export default function StatCard({ label, value, hint, icon }: Props) {
  return (
    <div className="stat-card">
      {icon && <div className="stat-icon">{icon}</div>}
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}
