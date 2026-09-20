<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api.js'

// 状态
const panelOpen = ref(false)
const tasks = ref([])
const loading = ref(false)
const showHistory = ref(false)

// 详情
const showDetail = ref(false)
const detailTask = ref(null)
const detailEvents = ref([])
const detailLoading = ref(false)

// WebSocket
let ws = null
let wsReconnectTimer = null

// Toast
const toast = ref({ msg: '', ok: true })
let toastTimer = null
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3000)
}

// 进行中的任务
const activeTasks = computed(() => tasks.value.filter(t => t.status === 'running' || t.status === 'pending'))
const finishedTasks = computed(() => tasks.value.filter(t => ['completed', 'failed', 'cancelled'].includes(t.status)))

// 进行中任务数量
const activeCount = computed(() => activeTasks.value.length)

// 总体进度（所有进行中任务的平均）
const overallProgress = computed(() => {
  if (activeTasks.value.length === 0) return 0
  const sum = activeTasks.value.reduce((acc, t) => acc + (t.progress || 0), 0)
  return Math.round(sum / activeTasks.value.length)
})

// 加载任务列表
async function loadTasks() {
  loading.value = true
  try {
    const r = await api.tasks({ limit: 30 })
    tasks.value = r.items || []
  } catch (e) {
    console.error('加载任务列表失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadTasks()
  connectWS()
})

onUnmounted(() => {
  if (ws) {
    ws.close()
    ws = null
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
})

// WebSocket 连接
function connectWS() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${proto}//${window.location.host}/api/v1/ws`
  try {
    ws = new WebSocket(wsUrl)
  } catch (e) {
    scheduleReconnect()
    return
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      handleWSEvent(data)
    } catch (e) {
      // 非 JSON 忽略
    }
  }

  ws.onclose = () => {
    scheduleReconnect()
  }

  ws.onerror = () => {
    if (ws) ws.close()
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  wsReconnectTimer = setTimeout(connectWS, 3000)
}

// 处理 WS 事件
function handleWSEvent(data) {
  const eventTypes = ['task_created', 'task_started', 'task_progress', 'task_completed', 'task_failed', 'task_cancelled', 'task_cancel_requested']
  if (!eventTypes.includes(data.type)) return

  const taskId = data.task_id
  const idx = tasks.value.findIndex(t => t.id === taskId)

  if (data.type === 'task_created') {
    // 新任务，插入顶部
    if (idx === -1) {
      tasks.value.unshift({
        id: taskId,
        task_type: data.task_type || '',
        title: data.title || '新任务',
        status: data.status || 'pending',
        progress: data.progress || 0,
        stage: '',
        created_at: new Date().toISOString(),
      })
    }
    return
  }

  if (idx === -1) {
    // 未知任务，刷新列表
    loadTasks()
    return
  }

  const task = tasks.value[idx]
  if (data.type === 'task_progress') {
    task.progress = data.progress ?? task.progress
    task.stage = data.stage ?? task.stage
    task.status = 'running'
  } else if (data.type === 'task_started') {
    task.status = 'running'
    task.started_at = new Date().toISOString()
  } else if (data.type === 'task_completed') {
    task.status = 'completed'
    task.progress = 100
    task.finished_at = new Date().toISOString()
    task.result = data.result || null
    showToast(`任务「${task.title}」已完成`, true)
  } else if (data.type === 'task_failed') {
    task.status = 'failed'
    task.error = data.error || ''
    task.finished_at = new Date().toISOString()
    showToast(`任务「${task.title}」失败：${data.error || '未知错误'}`, false)
  } else if (data.type === 'task_cancelled') {
    task.status = 'cancelled'
    task.finished_at = new Date().toISOString()
  } else if (data.type === 'task_cancel_requested') {
    task.stage = '取消请求已发出...'
  }
}

// 切换面板
function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value) {
    loadTasks()
  }
}

// 打开详情
async function openDetail(task) {
  detailTask.value = task
  showDetail.value = true
  detailLoading.value = true
  detailEvents.value = []
  try {
    const [t, events] = await Promise.all([
      api.taskDetail(task.id),
      api.taskEvents(task.id),
    ])
    detailTask.value = t
    detailEvents.value = events || []
  } catch (e) {
    showToast(e.message, false)
  } finally {
    detailLoading.value = false
  }
}

// 取消任务
async function cancelTask(task) {
  if (!confirm(`确定取消任务「${task.title}」？`)) return
  try {
    await api.cancelTask(task.id)
    showToast('取消请求已发出')
    loadTasks()
  } catch (e) {
    showToast(e.message, false)
  }
}

// 重试任务
async function retryTask(task) {
  try {
    const r = await api.retryTask(task.id)
    if (r.ok) {
      showToast('重试任务已创建')
      loadTasks()
    } else {
      showToast(r.message, false)
    }
  } catch (e) {
    showToast(e.message, false)
  }
}

