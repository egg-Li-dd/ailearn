<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '../api.js'

// 状态
const loading = ref(false)
const conversations = ref([])
const selectedConvId = ref(null)
const messagesLoading = ref(false)
const messages = ref([])
const courseName = ref('')
const totalMessages = ref(0)
const search = ref('')
const roleFilter = ref('all') // all / user / assistant
const expandedMsgId = ref(null)
const deletingId = ref(null)
const clearing = ref(false)

// Toast
const toast = ref({ msg: '', ok: true })
let toastTimer = null
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3000)
}

// 统计
const stats = computed(() => {
  const totalConv = conversations.value.length
  const totalMsg = conversations.value.reduce((s, c) => s + (c.message_count || 0), 0)
  const activeCourses = new Set(conversations.value.map(c => c.course_id).filter(Boolean)).size
  return { totalConv, totalMsg, activeCourses }
})

// 过滤后的消息
const filteredMessages = computed(() => {
  let list = messages.value
  if (roleFilter.value !== 'all') {
    list = list.filter(m => m.role === roleFilter.value)
  }
  if (search.value.trim()) {
    const kw = search.value.trim().toLowerCase()
    list = list.filter(m =>
      (m.content_preview || '').toLowerCase().includes(kw) ||
      (m.content || '').toLowerCase().includes(kw)
    )
  }
  return list
})

// 加载对话列表
async function loadConversations() {
  loading.value = true
  try {
    const data = await api.classroomConversations()
    conversations.value = data || []
  } catch (e) {
    showToast(e.message || '加载对话列表失败', false)
  } finally {
    loading.value = false
  }
}

// 加载指定对话的消息
async function loadMessages(convId) {
  selectedConvId.value = convId
  messagesLoading.value = true
  messages.value = []
  expandedMsgId.value = null
  try {
    const data = await api.classroomMessages(convId)
    messages.value = data.messages || []
    courseName.value = data.course_name || ''
    totalMessages.value = data.total || 0
  } catch (e) {
    showToast(e.message || '加载消息失败', false)
  } finally {
    messagesLoading.value = false
  }
}

// 删除单条消息
async function deleteMessage(msg) {
  if (!confirm(`确定删除这条消息吗？\n\n${(msg.content_preview || '').substring(0, 80)}`)) return
  deletingId.value = msg.id
  try {
    await api.deleteClassroomMessage(msg.id)
    messages.value = messages.value.filter(m => m.id !== msg.id)
    totalMessages.value = Math.max(0, totalMessages.value - 1)
    // 更新对话列表中的计数
    const conv = conversations.value.find(c => c.conversation_id === selectedConvId.value)
    if (conv) conv.message_count = Math.max(0, (conv.message_count || 1) - 1)
    showToast('消息已删除')
  } catch (e) {
    showToast(e.message || '删除失败', false)
  } finally {
    deletingId.value = null
  }
}

// 清空对话
async function clearConversation() {
  if (!selectedConvId.value) return
  if (!confirm(`确定清空「${courseName.value || '该课堂'}」的全部 ${totalMessages.value} 条消息吗？此操作不可恢复。`)) return
  clearing.value = true
  try {
    const result = await api.clearClassroomConversation(selectedConvId.value)
    messages.value = []
    totalMessages.value = 0
    const conv = conversations.value.find(c => c.conversation_id === selectedConvId.value)
    if (conv) {
      conv.message_count = 0
      conv.last_message_at = null
      conv.last_message_preview = null
    }
    showToast(`已清空 ${result.deleted} 条消息`)
  } catch (e) {
    showToast(e.message || '清空失败', false)
  } finally {
    clearing.value = false
  }
}

// 格式化时间
function fmtTime(iso) {
  if (!iso) return '--'
  try {
    const d = new Date(iso)
    const now = new Date()
    const sameDay = d.toDateString() === now.toDateString()
    const yest = new Date(now); yest.setDate(yest.getDate() - 1)
    const isYest = d.toDateString() === yest.toDateString()
    const time = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
    if (sameDay) return `今天 ${time}`
    if (isYest) return `昨天 ${time}`
    return `${d.getMonth() + 1}/${d.getDate()} ${time}`
  } catch {
    return iso
  }
}

