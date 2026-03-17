/**
 * useProjectSSE
 *
 * 统一管理所有"处理中"项目的 SSE 订阅：
 *   - 有新的 processing 项目时自动订阅
 *   - 项目完成/删除时自动取消订阅
 *   - SSE `done` 事件触发 onProjectDone 回调（通常用于刷新项目列表）
 */

import { useEffect, useRef } from 'react'
import { useSimpleProgressStore } from '../stores/useSimpleProgressStore'

export const useProjectSSE = (
  projectIds: string[],
  onProjectDone?: (projectId: string) => void
) => {
  const subscribeSSE = useSimpleProgressStore((s) => s.subscribeSSE)
  const unsubscribers = useRef<Map<string, () => void>>(new Map())

  // 每次 projectIds 变化时，增量订阅/取消
  useEffect(() => {
    const current = new Set(projectIds)

    // 订阅新增的 id
    current.forEach((id) => {
      if (!unsubscribers.current.has(id)) {
        const unsub = subscribeSSE(id, onProjectDone)
        unsubscribers.current.set(id, unsub)
      }
    })

    // 取消已移除的 id
    unsubscribers.current.forEach((unsub, id) => {
      if (!current.has(id)) {
        unsub()
        unsubscribers.current.delete(id)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectIds.join(',')])

  // 组件卸载时全部取消
  useEffect(() => {
    return () => {
      unsubscribers.current.forEach((unsub) => unsub())
      unsubscribers.current.clear()
    }
  }, [])
}

export default useProjectSSE
