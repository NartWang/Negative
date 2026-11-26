import { useCallback, useRef, useState } from 'react'
import FeedView, { type FeedViewHandle } from './FeedView'
import CollectionsView from './CollectionsView'
import CollectionDetail from './CollectionDetail'
import PublishedStoryDetail from './PublishedStoryDetail'
import InteractionSummary from './InteractionSummary'
import { Bell } from '../../components/Icon'
import './style.css'

interface ResonanceProps {
  onOpenOwnStoryWork: (workId: number) => void
  onGoStories?: () => void
}

type View = 'feed' | 'collections'

export default function Resonance({ onOpenOwnStoryWork, onGoStories }: ResonanceProps) {
  const [activeView, setActiveView] = useState<View>('feed')
  const [detailOwnerId, setDetailOwnerId] = useState<number | null>(null)
  const [publishedDetailWorkId, setPublishedDetailWorkId] = useState<number | null>(null)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [feedRefreshKey, setFeedRefreshKey] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  const feedRef = useRef<FeedViewHandle>(null)

  const openPublishedDetail = useCallback((workId: number) => {
    setPublishedDetailWorkId(workId)
  }, [])

  const closePublishedDetail = useCallback(() => {
    setPublishedDetailWorkId(null)
  }, [])

  const handleWorkGone = useCallback(() => {
    setPublishedDetailWorkId(null)
    setNotice('这个故事已不可见')
    setFeedRefreshKey(key => key + 1)
  }, [])

  const handleCollectionGone = useCallback(() => {
    setDetailOwnerId(null)
    setNotice('这个故事已不可见')
  }, [])

  const locateWorkInFeed = useCallback((workId: number) => {
    setSummaryOpen(false)
    setActiveView('feed')
    setDetailOwnerId(null)
    window.setTimeout(() => {
      void feedRef.current?.loadUntilWork(workId)
    }, 0)
  }, [])

  if (publishedDetailWorkId !== null) {
    return (
      <PublishedStoryDetail
        workId={publishedDetailWorkId}
        onBack={closePublishedDetail}
        onWorkGone={handleWorkGone}
      />
    )
  }

  return (
    <main className="resonance-page">
      <header className="resonance-header">
        <div className="resonance-titlebar">
          <h1>回响</h1>
          <button
            type="button"
            className="resonance-bell"
            aria-label="互动汇总"
            onClick={() => setSummaryOpen(true)}
          >
            <Bell />
          </button>
        </div>
        <div className="resonance-tabs" role="tablist" aria-label="回响视图">
          <button
            type="button"
            role="tab"
            aria-selected={activeView === 'feed'}
            className={activeView === 'feed' ? 'active' : ''}
            onClick={() => { setActiveView('feed'); setDetailOwnerId(null) }}
          >
            动态
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeView === 'collections'}
            className={activeView === 'collections' ? 'active' : ''}
            onClick={() => setActiveView('collections')}
          >
            收录
          </button>
        </div>
      </header>

      {notice && (
        <div className="resonance-locate-state" role="alert">
          {notice}
        </div>
      )}

      {activeView === 'feed' && (
        <FeedView
          ref={feedRef}
          key={feedRefreshKey}
          onOpenOwnStoryWork={onOpenOwnStoryWork}
          onOpenPublishedDetail={openPublishedDetail}
          onGoStories={onGoStories}
        />
      )}
      {activeView === 'collections' && detailOwnerId === null && (
        <CollectionsView onOpenOwner={setDetailOwnerId} />
      )}
      {activeView === 'collections' && detailOwnerId !== null && (
        <CollectionDetail
          ownerUserId={detailOwnerId}
          onBack={() => setDetailOwnerId(null)}
          onOpenPublishedDetail={openPublishedDetail}
          onCollectionGone={handleCollectionGone}
        />
      )}

      <InteractionSummary
        open={summaryOpen}
        onClose={() => setSummaryOpen(false)}
        onLocateWork={locateWorkInFeed}
      />
    </main>
  )
}
