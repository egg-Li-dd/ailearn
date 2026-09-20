<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api } from '../api.js'

// 状态
const loading = ref(false)
const logs = ref([])
const stats = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const totalPages = ref(0)

// 筛选
const filterSource = ref('all')
const filterLevel = ref('')
const filterModule = ref('')
const filterFunction = ref('')
const keyword = ref('')

// 实时流
const liveStream = ref(false)
const livePaused = ref(false)
const liveBuffer = ref([])
let ws = null
let wsReconnectTimer = null

// 详情
const showDetail = ref(false)
const detail = ref(null)

// Toast
const toast = ref({ msg: '', ok: true })
let toastTimer = null
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3000)
}

const sourceOptions = [
  { value: 'all', label: '全部来源' },
  { value: 'system', label: '系统日志' },
  { value: 'ai_call', label: 'AI 调用' },
  { value: 'audit', label: '操作审计' },
]

const levelOptions = [
  { value: '', label: '全部级别' },
  { value: 'CRITICAL', label: '严重' },
  { value: 'ERROR', label: '错误' },
  { value: 'WARNING', label: '警告' },
  { value: 'INFO', label: '信息' },
]

const moduleOptions = [
  { value: '', label: '全部模块' },
  { value: 'scheduler', label: '调度器' },
  { value: 'ai_gateway', label: 'AI 网关' },
  { value: 'ai_call', label: 'AI 调用' },
  { value: 'ai_action', label: 'AI 调整' },
  { value: 'task_center', label: '任务中心' },
  { value: 'classroom', label: '课堂' },
  { value: 'knowledge', label: '知识树' },
  { value: 'quiz', label: '出题' },
  { value: 'review', label: '复习' },
  { value: 'session', label: '会话' },
  { value: 'system', label: '系统' },
]

const functionOptions = [
  { value: '', label: '全部功能' },
  { value: 'generate', label: 'AI 生成数据' },
  { value: 'action', label: 'AI 调整数据' },
  { value: 'quiz', label: '出题' },
  { value: 'quiz_answer', label: '判卷' },
  { value: 'planner', label: '学习规划' },
  { value: 'tutor', label: '答疑辅导' },
  { value: 'classroom', label: '课堂互动' },
  { value: 'knowledge', label: '知识树' },
  { value: 'review', label: '复习推荐' },
]

// 加载统计
async function loadStats() {
  try {
    stats.value = await api.logStats()
  } catch (e) {
    console.error('加载日志统计失败', e)
  }
}

// 加载日志列表
async function loadLogs() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      source: filterSource.value,
    }
    if (filterLevel.value) params.level = filterLevel.value
    if (filterModule.value) params.module = filterModule.value
    if (filterFunction.value) params.function_type = filterFunction.value
    if (keyword.value) params.keyword = keyword.value
    const r = await api.logs(params)
    logs.value = r.items
    total.value = r.total
    totalPages.value = r.total_pages
  } catch (e) {
    showToast(e.message, false)
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadLogs()])
}

onMounted(() => {
  loadAll()
})

// 筛选变化
function applyFilter() {
  page.value = 1
  loadLogs()
}

// 分页
function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadLogs()
}

const pageNumbers = computed(() => {
  const pages = []
  const maxShow = 5
  let start = Math.max(1, page.value - 2)
  let end = Math.min(totalPages.value, start + maxShow - 1)
  if (end - start < maxShow - 1) start = Math.max(1, end - maxShow + 1)
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})

// 详情
async function openDetail(item) {
  detail.value = item
  showDetail.value = true
}

// 实时日志流
function toggleLiveStream() {
  if (liveStream.value) {
    stopLiveStream()
  } else {
    startLiveStream()
  }
}

function startLiveStream() {
  liveStream.value = true
  livePaused.value = false
  connectWS()
}

