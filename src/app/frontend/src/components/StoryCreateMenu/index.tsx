import { useState } from 'react'
import BottomSheet from '../BottomSheet'
import { BookOpen, MessageCircle, PenLine, Sparkle } from '../Icon'
import { getLocalDateStr } from '../../utils/date'
import './style.css'

interface Props {
  open: boolean
  date?: string
  onClose: () => void
  onCreateDiary: (date: string) => void
  onCreateDailyPicturebook: (date: string) => void
  onCreateTimeStory: () => void
  onCreateMotionComic: () => void
}

type Branch = 'root' | 'picturebook'

export default function StoryCreateMenu({
  open,
  date,
  onClose,
  onCreateDiary,
  onCreateDailyPicturebook,
  onCreateTimeStory,
  onCreateMotionComic,
}: Props) {
  const [branch, setBranch] = useState<Branch>('root')
  const [notice, setNotice] = useState('')
  const targetDate = date ?? getLocalDateStr()

  const close = () => {
    setBranch('root')
    setNotice('')
    onClose()
  }

  const createDiary = () => {
    close()
    onCreateDiary(targetDate)
  }

  const createDailyPicturebook = () => {
    close()
    onCreateDailyPicturebook(targetDate)
  }

  const createTimeStory = () => {
    close()
    onCreateTimeStory()
  }

  const createMotionComic = () => {
    close()
    onCreateMotionComic()
  }

  return (
    <BottomSheet open={open} onClose={close} title="创建故事">
      <div className="story-create-menu">
        {branch === 'root' ? (
          <div className="story-create-actions">
            <button type="button" className="story-create-row" onClick={createDiary}>
              <span className="story-create-icon"><PenLine /></span>
              <span>
                <strong>生成日记</strong>
                <small>写今天</small>
              </span>
            </button>
            <button type="button" className="story-create-row" onClick={() => setBranch('picturebook')}>
              <span className="story-create-icon"><BookOpen /></span>
              <span>
                <strong>生成绘本</strong>
                <small>从日记出发</small>
              </span>
            </button>
            <button
              type="button"
              className="story-create-row"
              onClick={createMotionComic}
            >
              <span className="story-create-icon"><MessageCircle /></span>
              <span>
                <strong>生成漫剧</strong>
                <small>选择绘本页</small>
              </span>
            </button>
          </div>
        ) : (
          <div className="story-create-actions">
            <button type="button" className="story-create-row" onClick={createDailyPicturebook}>
              <span className="story-create-icon"><BookOpen /></span>
              <span>
                <strong>当日绘本</strong>
                <small>{targetDate}</small>
              </span>
            </button>
            <button type="button" className="story-create-row" onClick={createTimeStory}>
              <span className="story-create-icon"><Sparkle /></span>
              <span>
                <strong>时光故事</strong>
                <small>按一段时间生成</small>
              </span>
            </button>
          </div>
        )}

        {notice && <p className="story-create-notice" role="status">{notice}</p>}
      </div>
    </BottomSheet>
  )
}
