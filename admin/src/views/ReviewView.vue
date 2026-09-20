<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '../api.js'

// 状态
const loading = ref(false)
const items = ref([])
const search = ref('')
const expandedId = ref(null)

// Toast
const toast = ref({ msg: '', ok: true })
let toastTimer = null
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3000)
}

// 评分中
const ratingId = ref(null)

// 统计
const stats = computed(() => {
  const total = items.value.length
  const open = items.value.filter(i => !i.rated).length
  const rated = total - open
  return { total, open, rated }
})

// 过滤后列表
const filtered = computed(() => {
  if (!search.value.trim()) return items.value
  const kw = search.value.trim().toLowerCase()
  return items.value.filter(i =>
    (i.node_name || '').toLowerCase().includes(kw) ||
    (i.summary || '').toLowerCase().includes(kw)
  )
})

// 加载
async function load() {
  loading.value = true
  try {
    const data = await api.reviewToday()
    items.value = (data || []).map(i => ({ ...i, rated: false }))
  } catch (e) {
    showToast(e.message || '加载失败', false)
  } finally {
    loading.value = false
  }
}

// 手动评分
async function rate(item, rating) {
  ratingId.value = item.id
  try {
    const result = await api.reviewRate(item.id, rating)
    item.rated = true
    item.rating_result = result
    showToast(`已评分：${result.rating_name || ''}，下次复习 ${result.next_label || ''}`)
  } catch (e) {
    showToast(e.message || '评分失败', false)
  } finally {
    ratingId.value = null
  }
}