function stopLiveStream() {
  liveStream.value = false
  livePaused.value = false
  liveBuffer.value = []
  if (ws) {
    ws.close()
    ws = null
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
}

function connectWS() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${proto}//${window.location.host}/api/v1/ws`
  try {
    ws = new WebSocket(wsUrl)
  } catch (e) {
    console.error('WS 连接失败', e)
    scheduleReconnect()
    return
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'log_entry') {
        if (!livePaused.value) {
          // 过滤：只显示当前筛选的级别和来源
          if (filterLevel.value && data.level !== filterLevel.value) return
          if (filterModule.value && data.module !== filterModule.value) return
          const entry = {
            id: 'live_' + Date.now() + '_' + Math.random(),
            source: 'system',
            level: data.level,
            module: data.module,
            function_type: '',
            action: '',
            message: data.message,
            detail: { logger_name: data.logger_name },
            task_id: data.task_id,
            created_at: data.created_at,
            _isNew: true,
          }
          liveBuffer.value.unshift(entry)
          if (liveBuffer.value.length > 100) liveBuffer.value.pop()
        }
      }
    } catch (e) {
      // 非 JSON 消息忽略
    }
  }

  ws.onclose = () => {
    if (liveStream.value) {
      scheduleReconnect()
    }
  }

  ws.onerror = () => {
    if (ws) ws.close()
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  wsReconnectTimer = setTimeout(() => {
    if (liveStream.value) connectWS()
  }, 3000)
}

function togglePause() {
  livePaused.value = !livePaused.value
}

function flushLiveBuffer() {
  if (liveBuffer.value.length === 0) return
  // 将缓冲的实时日志插入列表顶部
  logs.value = [...liveBuffer.value, ...logs.value].slice(0, pageSize.value * 2)
  liveBuffer.value = []
}

// 合并显示的日志（实时流 + 历史列表）
const displayLogs = computed(() => {
  if (!liveStream.value || livePaused.value) return logs.value
  return [...liveBuffer.value, ...logs.value]
})

