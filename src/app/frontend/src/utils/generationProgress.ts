/**
 * 生成进度的纯函数:阶段下界 + 真实节点 + 区间内有界插值。
 *
 * 规格 5.3 / 5.5:
 * - 视觉进度单调不减;
 * - 到达下一个真实节点之前停住;
 * - 后端确认完成之前最多 99%,确认后 100%。
 */

export interface PicturebookProgressInput {
  stage: string
  ready: number
  total: number
  done: boolean
}

export interface MotionComicProgressInput {
  stage: string
  ready: number
  total: number
  done: boolean
}

const PICTUREBOOK_STAGE_FLOORS: Record<string, number> = {
  queued: 0,
  character: 3,
  story: 8,
  prompts: 15,
}

const MOTION_COMIC_STAGE_FLOORS: Record<string, number> = {
  queued: 0,
  frames: 5,
  submitting: 10,
  stitching: 95,
}

export function picturebookProgress(input: PicturebookProgressInput): number {
  if (input.done) return 100
  const total = Math.max(0, input.total)
  const ready = Math.max(0, Math.min(input.ready, total))
  if (input.stage === 'rendering') {
    if (total <= 0) return 20
    const percent = 20 + (ready / total) * 80
    // 9/9 页但尚未正式提升完成时最多 99%。
    return Math.min(99, percent)
  }
  if (input.stage === 'done') return 100
  return PICTUREBOOK_STAGE_FLOORS[input.stage] ?? 0
}

export function motionComicProgress(input: MotionComicProgressInput): number {
  if (input.done) return 100
  const total = Math.max(0, input.total)
  const ready = Math.max(0, Math.min(input.ready, total))
  if (input.stage === 'rendering') {
    if (total <= 0) return 15
    const percent = 15 + (ready / total) * 75
    return Math.min(99, percent)
  }
  if (input.stage === 'done') return 100
  return MOTION_COMIC_STAGE_FLOORS[input.stage] ?? 0
}

/**
 * 绘本整本渲染的名义总时长:进度条按 180s / total 在每页区间内插值。
 * 只是视觉节奏,不是承诺;真实节点仍然来自后端。
 */
export const PICTUREBOOK_NOMINAL_TOTAL_MS = 180_000

export interface ProgressWindow {
  /** 后端真实进度下界 */
  real: number
  /** 下一个真实节点(插值不可越过) */
  next: number
  /** 当前区间的名义时长;非渲染阶段为 null(不插值) */
  nominalMs: number | null
}

/**
 * 把绘本进度拆成「真实下界 + 下一节点 + 区间名义时长」,
 * 供 FilmFolder 用 interpolateProgress 做时间驱动的平滑动画。
 */
export function picturebookProgressWindow(
  input: PicturebookProgressInput,
): ProgressWindow {
  const real = picturebookProgress(input)
  const total = Math.max(0, input.total)
  if (input.done || input.stage !== 'rendering' || total <= 0) {
    return { real, next: real, nominalMs: null }
  }
  const nextReady = Math.min(total, Math.max(0, input.ready) + 1)
  const next = Math.min(99, 20 + (nextReady / total) * 80)
  return {
    real,
    next: Math.max(real, next),
    nominalMs: PICTUREBOOK_NOMINAL_TOTAL_MS / total,
  }
}

/**
 * 两个真实节点之间的平滑动画:从 realPercent 缓慢逼近 nextMilestone,
 * 永不越过;到达上限后停住等待真实结果。
 *
 * @param realPercent 后端真实进度下界
 * @param nextMilestone 下一个真实节点(不可越过)
 * @param elapsedMs 进入当前区间以来的毫秒数
 * @param nominalMs 区间的名义时长(绘本默认 180s/total)
 */
export function interpolateProgress(
  realPercent: number,
  nextMilestone: number,
  elapsedMs: number,
  nominalMs: number,
): number {
  const floor = Math.max(0, Math.min(99, realPercent))
  const ceiling = Math.max(floor, Math.min(99, nextMilestone))
  if (nominalMs <= 0) return floor
  const ratio = Math.max(0, Math.min(1, elapsedMs / nominalMs))
  return Math.min(ceiling, floor + (ceiling - floor) * ratio)
}
