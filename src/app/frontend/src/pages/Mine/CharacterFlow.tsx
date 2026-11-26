import { useEffect, useRef, useState } from 'react'
import { characterApi, uploadApi } from '../../api/client'
import type { CharacterProfile } from '../../types'
import { useToast } from '../../contexts/ToastContext'
import PixelSprite from '../../components/PixelSprite'
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Heart,
  ImageIcon,
  Lock,
  Pencil,
  Sparkle,
  UserRound,
} from '../../components/Icon'
import {
  ACTION_LABELS,
  actionUrl,
  CATEGORY_TABS,
  CHARACTER_PRESETS,
  findPreset,
  presetIdFromUrl,
  presetMainUrl,
  presetThumbUrl,
  sampleShowcase,
  sceneUrl,
  type ActionKey,
  type CategoryTab,
  type CharacterPreset,
} from './characterPresets'
import './theme.css'
import './CharacterFlow.css'

type Step = 'entry' | 'preset' | 'photo' | 'confirm'

interface Props {
  character: CharacterProfile | null
  /**
   * `create` is first-time onboarding; `change` is replacing a confirmed
   * character. Same capabilities, different framing: replacing needs to show
   * who the current star is and reassure that finished books stay untouched.
   */
  mode?: 'create' | 'change'
  onSaved: (character: CharacterProfile) => void
  onClose: () => void
}

const SHOWCASE_INTERVAL = 4000

// Progress copy from 创建角色界面规格.md / 产品方案第五节. No time promises.
const GENERATE_STAGES = [
  '正在检查照片',
  '正在提取外观特征',
  '正在设计你的角色',
  '正在检查角色一致性',
]

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Dried-flower / leaf watermark used as page decoration on the entry screen. */
function LeafMark({ className }: { className: string }) {
  return (
    <span className={`m-leaf ${className}`} aria-hidden="true">
      <svg viewBox="0 0 48 72" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <path d="M24 70V10" />
        <path d="M24 26c-8-2-13-8-14-16 8 1 13 6 14 16Z" />
        <path d="M24 26c8-2 13-8 14-16-8 1-13 6-14 16Z" />
        <path d="M24 44c-7-2-11-7-12-14 7 1 11 6 12 14Z" />
        <path d="M24 44c7-2 11-7 12-14-7 1-11 6-12 14Z" />
        <circle cx="24" cy="8" r="3" />
      </svg>
    </span>
  )
}

