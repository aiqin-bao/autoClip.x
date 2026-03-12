import React, { useState, useEffect, useCallback } from 'react'
import { Button, message, Progress, Input, Space, Select, Tag, Tooltip } from 'antd'
import { DownloadOutlined, SearchOutlined, QrcodeOutlined, CheckCircleOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { projectApi, douyinApi, VideoCategory, BilibiliDownloadTask } from '../services/api'

interface DouyinDownloadProps {
  onDownloadSuccess?: (projectId: string) => void
}

// 从分享文本中提取抖音链接（前端侧预处理）
function extractDouyinUrl(text: string): string | null {
  const patterns = [
    /https?:\/\/v\.douyin\.com\/[A-Za-z0-9_\-]+\/?/,
    /https?:\/\/www\.douyin\.com\/video\/\d+/,
    /https?:\/\/vm\.tiktok\.com\/[A-Za-z0-9_\-]+\/?/,
    /https?:\/\/(www\.)?tiktok\.com\/@[^/]+\/video\/\d+/,
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m) return m[0].replace(/\/$/, '')
  }
  return null
}

const DouyinDownload: React.FC<DouyinDownloadProps> = ({ onDownloadSuccess }) => {
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

  // 登录状态
  const [loginStatus, setLoginStatus] = useState<{
    status: string
    message: string
    has_cookies: boolean
    cookie_valid: boolean
    cookie_age_hours?: number
    authenticated?: boolean
  } | null>(null)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginPollInterval, setLoginPollInterval] = useState<number | null>(null)

  // 加载视频分类 + 登录状态
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
    fetchLoginStatus()
  }, [])

  useEffect(() => {
    return () => {
      if (pollingInterval) clearInterval(pollingInterval)
      if (loginPollInterval) clearInterval(loginPollInterval)
    }
  }, [pollingInterval, loginPollInterval])

  const fetchLoginStatus = useCallback(async () => {
    try {
      const res = await douyinApi.getLoginStatus()
      setLoginStatus(res)
    } catch {
      // 忽略
    }
  }, [])

  const handleStartLogin = async () => {
    setLoginLoading(true)
    try {
      await douyinApi.startLogin()
      message.info('浏览器窗口正在打开，请在弹出窗口中登录抖音')

      // 每 3 秒轮询登录状态，最多 6 分钟
      let checks = 0
      const interval = window.setInterval(async () => {
        checks++
        const status = await douyinApi.getLoginStatus()
        setLoginStatus(status)
        if (status.status === 'success' || status.cookie_valid) {
          clearInterval(interval)
          setLoginPollInterval(null)
          setLoginLoading(false)
          message.success('Cookie 获取成功！请重新点击"识别视频信息"')
          setError('')
        } else if (status.status === 'failed') {
          clearInterval(interval)
          setLoginPollInterval(null)
          setLoginLoading(false)
          message.error('登录失败：' + status.message)
        } else if (checks > 120) {
          clearInterval(interval)
          setLoginPollInterval(null)
          setLoginLoading(false)
        }
      }, 3000)
      setLoginPollInterval(interval)
    } catch (e: any) {
      setLoginLoading(false)
      message.error(e?.response?.data?.detail || '启动登录失败')
    }
  }

  const handleClearCookies = async () => {
    try {
      await douyinApi.clearCookies()
      message.success('Cookie 已清除')
      fetchLoginStatus()
    } catch {
      message.error('清除失败')
    }
  }

  const parseVideo = async () => {
    const text = shareText.trim()
    if (!text) {
      setError('请粘贴抖音分享文本或链接')
      return
    }

    // 先在前端尝试提取 URL
    const url = extractDouyinUrl(text) || (text.startsWith('http') ? text : null)
    if (!url) {
      setError('未检测到抖音链接，请确认粘贴了含有 v.douyin.com 的分享内容')
      return
    }

    setParsing(true)
    setError('')
    try {
      const res = await douyinApi.parseVideoInfo(text)
      setVideoInfo(res.video_info)
      setExtractedUrl(res.extracted_url || url)
      if (!projectName && res.video_info?.title) {
        setProjectName(res.video_info.title.slice(0, 50))
      }
    } catch (e: any) {
      const detail: string = e?.response?.data?.detail || ''
      if (detail.includes('NEED_LOGIN') || detail.includes('Cookie') || detail.includes('cookie') || detail.includes('Fresh')) {
        setError('NEED_LOGIN')
      } else {
        setError(detail || '解析失败，请检查链接是否有效')
      }
      setVideoInfo(null)
    } finally {
      setParsing(false)
    }
  }

  const handleDownload = async () => {
    const text = shareText.trim()
    if (!text) {
      message.error('请粘贴抖音分享内容')
      return
    }
    if (!projectName.trim()) {
      message.error('请填写项目名称')
      return
    }

    setDownloading(true)
    try {
      const res = await douyinApi.createDownloadTask({
        share_text: text,
        project_name: projectName.trim(),
        video_category: selectedCategory,
      })

      if (res.project_id) {
        setDownloading(false)
        resetForm()
        message.success('抖音项目已创建，正在后台下载，您可以继续添加其他项目')
        if (onDownloadSuccess) onDownloadSuccess(res.project_id)
      } else {
        // 旧格式兼容：轮询任务
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
        const task = await douyinApi.getTaskStatus(taskId)
        setCurrentTask(task)
        if (task.status === 'completed') {
          clearInterval(interval)
          setPollingInterval(null)
          setDownloading(false)
          message.success('抖音视频下载完成！')
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

        {/* Cookie / 登录状态栏 */}
        <div style={{
          background: loginStatus?.cookie_valid
            ? 'rgba(82, 196, 26, 0.08)'
            : 'rgba(255, 77, 79, 0.08)',
          border: `1px solid ${loginStatus?.cookie_valid ? 'rgba(82,196,26,0.3)' : 'rgba(255,77,79,0.25)'}`,
          borderRadius: '10px',
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
            {loginStatus?.cookie_valid ? (
              <CheckCircleOutlined style={{ color: '#52c41a', fontSize: '16px', flexShrink: 0 }} />
            ) : (
              <QrcodeOutlined style={{ color: '#ff4d4f', fontSize: '16px', flexShrink: 0 }} />
            )}
            <div style={{ fontSize: '12px', color: loginStatus?.cookie_valid ? '#95de64' : '#ff7875', minWidth: 0 }}>
              {loginStatus?.cookie_valid ? (
                <>
                  <span style={{ fontWeight: 600 }}>Cookie 有效</span>
                  {loginStatus.authenticated && <Tag color="gold" style={{ marginLeft: 6, fontSize: '10px' }}>已登录账号</Tag>}
                  <span style={{ color: '#666', marginLeft: 6 }}>
                    ({loginStatus.cookie_age_hours?.toFixed(1)}h 前获取)
                  </span>
                </>
              ) : loginStatus?.status === 'waiting' ? (
                <span>浏览器窗口已打开，请在窗口中完成登录...</span>
              ) : (
                <span>未登录 — 需要扫码授权才能访问抖音</span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
            {loginStatus?.cookie_valid && (
              <Tooltip title="清除 Cookie，重新登录">
                <Button
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={handleClearCookies}
                  style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.15)', color: '#666' }}
                />
              </Tooltip>
            )}
            <Tooltip title={loginStatus?.cookie_valid ? '刷新 Cookie 状态' : '打开浏览器窗口扫码登录'}>
              <Button
                size="small"
                loading={loginLoading}
                icon={loginStatus?.cookie_valid ? <ReloadOutlined /> : <QrcodeOutlined />}
                onClick={loginStatus?.cookie_valid ? fetchLoginStatus : handleStartLogin}
                style={{
                  background: loginStatus?.cookie_valid
                    ? 'transparent'
                    : 'rgba(255, 77, 79, 0.2)',
                  border: `1px solid ${loginStatus?.cookie_valid ? 'rgba(255,255,255,0.15)' : 'rgba(255,77,79,0.5)'}`,
                  color: loginStatus?.cookie_valid ? '#aaa' : '#ff4d4f',
                  fontWeight: loginStatus?.cookie_valid ? 400 : 600,
                }}
              >
                {loginLoading ? '等待登录...' : loginStatus?.cookie_valid ? '刷新' : '扫码登录'}
              </Button>
            </Tooltip>
          </div>
        </div>

        {/* NEED_LOGIN 错误提示 */}
        {error === 'NEED_LOGIN' && (
          <div style={{
            background: 'rgba(255, 77, 79, 0.1)',
            border: '1px solid rgba(255,77,79,0.35)',
            borderRadius: '10px',
            padding: '14px',
            fontSize: '13px',
          }}>
            <div style={{ color: '#ff4d4f', fontWeight: 600, marginBottom: '8px' }}>
              ⚠️ 需要抖音授权
            </div>
            <div style={{ color: '#ccc', marginBottom: '12px' }}>
              解析抖音视频需要有效的 Cookie。点击下方按钮，在弹出的浏览器窗口中登录抖音即可（支持 App 扫码）。
            </div>
            <Button
              icon={<QrcodeOutlined />}
              loading={loginLoading}
              onClick={handleStartLogin}
              style={{
                background: 'rgba(255,77,79,0.2)',
                border: '1px solid rgba(255,77,79,0.5)',
                color: '#ff4d4f',
                fontWeight: 600,
                width: '100%',
              }}
            >
              {loginLoading ? '等待扫码登录...' : '打开浏览器扫码登录抖音'}
            </Button>
          </div>
        )}

        {/* 分享文本输入 */}
        <div>
          <span style={labelStyle}>粘贴抖音分享内容（可直接粘贴完整分享文本）</span>
          <Input.TextArea
            placeholder={
              '直接从抖音复制分享文字粘贴到这里，例如：\n5.30 复制打开抖音，看看【xxx的作品】# 我的生活 ... https://v.douyin.com/zjv3JEE-J5M/ v@S.lP fbN:/ 11/11\n\n也可以只粘贴链接：https://v.douyin.com/zjv3JEE-J5M/'
            }
            value={shareText}
            autoSize={{ minRows: 3, maxRows: 6 }}
            onChange={(e) => {
              setShareText(e.target.value)
              if (videoInfo) { setVideoInfo(null); setProjectName('') }
              if (error) setError('')
            }}
            onBlur={() => {
              // 失焦时自动解析
              if (shareText.trim() && !videoInfo && !parsing) {
                const url = extractDouyinUrl(shareText.trim())
                if (url) parseVideo()
              }
            }}
            style={{ ...inputTextStyle, resize: 'vertical' }}
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
              background: 'rgba(255, 77, 79, 0.15)',
              border: '1px solid rgba(255, 77, 79, 0.4)',
              color: '#ff4d4f',
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
            background: 'rgba(255, 77, 79, 0.08)',
            border: '1px solid rgba(255, 77, 79, 0.25)',
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

        {/* 只有解析成功后才显示项目设置 */}
        {videoInfo && (
          <>
            {/* 项目名称 */}
            <div>
              <span style={labelStyle}>项目名称</span>
              <Input
                placeholder="填写项目名称"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                style={inputTextStyle}
              />
            </div>

            {/* 视频分类 */}
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

            {/* 下载按钮 */}
            <Button
              type="primary"
              onClick={handleDownload}
              loading={downloading}
              icon={<DownloadOutlined />}
              disabled={!projectName.trim()}
              style={{
                background: downloading ? undefined : 'linear-gradient(135deg, #ff4d4f 0%, #ff7875 100%)',
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
            background: 'rgba(255, 77, 79, 0.06)',
            border: '1px solid rgba(255, 77, 79, 0.2)',
            borderRadius: '10px',
            padding: '14px',
          }}>
            <div style={{ color: '#aaa', fontSize: '12px', marginBottom: '8px' }}>
              正在下载：{currentTask.project_name}
            </div>
            <Progress
              percent={Math.round(currentTask.progress)}
              strokeColor={{ from: '#ff4d4f', to: '#ff7875' }}
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
            <div>1. 打开抖音 App，找到想要下载的视频</div>
            <div>2. 点击右下角 <b>分享</b> → <b>复制链接</b></div>
            <div>3. 将复制的内容粘贴到上方输入框</div>
            <div>4. 系统会自动识别并下载无水印视频</div>
            <div style={{ marginTop: '8px', color: '#666' }}>
              ⚡ 支持抖音分享文本、纯链接，视频无字幕时自动使用 AI 语音识别
            </div>
            <div style={{ marginTop: '6px', color: '#555', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px' }}>
              🍪 首次使用请点击上方 <b style={{ color: '#ff7875' }}>扫码登录</b> 按钮完成授权，之后 Cookie 自动保存，7 天内免登录
            </div>
          </div>
        )}
      </Space>
    </div>
  )
}

export default DouyinDownload
