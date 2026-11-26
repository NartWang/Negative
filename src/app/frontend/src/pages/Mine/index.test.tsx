import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import Mine from './index'
import {
  profileApi,
  characterApi,
  storyApi,
  subscriptionsApi,
  uploadApi,
} from '../../api/client'
import { ToastProvider } from '../../contexts/ToastContext'
import type { CharacterProfile, Profile, Subscription } from '../../types'

const authState = vi.hoisted(() => ({ userId: 1, nickname: '小满' }))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: authState.userId,
      nickname: authState.nickname,
      avatar_url: null,
      signature: null,
      created_at: '2026-08-01T08:00:00Z',
    },
    status: 'ready',
    bootstrapError: null,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    profileApi: { ...actual.profileApi, get: vi.fn(), update: vi.fn() },
    exportApi: { ...actual.exportApi, downloadPdf: vi.fn() },
    uploadApi: { ...actual.uploadApi, upload: vi.fn() },
    characterApi: {
      ...actual.characterApi,
      get: vi.fn(),
      update: vi.fn(),
      generate: vi.fn(),
    },
    storyApi: { ...actual.storyApi, listWorks: vi.fn() },
    subscriptionsApi: {
      ...actual.subscriptionsApi,
      following: vi.fn(),
      audience: vi.fn(),
      createInvite: vi.fn(),
      joinInvite: vi.fn(),
      remove: vi.fn(),
    },
  }
})

const profile = (overrides: Partial<Profile> = {}): Profile => ({
  id: 1,
  nickname: '小满',
  avatar_url: null,
  signature: '',
  created_at: '2026-08-01T08:00:00Z',
  ...overrides,
})

const character = (overrides: Partial<CharacterProfile> = {}): CharacterProfile => ({
  user_id: 1,
  source_photo_url: null,
  reference_image_url: null,
  character_description: '',
  nickname: '',
  display_action: null,
  source_type: '',
  version: 0,
  created_at: null,
  updated_at: null,
  ...overrides,
})

const subscription = (
  id: number,
  direction: 'audience' | 'following',
  nickname = '阿禾',
): Subscription => ({
  id,
  owner_user_id: direction === 'following' ? 99 : 1,
  subscriber_user_id: direction === 'audience' ? 99 : 1,
  status: 'active',
  owner: direction === 'following' ? { id: 99, nickname, avatar_url: null } : undefined,
  subscriber: direction === 'audience' ? { id: 99, nickname, avatar_url: null } : undefined,
  created_at: '2026-08-04T08:00:00Z',
})

function renderMine() {
  render(
    <ToastProvider>
      <Mine userId={1} />
    </ToastProvider>,
  )
}

/** Relationship management now lives behind the 「关注与粉丝」setting row. */
async function openRelationships(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /关注与粉丝/ }))
  return screen.findByText('看见我的人')
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(profileApi.get).mockResolvedValue(profile())
  vi.mocked(characterApi.get).mockResolvedValue(character())
  vi.mocked(storyApi.listWorks).mockResolvedValue([])
  vi.mocked(subscriptionsApi.following).mockResolvedValue([])
  vi.mocked(subscriptionsApi.audience).mockResolvedValue([])
  vi.mocked(subscriptionsApi.createInvite).mockResolvedValue({
    id: 'inv-1',
    code: 'ABCD-EFGH-JKMP-QRST',
    expires_at: '2026-08-08T08:00:00Z',
  })
  vi.mocked(subscriptionsApi.joinInvite).mockResolvedValue(subscription(10, 'following'))
})