// 删除任务
async function deleteTask(task) {
  if (!confirm(`确定删除任务记录「${task.title}」？`)) return
  try {
    await api.deleteTask(task.id)
    showToast('已删除')
    loadTasks()
    if (detailTask.value?.id === task.id) {
      showDetail.value = false
    }
  } catch (e) {
    showToast(e.message, false)
  }
}

// 格式化
function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatElapsed(seconds) {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`
  return `${Math.floor(seconds / 3600)}时${Math.floor((seconds % 3600) / 60)}分`
}

function statusLabel(status) {
  return { pending: '等待中', running: '进行中', completed: '已完成', failed: '失败', cancelled: '已取消' }[status] || status
}

function statusClass(status) {
  return { pending: 'pending', running: 'running', completed: 'completed', failed: 'failed', cancelled: 'cancelled' }[status] || ''
}

function taskTypeLabel(type) {
  return {
    ai_generate: 'AI生成',
    ai_action: 'AI调整',
    auto_config: '一键配置',
    knowledge_refine: '知识细化',
    batch_import: '批量导入',
    weekly_report: '周报生成',
    plan_session: '会话规划',
    custom: '自定义',
  }[type] || type
}

function timeAgo(iso) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}
</script>

<template>
  <div class="task-float">
    <!-- 悬浮按钮 -->
    <button
      class="float-btn"
      :class="{ active: panelOpen, hasTasks: activeCount > 0 }"
      @click="togglePanel"
      :title="activeCount > 0 ? `${activeCount} 个任务进行中` : '任务中心'"
    >
      <span v-if="activeCount > 0" class="float-spinner"></span>
      <span v-else class="float-icon">📋</span>
      <span v-if="activeCount > 0" class="float-badge">{{ activeCount }}</span>
      <span v-if="activeCount > 0" class="float-progress">{{ overallProgress }}%</span>
    </button>

    <!-- 展开面板 -->
    <transition name="slide-up">
      <div v-if="panelOpen" class="float-panel">
        <div class="panel-head">
          <h3>任务中心</h3>
          <div class="panel-head-actions">
            <button class="icon-btn" @click="loadTasks" title="刷新">↻</button>
            <button class="icon-btn" @click="panelOpen = false">✕</button>
          </div>
        </div>

        <div class="panel-body">
          <!-- 进行中 -->
          <div v-if="activeTasks.length > 0" class="task-section">
            <div class="section-label">进行中 ({{ activeTasks.length }})</div>
            <div v-for="task in activeTasks" :key="task.id" class="task-card running" @click="openDetail(task)">
              <div class="task-card-head">
                <span class="task-title">{{ task.title }}</span>
                <span class="task-type">{{ taskTypeLabel(task.task_type) }}</span>
              </div>
              <div class="task-progress-wrap">
                <div class="task-progress-bar">
                  <div class="task-progress-fill" :style="{ width: task.progress + '%' }"></div>
                </div>
                <span class="task-progress-text">{{ task.progress }}%</span>
              </div>
              <div class="task-card-foot">
                <span class="task-stage">{{ task.stage || '执行中...' }}</span>
                <span class="task-time">{{ formatElapsed(task.elapsed_seconds) }}</span>
              </div>
              <div class="task-card-ops" @click.stop>
                <button class="btn ghost mini danger" @click="cancelTask(task)">取消</button>
              </div>
            </div>
          </div>

          <!-- 已完成 -->
          <div class="task-section">
            <div class="section-label" @click="showHistory = !showHistory" style="cursor:pointer">
              已结束 ({{ finishedTasks.length }})
              <span class="toggle-icon">{{ showHistory ? '▲' : '▼' }}</span>
            </div>
            <div v-if="showHistory">
              <div v-for="task in finishedTasks" :key="task.id" class="task-card" :class="statusClass(task.status)" @click="openDetail(task)">
                <div class="task-card-head">
                  <span class="task-title">{{ task.title }}</span>
                  <span class="task-status" :class="statusClass(task.status)">{{ statusLabel(task.status) }}</span>
                </div>
                <div class="task-card-foot">
                  <span class="task-stage">{{ task.stage || (task.error ? task.error.slice(0, 30) : '—') }}</span>
                  <span class="task-time">{{ timeAgo(task.finished_at || task.created_at) }}</span>
                </div>
                <div class="task-card-ops" @click.stop>
                  <button v-if="task.status === 'failed'" class="btn ghost mini" @click="retryTask(task)">重试</button>
                  <button class="btn ghost mini danger" @click="deleteTask(task)">删除</button>
                </div>
              </div>
              <div v-if="finishedTasks.length === 0" class="empty-mini">暂无已结束的任务</div>
            </div>
          </div>

          <div v-if="tasks.length === 0 && !loading" class="empty-mini">
            <div class="empty-icon">📋</div>
            <div>暂无任务</div>
            <div class="empty-desc">执行耗时操作时会显示在这里</div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 详情弹窗 -->
    <div v-if="showDetail" class="detail-overlay" @click.self="showDetail = false">
      <div class="detail-modal">
        <div class="modal-head">
          <h3>任务详情</h3>
          <button class="icon-btn" @click="showDetail = false">✕</button>
        </div>

        <div v-if="detailLoading" class="loading-state">
          <div class="spinner"></div>
          <span>加载中…</span>
        </div>

        <div v-else-if="detailTask" class="modal-body">
          <div class="detail-info-grid">
            <div class="info-item">
              <span class="info-label">标题</span>
              <span class="info-value">{{ detailTask.title }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">类型</span>
              <span class="info-value">{{ taskTypeLabel(detailTask.task_type) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">状态</span>
              <span class="task-status" :class="statusClass(detailTask.status)">{{ statusLabel(detailTask.status) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">进度</span>
              <span class="info-value">{{ detailTask.progress }}%</span>
            </div>
            <div class="info-item">
              <span class="info-label">创建时间</span>
              <span class="info-value mono">{{ formatTime(detailTask.created_at) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">耗时</span>
              <span class="info-value">{{ formatElapsed(detailTask.elapsed_seconds) }}</span>
            </div>
          </div>

          <div v-if="detailTask.stage" class="info-item full">
            <span class="info-label">当前阶段</span>
            <span class="info-value">{{ detailTask.stage }}</span>
          </div>

          <div v-if="detailTask.error" class="error-box">
            <span class="error-icon">⚠️</span>
            <span class="error-text">{{ detailTask.error }}</span>
          </div>

          <div v-if="detailTask.result" class="result-box">
            <div class="result-title">执行结果</div>
            <pre class="result-content">{{ JSON.stringify(detailTask.result, null, 2) }}</pre>
          </div>

          <div v-if="detailTask.metadata && Object.keys(detailTask.metadata).length" class="info-item full">
            <span class="info-label">参数</span>
            <pre class="meta-content">{{ JSON.stringify(detailTask.metadata, null, 2) }}</pre>
          </div>

          <!-- 事件流水 -->
          <div class="events-section">
            <div class="events-title">执行时间线</div>
            <div class="events-timeline">
              <div v-for="event in detailEvents" :key="event.id" class="event-item">
                <div class="event-dot" :class="event.event_type"></div>
                <div class="event-content">
                  <div class="event-message">{{ event.message }}</div>
                  <div class="event-time">{{ formatTime(event.created_at) }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button v-if="detailTask?.status === 'running' || detailTask?.status === 'pending'" class="btn danger" @click="cancelTask(detailTask); showDetail = false">取消任务</button>
          <button v-if="detailTask?.status === 'failed'" class="btn" @click="retryTask(detailTask)">重试</button>
          <button v-if="['completed','failed','cancelled'].includes(detailTask?.status)" class="btn danger" @click="deleteTask(detailTask); showDetail = false">删除记录</button>
          <button class="btn ghost" @click="showDetail = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.msg" class="toast" :class="{ error: !toast.ok }">{{ toast.msg }}</div>
  </div>
</template>

<style scoped>
.task-float {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 100;
}

/* 悬浮按钮 */
.float-btn {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: none;
  background: var(--primary);
  color: #fff;
  font-size: 22px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(62, 99, 221, .3);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all .2s ease;
}
.float-btn:hover {
  transform: scale(1.05);
  box-shadow: 0 6px 20px rgba(62, 99, 221, .4);
}
.float-btn.active {
  background: var(--text);
}
.float-icon { font-size: 22px; }
.float-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid rgba(255,255,255,.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.float-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  background: #E74C3C;
  color: #fff;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.float-progress {
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--text);
  color: var(--bg-card);
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
  white-space: nowrap;
}

/* 展开面板 */
.float-panel {
  position: absolute;
  bottom: 68px;
  right: 0;
  width: 360px;
  max-height: 70vh;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.slide-up-enter-active, .slide-up-leave-active {
  transition: all .2s ease;
}
.slide-up-enter-from, .slide-up-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-sunken);
}
.panel-head h3 { font-size: 15px; font-weight: 600; }
.panel-head-actions { display: flex; gap: 6px; }

.icon-btn {
  width: 26px; height: 26px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); display: flex; align-items: center; justify-content: center;
  font-size: 12px; cursor: pointer; padding: 0; color: var(--text-secondary);
}
.icon-btn:hover { background: var(--bg-sunken); }

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.task-section { margin-bottom: 12px; }
.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .5px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.toggle-icon { font-size: 9px; }

/* 任务卡片 */
.task-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all .15s;
}
.task-card:hover { border-color: var(--primary); }
.task-card.running { border-left: 3px solid var(--primary); }
.task-card.completed { border-left: 3px solid #3E8E58; opacity: .85; }
.task-card.failed { border-left: 3px solid #C24238; opacity: .85; }
.task-card.cancelled { border-left: 3px solid var(--text-muted); opacity: .7; }

.task-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.task-title { font-size: 13px; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-type { font-size: 10px; color: var(--text-muted); background: var(--bg-sunken); padding: 2px 6px; border-radius: 4px; flex-shrink: 0; margin-left: 8px; }

.task-status {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  margin-left: 8px;
}
.task-status.pending { background: #FFF3DC; color: #B7791F; }
.task-status.running { background: var(--primary-weak); color: var(--primary); }
.task-status.completed { background: #E8F5EC; color: #3E8E58; }
.task-status.failed { background: #FDECEA; color: #C24238; }
.task-status.cancelled { background: var(--bg-sunken); color: var(--text-muted); }

.task-progress-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.task-progress-bar {
  flex: 1;
  height: 6px;
  background: var(--bg-sunken);
  border-radius: 3px;
  overflow: hidden;
}
.task-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), #6B8AE8);
  border-radius: 3px;
  transition: width .3s;
}
.task-progress-text { font-size: 11px; font-weight: 600; color: var(--primary); font-variant-numeric: tabular-nums; min-width: 32px; text-align: right; }

.task-card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--text-muted);
}
.task-stage { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-time { flex-shrink: 0; margin-left: 8px; font-family: var(--font-mono); }

.task-card-ops {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
  justify-content: flex-end;
}

.empty-mini {
  text-align: center;
  padding: 24px 12px;
  color: var(--text-muted);
  font-size: 12px;
}
.empty-mini .empty-icon { font-size: 28px; margin-bottom: 8px; opacity: .5; }
.empty-mini .empty-desc { font-size: 11px; margin-top: 4px; }

/* 详情弹窗 */
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.4);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
}
.detail-modal {
  width: 520px;
  max-width: 92vw;
  max-height: 85vh;
  background: var(--bg-card);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.modal-head h3 { font-size: 16px; font-weight: 600; }
.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.detail-info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.info-item { display: flex; flex-direction: column; gap: 3px; margin-bottom: 12px; }
.info-item.full { grid-column: 1 / -1; }
.info-label { font-size: 11px; color: var(--text-muted); }
.info-value { font-size: 13px; font-weight: 500; word-break: break-all; }
.mono { font-family: var(--font-mono); }

.error-box {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  background: #FDECEA;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #C24238;
}
.error-text { word-break: break-all; line-height: 1.4; }

.result-box { margin-bottom: 16px; }
.result-title { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.result-content {
  padding: 10px;
  background: var(--bg-sunken);
  border-radius: 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}
.meta-content {
  padding: 10px;
  background: var(--bg-sunken);
  border-radius: 8px;
  font-size: 11px;
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 150px;
  overflow-y: auto;
  margin-top: 4px;
}

/* 事件时间线 */
.events-section { margin-top: 16px; }
.events-title { font-size: 12px; font-weight: 600; margin-bottom: 10px; color: var(--text-secondary); }
.events-timeline { padding-left: 8px; }
.event-item {
  display: flex;
  gap: 10px;
  padding-bottom: 12px;
  position: relative;
}
.event-item::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 16px;
  bottom: 0;
  width: 1px;
  background: var(--border);
}
.event-item:last-child::before { display: none; }
.event-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--border);
  flex-shrink: 0;
  margin-top: 3px;
  z-index: 1;
}
.event-dot.created { background: var(--primary); }
.event-dot.started { background: #3498DB; }
.event-dot.progress { background: #F39C12; }
.event-dot.completed { background: #3E8E58; }
.event-dot.failed { background: #C24238; }
.event-dot.cancelled { background: var(--text-muted); }
.event-content { flex: 1; }
.event-message { font-size: 12px; line-height: 1.4; }
.event-time { font-size: 10px; color: var(--text-muted); margin-top: 2px; font-family: var(--font-mono); }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 10px;
}
.spinner {
  width: 24px;
  height: 24px;
  border: 3px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 100px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 20px;
  background: var(--text);
  color: var(--bg-card);
  border-radius: 8px;
  font-size: 13px;
  z-index: 300;
}
.toast.error { background: #C24238; color: #fff; }

/* 响应式 */
@media (max-width: 600px) {
  .float-panel { width: calc(100vw - 48px); right: -12px; }
  .detail-info-grid { grid-template-columns: 1fr; }
}
</style>
