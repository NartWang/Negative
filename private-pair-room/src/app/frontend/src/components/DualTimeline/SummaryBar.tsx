import './style.css'

interface Props {
  summary: string | null
  loading?: boolean
}

export default function SummaryBar({ summary, loading }: Props) {
  return (
    <div className="dt-summary">
      <span className="dt-summary-spark">✨</span>
      <span className="dt-summary-text">
        {loading ? '正在读两个人的一天…' : (summary ?? '')}
      </span>
    </div>
  )
}