describe('Mine · 我的小主角', () => {
  test('with no character it invites the user to pick one', async () => {
    renderMine()

    expect(await screen.findByRole('heading', { name: '我的小主角' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '还没有小主角' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '选一位日记小主角' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /修改角色昵称/ })).not.toBeInTheDocument()
  })

  test('a confirmed preset character shows its name, book count and action set', async () => {
    vi.mocked(characterApi.get).mockResolvedValue(character({
      reference_image_url: '/characters/main/p02.webp',
      character_description: '阿禾 · 温柔细腻',
      nickname: '阿禾',
      display_action: 'idle',
      source_type: 'preset',
      version: 1,
    }))
    vi.mocked(storyApi.listWorks).mockResolvedValue([
      { id: 1 }, { id: 2 }, { id: 3 },
    ] as unknown as Awaited<ReturnType<typeof storyApi.listWorks>>)

    renderMine()

    expect(await screen.findByRole('heading', { name: '阿禾' })).toBeInTheDocument()
    expect(screen.getByText('已陪你完成 3 本绘本')).toBeInTheDocument()
    const actions = screen.getByRole('group', { name: '更换展示动作' })
    expect(within(actions).getByRole('button', { name: /日常/ })).toHaveAttribute('aria-pressed', 'true')
    expect(within(actions).getByRole('button', { name: /阅读/ })).toBeInTheDocument()
  })

  test('switching the display action persists it through characterApi', async () => {
    vi.mocked(characterApi.get).mockResolvedValue(character({
      reference_image_url: '/characters/main/p02.webp',
      nickname: '阿禾',
      display_action: 'idle',
      source_type: 'preset',
      version: 1,
    }))
    vi.mocked(characterApi.update).mockImplementation(async data => character({
      reference_image_url: '/characters/main/p02.webp',
      nickname: '阿禾',
      source_type: 'preset',
      version: 2,
      ...data,
    } as Partial<CharacterProfile>))
    const user = userEvent.setup()
    renderMine()

    const actions = await screen.findByRole('group', { name: '更换展示动作' })
    await user.click(within(actions).getByRole('button', { name: /思考/ }))

    await waitFor(() => expect(characterApi.update).toHaveBeenCalledWith({ display_action: 'think' }))
  })

  test('renaming the character only sends the nickname', async () => {
    vi.mocked(characterApi.get).mockResolvedValue(character({
      reference_image_url: '/characters/main/p03.webp',
      nickname: '小夏',
      source_type: 'preset',
      version: 1,
    }))
    vi.mocked(characterApi.update).mockResolvedValue(character({
      reference_image_url: '/characters/main/p03.webp',
      nickname: '夏夏',
      source_type: 'preset',
      version: 2,
    }))
    const user = userEvent.setup()
    renderMine()

    await user.click(await screen.findByRole('button', { name: /修改角色昵称/ }))
    const input = await screen.findByLabelText('给 TA 起个名字')
    await user.clear(input)
    await user.type(input, '夏夏')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(characterApi.update).toHaveBeenCalledWith({ nickname: '夏夏' }))
    expect(await screen.findByRole('heading', { name: '夏夏' })).toBeInTheDocument()
  })

  test('creation preferences and profile editing are no longer surfaced here', async () => {
    renderMine()

    expect(await screen.findByRole('heading', { name: '角色设置' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /我的创作偏好/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编辑我的资料/ })).not.toBeInTheDocument()
    // What remains is the character itself, relationships and the account.
    expect(screen.getByRole('button', { name: /选一位小主角/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /关注与粉丝/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /账号/ })).toBeInTheDocument()
  })
})

