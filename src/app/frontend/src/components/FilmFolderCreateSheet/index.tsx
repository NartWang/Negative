import BottomSheet from '../BottomSheet'

export interface FilmFolderCreateSheetProps {
  open: boolean
  onClose: () => void
  onCreateDailyPicturebook: () => void
  onCreateTimeStory: () => void
}

/** 绘本分区生成入口弹窗:当日绘本 / 时光故事。 */
export default function FilmFolderCreateSheet({
  open,
  onClose,
  onCreateDailyPicturebook,
  onCreateTimeStory,
}: FilmFolderCreateSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} title="生成绘本">
      <div className="film-folder-create-options">
        <button
          type="button"
          className="film-folder-create-option"
          onClick={() => {
            onClose()
            onCreateDailyPicturebook()
          }}
        >
          当日绘本
        </button>
        <button
          type="button"
          className="film-folder-create-option"
          onClick={() => {
            onClose()
            onCreateTimeStory()
          }}
        >
          时光故事
        </button>
      </div>
    </BottomSheet>
  )
}
