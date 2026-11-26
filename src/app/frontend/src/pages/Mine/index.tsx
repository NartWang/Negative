import { useEffect, useState } from 'react'
import {
  characterApi,
  profileApi,
  storyApi,
  subscriptionsApi,
} from '../../api/client'
import type {
  CharacterProfile,
  Profile,
  Subscription,
} from '../../types'
import { useToast } from '../../contexts/ToastContext'
import { useAuth } from '../../contexts/AuthContext'
import BottomSheet from '../../components/BottomSheet'
import PixelSprite from '../../components/PixelSprite'
import { Check, ChevronRight, Pencil } from '../../components/Icon'
import CharacterFlow from './CharacterFlow'
import {
  ACTION_LABELS,
  actionUrl,
  presetOf,
  sceneUrl,
  type ActionKey,
} from './characterPresets'
import './theme.css'
import './style.css'

type Sheet = 'nickname' | 'relations' | 'account'

interface Props {
  userId?: number
  /** Jump to the stories tab so the character can star in a new picture book. */
  onGoStories?: () => void
}

export default function Mine({ onGoStories }: Props) {
  const toast = useToast()
  const { user, logout } = useAuth()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [character, setCharacter] = useState<CharacterProfile | null>(null)
  const [workCount, setWorkCount] = useState(0)
  const [following, setFollowing] = useState<Subscription[]>([])
  const [audience, setAudience] = useState<Subscription[]>([])
  const [flowOpen, setFlowOpen] = useState(false)
  const [sheet, setSheet] = useState<Sheet | null>(null)
  const [nicknameDraft, setNicknameDraft] = useState('')
  const [savingNickname, setSavingNickname] = useState(false)

  const [relationMode, setRelationMode] = useState<'list' | 'invite' | 'join'>('list')
  const [inviteResult, setInviteResult] = useState<{ code: string; expires_at: string } | null>(null)
  const [joinCode, setJoinCode] = useState('')
  const [relationshipBusy, setRelationshipBusy] = useState(false)
  const [relationshipError, setRelationshipError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [accountBusy, setAccountBusy] = useState(false)
  const [accountError, setAccountError] = useState<string | null>(null)

  const refreshRelationships = async () => {
    const [nextFollowing, nextAudience] = await Promise.all([
      subscriptionsApi.following(),
      subscriptionsApi.audience(),
    ])
    setFollowing(nextFollowing)
    setAudience(nextAudience)
  }

  useEffect(() => {
    profileApi.get().then(setProfile).catch(() => toast.error('加载资料失败'))
    characterApi.get().then(setCharacter).catch(() => {})
    storyApi.listWorks().then(works => setWorkCount(works.length)).catch(() => {})
    refreshRelationships().catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast])

  const preset = presetOf(character)
  const heroSrc = character?.reference_image_url || character?.source_photo_url || null
  const characterName = character?.nickname?.trim() || preset?.name || ''
  const hasCharacter = Boolean(heroSrc)
  const availableActions = preset?.actions ?? []
  const activeAction = (character?.display_action as ActionKey | null) ?? availableActions[0] ?? null
  const heroDisplaySrc =
    preset && activeAction && availableActions.includes(activeAction)
      ? actionUrl(preset.id, activeAction)
      : heroSrc

  const openSheet = (next: Sheet) => {
    setRelationshipError(null)
    if (next === 'nickname') setNicknameDraft(characterName)
    if (next === 'relations') { setRelationMode('list'); setInviteResult(null) }
    setSheet(next)
  }

  const pickAction = async (action: ActionKey) => {
    if (!character) return
    const previous = character
    setCharacter({ ...character, display_action: action })
    try {
      setCharacter(await characterApi.update({ display_action: action }))
    } catch {
      setCharacter(previous)
      toast.error('切换展示动作失败')
    }
  }

  const saveNickname = async () => {
    const value = nicknameDraft.trim()
    if (!value) return
    setSavingNickname(true)
    try {
      setCharacter(await characterApi.update({ nickname: value }))
      setSheet(null)
      toast.success('已保存')
    } catch {
      toast.error('保存失败')
    } finally {
      setSavingNickname(false)
    }
  }

  const createInvite = async () => {
    setRelationshipBusy(true)
    setRelationshipError(null)
    try {
      setInviteResult(await subscriptionsApi.createInvite())
      toast.success('邀请码已生成')
    } catch {
      setRelationshipError('暂时无法生成邀请码')
    } finally {
      setRelationshipBusy(false)
    }
  }

  const joinInvite = async () => {
    const code = joinCode.trim()
    if (!code) return
    setRelationshipBusy(true)
    setRelationshipError(null)
    try {
      await subscriptionsApi.joinInvite(code)
      setJoinCode('')
      setRelationMode('list')
      await refreshRelationships()
      toast.success('已建立关系')
    } catch {
      setRelationshipError('邀请码不可用或已过期')
    } finally {
      setRelationshipBusy(false)
    }
  }

  const removeRelationship = async (
    subscription: Subscription,
    direction: 'audience' | 'following',
  ) => {
    const person = direction === 'audience'
      ? subscription.subscriber?.nickname
      : subscription.owner?.nickname
    const label = person ?? '这位用户'
    const message = direction === 'audience'
      ? `退出与「${label}」的可见关系吗？对方将看不到你已授权的作品。`
      : `退出与「${label}」的关注关系吗？你将看不到对方授权给你的作品。`
    if (!window.confirm(message)) return
    setRemovingId(subscription.id)
    setRelationshipError(null)
    try {
      await subscriptionsApi.remove(subscription.id)
      await refreshRelationships()
      toast.success('关系已退出')
    } catch {
      setRelationshipError('退出关系失败')
    } finally {
      setRemovingId(null)
    }
  }

  const runLogout = async () => {
    setAccountBusy(true)
    setAccountError(null)
    try { await logout() }
    catch { setAccountError('退出失败，请稍后重试') }
    finally { setAccountBusy(false) }
  }

  if (!profile) {
    return <div className="page mine-page mine-scope"><p style={{ padding: 20 }} className="muted">加载中…</p></div>
  }

  if (flowOpen) {
    return (
      <CharacterFlow
        character={character}
        mode={hasCharacter ? 'change' : 'create'}
        onClose={() => setFlowOpen(false)}
        onSaved={next => {
          setCharacter(next)
          setFlowOpen(false)
          toast.success('小主角已确认')
        }}
      />
    )
  }

  return (
    <div className="page mine-page mine-scope">
      <h1 className="mine-page-title">我的小主角</h1>

      <section className="hero-card" aria-labelledby="hero-name">
        <div className={`hero-stage ${hasCharacter ? 'has-scene' : ''}`}>
          {hasCharacter ? (
            <img
              className="hero-scene"
              src={sceneUrl(activeAction ?? 'idle')}
              alt=""
              aria-hidden="true"
            />
          ) : (
            <div className="hero-glow" aria-hidden="true" />
          )}
          <PixelSprite
            src={heroDisplaySrc}
            alt={hasCharacter ? (characterName || '我的小主角') : '还没有小主角'}
            eager
            className="hero-sprite"
          />
          <div className="hero-shadow" aria-hidden="true" />
        </div>

        {hasCharacter ? (
          <>
            <h2 className="hero-name" id="hero-name">{characterName || '还没起名字'}</h2>
            <p className="hero-meta">
              {workCount > 0 ? `已陪你完成 ${workCount} 本绘本` : '还没有一起完成的绘本'}
            </p>

            {preset && availableActions.length > 0 && (
              <div className="action-row" role="group" aria-label="更换展示动作">
                {availableActions.map(action => (
                  <button
                    key={action}
                    type="button"
                    className={`action-chip ${activeAction === action ? 'active' : ''}`}
                    aria-pressed={activeAction === action}
                    onClick={() => void pickAction(action)}
                  >
                    <span
                      className="action-thumb"
                      style={{ backgroundImage: `url(${sceneUrl(action)})` }}
                    >
                      <PixelSprite src={actionUrl(preset.id, action)} alt="" />
                    </span>
                    <span className="action-label">{ACTION_LABELS[action]}</span>
                    {activeAction === action && (
                      <span className="action-tick" aria-hidden="true"><Check /></span>
                    )}
                  </button>
                ))}
              </div>
            )}

            <button type="button" className="m-primary" onClick={() => onGoStories?.()}>
              用 TA 生成这篇绘本
            </button>
          </>
        ) : (
          <>
            <h2 className="hero-name" id="hero-name">还没有小主角</h2>
            <p className="hero-meta">选一位角色代表你走进故事，TA 会成为之后绘本里的固定主角。</p>
            <button type="button" className="m-primary" onClick={() => setFlowOpen(true)}>
              选一位日记小主角
            </button>
          </>
        )}
      </section>

      <section className="settings-section" aria-labelledby="character-settings-title">
        <h2 className="settings-title" id="character-settings-title">角色设置</h2>
        <div className="settings-list">
          {hasCharacter && (
            <button type="button" className="settings-row" onClick={() => openSheet('nickname')}>
              <span className="settings-label">修改角色昵称</span>
              <ChevronRight />
            </button>
          )}
          <button type="button" className="settings-row" onClick={() => setFlowOpen(true)}>
            <span className="settings-label">{hasCharacter ? '更换小主角' : '选一位小主角'}</span>
            <ChevronRight />
          </button>
          <button type="button" className="settings-row" onClick={() => openSheet('relations')}>
            <span className="settings-label">关注与粉丝</span>
            <ChevronRight />
          </button>
          <button type="button" className="settings-row" onClick={() => openSheet('account')}>
            <span className="settings-label">账号</span>
            <ChevronRight />
          </button>
        </div>
        {hasCharacter && (
          <p className="settings-footnote">
            换角色只影响之后生成的绘本，已完成的绘本不会改变。
          </p>
        )}
      </section>

      <BottomSheet open={sheet === 'nickname'} onClose={() => setSheet(null)} title="角色昵称">
        <div className="mine-scope sheet-body">
          <label className="m-field-label" htmlFor="character-nickname">给 TA 起个名字</label>
          <div className="m-input-wrap">
            <input
              id="character-nickname"
              value={nicknameDraft}
              maxLength={24}
              placeholder={preset?.name ?? '小满'}
              onChange={event => setNicknameDraft(event.target.value)}
            />
            <Pencil />
          </div>
          <button
            type="button"
            className="m-primary"
            disabled={!nicknameDraft.trim() || savingNickname}
            onClick={() => void saveNickname()}
          >
            {savingNickname ? '保存中' : '保存'}
          </button>
        </div>
      </BottomSheet>

      <BottomSheet
        open={sheet === 'relations'}
        onClose={() => !relationshipBusy && setSheet(null)}
        title="关注与粉丝"
      >
        <div className="mine-scope sheet-body">
          {relationMode === 'list' && (
            <>
              <div className="relationship-actions">
                <button
                  type="button"
                  onClick={() => { setRelationMode('invite'); setRelationshipError(null); setInviteResult(null) }}
                >
                  邀请
                </button>
                <button
                  type="button"
                  onClick={() => { setRelationMode('join'); setRelationshipError(null) }}
                >
                  加入
                </button>
              </div>
              <div className="relationship-block">
                <div className="relationship-title">
                  <span>看见我的人</span>
                  <small>{audience.length} 人</small>
                </div>
                {audience.length === 0 ? (
                  <p className="relationship-empty">还没有人可以看见你的作品。</p>
                ) : audience.map(item => (
                  <div className="relationship-row" key={`audience-${item.id}`}>
                    <span className="avatar-dot">{item.subscriber?.nickname?.slice(0, 1) ?? '人'}</span>
                    <strong>{item.subscriber?.nickname ?? '未命名用户'}</strong>
                    <button
                      type="button"
                      disabled={removingId === item.id}
                      onClick={() => void removeRelationship(item, 'audience')}
                    >
                      退出关系
                    </button>
                  </div>
                ))}
              </div>
              <div className="relationship-block">
                <div className="relationship-title">
                  <span>我关心的人</span>
                  <small>{following.length} 人</small>
                </div>
                {following.length === 0 ? (
                  <p className="relationship-empty">加入对方的邀请码后，会在这里出现。</p>
                ) : following.map(item => (
                  <div className="relationship-row" key={`following-${item.id}`}>
                    <span className="avatar-dot">{item.owner?.nickname?.slice(0, 1) ?? '人'}</span>
                    <strong>{item.owner?.nickname ?? '未命名用户'}</strong>
                    <button
                      type="button"
                      disabled={removingId === item.id}
                      onClick={() => void removeRelationship(item, 'following')}
                    >
                      退出关系
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          {relationMode === 'invite' && (
            <div className="relationship-sheet">
              <p>生成邀请码后，把它发给你想分享生活空间的人。对方加入后，只能看到你主动设置可见范围的作品。</p>
              {inviteResult ? (
                <div className="invite-code" aria-label="邀请码">{inviteResult.code}</div>
              ) : (
                <button type="button" className="m-primary" onClick={createInvite} disabled={relationshipBusy}>
                  {relationshipBusy ? '生成中' : '生成邀请码'}
                </button>
              )}
              <button type="button" className="m-ghost" onClick={() => setRelationMode('list')}>返回列表</button>
            </div>
          )}

          {relationMode === 'join' && (
            <div className="relationship-sheet">
              <label htmlFor="subscription-code">邀请码</label>
              <input
                id="subscription-code"
                value={joinCode}
                onChange={event => setJoinCode(event.target.value)}
                placeholder="输入对方发来的邀请码"
              />
              <button
                type="button"
                className="m-primary"
                onClick={joinInvite}
                disabled={relationshipBusy || !joinCode.trim()}
              >
                {relationshipBusy ? '加入中' : '加入'}
              </button>
              <button type="button" className="m-ghost" onClick={() => setRelationMode('list')}>返回列表</button>
            </div>
          )}

          {relationshipError && <p className="relationship-error" role="alert">{relationshipError}</p>}
        </div>
      </BottomSheet>

      <BottomSheet open={sheet === 'account'} onClose={() => !accountBusy && setSheet(null)} title="账号">
        <div className="mine-scope sheet-body">
          <div className="account-row">
            <span>当前账号</span>
            <strong>{user?.nickname ?? profile.nickname}</strong>
          </div>
          <button type="button" className="m-danger" onClick={runLogout} disabled={accountBusy}>
            退出登录
          </button>
          {accountError && <p className="relationship-error" role="alert">{accountError}</p>}
        </div>
      </BottomSheet>
    </div>
  )
}
