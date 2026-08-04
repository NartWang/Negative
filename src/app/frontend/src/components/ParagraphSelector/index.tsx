import './style.css'

interface Props {
  text: string
  selected: number[] // indices of selected paragraphs; empty array means "whole diary"
  onChange: (next: number[]) => void
}

export default function ParagraphSelector({ text, selected, onChange }: Props) {
  const paragraphs = text.split(/\n\s*\n/).map(p => p.trim()).filter(p => p.length > 0)
  if (paragraphs.length === 0) {
    return <p className="ps-empty">先在上面写点内容，再来选段。</p>
  }
  const toggle = (i: number) => {
    if (selected.includes(i)) onChange(selected.filter(x => x !== i))
    else onChange([...selected, i].sort())
  }
  const wholeActive = selected.length === 0
  return (
    <div className="paragraph-selector">
      <button className={`ps-chip ${wholeActive ? 'active' : ''}`} onClick={() => onChange([])}>整篇</button>
      {paragraphs.map((p, i) => (
        <button
          key={i}
          className={`ps-row ${selected.includes(i) ? 'active' : ''}`}
          onClick={() => toggle(i)}
        >
          <span className="ps-check">{selected.includes(i) ? '☑' : '☐'}</span>
          <span className="ps-text">{p.length > 70 ? p.slice(0, 70) + '…' : p}</span>
        </button>
      ))}
    </div>
  )
}