// 清理日志
async function cleanupLogs() {
  const days = prompt('清理多少天前的日志？（默认30天）', '30')
  if (days === null) return
  const d = parseInt(days)
  if (isNaN(d) || d < 1) {
    showToast('请输入有效的天数', false)
    return
  }
  if (!confirm(`确定清理 ${d} 天前的日志？此操作不可恢复。`)) return
  try {
    const r = await api.cleanupLogs(filterSource.value, d)
    showToast(`已清理：系统${r.deleted.system}条，审计${r.deleted.audit}条，AI调用${r.deleted.ai_call}条`)
    loadAll()
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

function sourceLabel(source) {
  return { system: '系统', ai_call: 'AI调用', audit: '审计' }[source] || source
}

function levelClass(level) {
  return {
    CRITICAL: 'critical',
    ERROR: 'error',
    WARNING: 'warning',
    INFO: 'info',
    DEBUG: 'debug',
  }[level] || 'info'
}

function levelLabel(level) {
  return { CRITICAL: '严重', ERROR: '错误', WARNING: '警告', INFO: '信息', DEBUG: '调试' }[level] || level
}

// 趋势图最大值
const trendMax = computed(() => {
  if (!stats.value) return 1
  return Math.max(1, ...stats.value.recent_24h.map(h => Math.max(h.errors, h.warnings, h.ai_calls)))
})

onUnmounted(() => {
  stopLiveStream()
})
</script>

<template>
  <div class="logs-page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2>日志中心</h2>
        <p class="sub">统一查看系统运行日志、AI 调用记录、操作审计日志</p>
      </div>
      <div class="head-actions">
        <button class="btn ghost" @click="loadAll">刷新</button>
        <button class="btn" :class="{ active: liveStream }" @click="toggleLiveStream">
          {{ liveStream ? '⏹ 停止实时' : '▶ 实时流' }}
        </button>
        <button class="btn danger" @click="cleanupLogs">清理日志</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div v-if="stats" class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon blue">📊</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.today_total }}</div>
          <div class="stat-label">今日日志总数</div>
          <div class="stat-sub">系统 + AI调用 + 审计</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon red">❌</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.today_errors }}</div>
          <div class="stat-label">今日错误</div>
          <div class="stat-sub">系统错误 + AI调用失败</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon orange">⚠️</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.today_warnings }}</div>
          <div class="stat-label">今日警告</div>
          <div class="stat-sub">WARNING 级别</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon green">🤖</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.ai_call_success_rate }}%</div>
          <div class="stat-label">AI 调用成功率</div>
          <div class="stat-sub">{{ stats.ai_call_count }} 次调用，失败 {{ stats.ai_call_failed }} 次</div>
        </div>
      </div>
    </div>

    <!-- 24h 趋势 -->
    <div v-if="stats" class="panel trend-panel">
      <div class="panel-head">
        <span class="panel-title">最近 24 小时趋势</span>
        <div class="trend-legend">
          <span class="legend-item"><span class="dot error"></span>错误</span>
          <span class="legend-item"><span class="dot warning"></span>警告</span>
          <span class="legend-item"><span class="dot ai"></span>AI调用</span>
        </div>
      </div>
      <div class="trend-chart">
        <div v-for="h in stats.recent_24h" :key="h.hour" class="trend-col" :title="`${h.hour}: 错误${h.errors} 警告${h.warnings} AI调用${h.ai_calls}`">
          <div class="trend-bar error" :style="{ height: (h.errors / trendMax * 100) + '%' }"></div>
          <div class="trend-bar warning" :style="{ height: (h.warnings / trendMax * 100) + '%' }"></div>
          <div class="trend-bar ai" :style="{ height: (h.ai_calls / trendMax * 100) + '%' }"></div>
          <span class="trend-label">{{ h.hour.slice(0, 2) }}</span>
        </div>
      </div>
    </div>

    <!-- 实时流控制栏 -->
    <div v-if="liveStream" class="live-bar">
      <span class="live-indicator"><span class="pulse"></span>实时流已连接</span>
      <span class="live-count">新日志 {{ liveBuffer.length }} 条</span>
      <div class="live-actions">
        <button class="btn ghost mini" @click="togglePause">{{ livePaused ? '继续' : '暂停' }}</button>
        <button class="btn mini" @click="flushLiveBuffer" :disabled="!liveBuffer.length">插入列表</button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filterSource" @change="applyFilter">
        <option v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-model="filterLevel" @change="applyFilter">
        <option v-for="opt in levelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-model="filterModule" @change="applyFilter">
        <option v-for="opt in moduleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-if="filterSource === 'all' || filterSource === 'ai_call'" v-model="filterFunction" @change="applyFilter">
        <option v-for="opt in functionOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <input v-model="keyword" placeholder="搜索关键词..." @keyup.enter="applyFilter" />
      <button class="btn ghost mini" @click="applyFilter">筛选</button>
      <span class="filter-total">共 {{ total }} 条</span>
    </div>

    <!-- 日志列表 -->
    <div class="panel">
      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <span>加载中…</span>
      </div>

      <div v-else-if="displayLogs.length === 0" class="empty">
        <div class="empty-icon">📜</div>
        <div class="empty-title">暂无日志</div>
        <div class="empty-desc">调整筛选条件或开启实时流查看新日志</div>
      </div>

      <table v-else>
        <thead>
          <tr>
            <th style="width:140px">时间</th>
            <th style="width:70px">来源</th>
            <th style="width:70px">级别</th>
            <th style="width:90px">模块</th>
            <th>消息</th>
            <th style="width:60px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in displayLogs" :key="item.id" class="clickable" :class="{ 'new-log': item._isNew }" @click="openDetail(item)">
            <td class="mono time-cell">{{ formatTime(item.created_at) }}</td>
            <td><span class="source-tag">{{ sourceLabel(item.source) }}</span></td>
            <td><span class="level-tag" :class="levelClass(item.level)">{{ levelLabel(item.level) }}</span></td>
            <td class="module-cell">{{ item.module || '—' }}</td>
            <td class="msg-cell">{{ item.message }}</td>
            <td @click.stop>
              <button class="btn ghost mini" @click="openDetail(item)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div v-if="totalPages > 1 && !liveStream" class="pagination">
        <button class="btn ghost mini" :disabled="page === 1" @click="goPage(page - 1)">上一页</button>
        <button v-for="p in pageNumbers" :key="p"
          class="btn mini" :class="p === page ? '' : 'ghost'"
          @click="goPage(p)">{{ p }}</button>
        <button class="btn ghost mini" :disabled="page === totalPages" @click="goPage(page + 1)">下一页</button>
        <span class="page-info">{{ page }} / {{ totalPages }}</span>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="showDetail" class="drawer-overlay" @click.self="showDetail = false">
      <div class="drawer">
        <div class="drawer-head">
          <h3>日志详情</h3>
          <button class="icon-btn" @click="showDetail = false">✕</button>
        </div>
        <div v-if="detail" class="drawer-body">
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">来源</span>
              <span class="detail-value">{{ sourceLabel(detail.source) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">级别</span>
              <span class="level-tag" :class="levelClass(detail.level)">{{ levelLabel(detail.level) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">模块</span>
              <span class="detail-value">{{ detail.module || '—' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">时间</span>
              <span class="detail-value mono">{{ formatTime(detail.created_at) }}</span>
            </div>
            <div v-if="detail.function_type" class="detail-item">
              <span class="detail-label">功能类型</span>
              <span class="detail-value">{{ detail.function_type }}</span>
            </div>
            <div v-if="detail.task_id" class="detail-item">
              <span class="detail-label">关联任务</span>
              <span class="detail-value mono">{{ detail.task_id.slice(0, 8) }}...</span>
            </div>
          </div>

          <div class="detail-section">
            <div class="section-title">消息</div>
            <div class="msg-box">{{ detail.message }}</div>
          </div>

          <div v-if="detail.detail" class="detail-section">
            <div class="section-title">详细信息</div>
            <pre class="detail-box">{{ JSON.stringify(detail.detail, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.msg" class="toast" :class="{ error: !toast.ok }">{{ toast.msg }}</div>
  </div>
</template>

<style scoped>
.logs-page { padding: 0; }

.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.page-head h2 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.page-head .sub { font-size: 12px; color: var(--text-muted); }
.head-actions { display: flex; gap: 8px; }
.head-actions .btn.active { background: var(--primary); color: #fff; }

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px;
}
.stat-icon { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.stat-icon.blue { background: var(--primary-weak); }
.stat-icon.red { background: #FDECEA; }
.stat-icon.orange { background: #FFF3DC; }
.stat-icon.green { background: #E8F5EC; }
.stat-body { flex: 1; min-width: 0; }
.stat-num { font-size: 22px; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.stat-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

/* 趋势图 */
.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; overflow: hidden; }
.panel-head { padding: 12px 16px; border-bottom: 1px solid var(--border); background: var(--bg-sunken); display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-size: 13px; font-weight: 600; }
.trend-legend { display: flex; gap: 12px; font-size: 11px; color: var(--text-muted); }
.legend-item { display: flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.error { background: #E74C3C; }
.dot.warning { background: #F39C12; }
.dot.ai { background: var(--primary); }

.trend-chart { display: flex; align-items: flex-end; gap: 2px; padding: 12px 16px; height: 100px; }
.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; position: relative; min-width: 0; }
.trend-bar { width: 100%; max-width: 12px; border-radius: 2px 2px 0 0; min-height: 1px; transition: height .3s; }
.trend-bar.error { background: #E74C3C; opacity: .8; }
.trend-bar.warning { background: #F39C12; opacity: .8; }
.trend-bar.ai { background: var(--primary); opacity: .6; }
.trend-label { font-size: 9px; color: var(--text-muted); margin-top: 4px; position: absolute; bottom: -16px; }

/* 实时流栏 */
.live-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; margin-bottom: 12px;
  background: #E8F5EC; border-radius: 8px; font-size: 12px;
}
.live-indicator { display: flex; align-items: center; gap: 6px; font-weight: 500; color: #3E8E58; }
.pulse { width: 8px; height: 8px; border-radius: 50%; background: #3E8E58; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .3; } }
.live-count { color: var(--text-muted); }
.live-actions { margin-left: auto; display: flex; gap: 6px; }

/* 筛选栏 */
.filter-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.filter-bar select, .filter-bar input { height: 32px; font-size: 12px; padding: 0 10px; }
.filter-bar input { width: 180px; }
.filter-total { margin-left: auto; font-size: 12px; color: var(--text-muted); }

/* 表格 */
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
thead th { text-align: left; font-weight: 500; color: var(--text-secondary); padding: 10px 12px; border-bottom: 1px solid var(--border); background: var(--bg-sunken); font-size: 11px; }
tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,.04); vertical-align: middle; }
tbody tr.clickable { cursor: pointer; transition: background .12s; }
tbody tr.clickable:hover { background: rgba(62,99,221,.04); }
tbody tr.new-log { animation: newLogFlash 2s ease; }
@keyframes newLogFlash { 0% { background: rgba(62,221,99,.15); } 100% { background: transparent; } }
.mono { font-family: var(--font-mono); }
.time-cell { font-size: 11.5px; color: var(--text-secondary); }
.module-cell { font-size: 11px; color: var(--text-secondary); }
.msg-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.source-tag { display: inline-block; padding: 2px 8px; border-radius: 5px; background: var(--bg-sunken); color: var(--text-secondary); font-size: 11px; }
.level-tag { display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 500; }
.level-tag.critical { background: #7B2D26; color: #fff; }
.level-tag.error { background: #FDECEA; color: #C24238; }
.level-tag.warning { background: #FFF3DC; color: #B7791F; }
.level-tag.info { background: var(--primary-weak); color: var(--primary); }
.level-tag.debug { background: var(--bg-sunken); color: var(--text-muted); }

/* 分页 */
.pagination { display: flex; align-items: center; gap: 6px; padding: 12px 16px; border-top: 1px solid var(--border); justify-content: center; }
.page-info { font-size: 12px; color: var(--text-muted); margin-left: 8px; }

/* 加载 / 空状态 */
.loading-state, .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 20px; gap: 10px; }
.empty-icon { font-size: 36px; opacity: .5; }
.empty-title { font-size: 15px; font-weight: 600; }
.empty-desc { font-size: 12px; color: var(--text-muted); text-align: center; }
.spinner { width: 24px; height: 24px; border: 3px solid var(--border); border-top-color: var(--primary); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 详情抽屉 */
.drawer-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.3); z-index: 200; display: flex; justify-content: flex-end; animation: fadeIn .15s ease; }
.drawer { width: 480px; max-width: 90vw; background: var(--bg-card); height: 100%; display: flex; flex-direction: column; animation: slideIn .2s ease; }
@keyframes fadeIn { from { opacity: 0; } }
@keyframes slideIn { from { transform: translateX(100%); } }
.drawer-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.drawer-head h3 { font-size: 16px; font-weight: 600; }
.drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px; }

.detail-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 16px; }
.detail-item { display: flex; flex-direction: column; gap: 3px; }
.detail-label { font-size: 11px; color: var(--text-muted); }
.detail-value { font-size: 13px; font-weight: 500; word-break: break-all; }

.detail-section { margin-bottom: 16px; }
.section-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; }
.msg-box { padding: 12px; background: var(--bg-sunken); border-radius: 8px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.detail-box { padding: 12px; background: var(--bg-sunken); border-radius: 8px; font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono); max-height: 300px; overflow-y: auto; }

.icon-btn {
  width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 7px;
  background: var(--bg-card); display: flex; align-items: center; justify-content: center;
  font-size: 13px; cursor: pointer; padding: 0;
}
.icon-btn:hover { background: var(--bg-sunken); }

/* Toast */
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  padding: 10px 20px; background: var(--text); color: var(--bg-card);
  border-radius: 8px; font-size: 13px; z-index: 300; animation: toastIn .2s ease;
}
.toast.error { background: #C24238; color: #fff; }
@keyframes toastIn { from { opacity: 0; transform: translateX(-50%) translateY(10px); } }

/* 响应式 */
@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