describe('Mine · 角色创建流程', () => {
  test('entry screen offers both equal creation routes', async () => {
    const user = userEvent.setup()
    renderMine()

    await user.click(await screen.findByRole('button', { name: '选一位日记小主角' }))

    expect(await screen.findByRole('heading', { name: '选一位日记小主角' })).toBeInTheDocument()
    expect(screen.getByText('TA 会陪你走进之后的每一本日记绘本')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /直接选角色/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /生成我的角色/ })).toBeInTheDocument()
    expect(screen.getByText('照片只用于创建角色，可在生成后删除')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /先写日记，稍后再选/ })).toBeInTheDocument()
  })

  test('preset grid filters by category and confirms the chosen character', async () => {
    vi.mocked(characterApi.update).mockResolvedValue(character({
      reference_image_url: '/characters/main/p13.webp',
      character_description: '云奶奶 · 慈爱温暖',
      nickname: '云奶奶',
      source_type: 'preset',
      version: 1,
    }))
    const user = userEvent.setup()
    renderMine()

    await user.click(await screen.findByRole('button', { name: '选一位日记小主角' }))
    await user.click(await screen.findByRole('button', { name: /直接选角色/ }))

    expect(await screen.findByText('33 个现成角色 · 不需要照片')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /云奶奶/ })).toBeInTheDocument()

    // 长辈 only holds two characters, so filtering must drop the rest.
    await user.click(screen.getByRole('tab', { name: '长辈' }))
    expect(screen.getByRole('button', { name: /云奶奶/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /小豆/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /云奶奶/ }))
    expect(screen.getByText('云奶奶', { selector: 'strong' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /看看 TA 在绘本里的样子/ }))

    expect(await screen.findByRole('heading', { name: '确认我的小主角' })).toBeInTheDocument()
    expect(screen.getByText('这是你想在故事里成为的样子吗？')).toBeInTheDocument()
    // Every preset ships a four-action set, so the display action defaults to idle.
    expect(screen.getByRole('group', { name: '展示动作' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '就用 TA 作为我的小主角' }))

    await waitFor(() => expect(characterApi.update).toHaveBeenCalledWith({
      reference_image_url: '/characters/main/p13.webp',
      source_photo_url: null,
      character_description: '云奶奶 · 慈爱温暖',
      nickname: '云奶奶',
      display_action: 'idle',
      source_type: 'preset',
    }))
    expect(await screen.findByRole('heading', { name: '云奶奶' })).toBeInTheDocument()
  })

  test('the confirm step can go back to browse other characters', async () => {
    const user = userEvent.setup()
    renderMine()

    await user.click(await screen.findByRole('button', { name: '选一位日记小主角' }))
    await user.click(await screen.findByRole('button', { name: /直接选角色/ }))
    await user.click(await screen.findByRole('button', { name: /橘子/ }))
    await user.click(screen.getByRole('button', { name: /看看 TA 在绘本里的样子/ }))
    await user.click(await screen.findByRole('button', { name: '再看看其他角色' }))

    expect(await screen.findByRole('heading', { name: '选择小主角' })).toBeInTheDocument()
    expect(characterApi.update).not.toHaveBeenCalled()
  })

  test('the photo route uploads then generates a pixel character master', async () => {
    vi.mocked(uploadApi.upload).mockResolvedValue({
      asset_id: 'asset-7',
      url: '/api/media/asset-7',
    } as Awaited<ReturnType<typeof uploadApi.upload>>)
    vi.mocked(characterApi.generate).mockResolvedValue(character({
      source_photo_url: '/api/media/asset-7',
      reference_image_url: '/api/media/asset-9',
      character_description: '短发，常背帆布包',
      nickname: '小满',
      source_type: 'photo_generated',
      version: 1,
    }))
    const user = userEvent.setup()
    renderMine()

    await user.click(await screen.findByRole('button', { name: '选一位日记小主角' }))
    await user.click(await screen.findByRole('button', { name: /生成我的角色/ }))

    const generate = await screen.findByRole('button', { name: '生成我的角色' })
    // Nothing can be generated before a photo exists.
    expect(generate).toBeDisabled()

    const file = new File(['x'], 'me.png', { type: 'image/png' })
    await user.upload(screen.getByLabelText('上传照片'), file)
    await waitFor(() => expect(uploadApi.upload).toHaveBeenCalledWith(file))

    await user.type(await screen.findByLabelText('请描述你自己（可选）'), '短发，常背帆布包')
    await user.click(await screen.findByRole('button', { name: '生成我的角色' }))

    await waitFor(() => expect(characterApi.generate).toHaveBeenCalledWith({
      source_photo_asset_id: 'asset-7',
      source_photo_url: '/api/media/asset-7',
      character_description: '短发，常背帆布包',
      nickname: '',
    }))
    // The generated master, not the raw photo, is what the confirm step shows.
    expect(await screen.findByRole('heading', { name: '确认我的小主角' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /小主角|小满/ })).toHaveAttribute(
      'src', '/api/media/asset-9',
    )
    expect(screen.getByRole('button', { name: '重新生成整套' })).toBeInTheDocument()
  })
})

