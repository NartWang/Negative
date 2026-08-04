import { useToastStack } from '../../contexts/ToastContext'
import './style.css'

export default function Toast() {
  const { toasts, dismiss } = useToastStack()
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map(t => (
        <button
          key={t.id}
          className={`toast toast-${t.kind} slide-up`}
          onClick={() => dismiss(t.id)}
        >
          <span className="toast-icon">
            {t.kind === 'success' ? '✓' : t.kind === 'error' ? '!' : 'ℹ'}
          </span>
          <span className="toast-message">{t.message}</span>
        </button>
      ))}
    </div>
  )
}
