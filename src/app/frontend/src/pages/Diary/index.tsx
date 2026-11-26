import { useCallback, useEffect, useState } from 'react'
import { storyApi } from '../../api/client'
import { useToast } from '../../contexts/ToastContext'
import { useCurrentDate } from '../../contexts/DateContext'
import EmptyState from '../../components/EmptyState'
import EmptyDiary from '../../components/illustrations/EmptyDiary'
import StoryChapterList from '../../components/StoryChapterList'
import { BookOpen } from '../../components/Icon'
import { getLocalDateStr } from '../../utils/date'
import type { StoryChapter } from '../../types'
import './style.css'

interface Props {
  userId?: number
  onOpenCreateMenu: (date: string) => void
  onOpenDay: (date: string) => void
  onOpenStoryWork: (workId: number) => void
  onOpenLegacyWeekly: (comicId: number) => void
  onOpenDrafts: () => void
}

export default function Diary({ onOpenCreateMenu, onOpenDay, onOpenStoryWork, onOpenLegacyWeekly, onOpenDrafts }: Props) {
  const toast = useToast()
  const { setCurrentDate } = useCurrentDate()
  const [chapters, setChapters] = useState<StoryChapter[]>([])
  const [draftCount, setDraftCount] = useState(0)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const result = await storyApi.chapters()
      setChapters(result.items)
      setDraftCount(result.draft_count)
    } catch {
      toast.error('加载失败，请重试')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { reload() }, [reload])

  const openForToday = () => {
    const today = getLocalDateStr()
    setCurrentDate(today)
    onOpenCreateMenu(today)
  }

  return (
    <div className="page diary-page">
      <header className="diary-header">
        <div>
          <h1 className="page-title">故事</h1>
          <p className="diary-sub">按月份整理的每日章节</p>
        </div>
        <div className="diary-header-actions">
          <button
            className="draft-box-btn pressable"
            type="button"
            onClick={onOpenDrafts}
            aria-label={`打开草稿箱，${draftCount} 篇草稿`}
          >
            <BookOpen />
            <span>{draftCount}</span>
          </button>
          <button className="new-diary-btn pressable" type="button" onClick={openForToday} aria-label="创建故事">
            +
          </button>
        </div>
      </header>

      {loading ? (
        <div className="diary-loading" role="status">正在整理故事…</div>
      ) : chapters.length === 0 ? (
        <EmptyState
          illustration={<EmptyDiary />}
          title="还没有故事章节"
          description="点击右上角 + 写下今天的故事"
        />
      ) : (
        <StoryChapterList
          chapters={chapters}
          onOpenDay={onOpenDay}
          onOpenRangeWork={(sourceKind, sourceId) => {
            if (sourceKind === 'legacy_weekly') {
              onOpenLegacyWeekly(sourceId)
              return
            }
            onOpenStoryWork(sourceId)
          }}
        />
      )}
    </div>
  )
}
