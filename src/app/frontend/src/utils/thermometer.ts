import type { Schedule, Fragment, Thermometer } from '../types'

export function computeQuant(
  fragmentsCount: number,
  schedulesTotal: number,
  schedulesCompleted: number,
  consecutiveDays: number,
): number {
  const frag = Math.min(Math.max(fragmentsCount, 0), 5) * 6
  const ratio = schedulesTotal ? schedulesCompleted / schedulesTotal : 0
  const sched = Math.max(0, Math.min(1, ratio)) * 20
  const streak = Math.min(Math.max(consecutiveDays, 0), 5) * 2
  return Math.round(frag + sched + streak)
}

const TIERS: { max: number; label: string; color: string }[] = [
  { max: 20,  label: '凉',   color: '#9CC5E0' },
  { max: 40,  label: '温凉', color: '#BFD4D6' },
  { max: 60,  label: '温热', color: '#E8C8A0' },
  { max: 80,  label: '温暖', color: '#E89D7B' },
  { max: 100, label: '炽热', color: '#E67862' },
]

export function labelForScore(score: number): { label: string; color: string } {
  const tier = TIERS.find(t => score <= t.max) ?? TIERS[TIERS.length - 1]
  return { label: tier.label, color: tier.color }
}

/**
 * Locally recompute thermometer when schedules/fragments change, preserving the
 * AI part from the last server response. Only call when `prev` exists.
 */
export function recomputeLocal(
  prev: Thermometer,
  schedules: Schedule[],
  fragments: Fragment[],
): Thermometer {
  const fragCount = fragments.length
  const total = schedules.length
  const done = schedules.filter(s => s.completed).length
  const quant = computeQuant(fragCount, total, done, prev.inputs.consecutive_days)
  const score = Math.max(0, Math.min(100, quant + prev.ai_score))
  const { label, color } = labelForScore(score)
  return {
    ...prev,
    score, label, color,
    quant_score: quant,
    inputs: {
      ...prev.inputs,
      fragments_count: fragCount,
      schedules_total: total,
      schedules_completed: done,
    },
  }
}
