import { useEffect, useState, useCallback, useRef } from 'react'
import { flushSync } from 'react-dom'
import { diaryApi, fragmentsApi } from '../../api/client'
import type { Fragment, FragmentUpdatePayload, DiaryEditorRequest } from '../../types'
import { useCurrentDate } from '../../contexts/DateContext'
import { useToast } from '../../contexts/ToastContext'
import DateBar from '../../components/DateBar'
import BottomSheet from '../../components/BottomSheet'
import FragmentComposer from '../../components/FragmentComposer'
import FragmentItem from '../../components/FragmentItem'
import { fragmentClockTime } from '../../utils/recordTime'
import './style.css'

interface Props {
  onOpenEditor: (request: DiaryEditorRequest) => void
  onOpenNotebook: (date: string) => void
}

export default function Today({ onOpenEditor, onOpenNotebook }: Props) {
  const { currentDate, isToday } = useCurrentDate()
  const toast = useToast()
  const [fragments, setFragments] = useState<Fragment[]>([])
  const [showSourceSheet, setShowSourceSheet] = useState(false)
  const [selectedFragmentIds, setSelectedFragmentIds] = useState<number[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [hasDiary, setHasDiary] = useState(false)
  const openingEditorRef = useRef(false)
  const [openingEditor, setOpeningEditor] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [f, diary] = await Promise.all([
        fragmentsApi.list(currentDate),
        diaryApi.get(currentDate).catch(() => null),
      ])
      setFragments(f)
      setHasDiary(Boolean(diary))
      setSelectedFragmentIds(f.map(item => item.id))
    } catch {
      setLoadError('加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }, [currentDate])

  useEffect(() => { reload() }, [reload])

  const updateFragment = async (id: number, data: FragmentUpdatePayload): Promise<void> => {
    const updated = await fragmentsApi.update(id, data)
    setFragments(current => current.map(f => f.id === id ? updated : f))
    toast.success('已保存')
  }

  const deleteFragment = async (id: number): Promise<void> => {
    const snapshot = fragments
    const selectedSnapshot = selectedFragmentIds
    setFragments(current => current.filter(f => f.id !== id))
    setSelectedFragmentIds(current => current.filter(item => item !== id))
    try {
      await fragmentsApi.delete(id)
      toast.success('已删除')
    } catch (error) {
      setFragments(snapshot)
      setSelectedFragmentIds(selectedSnapshot)
      toast.error('删除失败')
      throw error
    }
  }

  const handleCreated = (created: Fragment) => {
    setFragments(current => [...current, created])
    setSelectedFragmentIds(current => [...current, created.id])
  }

  const sortedFragments = [...fragments].sort((a, b) => {
    const byTime = fragmentClockTime(b).localeCompare(fragmentClockTime(a))
    if (byTime !== 0) return byTime
    const byCreated = (b.created_at || '').localeCompare(a.created_at || '')
    if (byCreated !== 0) return byCreated
    return b.id - a.id
  })
  const selectedCount = selectedFragmentIds.length

  const toggleSelectedFragment = (id: number) => {
    setSelectedFragmentIds(current => current.includes(id)
      ? current.filter(item => item !== id)
      : [...current, id])
  }

  const openEditorWithSelection = () => {
    if (selectedCount === 0 || openingEditorRef.current) return
    openingEditorRef.current = true
    // Commit the pending UI synchronously so a second same-tick click already
    // sees the disabled "正在打开…" button, then navigate synchronously.
    flushSync(() => setOpeningEditor(true))
    try {
      onOpenEditor({
        date: currentDate,
        selection: {
          schedule_ids: [],
          fragment_ids: selectedFragmentIds,
        },
      })
      setShowSourceSheet(false)
    } catch {
      openingEditorRef.current = false
      setOpeningEditor(false)
      toast.error('暂时打不开日记，请重试')
    }
  }

  return (
    <div className="page today-page">
      <DateBar onOpenNotebook={() => onOpenNotebook(currentDate)} />

      <main className="today-body">
        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="retry-btn" onClick={() => { void reload() }}>
              重试加载
            </button>
          </div>
        ) : (
          <>
            <section aria-labelledby="fragment-composer-title">
              <h2 id="fragment-composer-title" className="section-title">随手记</h2>
              <FragmentComposer date={currentDate} onCreated={handleCreated} />
            </section>

            <section className="fragment-timeline" role="region" aria-label="已记下">
              <header className="fragment-timeline-header">
                <h2 className="fragment-timeline-title">已记下</h2>
                <span className="fragment-timeline-count" aria-label={`已记下 ${fragments.length} 条`}>
                  {fragments.length}
                </span>
              </header>
              {loading && fragments.length === 0 ? (
                <p className="fragment-timeline-empty">加载中…</p>
              ) : fragments.length === 0 ? (
                <p className="fragment-timeline-empty">还没有记录，先记下第一条吧</p>
              ) : (
                <div className="fragment-list">
                  {sortedFragments.map(f => (
                    <FragmentItem
                      key={f.id}
                      fragment={f}
                      onUpdate={updateFragment}
                      onDelete={deleteFragment}
                    />
                  ))}
                </div>
              )}
            </section>

            {fragments.length > 0 && (
              <button
                type="button"
                className="generate-btn pressable"
                onClick={() => setShowSourceSheet(true)}
              >
                {hasDiary
                  ? `打开 ${currentDate} 的日记`
                  : isToday
                    ? '生成今日日记'
                    : `生成 ${currentDate} 的日记`}
                <span>{selectedCount} 条素材</span>
              </button>
            )}
          </>
        )}
      </main>

      <BottomSheet open={showSourceSheet} onClose={() => setShowSourceSheet(false)} title="选择生成素材">
        <div className="source-picker">
          <section>
            <h3>随手记</h3>
            {fragments.map(fragment => (
              <label key={fragment.id} className="source-row">
                <input
                  type="checkbox"
                  checked={selectedFragmentIds.includes(fragment.id)}
                  onChange={() => toggleSelectedFragment(fragment.id)}
                />
                <span>{fragment.content?.trim() || (fragment.photo_url ? '一张照片' : '一条随记')}</span>
              </label>
            ))}
          </section>
          <button
            className="submit-btn"
            type="button"
            disabled={selectedCount === 0 || openingEditor}
            onClick={openEditorWithSelection}
          >
            {openingEditor ? '正在打开…' : `用 ${selectedCount} 条素材生成`}
          </button>
        </div>
      </BottomSheet>
    </div>
  )
}
