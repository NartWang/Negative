import { useEffect, useState, useCallback } from 'react'
import { diaryApi, weeklyComicApi } from '../../api/client'
import type { Diary, WeeklyComic, DrawStyle } from '../../types'
import { useToast } from '../../contexts/ToastContext'
import { useCurrentDate } from '../../contexts/DateContext'
import DiaryCard from '../../components/DiaryCard'
import EmptyState from '../../components/EmptyState'
import EmptyDiary from '../../components/illustrations/EmptyDiary'
import Banner from '../../components/WeeklyComic/Banner'
import GenerateSheet from '../../components/WeeklyComic/GenerateSheet'
import ResultModal from '../../components/WeeklyComic/ResultModal'
import Thumbnails from '../../components/WeeklyComic/Thumbnails'
import DualBanner from '../../components/DualTimeline/Banner'
import DualThumbnails from '../../components/DualTimeline/Thumbnails'
import DualResultModal from '../../components/DualTimeline/ResultModal'
import { dualTimelineApi } from '../../api/client'
import type { DualTimelineComic } from '../../types'
import { getLocalDateStr } from '../../utils/date'
import './style.css'

interface Props {
  userId?: number
  onOpenEditor: (date: string) => void
  onOpenDualTimeline: () => void
}

export default function Diary({ userId, onOpenEditor, onOpenDualTimeline }: Props) {
  const toast = useToast()
  const { setCurrentDate } = useCurrentDate()
  const [diaries, setDiaries] = useState<Diary[]>([])
  const [comics, setComics] = useState<WeeklyComic[]>([])
  const [dualComics, setDualComics] = useState<DualTimelineComic[]>([])
  const [dualShown, setDualShown] = useState<DualTimelineComic | null>(null)
  const [showSheet, setShowSheet] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [showResult, setShowResult] = useState<WeeklyComic | null>(null)
  const [lastArgs, setLastArgs] = useState<{
    week_start: string; week_end: string; style: DrawStyle; custom_style_prompt?: string
  } | null>(null)

  const reload = useCallback(async () => {
    try {
      const [d, c, dt] = await Promise.all([
        diaryApi.list({ status: 'all' }),
        weeklyComicApi.list(),
        dualTimelineApi.list(),
      ])
      setDiaries(d); setComics(c); setDualComics(dt)
    } catch {
      toast.error('加载失败，请重试')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { reload() }, [reload])

  const confirmedCount = diaries.filter(d => d.status === 'confirmed').length
  const imageCount = diaries.reduce((sum, d) => sum + (d.images?.filter(i => i.kept === 1).length || 0), 0)

  const openForToday = () => {
    const today = getLocalDateStr()
    setCurrentDate(today)
    onOpenEditor(today)
  }

  const openExisting = (d: Diary) => {
    setCurrentDate(d.date)
    onOpenEditor(d.date)
  }

  const runGenerate = async (args: {
    week_start: string; week_end: string; style: DrawStyle; custom_style_prompt?: string
  }) => {
    setLastArgs(args)
    setGenerating(true)
    toast.info('正在把这一周折叠成画，预计 30-60 秒…')
    try {
      const c = await weeklyComicApi.generate(args)
      setShowSheet(false)
      setShowResult(c)
      setComics(prev => [c, ...prev])
      toast.success('生成完成 ✨')
    } catch (e) {
      const msg = (e as Error)?.message || '生成失败'
      toast.error(msg)
    } finally {
      setGenerating(false)
    }
  }

  const retry = async () => {
    if (!lastArgs) return
    setShowResult(null)
    await runGenerate(lastArgs)
  }

  const share = () => {
    toast.info('长按图片可保存到相册分享 ✨')
  }

  const remove = async () => {
    if (!showResult) return
    const id = showResult.id
    setShowResult(null)
    setComics(prev => prev.filter(c => c.id !== id))
    try { await weeklyComicApi.delete(id); toast.success('已删除') }
    catch { reload(); toast.error('删除失败') }
  }

  const removeDual = async () => {
    if (!dualShown) return
    const id = dualShown.id
    setDualShown(null)
    setDualComics(prev => prev.filter(c => c.id !== id))
    try { await dualTimelineApi.delete(id); toast.success('已删除') }
    catch { reload(); toast.error('删除失败') }
  }

  return (
    <div className="page diary-page">
      <header className="diary-header">
        <div>
          <h1 className="page-title">回忆</h1>
          <p className="diary-sub">已写 {confirmedCount} 篇 · 已生成 {imageCount} 张画</p>
        </div>
        <button className="new-diary-btn pressable" onClick={openForToday} aria-label="新建今日日记">+</button>
      </header>

      <Banner onGenerate={() => setShowSheet(true)} />
      <Thumbnails comics={comics} onOpen={setShowResult} />
      <DualBanner onOpen={onOpenDualTimeline} />
      <DualThumbnails comics={dualComics} onOpen={setDualShown} />

      {diaries.length === 0 ? (
        <EmptyState
          illustration={<EmptyDiary />}
          title="还没有日记"
          description="点击右上角 + 写下今天的故事"
        />
      ) : (
        <div className="diary-grid">
          {diaries.map(d => (
            <DiaryCard key={d.id} diary={d} onClick={() => openExisting(d)} />
          ))}
        </div>
      )}

      <GenerateSheet
        userId={userId}
        open={showSheet}
        onClose={() => !generating && setShowSheet(false)}
        onSubmit={runGenerate}
        generating={generating}
      />

      <ResultModal
        comic={showResult}
        onClose={() => setShowResult(null)}
        onRetry={retry}
        onShare={share}
        onDelete={remove}
      />
      <DualResultModal
        comic={dualShown}
        onClose={() => setDualShown(null)}
        onRetry={onOpenDualTimeline}
        onShare={() => toast.info('长按图片可保存到相册分享 ✨')}
        onDelete={removeDual}
      />
    </div>
  )
}
