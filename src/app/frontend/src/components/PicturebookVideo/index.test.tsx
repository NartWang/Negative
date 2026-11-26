import { beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PicturebookVideo from './index'

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) { super(message) }
  },
  picturebookVideoApi: {
    latest: vi.fn(async () => null),
    start: vi.fn(),
    get: vi.fn(),
    retry: vi.fn(),
  },
}))

import { picturebookVideoApi } from '../../api/client'

const runningJob = {
  id: 99, picturebook_job_id: 201, work_id: null, style: 'pixel',
  status: 'running', stage: 'rendering', stage_label: '正在让画面动起来',
  error: null, include_cover: false, segment_duration: 5, ratio: '16:9',
  total_segments: 2, ready_segments: 0, duration_seconds: null,
  video_url: null, created_at: 't', updated_at: 't',
  segments: [
    { segment_index: 1, first_page_index: 1, last_page_index: 2, status: 'pending', error: null },
    { segment_index: 2, first_page_index: 2, last_page_index: 3, status: 'pending', error: null },
  ],
}

describe('PicturebookVideo draft awareness', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(picturebookVideoApi.start).mockResolvedValue(runningJob as never)
  })

  test('start includes draft_id when supplied', async () => {
    render(
      <PicturebookVideo
        source={{ kind: 'work', id: 42 }}
        pageIndexes={[1, 2, 3]}
        draftId={7}
      />,
    )
    await waitFor(() => expect(picturebookVideoApi.latest).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: /生成绘本视频/ }))
    await waitFor(() => expect(picturebookVideoApi.start).toHaveBeenCalled())
    expect(vi.mocked(picturebookVideoApi.start).mock.calls[0][1]).toEqual({
      page_indexes: [1, 2, 3],
      draft_id: 7,
    })
  })

  test('legacy start omits draft_id entirely', async () => {
    render(
      <PicturebookVideo source={{ kind: 'job', id: 9 }} pageIndexes={[1, 2]} />,
    )
    await waitFor(() => expect(picturebookVideoApi.latest).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: /生成绘本视频/ }))
    await waitFor(() => expect(picturebookVideoApi.start).toHaveBeenCalled())
    expect(vi.mocked(picturebookVideoApi.start).mock.calls[0][1]).toEqual({
      page_indexes: [1, 2],
    })
  })
})