// 消息类型标签
function typeLabel(t) {
  return {
    legacy: '文本', text: '文本', quiz: '题目', feedback: '判卷',
    quiz_session: '小测', cloze: '填空', error: '错误'
  }[t] || t || '文本'
}

function typeClass(t) {
  return {
    quiz: 'type-quiz', feedback: 'type-feedback', cloze: 'type-cloze',
    error: 'type-error', quiz_session: 'type-session'
  }[t] || 'type-text'
}

// 展开/收起消息详情
function toggleExpand(id) {
  expandedMsgId.value = expandedMsgId.value === id ? null : id
}

onMounted(loadConversations)
</script>

<template>
  <div class="messages-view">
    <!-- 标题 -->
    <div class="page-header">
      <h2>课堂消息</h2>
      <div class="header-actions">
        <button class="btn-refresh" @click="loadConversations" :disabled="loading">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.totalConv }}</div>
        <div class="stat-label">课堂对话</div>
      </div>
      <div class="stat-card stat-msg">
        <div class="stat-value">{{ stats.totalMsg }}</div>
        <div class="stat-label">消息总数</div>
      </div>
      <div class="stat-card stat-course">
        <div class="stat-value">{{ stats.activeCourses }}</div>
        <div class="stat-label">涉及科目</div>
      </div>
    </div>

    <!-- 主体：两栏 -->
    <div class="main-panel">
      <!-- 左栏：对话列表 -->
      <div class="conv-panel">
        <div class="panel-title">对话列表</div>
        <div v-if="loading" class="panel-loading">加载中…</div>
        <div v-else-if="conversations.length === 0" class="panel-empty">
          暂无课堂对话
        </div>
        <div v-else class="conv-list">
          <div
            v-for="conv in conversations"
            :key="conv.conversation_id"
            class="conv-item"
            :class="{ active: selectedConvId === conv.conversation_id }"
            @click="loadMessages(conv.conversation_id)"
          >
            <div class="conv-header">
              <span class="conv-course">{{ conv.course_name || '未分类' }}</span>
              <span class="conv-count">{{ conv.message_count }}条</span>
            </div>
            <div class="conv-preview">{{ conv.last_message_preview || '暂无消息' }}</div>
            <div class="conv-meta">{{ fmtTime(conv.last_message_at) }}</div>
          </div>
        </div>
      </div>

      <!-- 右栏：消息列表 -->
      <div class="msg-panel">
        <template v-if="selectedConvId">
          <div class="msg-toolbar">
            <div class="msg-title">
              <span class="msg-course">{{ courseName || '课堂消息' }}</span>
              <span class="msg-total">共 {{ totalMessages }} 条</span>
            </div>
            <div class="toolbar-actions">
              <select v-model="roleFilter" class="role-select">
                <option value="all">全部角色</option>
                <option value="user">学生</option>
                <option value="assistant">教练</option>
              </select>
              <input
                v-model="search"
                type="text"
                placeholder="搜索消息内容…"
                class="search-input"
              />
              <button
                class="btn-clear"
                @click="clearConversation"
                :disabled="clearing || messages.length === 0"
              >
                {{ clearing ? '清空中…' : '清空对话' }}
              </button>
            </div>
          </div>

          <div v-if="messagesLoading" class="panel-loading">加载消息中…</div>
          <div v-else-if="filteredMessages.length === 0" class="panel-empty">
            {{ messages.length === 0 ? '该对话暂无消息' : '没有匹配的消息' }}
          </div>
          <div v-else class="msg-list">
            <div
              v-for="msg in filteredMessages"
              :key="msg.id"
              class="msg-item"
              :class="[msg.role, typeClass(msg.type)]"
            >
              <div class="msg-header" @click="toggleExpand(msg.id)">
                <span class="msg-role">{{ msg.role === 'user' ? '学生' : '教练' }}</span>
                <span class="msg-type" :class="typeClass(msg.type)">{{ typeLabel(msg.type) }}</span>
                <span class="msg-time">{{ fmtTime(msg.created_at) }}</span>
                <span v-if="msg.ai_total_tokens" class="msg-tokens">{{ msg.ai_total_tokens }} tokens</span>
                <span class="expand-icon">{{ expandedMsgId === msg.id ? '▲' : '▼' }}</span>
              </div>
              <div class="msg-content">{{ msg.content_preview }}</div>

              <!-- 知识点映射 -->
              <div v-if="msg.knowledge_refs && msg.knowledge_refs.length" class="msg-knowledge">
                <span class="knowledge-label">关联知识点：</span>
                <span
                  v-for="kn in msg.knowledge_refs"
                  :key="kn.id"
                  class="knowledge-tag"
                  :title="`知识点ID: ${kn.id}`"
                >
                  {{ kn.name }}
                </span>
              </div>

              <!-- 展开详情 -->
              <div v-if="expandedMsgId === msg.id" class="msg-detail">
                <div class="detail-label">完整内容</div>
                <div class="detail-text">{{ msg.content }}</div>
                <div v-if="msg.ai_model" class="detail-meta">
                  模型: {{ msg.ai_model }}
                  <span v-if="msg.ai_channel"> · 渠道: {{ msg.ai_channel }}</span>
                  <span v-if="msg.ai_cost != null"> · 费用: ¥{{ msg.ai_cost.toFixed(4) }}</span>
                </div>
                <div class="detail-actions">
                  <button
                    class="btn-delete"
                    @click.stop="deleteMessage(msg)"
                    :disabled="deletingId === msg.id"
                  >
                    {{ deletingId === msg.id ? '删除中…' : '删除此消息' }}
                  </button>
                </div>
              </div>

              <!-- 快捷删除（不展开也能删） -->
              <button
                v-if="expandedMsgId !== msg.id"
                class="msg-delete-quick"
                @click.stop="deleteMessage(msg)"
                :disabled="deletingId === msg.id"
                title="删除此消息"
              >✕</button>
            </div>
          </div>
        </template>
        <div v-else class="panel-placeholder">
          <div class="placeholder-icon">💬</div>
          <div class="placeholder-title">选择一个对话查看消息</div>
          <div class="placeholder-desc">从左侧列表选择课堂对话，可查看历史消息、关联知识点并快捷管理</div>
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
.messages-view { max-width: 1200px; }

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
.stat-msg .stat-value { color: var(--primary); }
.stat-course .stat-value { color: var(--success, #27ae60); }

/* 主体两栏 */
.main-panel {
  display: flex; gap: 16px; align-items: flex-start;
}
.conv-panel {
  width: 280px; flex-shrink: 0;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden;
}
.panel-title {
  padding: 12px 16px; font-size: 14px; font-weight: 600;
  border-bottom: 1px solid var(--border); color: var(--text);
}
.panel-loading, .panel-empty {
  padding: 32px 16px; text-align: center; color: var(--text-muted); font-size: 13px;
}
.conv-list { max-height: 600px; overflow-y: auto; }
.conv-item {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  cursor: pointer; transition: background 0.15s;
}
.conv-item:hover { background: var(--bg-sunken); }
.conv-item.active { background: var(--primary-weak, #eef2ff); border-left: 3px solid var(--primary); }
.conv-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;
}
.conv-course { font-size: 13px; font-weight: 600; color: var(--text); }
.conv-count { font-size: 11px; color: var(--text-muted); }
.conv-preview {
  font-size: 12px; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  margin-bottom: 2px;
}
.conv-meta { font-size: 11px; color: var(--text-muted); }

/* 右栏消息 */
.msg-panel {
  flex: 1; min-width: 0;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; overflow: hidden;
}
.msg-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  flex-wrap: wrap; gap: 8px;
}
.msg-title { display: flex; align-items: center; gap: 10px; }
.msg-course { font-size: 15px; font-weight: 600; color: var(--text); }
.msg-total { font-size: 12px; color: var(--text-muted); }
.toolbar-actions { display: flex; gap: 8px; align-items: center; }
.role-select {
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text); font-size: 12px; cursor: pointer;
}
.search-input {
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-card); color: var(--text); font-size: 12px; width: 160px;
}
.search-input:focus { outline: none; border-color: var(--primary); }
.btn-clear {
  padding: 6px 12px; border: 1px solid var(--danger, #e74c3c); border-radius: 6px;
  background: transparent; color: var(--danger, #e74c3c); font-size: 12px; cursor: pointer;
}
.btn-clear:hover { background: rgba(231,76,60,0.08); }
.btn-clear:disabled { opacity: 0.5; cursor: not-allowed; }

.msg-list { max-height: 600px; overflow-y: auto; padding: 8px; }
.msg-item {
  position: relative;
  padding: 10px 14px; margin-bottom: 8px;
  border-radius: 8px; border: 1px solid var(--border);
  background: var(--bg-sunken, #f8f9fa);
}
.msg-item.user { background: #e8f4fd; border-color: #b3d9f2; }
.msg-item.assistant { background: var(--bg-card); }
.msg-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
  cursor: pointer; font-size: 12px;
}
.msg-role { font-weight: 600; color: var(--text); }
.msg-item.user .msg-role { color: #2980b9; }
.msg-type {
  padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 500;
}
.type-text { background: #e0e0e0; color: #555; }
.type-quiz { background: #fef3e2; color: #f39c12; }
.type-feedback { background: #e8f8f0; color: #27ae60; }
.type-cloze { background: #f3e8fd; color: #8e44ad; }
.type-error { background: #fde8e8; color: #e74c3c; }
.type-session { background: #eef2ff; color: var(--primary); }
.msg-time { color: var(--text-muted); margin-left: auto; }
.msg-tokens { color: var(--text-muted); font-size: 11px; }
.expand-icon { font-size: 10px; color: var(--text-muted); }

.msg-content {
  font-size: 13px; color: var(--text-secondary); line-height: 1.5;
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}

.msg-knowledge { margin-top: 6px; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.knowledge-label { font-size: 11px; color: var(--text-muted); }
.knowledge-tag {
  padding: 2px 8px; border-radius: 10px; font-size: 11px;
  background: var(--primary-weak, #eef2ff); color: var(--primary);
  cursor: default;
}

.msg-detail {
  margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border);
}
.detail-label { font-size: 11px; font-weight: 600; color: var(--primary); margin-bottom: 4px; }
.detail-text {
  font-size: 12px; color: var(--text-secondary); line-height: 1.6;
  white-space: pre-wrap; word-break: break-all;
  max-height: 300px; overflow-y: auto;
  padding: 8px; background: var(--bg-card); border-radius: 6px;
}
.detail-meta { margin-top: 6px; font-size: 11px; color: var(--text-muted); }
.detail-actions { margin-top: 8px; }
.btn-delete {
  padding: 5px 12px; border: 1px solid var(--danger, #e74c3c); border-radius: 6px;
  background: transparent; color: var(--danger, #e74c3c); font-size: 12px; cursor: pointer;
}
.btn-delete:hover { background: rgba(231,76,60,0.08); }
.btn-delete:disabled { opacity: 0.5; cursor: not-allowed; }

.msg-delete-quick {
  position: absolute; top: 8px; right: 8px;
  width: 22px; height: 22px; border: none; border-radius: 50%;
  background: rgba(0,0,0,0.06); color: var(--text-muted);
  font-size: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.msg-delete-quick:hover { background: rgba(231,76,60,0.15); color: var(--danger, #e74c3c); }
.msg-delete-quick:disabled { opacity: 0.4; cursor: not-allowed; }

.panel-placeholder {
  padding: 60px 24px; text-align: center; color: var(--text-muted);
}
.placeholder-icon { font-size: 40px; margin-bottom: 12px; }
.placeholder-title { font-size: 16px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.placeholder-desc { font-size: 13px; }

/* Toast */
.toast {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
  padding: 10px 24px; border-radius: 8px; background: #2ecc71;
  color: white; font-size: 13px; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  max-width: 480px; min-width: 200px; text-align: center;
}
.toast.error { background: #e74c3c; }

@media (max-width: 768px) {
  .main-panel { flex-direction: column; }
  .conv-panel { width: 100%; }
  .conv-list { max-height: 240px; }
  .msg-list { max-height: 400px; }
}
</style>
