import { useCallback, useEffect, useRef, useState } from 'react'
import CharacterProgress from '../../components/CharacterProgress'
import FilmFolderCreateSheet from '../../components/FilmFolderCreateSheet'
import MonthlyWorkCollection from '../../components/MonthlyWorkCollection'
import PdfExportSheet from '../../components/PdfExportSheet'
import Modal from '../../components/Modal'
import {
  ApiError,
  characterApi,
  filmFolderApi,
  picturebookApi,
  picturebookVideoApi,
  storyApi,
} from '../../api/client'
import { Download } from '../../components/Icon'
import type {
  CharacterProfile,
  FilmFolderItem,
  FilmFolderMedium,
  FilmFolderResponse,
} from '../../types'
import {
  interpolateProgress,
  motionComicProgress,
  picturebookProgressWindow,
} from '../../utils/generationProgress'
import './style.css'

export interface FilmFolderProps {
  initialMedium?: FilmFolderMedium
  onCreateDailyPicturebook(date?: string): void
  onCreateTimeStory(): void
  onCreateMotionComic(draftId?: number): void
  onContinue(medium: FilmFolderMedium): void
  onOpenPicturebook(item: FilmFolderItem): void
  onOpenMotionComic(videoJobId: number): void
}

const POLL_INTERVAL: Record<FilmFolderMedium, number> = {
  picturebook: 4000,
  motion_comic: 5000,
}

const ANIMATION_TICK_MS = 250
const COMPLETION_HOLD_MS = 800
const SAFE_FAILURE_MESSAGE = '生成失败，可以在继续创作中重试'

interface DisplayedJob {
  medium: FilmFolderMedium
  jobId: number
  epoch: number
}

