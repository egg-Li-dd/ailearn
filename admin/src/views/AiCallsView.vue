<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '../api.js'

// 状态
const loading = ref(false)
const calls = ref([])
const stats = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const totalPages = ref(0)

// 筛选
const filterFunction = ref('')
const filterStatus = ref('')
const filterModel = ref('')

// 详情
const showDetail = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

// Toast
const toast = ref({ msg: '', ok: true })
let toastTimer = null
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3000)
}

// 功能类型选项
const functionOptions = [
  { value: '', label: '全部功能' },
  { value: 'generate', label: 'AI 生成数据' },
  { value: 'action', label: 'AI 调整数据' },
  { value: 'quiz', label: '出题' },
  { value: 'quiz_answer', label: '判卷' },
  { value: 'planner', label: '学习规划' },
  { value: 'tutor', label: '答疑辅导' },
  { value: 'sediment', label: '知识沉淀' },
  { value: 'classroom', label: '课堂互动' },
  { value: 'handwrite', label: '手写批改' },
  { value: 'knowledge', label: '知识树' },
  { value: 'stats', label: '统计周报' },
  { value: 'review', label: '复习推荐' },
  { value: 'test', label: '连接测试' },
  { value: 'other', label: '其他' },
]

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

// 加载数据
async function loadStats() {
  try {
    stats.value = await api.aiCallStats()
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

async function loadCalls() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterFunction.value) params.function_type = filterFunction.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterModel.value) params.model = filterModel.value
    const r = await api.aiCalls(params)
    calls.value = r.items
    total.value = r.total
    totalPages.value = r.total_pages
  } catch (e) {
    showToast(e.message, false)
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadCalls()])
}

onMounted(loadAll)

// 筛选变化
function applyFilter() {
  page.value = 1
  loadCalls()
}

// 分页
function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadCalls()
}

// 详情
async function openDetail(id) {
  detailLoading.value = true
  showDetail.value = true
  try {
    detail.value = await api.aiCallDetail(id)
  } catch (e) {
    showToast(e.message, false)
  } finally {
    detailLoading.value = false
  }
}

// 删除
async function deleteCall(item) {
  if (!confirm(`确定删除这条调用记录？`)) return
  try {
    await api.deleteAiCall(item.id)
    showToast('已删除')
    await loadAll()
  } catch (e) {
    showToast(e.message, false)
  }
}

async function clearAll() {
  if (!confirm(`确定清空所有调用记录？此操作不可恢复。`)) return
  try {
    await api.clearAiCalls()
    showToast('已清空所有记录')
    page.value = 1
    await loadAll()
  } catch (e) {
    showToast(e.message, false)
  }
}

// 格式化
function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

function formatCost(cost) {
  if (!cost) return '¥0.000000'
  if (cost < 0.001) return `¥${cost.toFixed(6)}`
  if (cost < 0.01) return `¥${cost.toFixed(4)}`
  return `¥${cost.toFixed(2)}`
}

