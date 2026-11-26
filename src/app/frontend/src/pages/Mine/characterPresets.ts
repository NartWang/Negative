import type { CharacterProfile } from '../../types'

export type PresetCategory = 'kid' | 'youth' | 'elder' | 'whimsy' | 'buddy' | 'job'
export type CategoryTab = 'all' | PresetCategory
export type ActionKey = 'idle' | 'think' | 'happy' | 'read'

export interface CharacterPreset {
  /** Asset id, also the stable identity stored in the character profile. */
  id: string
  /** Life-like display name. Internal file numbers are never shown to users. */
  name: string
  /** Short temperament label rendered as a pill under the name. */
  trait: string
  category: PresetCategory
  /**
   * Consistency-checked action set. `idle` is the master artwork; the other three
   * are identity-locked generations (see `scripts/generate_character_actions.py`).
   * Characters whose set is missing simply do not render an action row.
   */
  actions?: ActionKey[]
}

/** Every preset ships the same four actions shown in the UI reference screens. */
const FULL_ACTION_SET: ActionKey[] = ['idle', 'think', 'happy', 'read']

export const CATEGORY_TABS: { key: CategoryTab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'kid', label: '小朋友' },
  { key: 'youth', label: '青年' },
  { key: 'elder', label: '长辈' },
  { key: 'whimsy', label: '奇趣' },
  { key: 'buddy', label: '伙伴' },
  { key: 'job', label: '职业' },
]

export const ACTION_LABELS: Record<ActionKey, string> = {
  idle: '日常',
  think: '思考',
  happy: '开心',
  read: '阅读',
}

const PRESET_SEED: Omit<CharacterPreset, 'actions'>[] = [
  { id: 'p01', name: '小满', trait: '安静清冷', category: 'youth' },
  { id: 'p02', name: '阿禾', trait: '温柔细腻', category: 'youth' },
  { id: 'p03', name: '小夏', trait: '活泼开朗', category: 'youth' },
  { id: 'p04', name: '糖糖', trait: '软萌爱笑', category: 'kid' },
  { id: 'p05', name: '小飒', trait: '利落有主见', category: 'youth' },
  { id: 'p06', name: '阿岸', trait: '稳重可靠', category: 'youth' },
  { id: 'p07', name: '阿彻', trait: '冷静有型', category: 'youth' },
  { id: 'p08', name: '小虎', trait: '元气十足', category: 'kid' },
  { id: 'p09', name: '小波', trait: '好奇友善', category: 'whimsy' },
  { id: 'p10', name: '小屏', trait: '安静专注', category: 'whimsy' },
  { id: 'p11', name: '橘子', trait: '乐观勇敢', category: 'buddy' },
  { id: 'p12', name: '团子', trait: '忠诚黏人', category: 'buddy' },
  { id: 'p13', name: '云奶奶', trait: '慈爱温暖', category: 'elder' },
  { id: 'p16', name: '山爷爷', trait: '硬朗爱笑', category: 'elder' },
  { id: 'p17', name: '星星', trait: '好奇爱问', category: 'kid' },
  { id: 'p18', name: '小豆', trait: '淘气机灵', category: 'kid' },
  { id: 'p19', name: '波波', trait: '时髦利落', category: 'youth' },
  { id: 'p21', name: '阿真', trait: '条理清晰', category: 'job' },
  { id: 'p22', name: '小码', trait: '专注安静', category: 'job' },
  { id: 'p23', name: '阿彩', trait: '敏感浪漫', category: 'job' },
  { id: 'p24', name: '林老师', trait: '耐心温和', category: 'job' },
  { id: 'p25', name: '阿工', trait: '务实可靠', category: 'job' },
  { id: 'p26', name: '白大夫', trait: '沉稳细致', category: 'job' },
  { id: 'p27', name: '阿律', trait: '冷静有力', category: 'job' },
  { id: 'p28', name: '小研', trait: '严谨好奇', category: 'job' },
  { id: 'p29', name: '阿拓', trait: '敢闯敢试', category: 'job' },
  { id: 'p30', name: '月月', trait: '安静做梦', category: 'whimsy' },
  { id: 'p31', name: '圆圆', trait: '憨直可靠', category: 'whimsy' },
  { id: 'p32', name: '云朵', trait: '轻盈自在', category: 'whimsy' },
  { id: 'p33', name: '阿星', trait: '一直在路上', category: 'whimsy' },
  { id: 'p34', name: '小枫', trait: '自由爱冒险', category: 'youth' },
  { id: 'p35', name: '阿雪', trait: '神秘慢热', category: 'whimsy' },
  { id: 'p36', name: '花花', trait: '天真烂漫', category: 'whimsy' },
]

export const CHARACTER_PRESETS: CharacterPreset[] = PRESET_SEED.map(preset => ({
  ...preset,
  actions: FULL_ACTION_SET,
}))

export const presetMainUrl = (id: string) => `/characters/main/${id}.webp`
export const presetThumbUrl = (id: string) => `/characters/thumb/${id}.webp`
export const actionUrl = (id: string, action: ActionKey) =>
  `/characters/actions/${id}/${action}.webp`

/**
 * Each form has its own picture-book set: 日常/思考/阅读 happen indoors at the
 * desk, 开心 happens outside. Shared by all 33 characters — the background says
 * where the scene is, the sprite says who is in it.
 */
export const sceneUrl = (action: ActionKey) => `/scenes/${action}.webp`

export function findPreset(id: string | null | undefined): CharacterPreset | undefined {
  if (!id) return undefined
  return CHARACTER_PRESETS.find(preset => preset.id === id)
}

/** The chosen preset is recoverable from the stored artwork url. */
export function presetIdFromUrl(url: string | null | undefined): string | null {
  const matched = url?.match(/\/characters\/main\/(p\d+)\.webp$/)
  return matched ? matched[1] : null
}

export function presetOf(character: CharacterProfile | null): CharacterPreset | undefined {
  return findPreset(presetIdFromUrl(character?.reference_image_url))
}

/** Deterministic sample used by the entry screen's rotating preview card. */
export function sampleShowcase(offset: number, size = 4): CharacterPreset[] {
  const pool = CHARACTER_PRESETS
  return Array.from({ length: size }, (_, index) => pool[(offset * size + index) % pool.length])
}