// 格式化时间
function fmtTime(iso) {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    const now = new Date()
    const sameDay = d.toDateString() === now.toDateString()
    if (sameDay) return `今天 ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch {
    return iso
  }
}

// FSRS 状态标签
function fsrsStateLabel(s) {
  return { learning: '学习中', relearning: '重学中', review: '复习期', new: '新卡' }[s] || s || '--'
}

// 掌握度样式
function masteryClass(m) {
  if (m >= 70) return 'mastery-high'
  if (m >= 40) return 'mastery-mid'
  return 'mastery-low'
}

// 展开/收起
function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
}

onMounted(load)
</script>

<template>
  <div class="review-view">
    <!-- 标题 -->
    <div class="page-header">
      <h2>复习队列</h2>
      <button class="btn-refresh" @click="load" :disabled="loading">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>

    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total }}</div>
        <div class="stat-label">今日到期</div>
      </div>
      <div class="stat-card stat-open">
        <div class="stat-value">{{ stats.open }}</div>
        <div class="stat-label">待复习</div>
      </div>
      <div class="stat-card stat-done">
        <div class="stat-value">{{ stats.rated }}</div>
        <div class="stat-label">已评分</div>
      </div>
    </div>

    <!-- 搜索 -->
    <div class="filter-bar">
      <input
        v-model="search"
        type="text"
        placeholder="搜索知识点名或要点…"
        class="search-input"
      />
      <span class="filter-count">{{ filtered.length }} 项</span>
    </div>

    <!-- 列表 -->
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="filtered.length === 0" class="empty">
      <div class="empty-icon">✅</div>
      <div class="empty-title">今日复习已清空</div>
      <div class="empty-desc">沉淀的新知识点会按记忆曲线自动排入队列</div>
    </div>
    <div v-else class="review-list">
      <div
        v-for="item in filtered"
        :key="item.id"
        class="review-card"
        :class="{ rated: item.rated }"
      >
        <!-- 头部 -->
        <div class="card-header" @click="toggleExpand(item.id)">
          <div class="card-title">
            <span class="node-name">{{ item.node_name }}</span>
            <span class="mastery-badge" :class="masteryClass(item.mastery)">
              掌握度 {{ item.mastery }}
            </span>
          </div>
          <div class="card-meta">
            <span>到期：{{ fmtTime(item.due_at) }}</span>
            <span>复习 {{ item.reps || 0 }} 次</span>
            <span v-if="item.lapses > 0" class="lapse">重做 {{ item.lapses }} 次</span>
          </div>
        </div>

        <!-- FSRS 信息 -->
        <div class="fsrs-row">
          <span class="fsrs-tag">{{ fsrsStateLabel(item.fsrs_state) }}</span>
          <span class="fsrs-detail">难度 {{ item.fsrs_d?.toFixed(1) || '--' }} · 稳定 {{ item.fsrs_s?.toFixed(1) || '--' }}天</span>
          <span class="expand-icon">{{ expandedId === item.id ? '▲' : '▼' }}</span>
        </div>

        <!-- 展开详情 -->
        <div v-if="expandedId === item.id" class="card-detail">
          <div v-if="item.summary" class="summary">
            <div class="detail-label">记忆要点</div>
            <div class="summary-text">{{ item.summary }}</div>
          </div>

          <!-- 背诵题预览 -->
          <div v-if="item.recite_question" class="question-preview">
            <div class="detail-label">背诵题</div>
            <div class="preview-text">{{ item.recite_question.question || '背诵：' + item.node_name }}</div>
            <div v-if="item.recite_question.content" class="preview-content">
              {{ item.recite_question.content.substring(0, 200) }}{{ item.recite_question.content.length > 200 ? '…' : '' }}
            </div>
          </div>

          <!-- 最近题目预览 -->
          <div v-if="item.recent_question" class="question-preview">
            <div class="detail-label">最近题目（{{ item.recent_question.qtype }}）</div>
            <div class="preview-text">{{ item.recent_question.question || '' }}</div>
            <div v-if="item.recent_question.options && item.recent_question.options.length" class="preview-options">
              <div v-for="(opt, i) in item.recent_question.options.slice(0, 4)" :key="i" class="option-item">
                {{ String.fromCharCode(65 + i) }}. {{ opt }}
              </div>
            </div>
          </div>

          <div v-if="!item.summary && !item.recite_question && !item.recent_question" class="no-detail">
            暂无题目或要点预览
          </div>
        </div>

        <!-- 评分结果 -->
        <div v-if="item.rated && item.rating_result" class="rating-result">
          <span class="result-icon">✓</span>
          <span>{{ item.rating_result.rating_name }} · 下次复习 {{ item.rating_result.next_label }}</span>
          <span class="result-mastery">掌握度 {{ item.rating_result.mastery }}%</span>
        </div>

        <!-- 评分按钮 -->
        <div v-if="!item.rated" class="rating-bar">
          <button
            v-for="(p, idx) in (item.previews || [])"
            :key="idx"
            class="rate-btn"
            :class="'rate-' + idx"
            :disabled="ratingId === item.id"
            @click="rate(item, idx)"
          >
            <span class="rate-label">{{ ['重做', '模糊', '记得', '清楚'][idx] }}</span>
            <span class="rate-preview">{{ p.label || '' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.msg" class="toast" :class="{ error: !toast.ok }">
      {{ toast.msg }}
    </div>
  </div>
</template>

<style scoped>
.review-view { max-width: 860px; }

.page-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; font-size: 20px; }
.btn-refresh {
  padding: 6px 16px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); color: var(--text-secondary); cursor: pointer;
  font-size: 13px;
}
.btn-refresh:hover { background: var(--bg-sunken); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* 统计 */
.stats-row { display: flex; gap: 12px; margin-bottom: 16px; }
.stat-card {
  flex: 1; padding: 14px 16px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border);
}
.stat-value { font-size: 24px; font-weight: 700; color: var(--text); }
.stat-label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.stat-open .stat-value { color: var(--danger, #e74c3c); }
.stat-done .stat-value { color: var(--success, #27ae60); }

/* 搜索 */
.filter-bar {
  display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
}
.search-input {
  flex: 1; padding: 8px 12px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--bg-card); color: var(--text);
  font-size: 13px; outline: none;
}
.search-input:focus { border-color: var(--primary); }
.filter-count { font-size: 12px; color: var(--text-muted); white-space: nowrap; }

/* 列表 */
.loading, .empty { text-align: center; padding: 48px 0; color: var(--text-muted); }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-title { font-size: 16px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.empty-desc { font-size: 13px; }

.review-list { display: flex; flex-direction: column; gap: 10px; }

.review-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden; transition: border-color 0.15s;
}
.review-card.rated { opacity: 0.7; }
.review-card:hover { border-color: var(--primary); }

.card-header {
  padding: 12px 16px; cursor: pointer;
}
.card-title {
  display: flex; align-items: center; gap: 10px; margin-bottom: 4px;
}
.node-name { font-size: 15px; font-weight: 600; color: var(--text); }
.mastery-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 500;
}
.mastery-low { background: #fde8e8; color: #e74c3c; }
.mastery-mid { background: #fef3e2; color: #f39c12; }
.mastery-high { background: #e8f8f0; color: #27ae60; }

.card-meta {
  display: flex; gap: 14px; font-size: 12px; color: var(--text-muted);
}
.lapse { color: var(--danger, #e74c3c); }

/* FSRS */
.fsrs-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 16px; border-top: 1px solid var(--border);
  font-size: 12px; color: var(--text-muted);
}
.fsrs-tag {
  padding: 2px 8px; border-radius: 6px;
  background: var(--primary-weak, #eef2ff); color: var(--primary);
  font-weight: 500;
}
.fsrs-detail { flex: 1; }
.expand-icon { font-size: 10px; }

/* 详情 */
.card-detail {
  padding: 12px 16px; border-top: 1px solid var(--border);
  background: var(--bg-sunken, #f8f9fa);
}
.detail-label {
  font-size: 11px; font-weight: 600; color: var(--primary);
  text-transform: uppercase; margin-bottom: 6px;
}
.summary-text { font-size: 13px; line-height: 1.6; color: var(--text-secondary); }
.question-preview { margin-top: 10px; }
.question-preview:first-child { margin-top: 0; }
.preview-text { font-size: 13px; color: var(--text); margin-bottom: 6px; }
.preview-content {
  font-size: 12px; color: var(--text-muted); line-height: 1.5;
  padding: 8px; background: var(--bg-card); border-radius: 6px;
}
.preview-options { display: flex; flex-direction: column; gap: 4px; }
.option-item { font-size: 12px; color: var(--text-secondary); }
.no-detail { font-size: 12px; color: var(--text-muted); font-style: italic; }

/* 评分结果 */
.rating-result {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; border-top: 1px solid var(--border);
  background: #e8f8f0; font-size: 13px; color: #27ae60;
}
.result-icon { font-weight: 700; }
.result-mastery { margin-left: auto; font-size: 12px; }

/* 评分按钮 */
.rating-bar {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
  padding: 12px 16px; border-top: 1px solid var(--border);
}
.rate-btn {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 8px 4px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); cursor: pointer; transition: all 0.15s;
}
.rate-btn:hover:not(:disabled) { transform: translateY(-1px); }
.rate-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rate-label { font-size: 13px; font-weight: 600; }
.rate-preview { font-size: 10px; color: var(--text-muted); }
.rate-0 { border-color: #e74c3c; color: #e74c3c; }
.rate-0:hover:not(:disabled) { background: #fde8e8; }
.rate-1 { border-color: #f39c12; color: #f39c12; }
.rate-1:hover:not(:disabled) { background: #fef3e2; }
.rate-2 { border-color: #3498db; color: #3498db; }
.rate-2:hover:not(:disabled) { background: #ebf5fb; }
.rate-3 { border-color: #27ae60; color: #27ae60; }
.rate-3:hover:not(:disabled) { background: #e8f8f0; }

/* Toast */
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
  padding: 10px 24px; border-radius: 8px; background: #2ecc71;
  color: white; font-size: 13px; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  max-width: 480px; min-width: 200px; text-align: center;
}
.toast.error { background: #e74c3c; }
</style>