describe('Mine · 关注与粉丝', () => {
  test('renders directional sections 看见我的人 and 我关心的人 with counts', async () => {
    vi.mocked(subscriptionsApi.audience).mockResolvedValue([
      subscription(1, 'audience', '阿禾'),
      subscription(2, 'audience', '小蓝'),
    ])
    vi.mocked(subscriptionsApi.following).mockResolvedValue([
      subscription(3, 'following', '小溪'),
    ])
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)

    expect(screen.getByText('我关心的人')).toBeInTheDocument()
    expect(screen.getByText('2 人')).toBeInTheDocument()
    expect(screen.getByText('1 人')).toBeInTheDocument()
  })

  test('create invite displays the invite code', async () => {
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)
    await user.click(screen.getByRole('button', { name: '邀请' }))
    await user.click(await screen.findByRole('button', { name: '生成邀请码' }))

    expect(await screen.findByLabelText('邀请码')).toHaveTextContent('ABCD-EFGH-JKMP-QRST')
    expect(subscriptionsApi.createInvite).toHaveBeenCalledOnce()
  })

  test('join-code submission calls joinInvite and refreshes both lists', async () => {
    vi.mocked(subscriptionsApi.following)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([subscription(3, 'following', '小溪')])
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)
    await user.click(screen.getByRole('button', { name: '加入' }))

    const input = await screen.findByLabelText('邀请码')
    await user.type(input, 'CODE-1234')
    const joinButtons = screen.getAllByRole('button', { name: '加入' })
    await user.click(joinButtons[joinButtons.length - 1])

    await waitFor(() => expect(subscriptionsApi.joinInvite).toHaveBeenCalledWith('CODE-1234'))
    await waitFor(() => expect(subscriptionsApi.following).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(subscriptionsApi.audience).toHaveBeenCalledTimes(2))
  })

  test('leave confirms then calls remove(id); API error preserves state', async () => {
    vi.mocked(subscriptionsApi.audience).mockResolvedValue([subscription(1, 'audience', '阿禾')])
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(subscriptionsApi.remove).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)
    await user.click(screen.getByRole('button', { name: '退出关系' }))

    await waitFor(() => expect(subscriptionsApi.remove).toHaveBeenCalledWith(1))
    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(await screen.findByRole('alert')).toHaveTextContent('退出关系失败')
    expect(screen.getByText('阿禾')).toBeInTheDocument()
  })

  test('successful leave refreshes both lists and clears the row', async () => {
    vi.mocked(subscriptionsApi.audience)
      .mockResolvedValueOnce([subscription(1, 'audience', '阿禾')])
      .mockResolvedValue([])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)
    await user.click(screen.getByRole('button', { name: '退出关系' }))

    await waitFor(() => expect(screen.queryByText('阿禾')).not.toBeInTheDocument())
    await waitFor(() => expect(subscriptionsApi.following).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(subscriptionsApi.audience).toHaveBeenCalledTimes(2))
  })

  test('create invite API error preserves state and shows a relationship error', async () => {
    vi.mocked(subscriptionsApi.createInvite).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    renderMine()

    await openRelationships(user)
    await user.click(screen.getByRole('button', { name: '邀请' }))
    await user.click(await screen.findByRole('button', { name: '生成邀请码' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法生成邀请码')
    expect(screen.getByRole('button', { name: '生成邀请码' })).not.toBeDisabled()
  })
})