function formatDuration(ms) {
  if (!ms) return '0ms'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// 输入消息格式化
function formatInputMessages(messages) {
  if (!messages) return ''
  if (typeof messages === 'string') return messages
  if (Array.isArray(messages)) {
    return messages.map(m => {
      const role = m.role || 'unknown'
      const content = typeof m.content === 'string' ? m.content : JSON.stringify(m.content)
      return `[${role}]\n${content}`
    }).join('\n\n---\n\n')
  }
  return JSON.stringify(messages, null, 2)
}

// 计算分页范围
const pageNumbers = computed(() => {
  const pages = []
  const maxShow = 5
  let start = Math.max(1, page.value - 2)
  let end = Math.min(totalPages.value, start + maxShow - 1)
  if (end - start < maxShow - 1) start = Math.max(1, end - maxShow + 1)
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})
</script>

<template>
  <div class="calls-page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2>AI 调用记录</h2>
        <p class="sub">追溯每次 AI 生成的输入输出、Token 消耗与费用预估</p>
      </div>
      <div class="head-actions">
        <button class="btn ghost" @click="loadAll">刷新</button>
        <button class="btn danger" @click="clearAll">清空记录</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div v-if="stats" class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon blue">📊</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.total }}</div>
          <div class="stat-label">总调用次数</div>
          <div class="stat-sub">成功 {{ stats.success }} / 失败 {{ stats.failed }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon green">✅</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.success_rate }}%</div>
          <div class="stat-label">成功率</div>
          <div class="stat-sub">平均 {{ formatDuration(stats.avg_duration_ms) }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon purple">🔢</div>
        <div class="stat-body">
          <div class="stat-num">{{ formatTokens(stats.total_tokens) }}</div>
          <div class="stat-label">总 Token 消耗</div>
          <div class="stat-sub">输入 + 输出</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon orange">💰</div>
        <div class="stat-body">
          <div class="stat-num">{{ formatCost(stats.total_cost) }}</div>
          <div class="stat-label">预估费用</div>
          <div class="stat-sub">按模型定价估算</div>
        </div>
      </div>
    </div>

    <!-- 功能分布 -->
    <div v-if="stats && stats.function_breakdown.length" class="panel">
      <div class="panel-head">
        <span class="panel-title">功能调用分布</span>
      </div>
      <div class="func-bars">
        <div v-for="item in stats.function_breakdown" :key="item.function_type" class="func-bar-row">
          <span class="func-name">{{ item.label }}</span>
          <div class="func-bar-wrap">
            <div class="func-bar" :style="{ width: (item.count / stats.total * 100) + '%' }"></div>
          </div>
          <span class="func-count">{{ item.count }}</span>
          <span class="func-tokens">{{ formatTokens(item.tokens) }}</span>
          <span class="func-cost">{{ formatCost(item.cost) }}</span>
        </div>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filterFunction" @change="applyFilter">
        <option v-for="opt in functionOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <select v-model="filterStatus" @change="applyFilter">
        <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
      </select>
      <input v-model="filterModel" placeholder="搜索模型名..." @keyup.enter="applyFilter" />
      <button class="btn ghost mini" @click="applyFilter">筛选</button>
      <span class="filter-total">共 {{ total }} 条记录</span>
    </div>

    <!-- 记录列表 -->
    <div class="panel">
      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <span>加载中…</span>
      </div>

      <div v-else-if="calls.length === 0" class="empty">
        <div class="empty-icon">📋</div>
        <div class="empty-title">暂无调用记录</div>
        <div class="empty-desc">使用 AI 功能后，调用记录会自动出现在这里</div>
      </div>

      <table v-else>
        <thead>
          <tr>
            <th style="width:140px">时间</th>
            <th style="width:100px">功能</th>
            <th>模型</th>
            <th style="width:80px">Token</th>
            <th style="width:90px">费用</th>
            <th style="width:70px">耗时</th>
            <th style="width:60px">状态</th>
            <th style="width:80px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in calls" :key="item.id" @click="openDetail(item.id)" class="clickable">
            <td class="mono time-cell">{{ formatTime(item.created_at) }}</td>
            <td><span class="func-tag">{{ item.function_label }}</span></td>
            <td class="mono model-cell">{{ item.model || '—' }}</td>
            <td class="mono">{{ formatTokens(item.total_tokens) }}</td>
            <td class="mono cost-cell">{{ formatCost(item.cost_estimate) }}</td>
            <td class="mono">{{ formatDuration(item.duration_ms) }}</td>
            <td>
              <span class="tag" :class="item.status === 'success' ? 'green' : 'red'">
                {{ item.status === 'success' ? '成功' : '失败' }}
              </span>
            </td>
            <td @click.stop>
              <button class="btn ghost mini" @click="openDetail(item.id)">详情</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="pagination">
        <button class="btn ghost mini" :disabled="page === 1" @click="goPage(page - 1)">上一页</button>
        <button v-for="p in pageNumbers" :key="p"
          class="btn mini" :class="p === page ? '' : 'ghost'"
          @click="goPage(p)">{{ p }}</button>
        <button class="btn ghost mini" :disabled="page === totalPages" @click="goPage(page + 1)">下一页</button>
        <span class="page-info">{{ page }} / {{ totalPages }}</span>
      </div>
    </div>

    <!-- 详情模态框 -->
    <div v-if="showDetail" class="overlay" @click.self="showDetail = false">
      <div class="modal detail-modal">
        <div class="modal-head">
          <h3>调用详情 #{{ detail?.id }}</h3>
          <button class="icon-btn" @click="showDetail = false">✕</button>
        </div>

        <div v-if="detailLoading" class="loading-state">
          <div class="spinner"></div>
          <span>加载中…</span>
        </div>

        <div v-else-if="detail" class="detail-body">
          <!-- 基本信息 -->
          <div class="detail-grid">
            <div class="detail-item">
              <span class="detail-label">功能</span>
              <span class="detail-value">{{ detail.function_label }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">模型</span>
              <span class="detail-value mono">{{ detail.model }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">渠道</span>
              <span class="detail-value">{{ detail.channel_name || '—' }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">状态</span>
              <span class="tag" :class="detail.status === 'success' ? 'green' : 'red'">
                {{ detail.status === 'success' ? '成功' : '失败' }}
              </span>
            </div>
            <div class="detail-item">
              <span class="detail-label">时间</span>
              <span class="detail-value mono">{{ formatTime(detail.created_at) }}</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">耗时</span>
              <span class="detail-value mono">{{ formatDuration(detail.duration_ms) }}</span>
            </div>
          </div>

          <!-- Token 与费用 -->
          <div class="token-row">
            <div class="token-item">
              <span class="token-label">输入 Token</span>
              <span class="token-value">{{ detail.prompt_tokens }}</span>
            </div>
            <div class="token-item">
              <span class="token-label">输出 Token</span>
              <span class="token-value">{{ detail.completion_tokens }}</span>
            </div>
            <div class="token-item">
              <span class="token-label">总 Token</span>
              <span class="token-value highlight">{{ detail.total_tokens }}</span>
            </div>
            <div class="token-item">
              <span class="token-label">预估费用</span>
              <span class="token-value cost">{{ formatCost(detail.cost_estimate) }}</span>
            </div>
          </div>

          <!-- 错误信息 -->
          <div v-if="detail.error_message" class="error-box">
            <span class="error-icon">⚠️</span>
            <span class="error-text">{{ detail.error_message }}</span>
          </div>

          <!-- 输入 -->
          <div class="io-section">
            <div class="io-head">
              <span class="io-title">📥 输入</span>
              <span class="io-meta">{{ detail.input_chars }} 字符</span>
            </div>
            <pre class="io-content">{{ formatInputMessages(detail.input_messages) }}</pre>
          </div>

          <!-- 输出 -->
          <div class="io-section">
            <div class="io-head">
              <span class="io-title">📤 输出</span>
              <span class="io-meta">{{ detail.output_chars }} 字符</span>
            </div>
            <pre class="io-content output">{{ detail.output_text || '(无输出)' }}</pre>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn danger" @click="deleteCall(detail); showDetail = false">删除记录</button>
          <button class="btn" @click="showDetail = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.msg" class="toast" :class="{ error: !toast.ok }">{{ toast.msg }}</div>
  </div>
</template>

<style scoped>
.calls-page { padding: 0; }

.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.page-head h2 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.page-head .sub { font-size: 12px; color: var(--text-muted); }
.head-actions { display: flex; gap: 8px; }

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px;
}
.stat-icon { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.stat-icon.blue { background: var(--primary-weak); }
.stat-icon.green { background: #E8F5EC; }
.stat-icon.purple { background: var(--ai-weak); }
.stat-icon.orange { background: #FFF3DC; }
.stat-body { flex: 1; min-width: 0; }
.stat-num { font-size: 22px; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.stat-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

/* 功能分布 */
.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; overflow: hidden; }
.panel-head { padding: 12px 16px; border-bottom: 1px solid var(--border); background: var(--bg-sunken); }
.panel-title { font-size: 13px; font-weight: 600; }

.func-bars { padding: 12px 16px; }
.func-bar-row { display: flex; align-items: center; gap: 10px; padding: 5px 0; }
.func-name { width: 90px; font-size: 12px; color: var(--text-secondary); flex-shrink: 0; }
.func-bar-wrap { flex: 1; height: 18px; background: var(--bg-sunken); border-radius: 4px; overflow: hidden; }
.func-bar { height: 100%; background: linear-gradient(90deg, var(--primary), #6B8AE8); border-radius: 4px; min-width: 2px; transition: width .3s; }
.func-count { width: 40px; text-align: right; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
.func-tokens { width: 60px; text-align: right; font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.func-cost { width: 70px; text-align: right; font-size: 11px; color: var(--warning); font-family: var(--font-mono); }

/* 筛选栏 */
.filter-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.filter-bar select, .filter-bar input { height: 32px; font-size: 12px; padding: 0 10px; }
.filter-bar input { width: 180px; }
.filter-total { margin-left: auto; font-size: 12px; color: var(--text-muted); }

/* 表格 */
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
thead th { text-align: left; font-weight: 500; color: var(--text-secondary); padding: 10px 12px; border-bottom: 1px solid var(--border); background: var(--bg-sunken); font-size: 11px; user-select: none; }
tbody td { padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,.04); vertical-align: middle; }
tbody tr.clickable { cursor: pointer; transition: background .12s; }
tbody tr.clickable:hover { background: rgba(62,99,221,.04); }
tbody tr:last-child td { border-bottom: none; }
.mono { font-family: var(--font-mono); }
.time-cell { font-size: 11.5px; color: var(--text-secondary); }
.model-cell { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cost-cell { color: var(--warning); font-weight: 500; }

.func-tag { display: inline-block; padding: 2px 8px; border-radius: 5px; background: var(--primary-weak); color: var(--primary); font-size: 11px; font-weight: 500; }

/* 分页 */
.pagination { display: flex; align-items: center; gap: 6px; padding: 12px 16px; border-top: 1px solid var(--border); justify-content: center; }
.page-info { font-size: 12px; color: var(--text-muted); margin-left: 8px; }

/* 加载 / 空状态 */
.loading-state, .empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 20px; gap: 10px; }
.empty-icon { font-size: 36px; opacity: .5; }
.empty-title { font-size: 15px; font-weight: 600; }
.empty-desc { font-size: 12px; color: var(--text-muted); text-align: center; }

/* 详情模态框 */
.detail-modal { width: 720px; max-width: 92vw; max-height: 88vh; display: flex; flex-direction: column; }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-shrink: 0; }
.modal-head h3 { font-size: 16px; font-weight: 600; }
.detail-body { overflow-y: auto; flex: 1; padding-right: 4px; }

.detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.detail-item { display: flex; flex-direction: column; gap: 3px; }
.detail-label { font-size: 11px; color: var(--text-muted); }
.detail-value { font-size: 13px; font-weight: 500; }

.token-row { display: flex; gap: 10px; margin-bottom: 14px; padding: 12px; background: var(--bg-sunken); border-radius: 10px; }
.token-item { flex: 1; text-align: center; }
.token-label { display: block; font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.token-value { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.token-value.highlight { color: var(--primary); }
.token-value.cost { color: var(--warning); }

.error-box { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; background: #FDECEA; border-radius: 8px; margin-bottom: 14px; font-size: 12px; color: var(--danger); }
.error-text { word-break: break-all; line-height: 1.4; }

.io-section { margin-bottom: 14px; }
.io-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.io-title { font-size: 13px; font-weight: 600; }
.io-meta { font-size: 11px; color: var(--text-muted); }
.io-content {
  background: var(--bg-sunken); border-radius: 8px; padding: 12px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
  max-height: 280px; overflow-y: auto; font-family: var(--font-mono); color: var(--text);
}
.io-content.output { background: #F0F7FF; border-left: 3px solid var(--primary); }

.modal-actions { display: flex; justify-content: space-between; gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); flex-shrink: 0; }
.modal-actions .btn { margin-left: auto; }
.modal-actions .btn + .btn { margin-left: 8px; }

.icon-btn {
  width: 28px; height: 28px; border: 1px solid var(--border); border-radius: 7px;
  background: var(--bg-card); display: flex; align-items: center; justify-content: center;
  font-size: 13px; cursor: pointer; transition: all .12s; padding: 0;
}
.icon-btn:hover { background: var(--bg-sunken); }

/* 响应式 */
@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .detail-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .stat-grid { grid-template-columns: 1fr; }
  .detail-grid { grid-template-columns: 1fr; }
  .token-row { flex-wrap: wrap; }
  .token-item { flex: 0 0 45%; }
}
</style>
