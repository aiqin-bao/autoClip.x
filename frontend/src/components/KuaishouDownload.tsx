import React, { useState, useEffect } from 'react'
import { Button, message, Progress, Input, Space, Select } from 'antd'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import { projectApi, kuaishouApi, VideoCategory, BilibiliDownloadTask } from '../services/api'

interface KuaishouDownloadProps {
  onDownloadSuccess?: (projectId: string) => void
}

// 从分享文本中提取快手链接
function extractKuaishouUrl(text: string): string | null {
  const patterns = [
    /https?:\/\/www\.kuaishou\.com\/f\/[A-Za-z0-9_\-]+/,
    /https?:\/\/www\.kuaishou\.com\/short-video\/[A-Za-z0-9_\-]+/,
    /https?:\/\/v\.kuaishou\.com\/[A-Za-z0-9_\-]+/,
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m) {
      let url = m[0].replace(/\/$/, '')
      // 移除查询参数
      if (url.includes('?')) {
        url = url.split('?')[0]
      }
      return url
    }
  }
  return null
}

const KuaishouDownload: React.FC<KuaishouDownloadProps> = ({ onDownloadSuccess }) => {
  const [shareText, setShareText] = useState('')
  const [projectName, setProjectName] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [categories, setCategories] = useState<VideoCategory[]>([])
  const [loadingCategories, setLoadingCategories] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [videoInfo, setVideoInfo] = useState<any>(null)
  const [extractedUrl, setExtractedUrl] = useState<string>('')
  const [error, setError] = useState('')
  const [currentTask, setCurrentTask] = useState<BilibiliDownloadTask | null>(null)
  const [pollingInterval, setPollingInterval] = useState<number | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoadingCategories(true)
      try {
        const res = await projectApi.getVideoCategories()
        setCategories(res.categories)
        setSelectedCategory(res.default_category || res.categories[0]?.value || 'default')
      } catch {
        message.error('加载视频分类失败')
      } finally {
        setLoadingCategories(false)
      }
    }
    load()
  }, [])

  useEffect(() => {
    return () => {
      if (pollingInterval) clearInterval(pollingInterval)
    }
  }, [pollingInterval])

  const parseVideo = async () => {
    const text = shareText.trim()
    if (!text) {
      setError('请粘贴快手分享链接')
      return
    }

    const url = extractKuaishouUrl(text) || (text.startsWith('http') ? text : null)
    if (!url) {
      setError('未检测到快手链接，请确认粘贴了正确的快手分享链接')
      return
    }

    setParsing(true)
    setError('')
    try {
      const res = await kuaishouApi.parseVideoInfo(text)
      setVideoInfo(res.video_info)
      setExtractedUrl(res.extracted_url || url)
      if (!projectName && res.video_info?.title) {
        setProjectName(res.video_info.title.slice(0, 50))
      }
    } catch (e: any) {
      const detail: string = e?.response?.data?.detail || ''
      setError(detail || '解析失败，请检查链接是否有效')
      setVideoInfo(null)
    } finally {
      setParsing(false)
    }
  }

  const handleDownload = async () => {
    const text = shareText.trim()
    if (!text) {
      message.error('请粘贴快手分享链接')
      return
    }
    if (!projectName.trim()) {
      message.error('请填写项目名称')
      return
    }

    setDownloading(true)
    try {
      const res = await kuaishouApi.createDownloadTask({
        share_text: text,
        project_name: projectName.trim(),
        video_category: selectedCategory,
      })

      if (res.project_id) {
        setDownloading(false)
        resetForm()
        message.success('快手项目已创建，正在后台下载，您可以继续添加其他项目')
        if (onDownloadSuccess) onDownloadSuccess(res.project_id)
      } else {
        setCurrentTask(res as any)
        startPolling((res as any).id)
      }
    } catch (e: any) {
      setDownloading(false)
      message.error(e?.response?.data?.detail || '创建下载任务失败')
    }
  }

  const startPolling = (taskId: string) => {
    const interval = window.setInterval(async () => {
      try {
        const task = await kuaishouApi.getTaskStatus(taskId)
        setCurrentTask(task)
        if (task.status === 'completed') {
          clearInterval(interval)
          setPollingInterval(null)
          setDownloading(false)
          message.success('快手视频下载完成！')
          if (task.project_id && onDownloadSuccess) onDownloadSuccess(task.project_id)
          resetForm()
        } else if (task.status === 'failed') {
          clearInterval(interval)
          setPollingInterval(null)
          setDownloading(false)
          message.error(`下载失败: ${task.error_message || '未知错误'}`)
          resetForm()
        }
      } catch {
        // 忽略轮询错误
      }
    }, 2000)
    setPollingInterval(interval)
  }

  const resetForm = () => {
    setShareText('')
    setProjectName('')
    setVideoInfo(null)
    setExtractedUrl('')
    setError('')
    setCurrentTask(null)
  }

  const inputTextStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.07)',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: '8px',
    color: '#ffffff',
    padding: '10px 14px',
  }
  const labelStyle: React.CSSProperties = {
    color: '#aaaaaa',
    fontSize: '13px',
    marginBottom: '6px',
    display: 'block',
  }

  return (
    <div style={{ width: '100%' }}>
      <Space direction="vertical" style={{ width: '100%' }} size={16}>

        {/* 分享链接输入 */}
        <div>
          <span style={labelStyle}>粘贴快手分享链接</span>
          <Input
            placeholder="例如：https://www.kuaishou.com/f/X7armvf4foO21Sq"
            value={shareText}
            onChange={(e) => {
              setShareText(e.target.value)
              if (videoInfo) { setVideoInfo(null); setProjectName('') }
              if (error) setError('')
            }}
            onBlur={() => {
              if (shareText.trim() && !videoInfo && !parsing) {
                const url = extractKuaishouUrl(shareText.trim())
                if (url) parseVideo()
              }
            }}
            style={inputTextStyle}
          />
          {error && <div style={{ color: '#ff4d4f', fontSize: '12px', marginTop: '4px' }}>{error}</div>}
        </div>

        {/* 解析按钮 */}
        {!videoInfo && (
          <Button
            onClick={parseVideo}
            loading={parsing}
            icon={<SearchOutlined />}
            style={{
              background: 'rgba(255, 120, 0, 0.15)',
              border: '1px solid rgba(255, 120, 0, 0.4)',
              color: '#ff7800',
              borderRadius: '8px',
              height: '40px',
              width: '100%',
            }}
          >
            {parsing ? '识别中...' : '识别视频信息'}
          </Button>
        )}

        {/* 视频信息卡片 */}
        {videoInfo && (
          <div style={{
            background: 'rgba(255, 120, 0, 0.08)',
            border: '1px solid rgba(255, 120, 0, 0.25)',
            borderRadius: '12px',
            padding: '16px',
          }}>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              {videoInfo.thumbnail && (
                <img
                  src={videoInfo.thumbnail}
                  alt="封面"
                  style={{ width: '80px', height: '106px', objectFit: 'cover', borderRadius: '6px', flexShrink: 0 }}
                />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: '#ffffff', fontWeight: 600, fontSize: '14px', marginBottom: '6px', wordBreak: 'break-word' }}>
                  {videoInfo.title}
                </div>
                <div style={{ color: '#aaaaaa', fontSize: '12px', lineHeight: '1.8' }}>
                  <span>👤 {videoInfo.uploader}</span>
                  {videoInfo.duration > 0 && (
                    <span style={{ marginLeft: '12px' }}>
                      ⏱ {Math.floor(videoInfo.duration / 60)}:{String(videoInfo.duration % 60).padStart(2, '0')}
                    </span>
                  )}
                  {videoInfo.view_count > 0 && (
                    <span style={{ marginLeft: '12px' }}>▶ {videoInfo.view_count.toLocaleString()}</span>
                  )}
                </div>
                {extractedUrl && (
                  <div style={{ color: '#666', fontSize: '11px', marginTop: '4px', wordBreak: 'break-all' }}>
                    {extractedUrl}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 项目设置 */}
        {videoInfo && (
          <>
            <div>
              <span style={labelStyle}>项目名称</span>
              <Input
                placeholder="填写项目名称"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                style={inputTextStyle}
              />
            </div>

            <div>
              <span style={labelStyle}>视频分类</span>
              <Select
                value={selectedCategory}
                onChange={setSelectedCategory}
                style={{ width: '100%' }}
                loading={loadingCategories}
                popupClassName="dark-select-dropdown"
                options={categories.map(cat => ({
                  label: `${cat.icon || ''} ${cat.name}`,
                  value: cat.value,
                }))}
              />
            </div>

            <Button
              type="primary"
              onClick={handleDownload}
              loading={downloading}
              icon={<DownloadOutlined />}
              disabled={!projectName.trim()}
              style={{
                background: downloading ? undefined : 'linear-gradient(135deg, #ff7800 0%, #ffa940 100%)',
                border: 'none',
                borderRadius: '8px',
                height: '44px',
                width: '100%',
                fontSize: '15px',
                fontWeight: 600,
              }}
            >
              {downloading ? '正在下载...' : '开始下载并切片'}
            </Button>
          </>
        )}

        {/* 下载进度 */}
        {currentTask && (currentTask.status === 'processing' || currentTask.status === 'pending') && (
          <div style={{
            background: 'rgba(255, 120, 0, 0.06)',
            border: '1px solid rgba(255, 120, 0, 0.2)',
            borderRadius: '10px',
            padding: '14px',
          }}>
            <div style={{ color: '#aaa', fontSize: '12px', marginBottom: '8px' }}>
              正在下载：{currentTask.project_name}
            </div>
            <Progress
              percent={Math.round(currentTask.progress)}
              strokeColor={{ from: '#ff7800', to: '#ffa940' }}
              trailColor="rgba(255,255,255,0.1)"
              size="small"
            />
          </div>
        )}

        {/* 提示说明 */}
        {!videoInfo && (
          <div style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '10px',
            padding: '14px',
            fontSize: '12px',
            color: '#888',
            lineHeight: '1.8',
          }}>
            <div style={{ color: '#aaa', fontWeight: 600, marginBottom: '6px' }}>📌 使用说明</div>
            <div>1. 打开快手 App，找到想要下载的视频</div>
            <div>2. 点击右下角 <b>分享</b> → <b>复制链接</b></div>
            <div>3. 将复制的链接粘贴到上方输入框</div>
            <div>4. 系统会自动识别并下载视频</div>
            <div style={{ marginTop: '8px', color: '#52c41a', fontWeight: 600 }}>
              ✨ 使用多种解析方案自动尝试，提供最佳下载体验
            </div>
            <div style={{ marginTop: '6px', color: '#888' }}>
              支持的解析方式：<br/>
              • videodl（8个通用解析器自动切换）<br/>
              • Playwright（备选方案）
            </div>
            <div style={{ marginTop: '8px', color: '#666' }}>
              如遇下载失败，建议：<br/>
              • 使用 B站/YouTube（更稳定）✅<br/>
              • 手动下载后通过"文件导入"上传 ✅
            </div>
          </div>
        )}
      </Space>
    </div>
  )
}

export default KuaishouDownload
