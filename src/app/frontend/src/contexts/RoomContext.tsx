import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { ApiError, roomsApi } from '../api/client'
import type { Invite, Room } from '../types'

type RoomStatus = 'loading' | 'ready' | 'retrying'
type RoomMutation = 'create' | 'invite' | 'join' | 'leave' | null
type LoadMode = 'initial' | 'retry' | 'poll'

interface RoomContextValue {
  room: Room | null
  invite: Invite | null
  status: RoomStatus
  error: string | null
  refresh: () => Promise<void>
  createRoom: () => Promise<void>
  rotateInvite: () => Promise<void>
  joinRoom: (code: string) => Promise<void>
  leaveRoom: () => Promise<void>
}

const RoomContext = createContext<RoomContextValue | null>(null)

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function RoomProvider({ children }: { children: ReactNode }) {
  const [room, setRoom] = useState<Room | null>(null)
  const [invite, setInvite] = useState<Invite | null>(null)
  const [status, setStatus] = useState<RoomStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [mutation, setMutation] = useState<RoomMutation>(null)
  const mountedRef = useRef(true)
  const mutationRef = useRef(false)
  const requestVersionRef = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)

  const invalidateRoomRead = useCallback(() => {
    requestVersionRef.current += 1
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  const loadCurrent = useCallback(async (mode: LoadMode) => {
    if (mutationRef.current) return
    const version = requestVersionRef.current + 1
    requestVersionRef.current = version
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    if (mode === 'initial') setStatus('loading')
    if (mode === 'retry') {
      setStatus('retrying')
      setError(null)
    }

    try {
      const current = await roomsApi.current(controller.signal)
      if (
        !mountedRef.current
        || requestVersionRef.current !== version
        || mutationRef.current
      ) return
      setRoom(current)
      if (!current || current.state === 'paired') setInvite(null)
      setError(null)
      setStatus('ready')
    } catch (cause) {
      if (
        !mountedRef.current
        || requestVersionRef.current !== version
        || isAbort(cause)
      ) return
      if (cause instanceof ApiError && cause.status === 401) return
      setError('暂时无法读取房间状态')
      setStatus('ready')
      throw cause
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    loadCurrent('initial').catch(() => undefined)
    return () => {
      mountedRef.current = false
      invalidateRoomRead()
    }
  }, [invalidateRoomRead, loadCurrent])

  useEffect(() => {
    if (room?.state !== 'waiting' || status !== 'ready' || mutation !== null) return
    const interval = window.setInterval(() => {
      loadCurrent('poll').catch(() => undefined)
    }, 5000)
    return () => window.clearInterval(interval)
  }, [room?.state, status, mutation, loadCurrent])

  const beginMutation = useCallback((next: Exclude<RoomMutation, null>) => {
    if (mutationRef.current) throw new Error('room operation already in progress')
    mutationRef.current = true
    setMutation(next)
    setError(null)
    invalidateRoomRead()
  }, [invalidateRoomRead])

  const endMutation = useCallback(() => {
    mutationRef.current = false
    setMutation(null)
    setStatus('ready')
  }, [])

  const refresh = useCallback(() => loadCurrent('retry'), [loadCurrent])

  const createRoom = useCallback(async () => {
    beginMutation('create')
    try {
      const created = await roomsApi.create()
      if (!mountedRef.current) return
      setRoom(created)
      const nextInvite = await roomsApi.createInvite(created.id)
      if (mountedRef.current) setInvite(nextInvite)
    } finally {
      if (mountedRef.current) endMutation()
      else mutationRef.current = false
    }
  }, [beginMutation, endMutation])

  const rotateInvite = useCallback(async () => {
    if (!room) return
    beginMutation('invite')
    try {
      const nextInvite = await roomsApi.createInvite(room.id)
      if (mountedRef.current) setInvite(nextInvite)
    } finally {
      if (mountedRef.current) endMutation()
      else mutationRef.current = false
    }
  }, [room, beginMutation, endMutation])

  const joinRoom = useCallback(async (code: string) => {
    beginMutation('join')
    try {
      const joined = await roomsApi.join(code)
      if (!mountedRef.current) return
      setInvite(null)
      setRoom(joined)
    } finally {
      if (mountedRef.current) endMutation()
      else mutationRef.current = false
    }
  }, [beginMutation, endMutation])

  const leaveRoom = useCallback(async () => {
    if (!room) return
    beginMutation('leave')
    try {
      await roomsApi.leave(room.id)
      if (!mountedRef.current) return
      setInvite(null)
      setRoom(null)
    } finally {
      if (mountedRef.current) endMutation()
      else mutationRef.current = false
    }
  }, [room, beginMutation, endMutation])

  const value = useMemo<RoomContextValue>(() => ({
    room,
    invite,
    status,
    error,
    refresh,
    createRoom,
    rotateInvite,
    joinRoom,
    leaveRoom,
  }), [room, invite, status, error, refresh, createRoom, rotateInvite, joinRoom, leaveRoom])

  return <RoomContext.Provider value={value}>{children}</RoomContext.Provider>
}

export function useRoom(): RoomContextValue {
  const context = useContext(RoomContext)
  if (!context) throw new Error('useRoom must be used inside RoomProvider')
  return context
}
