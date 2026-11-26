import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PdfExportSheet from './index'
import type { FilmFolderItem, FilmFolderResponse } from '../../types'

vi.mock('../../api/client', () => ({
  exportApi: {
    downloadPicturebookPdf: vi.fn(),
    downloadMotionComic: vi.fn(),
  },
  filmFolderApi: {
    picturebooks: vi.fn(),
    motionComics: vi.fn(),
  },
}))

const downloadSpy = vi.fn()
vi.mock('../../utils/downloadBlob', () => ({
  downloadBlob: (...args: unknown[]) => downloadSpy(...args),
}))

import { exportApi, filmFolderApi } from '../../api/client'

const BOOK: FilmFolderItem = {
  id: 42,
  source_kind: 'canonical_work',
  work_kind: 'daily_picturebook',
  title: '雨天的一页',
  display_start_date: '2026-08-09',
  display_end_date: '2026-08-09',
  cover_url: '/cover.png',
  completed_at: '2026-08-09T10:00:00Z',
}
const VIDEO: FilmFolderItem = {
  ...BOOK,
  id: 7,
  source_kind: 'video_job',
  title: '程序员小马',
}
const response = (items: FilmFolderItem[]): FilmFolderResponse => ({
  active_generation: null,
  unfinished_count: 0,
  items,
})

describe('work export sheet', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    downloadSpy.mockClear()
    vi.mocked(filmFolderApi.picturebooks).mockResolvedValue(response([BOOK]))
    vi.mocked(filmFolderApi.motionComics).mockResolvedValue(response([VIDEO]))
    vi.mocked(exportApi.downloadPicturebookPdf).mockResolvedValue(new Blob(['pdf']))
    vi.mocked(exportApi.downloadMotionComic).mockResolvedValue(new Blob(['mp4']))
  })

  test('exports one selected picturebook as PDF', async () => {
    render(<PdfExportSheet open medium="picturebook" onClose={() => undefined} />)
    fireEvent.click(await screen.findByRole('radio', { name: /雨天的一页/ }))
    fireEvent.click(screen.getByRole('button', { name: '下载绘本 PDF' }))

    await waitFor(() => expect(exportApi.downloadPicturebookPdf)
      .toHaveBeenCalledWith('canonical_work', 42))
    expect(downloadSpy).toHaveBeenCalledWith(expect.any(Blob), '雨天的一页.pdf')
  })

  test('exports one selected motion comic as MP4', async () => {
    render(<PdfExportSheet open medium="motion_comic" onClose={() => undefined} />)
    fireEvent.click(await screen.findByRole('radio', { name: /程序员小马/ }))
    fireEvent.click(screen.getByRole('button', { name: '下载漫剧视频' }))

    await waitFor(() => expect(exportApi.downloadMotionComic).toHaveBeenCalledWith(7))
    expect(downloadSpy).toHaveBeenCalledWith(expect.any(Blob), '程序员小马.mp4')
  })

  test('keeps selection after a failed export', async () => {
    vi.mocked(exportApi.downloadPicturebookPdf).mockRejectedValue(new Error('boom'))
    render(<PdfExportSheet open medium="picturebook" onClose={() => undefined} />)
    const option = await screen.findByRole('radio', { name: /雨天的一页/ })
    fireEvent.click(option)
    fireEvent.click(screen.getByRole('button', { name: '下载绘本 PDF' }))
    await screen.findByRole('alert')
    expect(option).toBeChecked()
  })
})
