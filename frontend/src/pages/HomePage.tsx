import React, { useState, useEffect } from 'react'
import { 
  Layout, 
  Typography, 
  Select, 
  Spin, 
  Empty,
  message,
  Pagination 
} from 'antd'
import { useNavigate } from 'react-router-dom'
import ProjectCard from '../components/ProjectCard'
import FileUpload from '../components/FileUpload'
import BilibiliDownload from '../components/BilibiliDownload'
import DouyinDownload from '../components/DouyinDownload'

import { projectApi } from '../services/api'
import { Project, useProjectStore } from '../store/useProjectStore'
import { useProjectPolling } from '../hooks/useProjectPolling'
import { useProjectSSE } from '../hooks/useProjectSSE'
// import { useWebSocket, WebSocketEventMessage } from '../hooks/useWebSocket'  // 已禁用WebSocket系统

const { Content } = Layout
const { Title, Text } = Typography
const { Option } = Select

const HomePage: React.FC = () => {
  const navigate = useNavigate()
  const { projects, setProjects, deleteProject, loading, setLoading } = useProjectStore()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [activeTab, setActiveTab] = useState<'upload' | 'bilibili' | 'douyin'>('upload')
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [pageSize, setPageSize] = useState<number>(20)
  const [total, setTotal] = useState<number>(0)

  // WebSocket连接已禁用，使用新的简化进度系统
  // const handleWebSocketMessage = (message: WebSocketEventMessage) => {
  //   console.log('HomePage收到WebSocket消息:', message)
  //   
  //   switch (message.type) {
  //     case 'task_progress_update':
  //       console.log('📊 收到任务进度更新:', message)
  //       // 刷新项目列表以获取最新状态
  //       loadProjects()
  //       break
  //       
  //     case 'project_update':
  //       console.log('📊 收到项目更新:', message)
  //       // 刷新项目列表以获取最新状态
  //       loadProjects()
  //       break
  //       
  //     default:
  //       console.log('忽略未知类型的WebSocket消息:', (message as any).type)
  //   }
  // }

  // const { isConnected, syncSubscriptions } = useWebSocket({
  //   userId: 'homepage-user',
  //   onMessage: handleWebSocketMessage
  // })

  // 正在处理中的项目 id 列表（用于 SSE 订阅）
  const processingIds = projects
    .filter((p) => p.status === 'processing')
    .map((p) => p.id)

  // SSE 订阅：有项目完成时立即刷新列表
  useProjectSSE(processingIds, () => {
    loadProjects()
  })

  // 保底轮询：处理中时 10s/次，空闲时 30s/次（大幅降低无效请求）
  const { refreshNow } = useProjectPolling({
    onProjectsUpdate: (updatedProjects) => {
      // 轮询时不更新分页数据，只在手动刷新时更新
      if (updatedProjects && updatedProjects.length > 0) {
        setProjects(updatedProjects)
      }
    },
    enabled: true,
    interval: processingIds.length > 0 ? 10000 : 30000,
  })

  useEffect(() => {
    loadProjects()
  }, [currentPage, pageSize, statusFilter])

  const loadProjects = async () => {
    setLoading(true)
    try {
      // 从后端API获取真实项目数据，传入分页参数
      const response = await projectApi.getProjects({
        page: currentPage,
        size: pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter
      })
      setProjects(response.items || [])
      setTotal(response.pagination?.total || 0)
    } catch (error) {
      message.error('加载项目失败')
      console.error('Load projects error:', error)
      // 如果API调用失败，设置空数组
      setProjects([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }

  // 使用集合差异对齐订阅项目WebSocket主题
  // WebSocket订阅已禁用，使用新的简化进度系统
  // useEffect(() => {
  //   if (isConnected && projects.length > 0) {
  //     const desiredChannels = projects.map(project => `project_${project.id}`)
  //     console.log('同步订阅项目频道:', desiredChannels)
  //     syncSubscriptions(desiredChannels)
  //   } else if (isConnected && projects.length === 0) {
  //     // 如果没有项目，清空所有订阅
  //     console.log('清空所有项目订阅')
  //     syncSubscriptions([])
  //   }
  // }, [isConnected, projects, syncSubscriptions])

  const handleDeleteProject = async (id: string) => {
    try {
      await projectApi.deleteProject(id)
      deleteProject(id)
      message.success('项目删除成功')
    } catch (error) {
      message.error('删除项目失败')
      console.error('Delete project error:', error)
    }
  }

  const handleRetryProject = async (projectId: string) => {
    try {
      // 查找项目状态
      const project = projects.find(p => p.id === projectId)
      if (!project) {
        message.error('项目不存在')
        return
      }
      
      // 统一使用retryProcessing API，它会自动处理视频文件不存在的情况
      await projectApi.retryProcessing(projectId)
      message.success('已开始重试处理项目')
      
      await loadProjects()
    } catch (error) {
      message.error('重试失败，请稍后再试')
      console.error('Retry project error:', error)
    }
  }

  const handleStartProcessing = async (projectId: string) => {
    try {
      await projectApi.startProcessing(projectId)
      message.success('项目已开始处理，请稍等片刻查看进度')
      // 立即刷新项目列表以显示最新状态
      setTimeout(async () => {
        try {
          await refreshNow()
        } catch (refreshError) {
          console.error('Failed to refresh after starting processing:', refreshError)
        }
      }, 1000)
    } catch (error: unknown) {
      const errorMessage = (error as { userMessage?: string })?.userMessage || '启动处理失败'
      message.error(errorMessage)
      console.error('Start processing error:', error)
      
      // 如果是超时错误，提示用户项目可能仍在处理
      if ((error as { code?: string; message?: string })?.code === 'ECONNABORTED' || (error as { code?: string; message?: string })?.message?.includes('timeout')) {
        message.info('请求超时，但项目可能已开始处理，请查看项目状态', 5)
        // 延迟刷新项目列表
        setTimeout(async () => {
          try {
            await refreshNow()
          } catch (refreshError) {
            console.error('Failed to refresh after timeout:', refreshError)
          }
        }, 3000)
      }
    }
  }

  const handleProjectCardClick = (project: Project) => {
    // 导入中状态的项目不能点击进入详情页
    if (project.status === 'pending') {
      message.warning('项目正在导入中，请稍后再查看详情')
      return
    }
    
    // 其他状态可以正常进入详情页
    navigate(`/project/${project.id}`)
  }

  // 后端已经处理了过滤和排序，前端直接使用
  const filteredProjects = projects

  return (
    <Layout style={{ 
      minHeight: '100vh', 
      background: '#0f0f0f'
    }}>
      <Content style={{ padding: '40px 24px', position: 'relative' }}>
        <div style={{ maxWidth: '1600px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
          {/* 文件上传区域 */}
          <div style={{ 
            marginBottom: '48px',
            marginTop: '20px',
            display: 'flex',
            justifyContent: 'center'
          }}>
            <div style={{
              width: '100%',
              maxWidth: '800px',
              background: 'rgba(26, 26, 46, 0.8)',
              backdropFilter: 'blur(20px)',
              borderRadius: '16px',
              border: '1px solid rgba(79, 172, 254, 0.2)',
              padding: '20px',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.05)'
            }}>
              {/* 标签页切换 */}
              <div style={{
                display: 'flex',
                marginBottom: '16px',
                borderRadius: '8px',
                background: 'rgba(0, 0, 0, 0.3)',
                padding: '3px',
                gap: '2px'
              }}>
                {([
                  { key: 'bilibili', label: '📺 B站/YouTube' },
                  { key: 'douyin',   label: '🎵 抖音' },
                  { key: 'upload',   label: '📁 文件导入' },
                ] as const).map(tab => (
                  <button
                    key={tab.key}
                    style={{
                      flex: 1,
                      padding: '11px 8px',
                      borderRadius: '8px',
                      background: activeTab === tab.key
                        ? tab.key === 'douyin'
                          ? 'rgba(255, 77, 79, 0.2)'
                          : 'rgba(79, 172, 254, 0.2)'
                        : 'transparent',
                      color: activeTab === tab.key
                        ? tab.key === 'douyin' ? '#ff7875' : '#4facfe'
                        : '#cccccc',
                      cursor: 'pointer',
                      fontSize: '14px',
                      fontWeight: 600,
                      transition: 'all 0.3s ease',
                      border: activeTab === tab.key
                        ? tab.key === 'douyin'
                          ? '1px solid rgba(255, 77, 79, 0.4)'
                          : '1px solid rgba(79, 172, 254, 0.4)'
                        : '1px solid transparent',
                      whiteSpace: 'nowrap',
                    }}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              
              {/* 内容区域 */}
              <div>
                {activeTab === 'bilibili' && (
                  <BilibiliDownload onDownloadSuccess={async (projectId: string) => {
                    await loadProjects()
                  }} />
                )}
                {activeTab === 'douyin' && (
                  <DouyinDownload onDownloadSuccess={async (projectId: string) => {
                    await loadProjects()
                  }} />
                )}
                {activeTab === 'upload' && (
                  <FileUpload onUploadSuccess={async (projectId: string) => {
                    await loadProjects()
                    message.success('项目创建成功，正在处理中...')
                  }} />
                )}
              </div>
            </div>
          </div>

          {/* 项目管理区域 */}
          <div style={{
            background: 'rgba(26, 26, 46, 0.7)',
            backdropFilter: 'blur(20px)',
            borderRadius: '24px',
            border: '1px solid rgba(79, 172, 254, 0.15)',
            padding: '32px',
            marginBottom: '32px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.03)'
          }}>
            {/* 项目列表标题区域 */}
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center',
              marginBottom: '24px',
              paddingBottom: '16px',
              borderBottom: '1px solid rgba(79, 172, 254, 0.1)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <Title 
                  level={2} 
                  style={{ 
                    margin: 0,
                    color: '#ffffff',
                    fontSize: '24px',
                    fontWeight: 600,
                    background: 'linear-gradient(135deg, #ffffff 0%, #cccccc 100%)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    backgroundClip: 'text'
                  }}
                >
                  我的项目
                </Title>
                <div style={{
                  padding: '8px 16px',
                  background: 'rgba(79, 172, 254, 0.1)',
                  borderRadius: '20px',
                  border: '1px solid rgba(79, 172, 254, 0.3)',
                  backdropFilter: 'blur(10px)'
                }}>
                  <Text style={{ color: '#4facfe', fontWeight: 600, fontSize: '14px' }}>
                    共 {total} 个项目
                  </Text>
                </div>
              </div>
              
              {/* 状态筛选移到右侧 */}
              <div style={{ 
                display: 'flex', 
                alignItems: 'center'
              }}>
                <Select
                  placeholder="选择状态"
                  value={statusFilter}
                  onChange={(value) => {
                    setStatusFilter(value)
                    setCurrentPage(1) // 改变筛选条件时重置到第一页
                  }}
                  style={{ 
                    minWidth: '140px',
                    height: '36px',
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(79, 172, 254, 0.2)',
                    borderRadius: '8px',
                    color: '#ffffff',
                    fontSize: '14px'
                  }}
                  styles={{
                    popup: {
                      root: {
                        background: 'rgba(26, 26, 46, 0.95)',
                        border: '1px solid rgba(79, 172, 254, 0.3)',
                        borderRadius: '8px',
                        backdropFilter: 'blur(20px)',
                        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)'
                      }
                    }
                  }}
                  suffixIcon={
                    <span style={{ 
                      color: '#8c8c8c', 
                      fontSize: '10px',
                      transition: 'all 0.2s ease'
                    }}>
                      ⌄
                    </span>
                  }
                  allowClear
                >
                  <Option value="all" style={{ color: '#ffffff' }}>全部状态</Option>
                  <Option value="completed" style={{ color: '#52c41a' }}>已完成</Option>
                  <Option value="processing" style={{ color: '#1890ff' }}>处理中</Option>
                  <Option value="error" style={{ color: '#ff4d4f' }}>处理失败</Option>
                </Select>
              </div>
            </div>

            {/* 项目列表内容 */}
             <div>
               {loading ? (
                 <div style={{ 
                   textAlign: 'center', 
                   padding: '60px 0',
                   background: '#262626',
                   borderRadius: '12px',
                   border: '1px solid #404040'
                 }}>
                   <Spin size="large" />
                   <div style={{ 
                     marginTop: '20px', 
                     color: '#cccccc',
                     fontSize: '16px'
                   }}>
                     正在加载项目列表...
                   </div>
                 </div>
               ) : filteredProjects.length === 0 ? (
                 <div style={{
                   textAlign: 'center',
                   padding: '60px 0',
                   background: '#262626',
                   borderRadius: '12px',
                   border: '1px solid #404040'
                 }}>
                   <Empty
                     image={Empty.PRESENTED_IMAGE_SIMPLE}
                     description={
                       <div>
                         <Text type="secondary">
                           {projects.length === 0 ? '还没有项目，请使用上方的导入区域创建第一个项目' : '没有找到匹配的项目'}
                         </Text>
                       </div>
                     }
                   />
                 </div>
               ) : (
                 <div style={{
                   display: 'grid',
                   gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                   gap: '16px',
                   justifyContent: 'start',
                   padding: '6px 0'
                 }}>
                   {filteredProjects.map((project: Project) => (
                     <div key={project.id} style={{ position: 'relative', zIndex: 1 }}>
                       <ProjectCard 
                         project={project} 
                         onDelete={handleDeleteProject}
                         onRetry={() => handleRetryProject(project.id)}
                         onClick={() => handleProjectCardClick(project)}
                       />
                     </div>
                   ))}
                 </div>
               )}
             </div>

             {/* 分页组件 */}
             {!loading && filteredProjects.length > 0 && (
               <div style={{
                 marginTop: '32px',
                 display: 'flex',
                 justifyContent: 'center',
                 alignItems: 'center',
                 gap: '16px',
                 paddingTop: '24px',
                 borderTop: '1px solid rgba(79, 172, 254, 0.1)'
               }}>
                 <Pagination
                   current={currentPage}
                   pageSize={pageSize}
                   total={total}
                   onChange={(page, size) => {
                     setCurrentPage(page)
                     if (size !== pageSize) {
                       setPageSize(size)
                       setCurrentPage(1) // 改变每页条数时重置到第一页
                     }
                   }}
                   showSizeChanger
                   showQuickJumper
                   pageSizeOptions={['20', '30', '50', '100']}
                   showTotal={(total, range) => (
                     <span style={{ color: '#cccccc', fontSize: '14px' }}>
                       显示 {range[0]}-{range[1]} 条，共 {total} 条
                     </span>
                   )}
                   style={{
                     display: 'flex',
                     alignItems: 'center'
                   }}
                   className="custom-pagination"
                 />
               </div>
             )}
           </div>
         </div>
      </Content>
      
      {/* 自定义分页样式 */}
      <style>{`
        .custom-pagination .ant-pagination-item {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(79, 172, 254, 0.2);
          border-radius: 6px;
        }
        .custom-pagination .ant-pagination-item a {
          color: #cccccc;
        }
        .custom-pagination .ant-pagination-item:hover {
          background: rgba(79, 172, 254, 0.1);
          border-color: rgba(79, 172, 254, 0.4);
        }
        .custom-pagination .ant-pagination-item:hover a {
          color: #4facfe;
        }
        .custom-pagination .ant-pagination-item-active {
          background: rgba(79, 172, 254, 0.2);
          border-color: #4facfe;
        }
        .custom-pagination .ant-pagination-item-active a {
          color: #4facfe;
          font-weight: 600;
        }
        .custom-pagination .ant-pagination-prev button,
        .custom-pagination .ant-pagination-next button,
        .custom-pagination .ant-pagination-jump-prev button,
        .custom-pagination .ant-pagination-jump-next button {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(79, 172, 254, 0.2);
          border-radius: 6px;
          color: #cccccc;
        }
        .custom-pagination .ant-pagination-prev:hover button,
        .custom-pagination .ant-pagination-next:hover button {
          background: rgba(79, 172, 254, 0.1);
          border-color: rgba(79, 172, 254, 0.4);
          color: #4facfe;
        }
        .custom-pagination .ant-pagination-disabled button {
          background: rgba(255, 255, 255, 0.02);
          border-color: rgba(79, 172, 254, 0.1);
          color: #666666;
        }
        .custom-pagination .ant-select-selector {
          background: rgba(255, 255, 255, 0.05) !important;
          border: 1px solid rgba(79, 172, 254, 0.2) !important;
          border-radius: 6px !important;
          color: #cccccc !important;
        }
        .custom-pagination .ant-select-selector:hover {
          background: rgba(79, 172, 254, 0.1) !important;
          border-color: rgba(79, 172, 254, 0.4) !important;
        }
        .custom-pagination .ant-select-arrow {
          color: #cccccc;
        }
        .custom-pagination .ant-pagination-options-quick-jumper input {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(79, 172, 254, 0.2);
          border-radius: 6px;
          color: #cccccc;
        }
        .custom-pagination .ant-pagination-options-quick-jumper input:hover {
          background: rgba(79, 172, 254, 0.1);
          border-color: rgba(79, 172, 254, 0.4);
        }
        .custom-pagination .ant-pagination-options-quick-jumper input:focus {
          background: rgba(79, 172, 254, 0.1);
          border-color: #4facfe;
          box-shadow: 0 0 0 2px rgba(79, 172, 254, 0.1);
        }
      `}</style>
    </Layout>
  )
}

export default HomePage