export default function FilmFolder({
  initialMedium = 'picturebook',
  onCreateDailyPicturebook,
  onCreateTimeStory,
  onCreateMotionComic,
  onContinue,
  onOpenPicturebook,
  onOpenMotionComic,
}: FilmFolderProps) {
  const [tab, setTab] = useState<FilmFolderMedium>(initialMedium)
  const [data, setData] = useState<Record<FilmFolderMedium, FilmFolderResponse | null>>({
    picturebook: null,
    motion_comic: null,
  })
  const [loadedTabs, setLoadedTabs] = useState<Set<FilmFolderMedium>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [character, setCharacter] = useState<CharacterProfile | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<FilmFolderItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [publishingId, setPublishingId] = useState<number | null>(null)
  // 刷新序列号:任务完成/失败后触发一次列表重读。
  const [reloadTick, setReloadTick] = useState(0)

  // —— 视觉进度状态:时间驱动插值 + 终端校验 + 完成停留 ——
  const [visualPercent, setVisualPercent] = useState(0)
  const [completionHold, setCompletionHold] = useState<{
    medium: FilmFolderMedium
    jobId: number
  } | null>(null)
  const windowStartedAtRef = useRef(0)
  const accumulatedWindowMsRef = useRef(0)
  const visualFloorRef = useRef(0)
  const nextMilestoneRef = useRef(0)
  const nominalMsRef = useRef<number | null>(null)
  const realNodeKeyRef = useRef('')
  const progressEpochRef = useRef(0)
  const displayedJobRef = useRef<DisplayedJob | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const completionTimerRef = useRef<number | null>(null)
  const animationTimerRef = useRef<number | null>(null)
  const pollHealthyRef = useRef(true)
  // 已提交视觉进度的权威值。所有写 visualPercent 的地方都先写它,
  // 避免批处理里多个 updater 读到陈旧 prev。
  const visualPercentRef = useRef(0)

  const updatePollHealthy = useCallback((healthy: boolean) => {
    pollHealthyRef.current = healthy
  }, [])

  const setVisual = useCallback((value: number) => {
    visualPercentRef.current = value
    setVisualPercent(value)
  }, [])

  const loadTab = useCallback(async (medium: FilmFolderMedium) => {
    try {
      const payload = medium === 'picturebook'
        ? await filmFolderApi.picturebooks()
        : await filmFolderApi.motionComics()
      setData(prev => ({ ...prev, [medium]: payload }))
      // 只清掉加载类错误;终态失败的安全提示由用户显式关闭。
      setError(prev => (prev === '加载失败,请重试' ? null : prev))
    } catch {
      setError('加载失败,请重试')
    }
  }, [])

  // 当前分区首次加载;切回已加载分区时若其仍有运行任务,也重读一次——
  // 离开期间后台任务可能已完成或失败。
  useEffect(() => {
    if (!loadedTabs.has(tab)) {
      setLoadedTabs(prev => new Set(prev).add(tab))
      void loadTab(tab)
      return
    }
    if (data[tab]?.active_generation) void loadTab(tab)
  }, [tab, loadedTabs, loadTab]) // eslint-disable-line react-hooks/exhaustive-deps

  // 完成/失败后刷新。
  useEffect(() => {
    if (reloadTick > 0) void loadTab(tab)
  }, [reloadTick, tab, loadTab])

  // 角色形象只读一次,失败静默降级默认人物。
  useEffect(() => {
    let cancelled = false
    characterApi.get()
      .then(profile => { if (!cancelled) setCharacter(profile) })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  const current = data[tab]
  const active = current?.active_generation ?? null

  const resetAnimation = useCallback(() => {
    accumulatedWindowMsRef.current = 0
    windowStartedAtRef.current = 0
    visualFloorRef.current = 0
    nextMilestoneRef.current = 0
    nominalMsRef.current = null
    realNodeKeyRef.current = ''
  }, [])

  const clearProgressTimers = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    if (completionTimerRef.current !== null) {
      window.clearTimeout(completionTimerRef.current)
      completionTimerRef.current = null
    }
    if (animationTimerRef.current !== null) {
      window.clearInterval(animationTimerRef.current)
      animationTimerRef.current = null
    }
  }, [])

  // 时间驱动插值:只在轮询健康且处于渲染区间时前进,
  // 失败冻结 = 暂停累计,恢复后从冻结值继续,不补算断线时长。
  // 健康状态读 ref:interval 只建一次,闭包里的 state 会过期。
  const ensureAnimation = useCallback(() => {
    if (animationTimerRef.current !== null) return
    animationTimerRef.current = window.setInterval(() => {
      if (!pollHealthyRef.current) return
      const nominal = nominalMsRef.current
      if (nominal === null) return
      const now = Date.now()
      if (windowStartedAtRef.current === 0) {
        windowStartedAtRef.current = now
        return
      }
      accumulatedWindowMsRef.current += now - windowStartedAtRef.current
      windowStartedAtRef.current = now
      const elapsed = accumulatedWindowMsRef.current
      const nextValue = Math.max(visualPercentRef.current, Math.min(
        nextMilestoneRef.current,
        interpolateProgress(visualFloorRef.current, nextMilestoneRef.current, elapsed, nominal),
      ))
      setVisual(nextValue)
    }, ANIMATION_TICK_MS)
  }, [setVisual])

  // 主轮询 effect:递归 setTimeout 单飞;active 消失时用详情接口校验终态。
  useEffect(() => {
    if (completionHold !== null && completionHold.medium !== tab) {
      setCompletionHold(null)
    }

    const displayedBefore = displayedJobRef.current
    const verifying = active === null
      && displayedBefore !== null
      && displayedBefore.medium === tab
      && displayedBefore.epoch === progressEpochRef.current

    if (active === null) {
      // 终态确认由 tick 内的 verifyTerminal 完成;这里只兜底「从未被
      // 跟踪/已被确认/来自其他分区」的 null 状态:结束旧纪元并复位。
      if (displayedBefore !== null && !verifying) {
        displayedJobRef.current = null
        progressEpochRef.current += 1
        clearProgressTimers()
        resetAnimation()
        setVisual(0)
        updatePollHealthy(true)
      }
      return
    }

    if (displayedBefore !== null
      && (displayedBefore.medium !== tab || displayedBefore.jobId !== active.id)) {
      // 不同的非空任务 = 新纪元;旧轮询/停留定时器一律作废。
      progressEpochRef.current += 1
      clearProgressTimers()
      resetAnimation()
      setVisual(0)
      updatePollHealthy(true)
    }
    const epoch = progressEpochRef.current
    displayedJobRef.current = { medium: tab, jobId: active.id, epoch }

    const applyRealNode = (summary: NonNullable<FilmFolderResponse['active_generation']>) => {
      if (tab === 'picturebook') {
        const window = picturebookProgressWindow({
          stage: summary.stage,
          ready: summary.ready,
          total: summary.total,
          done: summary.status === 'done',
        })
        // 真实节点变了才重置区间时钟;同节点的成功轮询不打断页内插值。
        // 唯一权威:节点键是否已见过。同一任务的同节点轮询永不重启时钟,
        // 新节点/新任务才重启;视觉进度只前进不回退(更低的真实节点不动头像)。
        const nodeKey = `${summary.stage}/${summary.ready}/${summary.total}`
        if (nodeKey !== realNodeKeyRef.current) {
          realNodeKeyRef.current = nodeKey
          accumulatedWindowMsRef.current = 0
          windowStartedAtRef.current = 0
          nominalMsRef.current = window.nominalMs
        }
        const floor = Math.max(visualPercentRef.current, window.real)
        visualFloorRef.current = floor
        nextMilestoneRef.current = Math.max(floor, window.next)
        setVisual(floor)
        ensureAnimation()
      } else {
        // 漫剧只用真实节点,不捏造 180s 插值。
        const real = motionComicProgress({
          stage: summary.stage,
          ready: summary.ready,
          total: summary.total,
          done: summary.status === 'done',
        })
        nominalMsRef.current = null
        const nextValue = Math.max(visualPercentRef.current, real)
        visualFloorRef.current = nextValue
        setVisual(nextValue)
      }
    }

    // effect 启动时立即把当前活动摘要作为初始真实节点,
    // 不等第一轮轮询,否则进度会从 0 起步。
    if (active) applyRealNode(active)

    const applySummary = (payload: FilmFolderResponse, summary: NonNullable<FilmFolderResponse['active_generation']>) => {
      setData(prev => ({ ...prev, [tab]: payload }))
      applyRealNode(summary)
    }

    // 返回 true 表示已拿到终态(done/failed),轮询纪元随之结束。
    const verifyTerminal = async (payload: FilmFolderResponse, jobId: number): Promise<boolean> => {
      let terminalStatus: string
      let terminalError: string | null = null
      try {
        const detail = tab === 'picturebook'
          ? await picturebookApi.get(jobId)
          : await picturebookVideoApi.get(jobId)
        terminalStatus = detail.status
        terminalError = detail.error ?? null
      } catch {
        // 详情读取失败:冻结现状,下一轮重试,绝不猜成功。
        return false
      }
      const displayed = displayedJobRef.current
      if (displayed === null || displayed.epoch !== epoch || displayed.jobId !== jobId) return true

      if (terminalStatus === 'running') {
        // 聚合接口先一步清空:保留旧摘要,下一轮再读。
        return false
      }
      // 终态确认后结束当前任务纪元:轮询链随之停止,
      // 否则 done/failed 会被每个轮询周期反复重演。
      // 节点键一并复位:下一个新任务的首个真实节点必须按新区间对待。
      displayedJobRef.current = null
      windowStartedAtRef.current = 0
      realNodeKeyRef.current = ''
      if (terminalStatus === 'done') {
        setData(prev => ({ ...prev, [tab]: payload }))
        nominalMsRef.current = null
        visualFloorRef.current = 100
        setVisual(100)
        setCompletionHold({ medium: tab, jobId })
        completionTimerRef.current = window.setTimeout(() => {
          completionTimerRef.current = null
          setCompletionHold(null)
          // 停留结束,进度条卸载;视觉基线归零,为下一个任务准备干净起点。
          visualFloorRef.current = 0
          setVisual(0)
          setReloadTick(value => value + 1)
        }, COMPLETION_HOLD_MS)
        return true
      }
      // failed:不显示 100%,立即收起进度条并给出安全文案。
      setData(prev => ({ ...prev, [tab]: payload }))
      setCompletionHold(null)
      visualFloorRef.current = 0
      setVisual(0)
      setError(terminalError || SAFE_FAILURE_MESSAGE)
      setReloadTick(value => value + 1)
      return true
    }

    const tick = async () => {
      pollTimerRef.current = null
      const jobId = active?.id ?? displayedJobRef.current?.jobId
      if (jobId === undefined) return
      let payload: FilmFolderResponse
      try {
        payload = tab === 'picturebook'
          ? await filmFolderApi.picturebooks()
          : await filmFolderApi.motionComics()
      } catch {
        // 单次失败:冻结百分比与累计区间,下一轮继续。
        updatePollHealthy(false)
        scheduleNext()
        return
      }
      const summary = payload.active_generation
      const displayed = displayedJobRef.current
      const currentEpoch = displayed !== null
        && displayed.epoch === epoch
        && displayed.jobId === jobId
      // 旧纪元的响应只允许带回「没有任务」或「换了新任务」的信号;
      // 它自己的旧任务进度永远不许回写。
      if (!currentEpoch && summary !== null && summary.id === jobId) return
      updatePollHealthy(true)

      if (summary === null) {
        if (!currentEpoch) {
          // 终态已确认过的空轮询:只需带回最新列表,不再校验。
          setData(prev => ({ ...prev, [tab]: payload }))
        } else {
          const verified = await verifyTerminal(payload, jobId)
          // 拿到终态后纪元已结束,不再排下一轮。
          if (verified) return
        }
      } else if (summary.id !== jobId) {
        // 槽位已换成别的任务:按新任务重建纪元。
        setData(prev => ({ ...prev, [tab]: payload }))
      } else {
        applySummary(payload, summary)
      }
      scheduleNext()
    }

    const scheduleNext = () => {
      const displayed = displayedJobRef.current
      if (displayed === null || displayed.epoch !== epoch) return
      if (pollTimerRef.current !== null) return
      pollTimerRef.current = window.setTimeout(tick, POLL_INTERVAL[tab])
    }

    scheduleNext()
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current)
        pollTimerRef.current = null
      }
      if (animationTimerRef.current !== null) {
        window.clearInterval(animationTimerRef.current)
        animationTimerRef.current = null
      }
    }
  }, [tab, active?.id, active === null]) // eslint-disable-line react-hooks/exhaustive-deps

  // 卸载兜底:取消所有挂起的轮询/停留/动画写入。
  useEffect(() => () => {
    progressEpochRef.current += 1
    displayedJobRef.current = null
    clearProgressTimers()
  }, [clearProgressTimers])

  const showProgress = active !== null || (completionHold !== null && completionHold.medium === tab)

  const handleCreate = () => {
    if (active || completionHold) return
    if (tab === 'picturebook') setCreateOpen(true)
    else onCreateMotionComic()
  }

  const handleOpen = (item: FilmFolderItem) => {
    if (tab === 'picturebook') onOpenPicturebook(item)
    else onOpenMotionComic(item.id)
  }

  const confirmDelete = async () => {
    if (!deleteTarget || deleteTarget.source_kind === 'video_job' || deleting) return
    setDeleting(true)
    try {
      await filmFolderApi.deletePicturebook(deleteTarget.source_kind, deleteTarget.id)
      setDeleteTarget(null)
      await loadTab('picturebook')
    } catch {
      setError('删除失败，请稍后重试')
    } finally {
      setDeleting(false)
    }
  }

  const publishToResonance = async (item: FilmFolderItem) => {
    if (item.source_kind !== 'canonical_work' || item.published || publishingId !== null) return
    setPublishingId(item.id)
    try {
      await storyApi.publish(item.id, [])
      await loadTab('picturebook')
    } catch (publishError) {
      if (publishError instanceof ApiError && publishError.status === 409) {
        setData(previous => ({
          ...previous,
          picturebook: previous.picturebook
            ? {
                ...previous.picturebook,
                items: previous.picturebook.items.map(currentItem =>
                  currentItem.id === item.id && currentItem.source_kind === item.source_kind
                    ? { ...currentItem, published: true }
                    : currentItem),
              }
            : null,
        }))
        setError(null)
      } else {
        setError('发布失败，请稍后重试')
      }
    } finally {
      setPublishingId(null)
    }
  }

  return (
    <main className="film-folder">
      <header className="film-folder-header">
        <div className="film-folder-heading">
          <h1>底片夹</h1>
          <p>收好每一本绘本与每一部漫剧</p>
        </div>
        <button
          type="button"
          className="film-folder-export"
          onClick={() => setExportOpen(true)}
        >
          <Download width={15} height={15} aria-hidden="true" />
          {tab === 'picturebook' ? '导出绘本' : '导出漫剧'}
        </button>
      </header>

      <div className="film-folder-tabs" role="tablist" aria-label="作品分区">
        {(
          [
            ['picturebook', '绘本'],
            ['motion_comic', '漫剧'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`film-folder-tab ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {showProgress && (
        <CharacterProgress
          percent={visualPercent}
          character={character}
          accessibleLabel={tab === 'picturebook' ? '绘本生成中' : '漫剧生成中'}
        />
      )}

      <button
        type="button"
        className="film-folder-create"
        onClick={handleCreate}
        disabled={Boolean(active) || completionHold !== null || current?.remaining === 0}
        title={
          active
            ? '当前作品完成后再生成'
            : current?.remaining === 0
              ? '可生成次数已用完'
              : undefined
        }
      >
        {tab === 'picturebook' ? '生成绘本' : '生成 AI 漫剧'}
        {typeof current?.remaining === 'number' && (
          <span className="film-folder-create-quota">
            {current.remaining > 0 ? `剩余 ${current.remaining} 次` : '次数用完'}
          </span>
        )}
      </button>

      {current && current.unfinished_count > 0 && (
        <button
          type="button"
          className="film-folder-continue"
          onClick={() => onContinue(tab)}
        >
          {tab === 'motion_comic'
            ? `继续生成 / 重试漫剧（${current.unfinished_count}）`
            : `继续创作（${current.unfinished_count}）`}
        </button>
      )}

      {error && (
        <div className="film-folder-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => { setError(null); void loadTab(tab) }}>重试</button>
        </div>
      )}

      {current ? (
        <>
          {tab === 'motion_comic' && current.items.length > 0 && (
            <p className="film-folder-motion-hint">还没有自己的漫剧，去生成一部吧</p>
          )}
          <MonthlyWorkCollection
            items={current.items}
            onOpen={handleOpen}
            onDelete={tab === 'picturebook' ? setDeleteTarget : undefined}
            onPublish={tab === 'picturebook' ? item => { void publishToResonance(item) } : undefined}
            publishingId={publishingId}
            emptyHint={tab === 'picturebook' ? '还没有绘本,去生成一本吧' : '还没有漫剧,去生成一部吧'}
          />
        </>
      ) : (
        !error && <p className="film-folder-loading">正在读取…</p>
      )}

      <FilmFolderCreateSheet
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreateDailyPicturebook={() => onCreateDailyPicturebook()}
        onCreateTimeStory={onCreateTimeStory}
      />
      <PdfExportSheet
        open={exportOpen}
        medium={tab}
        onClose={() => setExportOpen(false)}
      />
      <Modal
        open={deleteTarget !== null}
        onClose={() => { if (!deleting) setDeleteTarget(null) }}
        title="删除这本绘本？"
        description={deleteTarget
          ? `确定删除《${deleteTarget.title}》吗？删除后无法恢复，但不会影响原始日记。`
          : undefined}
        confirmText={deleting ? '正在删除…' : '确认删除'}
        cancelText="取消"
        danger
        onConfirm={() => { void confirmDelete() }}
      />
    </main>
  )
}