export default function CharacterFlow({ character, mode = 'create', onSaved, onClose }: Props) {
  const toast = useToast()
  const storedPresetId = presetIdFromUrl(character?.reference_image_url)
  const isChanging = mode === 'change'
  const currentPreset = findPreset(storedPresetId)
  const currentName = character?.nickname?.trim() || currentPreset?.name || ''

  const [step, setStep] = useState<Step>('entry')
  const [selectedId, setSelectedId] = useState<string | null>(storedPresetId)
  const [category, setCategory] = useState<CategoryTab>('all')
  const [nickname, setNickname] = useState(character?.nickname ?? '')
  const [action, setAction] = useState<ActionKey | null>(
    (character?.display_action as ActionKey | null) ?? null
  )
  const [photoUrl, setPhotoUrl] = useState<string | null>(character?.source_photo_url ?? null)
  const [photoAssetId, setPhotoAssetId] = useState<string | null>(null)
  const [photoNote, setPhotoNote] = useState(character?.character_description ?? '')
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  /** Pixel master produced from the photo; null until a generation succeeds. */
  const [generatedUrl, setGeneratedUrl] = useState<string | null>(
    character?.source_type === 'photo_generated' ? character.reference_image_url : null
  )
  const [generateStage, setGenerateStage] = useState<number | null>(null)
  const [showcaseOffset, setShowcaseOffset] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (prefersReducedMotion() || step !== 'entry') return
    const timer = window.setInterval(
      () => setShowcaseOffset(current => current + 1),
      SHOWCASE_INTERVAL,
    )
    return () => window.clearInterval(timer)
  }, [step])

  // Staged progress copy required by 创建角色界面规格.md — never a bare spinner.
  useEffect(() => {
    if (generateStage === null) return
    const timer = window.setInterval(() => {
      setGenerateStage(current =>
        current === null ? null : Math.min(current + 1, GENERATE_STAGES.length - 1)
      )
    }, 6000)
    return () => window.clearInterval(timer)
  }, [generateStage])

  const selected = findPreset(selectedId)
  const isPhotoRoute = step === 'photo'
    || (step === 'confirm' && !selected && Boolean(generatedUrl || photoUrl))
  const actions = selected?.actions ?? []
  const effectiveAction = action && actions.includes(action) ? action : actions[0] ?? null
  const previewSrc = selected
    ? (effectiveAction ? actionUrl(selected.id, effectiveAction) : presetMainUrl(selected.id))
    : generatedUrl ?? photoUrl
  /** Photo-route characters have no form yet, so they stand in the everyday room. */
  const sceneAction: ActionKey = effectiveAction ?? 'idle'

  const visiblePresets = category === 'all'
    ? CHARACTER_PRESETS
    : CHARACTER_PRESETS.filter(preset => preset.category === category)

  const goBack = () => {
    if (step === 'entry') return onClose()
    if (step === 'confirm') return setStep(isPhotoRoute ? 'photo' : 'preset')
    setStep('entry')
  }

  const openPresetStep = () => {
    setPhotoUrl(character?.source_photo_url ?? null)
    setStep('preset')
  }

  const choosePreset = (preset: CharacterPreset) => {
    setSelectedId(preset.id)
    if (!nickname.trim()) setNickname(preset.name)
    setAction(preset.actions?.[0] ?? null)
  }

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const { url, asset_id } = await uploadApi.upload(file)
      setPhotoUrl(url)
      setPhotoAssetId(asset_id ?? null)
      setSelectedId(null)
      setGeneratedUrl(null)
      toast.success('照片已上传')
    } catch {
      toast.error('上传失败，请换一张照片')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const generateFromPhoto = async () => {
    if (!photoUrl && !photoAssetId) return
    setGenerateStage(0)
    try {
      const saved = await characterApi.generate({
        source_photo_asset_id: photoAssetId,
        source_photo_url: photoUrl,
        character_description: photoNote.trim(),
        nickname: nickname.trim(),
      })
      setGeneratedUrl(saved.reference_image_url)
      setSelectedId(null)
      setStep('confirm')
      toast.success('角色已生成')
    } catch {
      toast.error('生成失败，请换一张更清楚的照片再试')
    } finally {
      setGenerateStage(null)
    }
  }

  const confirmCharacter = async () => {
    setSaving(true)
    try {
      const saved = selected
        ? await characterApi.update({
          reference_image_url: presetMainUrl(selected.id),
          source_photo_url: null,
          character_description: `${selected.name} · ${selected.trait}`,
          nickname: nickname.trim() || selected.name,
          display_action: effectiveAction,
          source_type: 'preset',
        })
        : await characterApi.update({
          reference_image_url: generatedUrl,
          source_photo_url: photoUrl,
          character_description: photoNote.trim(),
          nickname: nickname.trim(),
          display_action: null,
          source_type: 'photo_generated',
        })
      onSaved(saved)
    } catch {
      toast.error('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const title = step === 'entry' ? (isChanging ? '换一位日记小主角' : '选一位日记小主角')
    : step === 'preset' ? (isChanging ? '换一位小主角' : '选择小主角')
      : step === 'photo' ? '生成我的角色'
        : isChanging ? '确认换成TA' : '确认我的小主角'

  return (
    <div className={`page flow-page mine-scope fade-in ${step === 'preset' ? 'is-picker' : ''} ${step === 'entry' ? 'is-entry' : ''}`}>
      <div className="m-topbar">
        <button type="button" className="m-back" onClick={goBack} aria-label="返回">
          <ArrowLeft />
        </button>
        <h1 className="m-topbar-title">{title}</h1>
        <span />
        {step === 'entry' && (
          <p className="m-topbar-sub">
            {isChanging
              ? '换角色只影响之后生成的绘本，已完成的绘本不会改变'
              : 'TA 会陪你走进之后的每一本日记绘本'}
          </p>
        )}
        {step === 'preset' && (
          <p className="m-topbar-sub">{CHARACTER_PRESETS.length} 个现成角色 · 不需要照片</p>
        )}
        {step === 'photo' && (
          <p className="m-topbar-sub">上传一张照片，生成更像你的形象</p>
        )}
      </div>

      {step === 'entry' && (
        <div className="flow-entry">
          <LeafMark className="leaf-left" />
          <LeafMark className="leaf-right" />

          {/* Replacing a character: show who is being replaced, and by what. */}
          {isChanging && currentName && (
            <div className="current-star">
              <span className="current-star-art">
                <PixelSprite
                  src={character?.reference_image_url ?? null}
                  alt={currentName}
                  eager
                />
              </span>
              <span className="current-star-copy">
                <small>现在的小主角</small>
                <strong>{currentName}</strong>
                {currentPreset && <em>{currentPreset.trait}</em>}
              </span>
            </div>
          )}

          {!isChanging && (
            <div className="showcase-card">
              <span className="showcase-polaroid" aria-hidden="true">
                <span className="polaroid-sky" />
                <span className="polaroid-hill" />
                <span className="polaroid-house" />
              </span>
              <span className="showcase-heart showcase-heart-a" aria-hidden="true"><Heart /></span>
              <span className="showcase-heart showcase-heart-b" aria-hidden="true"><Heart /></span>
              <div className="showcase-row" key={showcaseOffset}>
                {sampleShowcase(showcaseOffset).map(preset => (
                  <span className="showcase-sprite" key={`${showcaseOffset}-${preset.id}`}>
                    <PixelSprite src={presetThumbUrl(preset.id)} alt={preset.name} eager />
                  </span>
                ))}
              </div>
            </div>
          )}

          <button type="button" className="route-card" onClick={openPresetStep}>
            <span className="route-icon" aria-hidden="true"><UserRound /></span>
            <span className="route-copy">
              <strong>直接选角色</strong>
              <small>{isChanging ? `从 ${CHARACTER_PRESETS.length} 个现成角色里换一位` : '无需照片，立即开始'}</small>
            </span>
            <span className="route-go" aria-hidden="true"><ChevronRight /></span>
          </button>

          <div className="route-block">
            <button type="button" className="route-card" onClick={() => setStep('photo')}>
              <span className="route-icon" aria-hidden="true"><ImageIcon /></span>
              <span className="route-copy">
                <strong>生成我的角色</strong>
                <small>上传一张照片，生成更像你的形象</small>
              </span>
              <span className="route-go" aria-hidden="true"><ChevronRight /></span>
            </button>
            <p className="route-privacy"><Lock />照片只用于创建角色，可在生成后删除</p>
          </div>

          <div className="flow-footer">
            <button type="button" className="flow-later" onClick={onClose}>
              {isChanging ? '先不换，返回' : '先写日记，稍后再选'} <ChevronRight />
            </button>
          </div>
        </div>
      )}

      {step === 'preset' && (
        <div className="flow-preset">
          <div className="preset-head">
            <div className="category-row" role="tablist" aria-label="角色分类">
              {CATEGORY_TABS.map(tab => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={category === tab.key}
                  className={`category-chip ${category === tab.key ? 'active' : ''}`}
                  onClick={() => setCategory(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Only the characters scroll: the heading, the categories and the
              call to action stay put, so the CTA is visible on arrival. */}
          <div className="preset-scroll">
            <div className="preset-grid">
              {visiblePresets.map(preset => (
                <button
                  key={preset.id}
                  type="button"
                  className={`preset-card ${selectedId === preset.id ? 'active' : ''}`}
                  aria-pressed={selectedId === preset.id}
                  onClick={() => choosePreset(preset)}
                >
                  {selectedId === preset.id && (
                    <span className="preset-tick" aria-hidden="true"><Check /></span>
                  )}
                  <span className="preset-art">
                    <PixelSprite src={presetThumbUrl(preset.id)} alt={preset.name} />
                  </span>
                  <span className="preset-name">{preset.name}</span>
                  <span className="preset-trait">{preset.trait}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flow-bar">
            {selected && (
              <p className="flow-bar-picked">已选择：<strong>{selected.name}</strong></p>
            )}
            <button
              type="button"
              className="m-primary flow-bar-cta"
              disabled={!selected}
              onClick={() => setStep('confirm')}
            >
              看看 TA 在绘本里的样子 <ChevronRight />
            </button>
          </div>
        </div>
      )}

      {step === 'photo' && (
        <div className="flow-photo">
          <button
            type="button"
            className={`upload-area ${photoUrl ? 'filled' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || generateStage !== null}
          >
            {photoUrl ? (
              <img src={photoUrl} alt="已上传的照片" />
            ) : (
              <>
                <span className="upload-icon" aria-hidden="true"><ImageIcon /></span>
                <strong>{uploading ? '正在上传…' : '上传一张照片'}</strong>
                <small>单人、正面、脸和发型清楚，光线均匀</small>
              </>
            )}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            aria-label="上传照片"
            style={{ display: 'none' }}
            onChange={handleUpload}
          />
          {photoUrl && (
            <button
              type="button"
              className="m-ghost photo-replace"
              disabled={generateStage !== null}
              onClick={() => fileInputRef.current?.click()}
            >
              换一张照片
            </button>
          )}

          <label className="m-field-label" htmlFor="photo-note">请描述你自己（可选）</label>
          <div className="m-input-wrap">
            <textarea
              id="photo-note"
              rows={3}
              maxLength={200}
              placeholder="短发，常背帆布包，像手账里的主角"
              value={photoNote}
              onChange={event => setPhotoNote(event.target.value)}
            />
          </div>

          {generateStage !== null ? (
            <div className="generate-progress" role="status" aria-live="polite">
              <span className="generate-spark" aria-hidden="true"><Sparkle /></span>
              <strong>{GENERATE_STAGES[generateStage]}</strong>
              <ol className="generate-steps">
                {GENERATE_STAGES.map((label, index) => (
                  <li key={label} className={index <= generateStage ? 'done' : ''}>{label}</li>
                ))}
              </ol>
              <small>生成需要一点时间，可以先放着不用离开这一页。</small>
            </div>
          ) : (
            <p className="m-notice">
              <Lock />
              照片只用于创建角色，可在生成后删除。生成的是一位Q 版像素小主角，不是照片本身。
            </p>
          )}

          <button
            type="button"
            className="m-primary"
            disabled={!photoUrl || uploading || generateStage !== null}
            onClick={() => void generateFromPhoto()}
          >
            {generateStage !== null ? '正在生成…' : '生成我的角色'}
          </button>
          <button
            type="button"
            className="m-ghost"
            disabled={generateStage !== null}
            onClick={openPresetStep}
          >
            先从现成角色里挑一位
          </button>
        </div>
      )}

      {step === 'confirm' && (
        <div className="flow-confirm">
          {/* Scene artwork per form; the CSS room underneath is the fallback if
              the background image is unavailable. */}
          <div className="scene-card">
            <span className="scene-tag">绘本场景预览</span>
            <div className="scene" aria-hidden="true">
              <span className="scene-window" />
              <span className="scene-plant" />
              <span className="scene-shelf" />
              <span className="scene-desk" />
              <span className="scene-book" />
              <span className="scene-cup" />
            </div>
            <img className="scene-bg" src={sceneUrl(sceneAction)} alt="" aria-hidden="true" />
            <div className="scene-actor">
              <PixelSprite
                src={previewSrc}
                alt={selected?.name || nickname.trim() || '我的小主角'}
                eager
              />
            </div>
          </div>

          <h2 className="confirm-question">这是你想在故事里成为的样子吗？</h2>

          <label className="m-field-label" htmlFor="confirm-nickname">角色昵称</label>
          <div className="m-input-wrap">
            <input
              id="confirm-nickname"
              value={nickname}
              maxLength={24}
              placeholder={selected?.name ?? '小满'}
              onChange={event => setNickname(event.target.value)}
            />
            <Pencil />
          </div>

          {selected && actions.length > 0 && (
            <>
              <div className="confirm-actions" role="group" aria-label="展示动作">
                {actions.map(key => (
                  <button
                    key={key}
                    type="button"
                    className={`confirm-action ${effectiveAction === key ? 'active' : ''}`}
                    aria-pressed={effectiveAction === key}
                    onClick={() => setAction(key)}
                  >
                    <span
                      className="confirm-action-art"
                      style={{ backgroundImage: `url(${sceneUrl(key)})` }}
                    >
                      <PixelSprite src={actionUrl(selected.id, key)} alt="" />
                    </span>
                    <span>{ACTION_LABELS[key]}</span>
                    {effectiveAction === key && (
                      <span className="confirm-action-tick" aria-hidden="true"><Check /></span>
                    )}
                  </button>
                ))}
              </div>
              <p className="m-notice">
                <Heart />
                确认的是整套角色，选择展示动作不会替换角色母版
              </p>
            </>
          )}

          <button
            type="button"
            className="m-primary"
            disabled={saving || (!selected && !previewSrc)}
            onClick={() => void confirmCharacter()}
          >
            {saving ? '保存中…' : '就用 TA 作为我的小主角'}
          </button>
          {isPhotoRoute ? (
            <button
              type="button"
              className="m-ghost"
              disabled={generateStage !== null}
              onClick={() => { setStep('photo'); void generateFromPhoto() }}
            >
              重新生成整套
            </button>
          ) : (
            <button type="button" className="m-ghost" onClick={() => setStep('preset')}>
              再看看其他角色
            </button>
          )}
        </div>
      )}
    </div>
  )
}
