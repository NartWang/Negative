import { useEffect, useState } from 'react'
import Today from './pages/Today'
import Diary from './pages/Diary'
import FilmFolder from './pages/FilmFolder'
import Mine from './pages/Mine'
import DiaryEditor from './pages/DiaryEditor'
import DiaryNotebook from './pages/DiaryNotebook'
import MotionComicWork from './pages/MotionComicWork'
import PicturebookWorkReader from './pages/PicturebookWorkReader'
import StoryDay from './pages/StoryDay'
import StoryDrafts from './pages/StoryDrafts'
import StoryWork from './pages/StoryWork'
import UnfinishedWorks from './pages/UnfinishedWorks'
import Auth from './pages/Auth'
import Resonance from './pages/Resonance'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { DateProvider } from './contexts/DateContext'
import { ToastProvider } from './contexts/ToastContext'
import Toast from './components/Toast'
import DailyPicturebookWizard from './components/DailyPicturebookWizard'
import TimeStoryWizard from './components/TimeStoryWizard'
import MotionComicWizard from './components/MotionComicWizard'
import PictureBookReader from './components/PictureBookReader'
import WeeklyComicResultModal from './components/WeeklyComic/ResultModal'
import StoryCreateMenu from './components/StoryCreateMenu'
import { ArrowLeft, BookOpen, MessageCircle, PenLine, UserRound } from './components/Icon'
import {
  isGenerationSlotConflict,
  picturebookApi,
  picturebookVideoApi,
  storyApi,
  weeklyComicApi,
} from './api/client'
import type { DiaryEditorRequest, FilmFolderMedium, StoryViewRequest, WeeklyComic } from './types'
import './App.css'

type Tab = 'record' | 'stories' | 'resonance' | 'mine'

function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="app-loading" role="status">
      <span className="loading-mark" aria-hidden="true">底片</span>
      <p>{label}</p>
    </main>
  )
}

