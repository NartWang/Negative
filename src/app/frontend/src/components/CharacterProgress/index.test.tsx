import { describe, expect, test } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import CharacterProgress from './index'
import type { CharacterProfile } from '../../types'

const presetCharacter: CharacterProfile = {
  user_id: 1,
  source_photo_url: null,
  reference_image_url: '/characters/main/p02.webp',
  character_description: '温柔',
  nickname: '阿禾',
  display_action: null,
  source_type: 'preset',
  version: 1,
  created_at: null,
  updated_at: null,
}

describe('CharacterProgress', () => {
  test('renders no visible copy, only track/fill/avatar', () => {
    const { container } = render(
      <CharacterProgress percent={40} character={presetCharacter} accessibleLabel="绘本生成中" />,
    )
    const root = container.firstElementChild!
    // 可见文字为空:唯一文字在 sr-only 隐藏节点里。
    const visibleText = [...root.querySelectorAll(':scope > *')]
      .filter(el => !el.classList.contains('sr-only'))
      .map(el => el.textContent)
      .join('')
    expect(visibleText).toBe('')
    expect(screen.queryByText(/%/)).toBeNull()
    expect(screen.queryByText(/页/)).toBeNull()
    // 状态文字只存在于 sr-only 隐藏节点,不进入可见渲染。
    const statusNode = screen.queryByText(/生成中/)
    expect(statusNode).not.toBeNull()
    expect(statusNode!.classList.contains('sr-only')).toBe(true)
  })

  test('exposes exact ARIA progress values and hidden status', () => {
    render(
      <CharacterProgress percent={40.4} character={null} accessibleLabel="绘本生成中" />,
    )
    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuemin')).toBe('0')
    expect(bar.getAttribute('aria-valuemax')).toBe('100')
    expect(bar.getAttribute('aria-valuenow')).toBe('40')
    // sr-only 状态存在但不可见。
    const hidden = bar.querySelector('.sr-only')!
    expect(hidden.textContent).toBe('绘本生成中')
  })

  test('clamps percent into track bounds', () => {
    render(
      <CharacterProgress percent={140} character={null} accessibleLabel="x" />,
    )
    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBe('100')
    const avatar = bar.querySelector('.character-progress-avatar') as HTMLElement
    expect(avatar.style.left).toBe('100%')
  })

  test('the avatar lives inside the inset track so endpoints stay visible', () => {
    const { container } = render(
      <CharacterProgress percent={50} character={null} accessibleLabel="x" />,
    )
    const track = container.querySelector('.character-progress-track')!
    const avatar = container.querySelector('.character-progress-avatar')!
    // 头像必须在内缩轨道坐标系内:track 宽度 = 容器 - 26px,
    // 26px 头像半宽平移后在 0%/100% 都不会被裁掉。
    expect(track.contains(avatar)).toBe(true)
  })

  test('percent 0 and 100 put fill and avatar exactly at the endpoints', () => {
    const { container, rerender } = render(
      <CharacterProgress percent={0} character={null} accessibleLabel="x" />,
    )
    let fill = container.querySelector('.character-progress-fill') as HTMLElement
    let avatar = container.querySelector('.character-progress-avatar') as HTMLElement
    expect(fill.style.width).toBe('0%')
    expect(avatar.style.left).toBe('0%')

    rerender(<CharacterProgress percent={100} character={null} accessibleLabel="x" />)
    fill = container.querySelector('.character-progress-fill') as HTMLElement
    avatar = container.querySelector('.character-progress-avatar') as HTMLElement
    expect(fill.style.width).toBe('100%')
    expect(avatar.style.left).toBe('100%')
  })

  test('preset with display_action uses action url; otherwise reference image', () => {
    const { rerender, container } = render(
      <CharacterProgress
        percent={10}
        character={{ ...presetCharacter, display_action: 'happy' }}
        accessibleLabel="x"
      />,
    )
    let img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBe('/characters/actions/p02/happy.webp')

    rerender(
      <CharacterProgress percent={10} character={presetCharacter} accessibleLabel="x" />,
    )
    img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBe('/characters/main/p02.webp')

    rerender(
      <CharacterProgress
        percent={10}
        character={{
          ...presetCharacter,
          source_type: 'photo_generated',
          reference_image_url: '/api/media/custom',
        }}
        accessibleLabel="x"
      />,
    )
    img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBe('/api/media/custom')
  })

  test('image error falls back to default without removing the track', () => {
    const { container } = render(
      <CharacterProgress percent={30} character={presetCharacter} accessibleLabel="x" />,
    )
    const img = container.querySelector('img')!
    fireEvent.error(img)
    expect(container.querySelector('img')!.getAttribute('src')).toBe(
      '/characters/main/p01.webp',
    )
    expect(container.querySelector('.character-progress-track')).not.toBeNull()
  })
})
