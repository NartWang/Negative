import type { RoomTemperatures } from '../../types'
import './style.css'

type Subject = 'own' | 'partner'

interface RoomTemperatureProps {
  temperatures: RoomTemperatures
  subject: Subject
  partnerName: string
  busy: boolean
  onSubjectChange: (subject: Subject) => void
  onPublish: () => Promise<void>
  onRevoke: () => Promise<void>
}

export default function RoomTemperature({
  temperatures, subject, partnerName, busy, onSubjectChange, onPublish, onRevoke,
}: RoomTemperatureProps) {
  const selected = temperatures[subject]
  const subjectName = subject === 'own' ? '我的状态' : `${partnerName}的状态`

  return (
    <section className="room-temperature" aria-labelledby="room-temperature-title">
      <div className="room-temperature-heading">
        <div>
          <p>状态窗</p>
          <h2 id="room-temperature-title">{subjectName}</h2>
        </div>
        <div className="temperature-subjects" aria-label="状态视角">
          <button
            type="button"
            style={{ minWidth: 0, overflowWrap: 'anywhere' }}
            aria-pressed={subject === 'own'}
            onClick={() => onSubjectChange('own')}
          >看我的状态</button>
          <button
            type="button"
            style={{ minWidth: 0, overflowWrap: 'anywhere' }}
            aria-pressed={subject === 'partner'}
            onClick={() => onSubjectChange('partner')}
          >看{partnerName}的状态</button>
        </div>
      </div>

      {selected.status === 'available' ? (
        <div className="temperature-reading">
          <span className="temperature-score">{selected.snapshot.score}</span>
          <div>
            <strong>
              <span className="temperature-swatch" style={{ backgroundColor: selected.snapshot.color }} aria-hidden="true" />
              {selected.snapshot.label}
            </strong>
            <span>{selected.snapshot.nickname} · {selected.snapshot.date}</span>
          </div>
        </div>
      ) : (
        <p className="temperature-unavailable" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
          {subject === 'own' ? '你还没有分享状态' : `${partnerName}还没有可见的状态`}
        </p>
      )}

      {subject === 'own' && (
        selected.status === 'available'
          ? <button className="temperature-control secondary" type="button" disabled={busy} onClick={() => void onRevoke()}>撤回我的状态</button>
          : <button className="temperature-control" type="button" disabled={busy} onClick={() => void onPublish()}>发布今天的状态</button>
      )}
    </section>
  )
}