function LegacyWeeklyComicView({ comicId, onBack }: { comicId: number; onBack: () => void }) {
  const [comic, setComic] = useState<WeeklyComic | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    weeklyComicApi.list()
      .then(items => {
        if (cancelled) return
        const found = items.find(item => item.id === comicId) ?? null
        if (found) {
          setComic(found)
        } else {
          setError('周漫画暂时打不开')
        }
      })
      .catch(() => {
        if (!cancelled) setError('周漫画暂时打不开')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [comicId])

  if (loading || error || !comic) {
    return (
      <main className="app-reader-page">
        <button type="button" className="app-reader-back" onClick={onBack} aria-label="返回故事">
          <ArrowLeft />
        </button>
        <div className="app-loading" role={error ? 'alert' : 'status'}>
          <p>{error ?? '正在读取周漫画…'}</p>
        </div>
      </main>
    )
  }

  return (
    <main className="app-reader-page">
      <button type="button" className="app-reader-back" onClick={onBack} aria-label="返回故事">
        <ArrowLeft />
      </button>
      <WeeklyComicResultModal
        comic={comic}
        onClose={onBack}
        onRetry={() => undefined}
        onShare={() => undefined}
        onDelete={() => undefined}
        readOnly
      />
    </main>
  )
}

function Shell() {
  const [activeTab, setActiveTab] = useState<Tab>('mine')
  const [editorRequest, setEditorRequest] = useState<DiaryEditorRequest | null>(null)
  const [storyRequest, setStoryRequest] = useState<StoryViewRequest | null>(null)
  const [notebookDate, setNotebookDate] = useState<string | null>(null)
  const [filmFolderMedium, setFilmFolderMedium] = useState<FilmFolderMedium>('picturebook')
  const userId = useAuth().user?.id

  const tabs: { key: Tab; label: string; icon: JSX.Element }[] = [
    { key: 'record', label: '记录', icon: <PenLine /> },
    { key: 'stories', label: '底片夹', icon: <BookOpen /> },
    { key: 'resonance', label: '回响', icon: <MessageCircle /> },
    { key: 'mine', label: '我的', icon: <UserRound /> },
  ]

  if (editorRequest) {
    return (
      <DiaryEditor
        userId={userId}
        date={editorRequest.date}
        selection={editorRequest.selection}
        onBack={() => setEditorRequest(null)}
        onChangeDate={date => setEditorRequest({ date })}
      />
    )
  }

  if (notebookDate) {
    return <DiaryNotebook initialDate={notebookDate} onBack={() => setNotebookDate(null)} />
  }

  if (storyRequest?.kind === 'day') {
    return (
      <StoryDay
        date={storyRequest.date}
        onBack={() => setStoryRequest(null)}
        onOpenPicturebook={(title, pages) => setStoryRequest({
          kind: 'picturebook_reader',
          title,
          pages,
          returnDate: storyRequest.date,
        })}
      />
    )
  }

  if (storyRequest?.kind === 'daily_picturebook') {
    return (
      <DailyPicturebookWizard
        userId={userId}
        date={storyRequest.date}
        workId={storyRequest.workId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'time_story') {
    return (
      <TimeStoryWizard
        userId={userId}
        workId={storyRequest.workId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'motion_comic') {
    return (
      <MotionComicWizard
        loadPicturebooks={() => storyApi.picturebooks()}
        draftId={storyRequest.draftId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'film_picturebook') {
    return (
      <PicturebookWorkReader
        sourceKind={storyRequest.sourceKind}
        sourceId={storyRequest.sourceId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'film_motion_comic') {
    return (
      <MotionComicWork
        videoJobId={storyRequest.videoJobId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'unfinished') {
    const medium = storyRequest.medium
    return (
      <UnfinishedWorks
        medium={medium}
        onBack={() => setStoryRequest(null)}
        onOpenPicturebook={item => {
          // canonical 作品的 id 恒为 work_id,按它进入创作向导。
          if (item.source_kind === 'canonical_work') {
            setStoryRequest({
              kind: item.work_kind === 'time_story' ? 'time_story' : 'daily_picturebook',
              workId: item.id,
            })
          }
        }}
        onRetryPicturebook={async item => {
          if (item.job_id === null) return
          try {
            await picturebookApi.retry(item.job_id)
            setStoryRequest(null)
          } catch (error) {
            // 同分区已有任务在跑:回底片夹展示进行中的进度。
            if (isGenerationSlotConflict(error, 'picturebook')) {
              setStoryRequest(null)
              return
            }
            throw error
          }
        }}
        onOpenMotionDraft={item => {
          setStoryRequest({ kind: 'motion_comic', draftId: item.id })
        }}
        onRetryMotionComic={async item => {
          if (item.video_job_id === null) return
          try {
            await picturebookVideoApi.retry(item.video_job_id)
            setStoryRequest(null)
          } catch (error) {
            if (isGenerationSlotConflict(error, 'motion_comic')) {
              setStoryRequest(null)
              return
            }
            throw error
          }
        }}
      />
    )
  }

  if (storyRequest?.kind === 'story_work') {
    const returnToResonance = storyRequest.from === 'resonance'
    return (
      <StoryWork
        workId={storyRequest.workId}
        onBack={() => {
          setStoryRequest(null)
          if (returnToResonance) setActiveTab('resonance')
        }}
        onOpenDraft={workId => setStoryRequest({ kind: 'time_story', workId })}
      />
    )
  }

  if (storyRequest?.kind === 'legacy_weekly') {
    return (
      <LegacyWeeklyComicView
        comicId={storyRequest.comicId}
        onBack={() => setStoryRequest(null)}
      />
    )
  }

  if (storyRequest?.kind === 'picturebook_reader') {
    const returnDate = storyRequest.returnDate
    const returnWorkId = storyRequest.returnWorkId
    return (
      <main className="app-reader-page">
        <button
          type="button"
          className="app-reader-back"
          onClick={() => setStoryRequest(
            returnWorkId ? { kind: 'story_work', workId: returnWorkId }
              : returnDate ? { kind: 'day', date: returnDate }
                : null,
          )}
          aria-label="返回故事"
        >
          <ArrowLeft />
        </button>
        <PictureBookReader pages={storyRequest.pages} title={storyRequest.title} />
      </main>
    )
  }

  if (storyRequest?.kind === 'story_drafts') {
    return (
      <StoryDrafts
        onBack={() => setStoryRequest(null)}
        onOpenDiaryDraft={date => {
          setStoryRequest(null)
          setEditorRequest({ date })
        }}
        onOpenStoryDraft={(workId, kind) => setStoryRequest({
          kind: kind === 'time_story' ? 'time_story' : 'daily_picturebook',
          workId,
        })}
      />
    )
  }

  const createMenuOpen = storyRequest?.kind === 'create_menu'

  return (
    <div className="app">
      <div className="app-content">
        {activeTab === 'record' && (
          <div key="record" className="tab-fade">
            <Today onOpenEditor={setEditorRequest} onOpenNotebook={setNotebookDate} />
          </div>
        )}
        {activeTab === 'stories' && (
          <div key="stories" className="tab-fade">
            <FilmFolder
              initialMedium={filmFolderMedium}
              onCreateDailyPicturebook={date => setStoryRequest({
                kind: 'daily_picturebook',
                date,
              })}
              onCreateTimeStory={() => setStoryRequest({ kind: 'time_story' })}
              onCreateMotionComic={draftId => setStoryRequest({
                kind: 'motion_comic',
                draftId,
              })}
              onContinue={medium => setStoryRequest({ kind: 'unfinished', medium })}
              onOpenPicturebook={item => {
                setFilmFolderMedium('picturebook')
                setStoryRequest({
                  kind: 'film_picturebook',
                  sourceKind: item.source_kind as 'canonical_work' | 'historical_job',
                  sourceId: item.id,
                })
              }}
              onOpenMotionComic={videoJobId => {
                setFilmFolderMedium('motion_comic')
                setStoryRequest({ kind: 'film_motion_comic', videoJobId })
              }}
            />
          </div>
        )}
        {activeTab === 'resonance' && (
          <div key="resonance" className="tab-fade">
            <Resonance
              onOpenOwnStoryWork={workId => setStoryRequest({
                kind: 'story_work',
                workId,
                from: 'resonance',
              })}
              onGoStories={() => setActiveTab('stories')}
            />
          </div>
        )}
        {activeTab === 'mine' && (
          <div key="mine" className="tab-fade">
            <Mine userId={userId} onGoStories={() => setActiveTab('stories')} />
          </div>
        )}
      </div>
      <nav className="tab-bar" aria-label="主导航">
        {tabs.map(tab => (
          <button
            key={tab.key}
            type="button"
            className={`tab-item ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
            aria-current={activeTab === tab.key ? 'page' : undefined}
          >
            <span className="tab-icon" aria-hidden="true">{tab.icon}</span>
            <span className="tab-label">{tab.label}</span>
          </button>
        ))}
      </nav>
      <StoryCreateMenu
        open={createMenuOpen}
        date={storyRequest?.kind === 'create_menu' ? storyRequest.date : undefined}
        onClose={() => setStoryRequest(null)}
        onCreateDiary={date => {
          setStoryRequest(null)
          setEditorRequest({ date })
        }}
        onCreateDailyPicturebook={date => setStoryRequest({ kind: 'daily_picturebook', date })}
        onCreateTimeStory={() => setStoryRequest({ kind: 'time_story' })}
        onCreateMotionComic={() => setStoryRequest({ kind: 'motion_comic' })}
      />
    </div>
  )
}

function ApplicationState() {
  const { user, status } = useAuth()
  if (status === 'loading') return <LoadingScreen label="正在确认账号…" />
  if (!user) return <Auth />
  return (
    <DateProvider>
      <ToastProvider>
        <Toast />
        <Shell />
      </ToastProvider>
    </DateProvider>
  )
}

export default function App() {
  return <AuthProvider><ApplicationState /></AuthProvider>
}
