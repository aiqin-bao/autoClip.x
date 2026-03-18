import React, { useState, useEffect, useCallback } from 'react'
import { Button, message, Progress, Input, Card, Typography, Space, Spin, Tag, Tooltip } from 'antd'
import { DownloadOutlined, QrcodeOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { projectApi, bilibiliApi, VideoCategory, BilibiliDownloadTask } from '../services/api'
import { useProjectStore } from '../store/useProjectStore'

const { Text } = Typography

interface BilibiliDownloadProps {
  onDownloadSuccess?: (projectId: string) => void
}

const BilibiliDownload: React.FC<BilibiliDownloadProps> = ({ onDownloadSuccess }) => {
  const [url, setUrl] = useState('')
  const [projectName, setProjectName] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [categories, setCategories] = useState<VideoCategory[]>([])
  const [loadingCategories, setLoadingCategories] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [currentTask, setCurrentTask] = useState<BilibiliDownloadTask | null>(null)
  const [pollingInterval, setPollingInterval] = useState<number | null>(null)
  const [videoInfo, setVideoInfo] = useState<any>(null)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState('')

  // 登录状态
  const [loginStatus, setLoginStatus] = useState<{
    status: string
    cookie_valid: boolean
    cookie_age_hours: number | null
    authenticated: boolean
    browser_profile: boolean
  } | null>(null)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginPollInterval, setLoginPollInterval] = useState<number | null>(null)

  const { addProject } = useProjectStore()

  const fetchLoginStatus = useCallback(async () => {
    try {
      const res = await bilibiliApi.getLoginStatus()
      setLoginStatus(res)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    const loadCategories = async () => {
      setLoadingCategories(true)
      try {
        const response = await projectApi.getVideoCategories()
        setCategories(response.categories)
        if (response.default_category) {
          setSelectedCategory(response.default_category)
        } else if (response.categories.length > 0) {
          setSelectedCategory(response.categories[0].value)
        }
      } catch {
        message.error('加载视频分类失败')
      } finally {
        setLoadingCategories(false)
      }
    }
    loadCategories()
    fetchLoginStatus()
  }, [fetchLoginStatus])

  useEffect(() => {
    return () => {
      if (pollingInterval) clearInterval(pollingInterval)
      if (loginPollInterval) clearInterval(loginPollInterval)
    }
  }, [pollingInterval, loginPollInterval])

  const handleStartLogin = async () => {
    setLoginLoading(true)
    try {
      const res = await bilibiliApi.startLogin()
      if (res.status === 'already_logged_in') {
        message.success('已处于登录状态')
        await fetchLoginStatus()
        setLoginLoading(false)
        return
      }
      message.info('浏览器窗口正在打开，请在弹出窗口中扫码登录 B站')
      let checks = 0
      const interval = window.setInterval(async () => {
        checks++
        const status = await bilibiliApi.getLoginStatus()
        setLoginStatus(status)
        if (status.status === 'success' || status.cookie_valid) {
          clearInterval(interval)
          setLoginPollInterval(null)
          setLoginLoading(false)
          message.success('B站登录成功！')
        } else if (checks > 120) {
          clearInterval(interval)
          setLoginPollInterval(null)
          setLoginLoading(false)
        }
      }, 3000)
      setLoginPollInterval(interval)
    } catch {
      setLoginLoading(false)
      message.error('启动登录失败')
    }
  }

  const handleClearLogin = async () => {
    try {
      await bilibiliApi.clearLogin()
      await fetchLoginStatus()
      message.success('B站登录状态已清除')
    } catch {
      message.error('清除失败')
    }
  }

  const validateVideoUrl = (url: string): boolean => {
    const bilibiliPatterns = [
      /^https?:\/\/www\.bilibili\.com\/video\/[Bb][Vv][0-9A-Za-z]+/,
      /^https?:\/\/bilibili\.com\/video\/[Bb][Vv][0-9A-Za-z]+/,
      /^https?:\/\/b23\.tv\/[0-9A-Za-z]+/,
      /^https?:\/\/www\.bilibili\.com\/video\/av\d+/,
      /^https?:\/\/bilibili\.com\/video\/av\d+/
    ]
    const youtubePatterns = [
      /^https?:\/\/(www\.)?youtube\.com\/watch\?v=[a-zA-Z0-9_-]+/,
      /^https?:\/\/youtu\.be\/[a-zA-Z0-9_-]+/,
      /^https?:\/\/(www\.)?youtube\.com\/embed\/[a-zA-Z0-9_-]+/,
      /^https?:\/\/(www\.)?youtube\.com\/v\/[a-zA-Z0-9_-]+/
    ]
    return bilibiliPatterns.some(p => p.test(url)) || youtubePatterns.some(p => p.test(url))
  }

  const getVideoType = (url: string): 'bilibili' | 'youtube' | null => {
    const bilibiliPatterns = [
      /^https?:\/\/www\.bilibili\.com\/video\/[Bb][Vv][0-9A-Za-z]+/,
      /^https?:\/\/bilibili\.com\/video\/[Bb][Vv][0-9A-Za-z]+/,
      /^https?:\/\/b23\.tv\/[0-9A-Za-z]+/,
      /^https?:\/\/www\.bilibili\.com\/video\/av\d+/,
      /^https?:\/\/bilibili\.com\/video\/av\d+/
    ]
    const youtubePatterns = [
      /^https?:\/\/(www\.)?youtube\.com\/watch\?v=[a-zA-Z0-9_-]+/,
      /^https?:\/\/youtu\.be\/[a-zA-Z0-9_-]+/,
      /^https?:\/\/(www\.)?youtube\.com\/embed\/[a-zA-Z0-9_-]+/,
      /^https?:\/\/(www\.)?youtube\.com\/v\/[a-zA-Z0-9_-]+/
    ]
    if (bilibiliPatterns.some(p => p.test(url))) return 'bilibili'
    if (youtubePatterns.some(p => p.test(url))) return 'youtube'
    return null
  }

  const parseVideoInfo = async () => {
    if (!url.trim()) { setError('请输入正确的视频链接'); return }
    const videoType = getVideoType(url.trim())
    if (!videoType) { setError('请输入正确的B站或YouTube视频链接'); return }
    setParsing(true)
    setError('')
    try {
      let response: any
      if (videoType === 'bilibili') {
        response = await bilibiliApi.parseVideoInfo(url.trim())
      } else {
        response = await bilibiliApi.parseYouTubeVideoInfo(url.trim())
      }
      const parsed = response.video_info
      setVideoInfo(parsed)
      if (!projectName && parsed.title) setProjectName(parsed.title)
    } catch {
      setError('请输入正确的视频链接')
      setVideoInfo(null)
    } finally {
      setParsing(false)
    }
  }

  const startPolling = (taskId: string, videoType: 'bilibili' | 'youtube') => {
    const interval = setInterval(async () => {
      try {
        const task = videoType === 'bilibili'
          ? await bilibiliApi.getTaskStatus(taskId)
          : await bilibiliApi.getYouTubeTaskStatus(taskId)
        setCurrentTask(task)
        if (task.status === 'completed') {
          clearInterval(interval)
          setPollingInterval(null)
          setDownloading(false)
          message.success('视频下载完成！')
          if (task.project_id && onDownloadSuccess) onDownloadSuccess(task.project_id)
          resetForm()
        } else if (task.status === 'failed') {
          clearInterval(interval)
          setPollingInterval(null)
          setDownloading(false)
          message.error(`下载失败: ${task.error_message || '未知错误'}`)
          resetForm()
        }
      } catch { /* ignore */ }
    }, 2000)
    setPollingInterval(interval)
  }

  const handleDownload = async () => {
    if (!url.trim()) { message.error('请输入视频链接'); return }
    const videoType = getVideoType(url.trim())
    if (!videoType) { message.error('请输入有效的B站或YouTube视频链接'); return }
    setDownloading(true)
    try {
      const requestBody: any = { url: url.trim(), video_category: selectedCategory }
      if (projectName.trim()) requestBody.project_name = projectName.trim()
      const response = videoType === 'bilibili'
        ? await bilibiliApi.createDownloadTask(requestBody)
        : await bilibiliApi.createYouTubeDownloadTask(requestBody)
      if (response.project_id) {
        setCurrentTask(null)
        setDownloading(false)
        resetForm()
        message.success(`${videoType === 'bilibili' ? 'B站' : 'YouTube'}项目创建成功，正在后台下载中`)
        if (onDownloadSuccess) onDownloadSuccess(response.project_id)
      } else {
        setCurrentTask(response)
        startPolling(response.id, videoType)
      }
    } catch (e: any) {
      setDownloading(false)
      message.error(e.response?.data?.detail || e.message || '创建下载任务失败')
    }
  }

  const resetForm = () => {
    setUrl('')
    setProjectName('')
    setCurrentTask(null)
    setVideoInfo(null)
    setError('')
  }

  const isBilibiliUrl = getVideoType(url.trim()) === 'bilibili'
  const isLoggedIn = loginStatus?.cookie_valid

  return (
    <div style={{ width: '100%', margin: '0 auto' }}>

      {/* B站登录状态栏（始终显示） */}
      {(
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderRadius: '8px',
          marginBottom: '16px',
          background: isLoggedIn ? 'rgba(82,196,26,0.08)' : 'rgba(255,77,79,0.08)',
          border: `1px solid ${isLoggedIn ? 'rgba(82,196,26,0.3)' : 'rgba(255,77,79,0.25)'}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
            <span style={{ fontSize: '18px' }}>📺</span>
            <div style={{ fontSize: '12px', color: isLoggedIn ? '#95de64' : '#ff7875' }}>
              {isLoggedIn ? (
                <span>
                  B站已登录
                  {loginStatus?.authenticated && <Tag color="gold" style={{ marginLeft: 6, fontSize: '10px' }}>已认证</Tag>}
                  {loginStatus?.cookie_age_hours != null && (
                    <span style={{ color: 'rgba(255,255,255,0.4)', marginLeft: 6 }}>
                      ({loginStatus.cookie_age_hours.toFixed(1)}h 前)
                    </span>
                  )}
                </span>
              ) : (
                <span>未登录 — 登录后可下载 AI 字幕等会员内容</span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
            {isLoggedIn && (
              <Tooltip title="清除登录状态">
                <Button
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={handleClearLogin}
                  style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.15)', color: '#aaa' }}
                />
              </Tooltip>
            )}
            <Tooltip title={isLoggedIn ? '刷新状态' : '扫码登录 B站'}>
              <Button
                size="small"
                icon={isLoggedIn ? <ReloadOutlined /> : <QrcodeOutlined />}
                onClick={isLoggedIn ? fetchLoginStatus : handleStartLogin}
                loading={loginLoading}
                style={{
                  background: isLoggedIn ? 'transparent' : 'rgba(255,77,79,0.15)',
                  border: `1px solid ${isLoggedIn ? 'rgba(255,255,255,0.15)' : 'rgba(255,77,79,0.5)'}`,
                  color: isLoggedIn ? '#aaa' : '#ff4d4f',
                  fontWeight: isLoggedIn ? 400 : 600,
                }}
              >
                {loginLoading ? '等待登录...' : isLoggedIn ? '刷新' : '扫码登录'}
              </Button>
            </Tooltip>
          </div>
        </div>
      )}

      {/* 输入表单 */}
      <div style={{ marginBottom: '16px' }}>
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          <div>
            <Input.TextArea
              placeholder="请粘贴B站或YouTube视频链接，支持：• B站：https://www.bilibili.com/video/BV1xx411c7mu • YouTube：https://www.youtube.com/watch?v=xxxxx"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                if (videoInfo) { setVideoInfo(null); setProjectName('') }
                if (error) setError('')
              }}
              onBlur={() => {
                if (url.trim() && !videoInfo && validateVideoUrl(url.trim())) parseVideoInfo()
              }}
              style={{
                background: 'rgba(38, 38, 38, 0.8)',
                border: '1px solid rgba(79, 172, 254, 0.3)',
                borderRadius: '8px',
                color: '#ffffff',
                fontSize: '14px',
                resize: 'none'
              }}
              rows={2}
              disabled={downloading || parsing}
            />
            {parsing && (
              <div style={{ marginTop: '8px', color: '#4facfe', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>正在解析视频信息...</span>
              </div>
            )}
            {error && !parsing && (
              <div style={{ marginTop: '8px', color: '#ff6b6b', fontSize: '14px' }}>
                <span>{error}</span>
              </div>
            )}
          </div>

          {videoInfo && (
            <div style={{
              background: 'rgba(102, 126, 234, 0.1)',
              border: '1px solid rgba(102, 126, 234, 0.3)',
              borderRadius: '8px',
              padding: '12px',
              marginBottom: '12px'
            }}>
              <Text style={{ color: '#667eea', fontWeight: 600, fontSize: '16px', display: 'block', marginBottom: '8px' }}>
                视频信息解析成功
              </Text>
              <Text style={{ color: '#ffffff', fontSize: '14px', display: 'block' }}>{videoInfo.title}</Text>
              <Text style={{ color: 'rgba(255,255,255,0.6)', fontSize: '12px' }}>
                {getVideoType(url) === 'bilibili' ? 'UP主' : '频道'}: {videoInfo.uploader || '未知'} • 时长: {videoInfo.duration ? `${Math.floor(videoInfo.duration / 60)}:${String(Math.floor(videoInfo.duration % 60)).padStart(2, '0')}` : '未知'}
              </Text>
            </div>
          )}

          {videoInfo && (
            <>
              <div>
                <Text style={{ color: '#ffffff', marginBottom: '12px', display: 'block', fontSize: '16px', fontWeight: 500 }}>项目名称（可选）</Text>
                <Input
                  placeholder="留空将使用视频标题作为项目名称"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  style={{
                    background: 'rgba(38, 38, 38, 0.8)',
                    border: '1px solid rgba(79, 172, 254, 0.3)',
                    borderRadius: '12px',
                    color: '#ffffff',
                    height: '48px',
                    fontSize: '14px'
                  }}
                  disabled={downloading}
                />
              </div>

              <div>
                <Text style={{ color: '#ffffff', marginBottom: '12px', display: 'block', fontSize: '16px', fontWeight: 500 }}>视频分类</Text>
                {loadingCategories ? (
                  <Spin size="small" />
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {categories.map(category => {
                      const isSelected = selectedCategory === category.value
                      return (
                        <div
                          key={category.value}
                          onClick={() => setSelectedCategory(category.value)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: '6px',
                            padding: '8px 12px', borderRadius: '6px',
                            border: isSelected ? `2px solid ${category.color}` : '2px solid rgba(255,255,255,0.1)',
                            background: isSelected ? `${category.color}25` : 'rgba(255,255,255,0.05)',
                            color: isSelected ? '#ffffff' : 'rgba(255,255,255,0.8)',
                            boxShadow: isSelected ? `0 0 12px ${category.color}40` : 'none',
                            cursor: 'pointer', transition: 'all 0.2s ease',
                            fontSize: '13px', fontWeight: isSelected ? 600 : 400, userSelect: 'none'
                          }}
                          onMouseEnter={(e) => { if (!isSelected) { e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.2)' } }}
                          onMouseLeave={(e) => { if (!isSelected) { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)' } }}
                        >
                          <span style={{ fontSize: '14px' }}>{category.icon}</span>
                          <span>{category.name}</span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </Space>
      </div>

      {videoInfo && (
        <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'center', gap: '12px' }}>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleDownload}
            loading={downloading}
            disabled={!url.trim()}
            size="large"
            style={{
              background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
              border: 'none', borderRadius: '12px', height: '48px',
              padding: '0 32px', fontSize: '16px', fontWeight: 600,
              boxShadow: '0 4px 20px rgba(79,172,254,0.3)', minWidth: '160px'
            }}
          >
            {downloading ? '导入中...' : '开始导入'}
          </Button>
          {downloading && (
            <Button
              onClick={() => { if (pollingInterval) { clearInterval(pollingInterval); setPollingInterval(null) } setDownloading(false); setCurrentTask(null); message.info('已停止监控下载任务') }}
              size="large"
              style={{
                background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.3)',
                color: '#ffffff', borderRadius: '12px', height: '48px', padding: '0 24px', fontSize: '14px'
              }}
            >
              停止监控
            </Button>
          )}
        </div>
      )}

      {currentTask && (
        <Card
          style={{
            background: 'rgba(38,38,38,0.8)', border: '1px solid rgba(79,172,254,0.3)',
            borderRadius: '12px', marginTop: '16px', backdropFilter: 'blur(10px)'
          }}
          styles={{ body: { padding: '16px' } }}
        >
          <Text style={{ color: '#ffffff', fontWeight: 600, fontSize: '18px', display: 'block', marginBottom: '16px' }}>导入进度</Text>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <Text style={{ color: '#cccccc', fontSize: '14px' }}>状态: {currentTask.status}</Text>
            <Text style={{ color: '#cccccc', fontSize: '14px' }}>{Math.round(currentTask.progress)}%</Text>
          </div>
          <Progress
            percent={Math.round(currentTask.progress)}
            status={currentTask.status === 'failed' ? 'exception' : 'active'}
            strokeColor={{ '0%': '#4facfe', '100%': '#00f2fe' }}
            trailColor="rgba(255,255,255,0.1)"
            strokeWidth={8}
            showInfo={false}
          />
          {currentTask.error_message && (
            <div style={{ marginTop: '16px', padding: '12px', background: 'rgba(255,77,79,0.1)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: '8px' }}>
              <Text style={{ color: '#ff4d4f', fontSize: '14px' }}>错误: {currentTask.error_message}</Text>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

export default BilibiliDownload
