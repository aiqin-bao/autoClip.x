/**
 * 进度状态管理
 * 优先使用 SSE 实时推送，SSE 不可用时降级为轮询（向后兼容）
 */

import { create } from 'zustand'

export interface SimpleProgress {
  project_id: string
  stage: string
  stage_name?: string
  percent: number
  message: string
  ts: number
}

interface SimpleProgressState {
  byId: Record<string, SimpleProgress>
  pollingInterval: number | null
  isPolling: boolean

  upsert: (progress: SimpleProgress) => void
  startPolling: (projectIds: string[], intervalMs?: number) => void
  stopPolling: () => void
  clearProgress: (projectId: string) => void
  clearAllProgress: () => void
  getProgress: (projectId: string) => SimpleProgress | null
  getAllProgress: () => Record<string, SimpleProgress>

  // SSE 订阅（单项目实时推送）
  subscribeSSE: (projectId: string, onDone?: (projectId: string) => void) => () => void
}

const API_BASE = 'http://localhost:8000/api/v1'

export const useSimpleProgressStore = create<SimpleProgressState>((set, get) => {
  let timer: ReturnType<typeof setInterval> | null = null

  return {
    byId: {},
    pollingInterval: null,
    isPolling: false,

    upsert: (progress: SimpleProgress) => {
      set((state) => ({
        byId: { ...state.byId, [progress.project_id]: progress },
      }))
    },

    // ──────────────────────────────────────────────
    // SSE 实时订阅（单项目）
    // ──────────────────────────────────────────────
    subscribeSSE: (projectId: string, onDone?: (projectId: string) => void) => {
      const url = `${API_BASE}/sse-progress/stream/${projectId}`
      let es: EventSource | null = null
      let closed = false

      const connect = () => {
        if (closed) return
        es = new EventSource(url)

        es.onmessage = (event) => {
          try {
            const data: SimpleProgress = JSON.parse(event.data)
            get().upsert(data)
            // stage === DONE 时也触发回调（兼容没有单独 done 事件的后端）
            if (data.stage === 'DONE' && onDone) onDone(projectId)
          } catch (_) {}
        }

        es.addEventListener('done', () => {
          es?.close()
          onDone?.(projectId)
        })

        es.onerror = () => {
          es?.close()
          // 断线后 3s 重连
          if (!closed) setTimeout(connect, 3000)
        }
      }

      connect()

      // 返回取消订阅函数
      return () => {
        closed = true
        es?.close()
      }
    },

    // ──────────────────────────────────────────────
    // 轮询（多项目批量，兼容旧代码）
    // ──────────────────────────────────────────────
    startPolling: (projectIds: string[], intervalMs: number = 2000) => {
      const { stopPolling, isPolling } = get()
      if (isPolling) stopPolling()
      if (projectIds.length === 0) return

      const fetchSnapshots = async () => {
        try {
          const qs = projectIds.map((id) => `project_ids=${id}`).join('&')
          const res = await fetch(`${API_BASE}/simple-progress/snapshot?${qs}`)
          if (!res.ok) return
          const snapshots: SimpleProgress[] = await res.json()
          snapshots.forEach((s) => get().upsert(s))
        } catch (_) {}
      }

      fetchSnapshots()
      timer = setInterval(fetchSnapshots, intervalMs)
      set({ isPolling: true, pollingInterval: intervalMs })
    },

    stopPolling: () => {
      if (timer) { clearInterval(timer); timer = null }
      set({ isPolling: false, pollingInterval: null })
    },

    clearProgress: (projectId: string) => {
      set((state) => {
        const nb = { ...state.byId }
        delete nb[projectId]
        return { byId: nb }
      })
    },

    clearAllProgress: () => set({ byId: {} }),

    getProgress: (projectId: string) => get().byId[projectId] || null,

    getAllProgress: () => get().byId,
  }
})

// ──────────────────────────────────────────────
// 辅助常量和函数（外部组件使用）
// ──────────────────────────────────────────────

export const STAGE_DISPLAY_NAMES: Record<string, string> = {
  INGEST:    '素材准备',
  SUBTITLE:  '字幕处理',
  ANALYZE:   '内容分析',
  HIGHLIGHT: '片段定位',
  EXPORT:    '视频导出',
  DONE:      '处理完成',
}

export const STAGE_COLORS: Record<string, string> = {
  INGEST:    '#1890ff',
  SUBTITLE:  '#52c41a',
  ANALYZE:   '#fa8c16',
  HIGHLIGHT: '#722ed1',
  EXPORT:    '#eb2f96',
  DONE:      '#13c2c2',
}

export const getStageDisplayName = (stage: string): string =>
  STAGE_DISPLAY_NAMES[stage] || stage

export const getStageColor = (stage: string): string =>
  STAGE_COLORS[stage] || '#666666'

export const isCompleted = (stage: string): boolean => stage === 'DONE'

export const isFailed = (message: string): boolean =>
  message.includes('失败') || message.includes('错误')
