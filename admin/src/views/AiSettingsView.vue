<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

// ---------- 状态 ----------
const activeTab = ref('channels') // channels / functions / data
const channels = ref([])
const channelTypes = ref({})
const stats = ref({ total: 0, enabled: 0, active: 0, error: 0, total_calls: 0, success_rate: 0, total_tokens: 0 })
const loading = ref(false)
const busy = ref(false)
const toast = ref({ msg: '', ok: true })
// 通道范围：global=全局通道, private=用户私有通道
const channelScope = ref('global')
const selectedUserKey = ref('')
const userList = ref([])
const newModel = ref('')
let toastTimer = null

// 功能配置
const funcConfig = ref({})
const funcChannels = ref([])
const funcLoading = ref(false)
const funcSaving = ref({})

// 模态框
const showModal = ref(false)
const editingId = ref(null)
const modalTab = ref('basic') // basic / models / advanced
const form = ref(defaultForm())

// 测试状态
const testingId = ref(null)
const fetchingModelsId = ref(null)

function defaultForm() {
  return {
    name: '',
    type: 'openai',
    base_url: 'https://api.deepseek.com/v1',
    api_key: '',
    models: [],
    default_model: '',
    vision_model: '',
    weight: 1,
    priority: 5,
    enabled: true,
    temperature: 0.7,
    user_key: null,
  }
}

function formatTokens(n) {
  if (!n) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

function addModel() {
  const m = newModel.value.trim()
  if (m && !form.value.models.includes(m)) {
    form.value.models.push(m)
  }
  newModel.value = ''
}

// ---------- 预设 ----------
const PRESETS = [
  { name: 'DeepSeek', type: 'openai', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: 'OpenCode Zen', type: 'openai', base_url: 'https://opencode.ai/zen/v1', model: 'deepseek-v4-flash' },
  { name: 'OpenCode Go', type: 'openai', base_url: 'https://opencode.ai/zen/go/v1', model: 'deepseek-v4-flash' },
  { name: '阿里云百炼', type: 'openai', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: '通义千问', type: 'openai', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: '智谱清言', type: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { name: '月之暗面', type: 'openai', base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k' },
  { name: 'OpenAI', type: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { name: '硅基流动', type: 'openai', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct' },
]

function applyPreset(p) {
  form.value.type = p.type
  form.value.base_url = p.base_url
  if (!form.value.default_model) form.value.default_model = p.model
  if (!form.value.name) form.value.name = p.name
}

// ---------- Toast ----------
function showToast(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = { msg: '', ok: true }), 3500)
}

// ---------- 数据加载 ----------
async function loadUsers() {
  try {
    userList.value = await api.adminUsers()
  } catch (e) {
    console.error('加载用户列表失败:', e)
  }
}

async function loadAll() {
  loading.value = true
  try {
    const params = { scope: channelScope.value }
    if (channelScope.value === 'private' && selectedUserKey.value) {
      params.user_key = selectedUserKey.value
    }
    const [r, s] = await Promise.all([api.aiChannels(params), api.aiChannelStats()])
    channels.value = r.channels || []
    channelTypes.value = r.types || {}
    stats.value = s
  } catch (e) {
    showToast(e.message, false)
  } finally {
    loading.value = false
  }

  // 加载功能配置
  try {
    const fc = await api.aiFunctionConfig()
    funcConfig.value = fc.configs || {}
    funcChannels.value = fc.channels || []
  } catch (e) {
    console.error('加载功能配置失败', e)
  }
}
onMounted(loadAll)

// ---------- 功能配置 ----------
async function saveFuncConfig(funcType, field, value) {
  funcSaving.value[funcType] = true
  try {
    await api.updateAiFunctionConfig(funcType, { [field]: value })
    if (funcConfig.value[funcType]) {
      funcConfig.value[funcType][field] = value
    }
    showToast('已保存')
  } catch (e) {
    showToast(e.message, false)
  } finally {
    funcSaving.value[funcType] = false
  }
}

function getFuncModels(funcType) {
  const cfg = funcConfig.value[funcType]
  if (!cfg || !cfg.channel_id) return []
  const ch = funcChannels.value.find(c => c.id === cfg.channel_id)
  return ch ? ch.models : []
}

const funcList = computed(() => {
  return Object.entries(funcConfig.value).map(([key, cfg]) => ({ key, ...cfg }))
})

function getFuncIcon(key) {
  const icons = {
    generate: '✨', action: '🔧', quiz: '📝', quiz_answer: '✅',
    planner: '📋', tutor: '💬', sediment: '📦', classroom: '🏫',
    handwrite: '✍️', knowledge: '🌳', stats: '📊', review: '🔄',
  }
  return icons[key] || '🤖'
}

// ---------- 功能配置：检测、一键配置、设置 ----------
const detectLoading = ref(false)
const detectResults = ref({})
const detectSummary = ref(null)

const autoConfigLoading = ref(false)
const autoConfigResult = ref(null)
const showAutoConfigConfirm = ref(false)
const autoConfigProgress = ref('')
let autoConfigPollTimer = null

const showSettingsModal = ref(false)
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settingsData = ref({ channel_id: null, model: '', prompt: '' })
const settingsChannels = ref([])
const settingsDefaultPrompt = ref('')
const settingsEditPrompt = ref(false)

async function detectConfig() {
  detectLoading.value = true
  try {
    const r = await api.detectAiFunctionConfig()
    detectResults.value = r.results
    detectSummary.value = r.summary
    const s = r.summary
    showToast(`检测完成：${s.ok} 正常 / ${s.warning} 警告 / ${s.error} 错误`, s.error === 0)
  } catch (e) {
    showToast(e.message, false)
  } finally {
    detectLoading.value = false
  }
}

function getDetectStatus(funcType) {
  return detectResults.value[funcType]?.status || 'unknown'
}

function getDetectMessage(funcType) {
  return detectResults.value[funcType]?.message || ''
}

async function runAutoConfig(apply = false) {
  autoConfigLoading.value = true
  autoConfigResult.value = null
  autoConfigProgress.value = '正在创建任务...'
  try {
    const r = await api.autoAiFunctionConfig(apply)
    const taskId = r.task_id
    autoConfigProgress.value = 'AI 正在决策中，请稍候（通常 1-5 分钟）...'

    const poll = async () => {
      try {
        const task = await api.getAutoConfigTask(taskId)
        if (task.status === 'completed') {
          if (autoConfigPollTimer) { clearInterval(autoConfigPollTimer); autoConfigPollTimer = null }
          autoConfigResult.value = task.result
          autoConfigLoading.value = false
          autoConfigProgress.value = ''
          if (apply) {
            showToast(`已应用 ${task.result.applied.length} 个功能配置`)
            await loadAll()
            detectResults.value = {}
            detectSummary.value = null
          } else {
            showToast(`AI 已生成 ${task.result.configured_count} 个配置建议`)
            showAutoConfigConfirm.value = true
          }
        } else if (task.status === 'failed') {
          if (autoConfigPollTimer) { clearInterval(autoConfigPollTimer); autoConfigPollTimer = null }
          autoConfigLoading.value = false
          autoConfigProgress.value = ''
          showToast(task.error || '一键配置失败', false)
        }
      } catch (e) {
        console.error('轮询任务状态失败', e)
      }
    }

    await poll()
    if (autoConfigLoading.value && !autoConfigPollTimer) {
      autoConfigPollTimer = setInterval(poll, 3000)
    }
  } catch (e) {
    autoConfigLoading.value = false
    autoConfigProgress.value = ''
    showToast(e.message, false)
  }
}

async function applyAutoConfig() {
  showAutoConfigConfirm.value = false
  if (autoConfigResult.value) {
    const suggestions = autoConfigResult.value.suggestions
    for (const [funcType, cfg] of Object.entries(suggestions)) {
      try {
        await api.updateAiFunctionConfig(funcType, {
          channel_id: cfg.channel_id,
          model: cfg.model,
          temperature: cfg.temperature,
        })
      } catch (e) {
        console.error(`应用 ${funcType} 配置失败`, e)
      }
    }
    showToast(`已应用 ${Object.keys(suggestions).length} 个功能配置`)
    await loadAll()
    detectResults.value = {}
    detectSummary.value = null
  }
}

async function loadSettings() {
  settingsLoading.value = true
  try {
    const r = await api.getAutoConfigSettings()
    settingsData.value = { ...r.settings }
    settingsChannels.value = r.channels || []
    settingsDefaultPrompt.value = r.default_prompt || ''
    settingsEditPrompt.value = !!(r.settings.prompt && r.settings.prompt.trim())
  } catch (e) {
    showToast(e.message, false)
  } finally {
    settingsLoading.value = false
  }
}

function openSettings() {
  showSettingsModal.value = true
  loadSettings()
}

async function saveSettings() {
  settingsSaving.value = true
  try {
    const payload = {
      channel_id: settingsData.value.channel_id || null,
      model: settingsData.value.model || '',
      prompt: settingsEditPrompt.value ? settingsData.value.prompt : '',
    }
    await api.updateAutoConfigSettings(payload)
    showToast('设置已保存')
    showSettingsModal.value = false
  } catch (e) {
    showToast(e.message, false)
  } finally {
    settingsSaving.value = false
  }
}

function getSettingsModels() {
  const ch = settingsChannels.value.find(c => c.id === settingsData.value.channel_id)
  return ch ? ch.models : []
}

function resetPromptToDefault() {
  settingsData.value.prompt = settingsDefaultPrompt.value
  settingsEditPrompt.value = true
}

// ---------- 渠道操作 ----------
function openCreate() {
  editingId.value = null
  form.value = defaultForm()
  modalTab.value = 'basic'
  showModal.value = true
}

function openEdit(ch) {
  editingId.value = ch.id
  form.value = {
    name: ch.name,
    type: ch.type,
    base_url: ch.base_url,
    api_key: '', // 不回显
    models: [...(ch.models || [])],
    default_model: ch.default_model,
    vision_model: ch.vision_model,
    weight: ch.weight,
    priority: ch.priority,
    enabled: ch.enabled,
    temperature: ch.temperature,
  }
  modalTab.value = 'basic'
  showModal.value = true
}

async function saveChannel() {
  if (!form.value.name.trim()) { showToast('请填写渠道名称', false); return }
  if (!form.value.base_url.trim()) { showToast('请填写 base_url', false); return }
  if (editingId.value === null && !form.value.api_key) { showToast('请填写 API Key', false); return }

  busy.value = true
  try {
    const payload = { ...form.value }
    if (editingId.value !== null && !payload.api_key) delete payload.api_key
    if (editingId.value === null) {
      await api.createAiChannel(payload)
      showToast('渠道已创建')
    } else {
      await api.updateAiChannel(editingId.value, payload)
      showToast('渠道已更新')
    }
    showModal.value = false
    await loadAll()
  } catch (e) {
    showToast(e.message, false)
  } finally {
    busy.value = false
  }
}

async function deleteChannel(ch) {
  if (!confirm(`确定删除渠道「${ch.name}」？此操作不可恢复。`)) return
  try {
    await api.deleteAiChannel(ch.id)
    showToast('已删除')
    await loadAll()
  } catch (e) {
    showToast(e.message, false)
  }
}

async function toggleChannel(ch) {
  try {
    await api.toggleAiChannel(ch.id)
    await loadAll()
  } catch (e) {
    showToast(e.message, false)
  }
}

async function testChannel(ch) {
  testingId.value = ch.id
  try {
    const r = await api.testAiChannel(ch.id)
    showToast(`连接正常：${r.reply}`)
    await loadAll()
  } catch (e) {
    showToast(`测试失败：${e.message}`, false)
    await loadAll()
  } finally {
    testingId.value = null
  }
}

async function fetchModels(ch) {
  fetchingModelsId.value = ch.id
  try {
    const r = await api.fetchAiChannelModels(ch.id)
    showToast(`识别到 ${r.models.length} 个模型`)
    if (editingId.value === ch.id) {
      form.value.models = r.models
      if (!form.value.default_model && r.models.length) form.value.default_model = r.models[0]
    }
    await loadAll()
  } catch (e) {
    showToast(`获取模型失败：${e.message}`, false)
  } finally {
    fetchingModelsId.value = null
  }
}

async function importFromOpencode() {
  try {
    const r = await api.opencodeImport()
    const p = r.providers[0]
    if (!p) { showToast('未找到可用 provider', false); return }
    openCreate()
    form.value.name = p.provider
    form.value.base_url = p.base_url
    form.value.api_key = p.api_key
    if (p.models && p.models.length) {
      form.value.models = p.models
      form.value.default_model = p.models[0]
    }
    showToast(`已导入 ${p.provider}，请确认后保存`)
  } catch (e) {
    showToast(e.message, false)
  }
}

// ---------- 计算属性 ----------
const typeLabel = computed(() => (type) => channelTypes.value[type]?.label || type)
const statusInfo = computed(() => (ch) => {
  if (!ch.enabled) return { text: '已禁用', cls: 'gray' }
  if (ch.status === 'active') return { text: '正常', cls: 'green' }
  if (ch.status === 'error') return { text: '异常', cls: 'red' }
  return { text: '未测试', cls: 'warn' }
})
const successRate = computed(() => (ch) => {
  if (ch.call_count === 0) return '—'
  return ((ch.success_count / ch.call_count) * 100).toFixed(0) + '%'
})

// ---------- 数据管理 ----------
const retentionDays = ref(30)
const retentionDefault = ref(30)
const retentionLoading = ref(false)
const retentionSaving = ref(false)
const cleanupLoading = ref(false)
const cleanupResult = ref(null)

async function loadDataSettings() {
  retentionLoading.value = true
  cleanupResult.value = null
  try {
    const r = await api.classroomRetention()
    retentionDays.value = r.days || 30
    retentionDefault.value = r.default || 30
  } catch (e) {
    showToast(e.message, false)
  } finally {
    retentionLoading.value = false
  }
}

async function saveRetention() {
  retentionSaving.value = true
  try {
    const days = Math.max(1, Math.min(365, parseInt(retentionDays.value) || 30))
    retentionDays.value = days
    await api.setClassroomRetention(days)
    showToast(`已设置保留 ${days} 天`)
  } catch (e) {
    showToast(e.message, false)
  } finally {
    retentionSaving.value = false
  }
}

async function runCleanup() {
  if (!confirm(`确定立即清理所有超过 ${retentionDays.value} 天的课堂历史消息？此操作不可恢复。`)) return
  cleanupLoading.value = true
  cleanupResult.value = null
  try {
    const r = await api.cleanupClassroom()
    cleanupResult.value = r
    showToast(`清理完成，共删除 ${r.total_deleted} 条消息`)
  } catch (e) {
    showToast(e.message, false)
  } finally {
    cleanupLoading.value = false
  }
}
</script>

<template>
  <div class="ai-channel-page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h2>{{ activeTab === 'channels' ? 'AI 渠道管理' : activeTab === 'functions' ? 'AI 功能配置' : '数据管理' }}</h2>
        <p class="sub">{{ activeTab === 'channels' ? '多渠道负载均衡 + 自动故障转移 · API Key 加密存储不回显' : activeTab === 'functions' ? '为每个功能指定使用的渠道和模型，精细化控制 AI 调用' : '课堂历史保留周期配置 · 手动清理过期数据' }}</p>
      </div>
      <div class="scope-switcher" v-if="activeTab === 'channels'">
        <button class="scope-btn" :class="{ active: channelScope === 'global' }" @click="channelScope='global'; loadAll()">🌐 全局通道</button>
        <button class="scope-btn" :class="{ active: channelScope === 'private' }" @click="channelScope='private'; loadAll()">👤 用户私有</button>
        <select v-if="channelScope === 'private'" v-model="selectedUserKey" @change="loadAll" class="user-select">
          <option value="">选择用户...</option>
          <option v-for="u in userList" :key="u.db_key" :value="u.db_key">{{ u.nickname || u.username }}</option>
        </select>
      </div>
      <div class="head-actions" v-if="activeTab === 'channels'">
        <button class="btn ghost" @click="importFromOpencode">从 OpenCode 导入</button>
        <button class="btn" @click="openCreate">+ 添加渠道</button>
      </div>
    </div>

    <!-- Tab 切换 -->
    <div class="tab-bar">
      <button class="tab-btn" :class="{ active: activeTab === 'channels' }" @click="activeTab = 'channels'">
        🔌 渠道管理
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'functions' }" @click="activeTab = 'functions'">
        ⚙️ 功能配置
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'data' }" @click="activeTab = 'data'; loadDataSettings()">
        🗄️ 数据管理
      </button>
    </div>

    <!-- ========== 渠道管理 Tab ========== -->
    <div v-if="activeTab === 'channels'">
    <!-- 统计卡片 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon blue">🔌</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.total }}</div>
          <div class="stat-label">渠道总数</div>
        </div>
        <div class="stat-sub">{{ stats.enabled }} 启用 / {{ stats.total - stats.enabled }} 禁用</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon green">✅</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.active }}</div>
          <div class="stat-label">正常运行</div>
        </div>
        <div class="stat-sub" v-if="stats.error">{{ stats.error }} 个异常</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon purple">📊</div>
        <div class="stat-body">
          <div class="stat-num">{{ stats.total_calls }}</div>
          <div class="stat-label">累计调用</div>
        </div>
        <div class="stat-sub">成功率 {{ stats.success_rate }}%</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon orange">🎯</div>
        <div class="stat-body">
          <div class="stat-num">{{ formatTokens(stats.total_tokens) }}</div>
          <div class="stat-label">Token 消耗</div>
        </div>
        <div class="stat-sub">所有渠道累计</div>
      </div>
    </div>

    <!-- 渠道列表 -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">渠道列表</span>
        <span class="panel-hint">优先级数字越小越优先 · 同优先级按权重分配</span>
      </div>

      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <span>加载中…</span>
      </div>

      <div v-else-if="channels.length === 0" class="empty-state">
        <div class="empty-icon">🔌</div>
        <div class="empty-title">还没有配置 AI 渠道</div>
        <div class="empty-desc">添加一个渠道后即可开始使用 AI 功能。支持 DeepSeek、通义千问、智谱、OpenAI 等所有 OpenAI 兼容服务。</div>
        <button class="btn" @click="openCreate">+ 添加第一个渠道</button>
      </div>

      <div v-else class="channel-grid">
        <div v-for="ch in channels" :key="ch.id" class="channel-card" :class="{ disabled: !ch.enabled }">
          <!-- 卡片头部 -->
          <div class="ch-head">
            <div class="ch-name-row">
              <span class="ch-name">{{ ch.name }}</span>
              <span class="tag" :class="statusInfo(ch).cls">{{ statusInfo(ch).text }}</span>
              <span class="tag blue">{{ typeLabel(ch.type) }}</span>
            </div>
            <div class="ch-actions">
              <button class="icon-btn" :disabled="testingId === ch.id" @click="testChannel(ch)" title="测试连接">
                <span v-if="testingId === ch.id" class="spinner mini"></span>
                <span v-else>🔌</span>
              </button>
              <button class="icon-btn" @click="openEdit(ch)" title="编辑">✏️</button>
              <button class="icon-btn danger" @click="deleteChannel(ch)" title="删除">🗑️</button>
            </div>
          </div>

          <!-- 卡片内容 -->
          <div class="ch-body">
            <div class="ch-field">
              <span class="ch-field-label">Base URL</span>
              <span class="ch-field-value mono">{{ ch.base_url || '—' }}</span>
            </div>
            <div class="ch-field">
              <span class="ch-field-label">API Key</span>
              <span class="ch-field-value">
                <span v-if="ch.has_key" class="key-dots">••••••••••••</span>
                <span v-else class="text-muted">未配置</span>
              </span>
            </div>
            <div class="ch-field">
              <span class="ch-field-label">默认模型</span>
              <span class="ch-field-value mono">{{ ch.default_model || '—' }}</span>
            </div>
            <div v-if="ch.vision_model" class="ch-field">
              <span class="ch-field-label">视觉模型</span>
              <span class="ch-field-value mono">{{ ch.vision_model }}</span>
            </div>
          </div>

          <!-- 模型标签 -->
          <div v-if="ch.models && ch.models.length" class="ch-models">
            <span class="ch-models-label">{{ ch.models.length }} 个模型</span>
            <div class="ch-model-tags">
              <span v-for="m in ch.models.slice(0, 4)" :key="m" class="model-tag">{{ m }}</span>
              <span v-if="ch.models.length > 4" class="model-tag more">+{{ ch.models.length - 4 }}</span>
            </div>
            <button class="btn ghost mini" :disabled="fetchingModelsId === ch.id" @click="fetchModels(ch)">
              <span v-if="fetchingModelsId === ch.id" class="spinner mini"></span>
              刷新模型
            </button>
          </div>
          <div v-else class="ch-models">
            <span class="text-muted">未获取模型列表</span>
            <button class="btn ghost mini" :disabled="fetchingModelsId === ch.id" @click="fetchModels(ch)">
              <span v-if="fetchingModelsId === ch.id" class="spinner mini"></span>
              获取模型
            </button>
          </div>

          <!-- 卡片底部：参数 + 统计 -->
          <div class="ch-foot">
            <div class="ch-param">
              <span class="param-label">优先级</span>
              <span class="param-value">{{ ch.priority }}</span>
            </div>
            <div class="ch-param">
              <span class="param-label">权重</span>
              <span class="param-value">{{ ch.weight }}</span>
            </div>
            <div class="ch-param">
              <span class="param-label">温度</span>
              <span class="param-value">{{ ch.temperature }}</span>
            </div>
            <div class="ch-param">
              <span class="param-label">调用</span>
              <span class="param-value">{{ ch.call_count }}</span>
            </div>
            <div class="ch-param">
              <span class="param-label">成功率</span>
              <span class="param-value" :class="{ ok: ch.call_count > 0 && ch.success_count / ch.call_count >= 0.9, bad: ch.call_count > 0 && ch.success_count / ch.call_count < 0.9 }">
                {{ successRate(ch) }}
              </span>
            </div>
            <label class="switch">
              <input type="checkbox" :checked="ch.enabled" @change="toggleChannel(ch)" />
              <span class="slider"></span>
            </label>
          </div>

          <!-- 错误信息 -->
          <div v-if="ch.status === 'error' && ch.last_error" class="ch-error">
            <span class="error-icon">⚠️</span>
            <span class="error-text">{{ ch.last_error }}</span>
          </div>
        </div>
      </div>
    </div>
    </div><!-- /渠道管理 Tab -->

    <!-- ========== 功能配置 Tab ========== -->
    <div v-if="activeTab === 'functions'" class="func-config-panel">
      <div class="func-config-hint">
        <span class="hint-icon">💡</span>
        <span>为每个功能指定使用的渠道和模型。未配置的功能将使用默认渠道（按优先级+权重自动选择）。</span>
      </div>

      <!-- 操作栏 -->
      <div class="func-toolbar">
        <div class="func-toolbar-left">
          <button class="btn ghost" :disabled="detectLoading" @click="detectConfig">
            <span v-if="detectLoading" class="spinner mini"></span>
            🔍 检测配置
          </button>
          <button class="btn" :disabled="autoConfigLoading" @click="runAutoConfig(false)">
            <span v-if="autoConfigLoading" class="spinner mini"></span>
            {{ autoConfigLoading ? 'AI 决策中…' : '⚡ 一键配置' }}
          </button>
          <button class="btn ghost icon-only" @click="openSettings" title="一键配置设置">
            ⚙️
          </button>
        </div>
        <div v-if="detectSummary" class="detect-summary">
          <span class="tag green">正常 {{ detectSummary.ok }}</span>
          <span v-if="detectSummary.warning" class="tag warn">警告 {{ detectSummary.warning }}</span>
          <span v-if="detectSummary.error" class="tag red">错误 {{ detectSummary.error }}</span>
        </div>
      </div>

      <!-- 进度提示 -->
      <div v-if="autoConfigProgress" class="auto-config-progress">
        <div class="spinner mini"></div>
        <span>{{ autoConfigProgress }}</span>
      </div>

      <div v-if="funcChannels.length === 0" class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">暂无可用渠道</div>
        <div class="empty-desc">请先在「渠道管理」中添加并启用至少一个渠道，获取模型列表后再配置功能。</div>
        <button class="btn" @click="activeTab = 'channels'">去添加渠道</button>
      </div>

      <div v-else class="func-grid">
        <div v-for="item in funcList" :key="item.key" class="func-card" :class="{ 'detect-error': getDetectStatus(item.key) === 'error', 'detect-warning': getDetectStatus(item.key) === 'warning', 'detect-ok': getDetectStatus(item.key) === 'ok' }">
          <div class="func-card-head">
            <div class="func-card-title">
              <span class="func-icon">{{ getFuncIcon(item.key) }}</span>
              <span class="func-name">{{ item.label }}</span>
              <span v-if="getDetectStatus(item.key) === 'ok'" class="detect-dot ok" title="配置正常">✓</span>
              <span v-else-if="getDetectStatus(item.key) === 'warning'" class="detect-dot warn" :title="getDetectMessage(item.key)">⚠</span>
              <span v-else-if="getDetectStatus(item.key) === 'error'" class="detect-dot error" :title="getDetectMessage(item.key)">✕</span>
            </div>
            <span v-if="item.model" class="tag green">已配置</span>
            <span v-else class="tag gray">默认</span>
          </div>
          <div v-if="getDetectMessage(item.key)" class="detect-msg" :class="getDetectStatus(item.key)">
            {{ getDetectMessage(item.key) }}
          </div>
          <div class="func-card-desc">{{ item.desc }}</div>

          <div class="func-config-row">
            <div class="func-config-field">
              <label>使用渠道</label>
              <select :value="item.channel_id || ''" @change="saveFuncConfig(item.key, 'channel_id', $event.target.value ? Number($event.target.value) : null)">
                <option value="">— 自动选择（默认）—</option>
                <option v-for="ch in funcChannels" :key="ch.id" :value="ch.id">{{ ch.name }}</option>
              </select>
            </div>
            <div class="func-config-field">
              <label>使用模型</label>
              <select :value="item.model || ''" :disabled="!item.channel_id" @change="saveFuncConfig(item.key, 'model', $event.target.value)">
                <option value="">— 渠道默认模型 —</option>
                <option v-for="m in getFuncModels(item.key)" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
          </div>

          <div class="func-config-row">
            <div class="func-config-field">
              <label>Temperature</label>
              <div class="temp-row">
                <input type="range" min="0" max="2" step="0.1" :value="item.temperature ?? 0.7"
                  @change="saveFuncConfig(item.key, 'temperature', Number($event.target.value))" class="range-input" />
                <span class="temp-value">{{ item.temperature ?? 0.7 }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 数据管理 Tab ========== -->
    <div v-if="activeTab === 'data'" class="data-manage-panel">
      <div class="func-config-hint">
        <span class="hint-icon">💡</span>
        <span>课堂历史消息按科目独立存储。设置保留天数后，超过期限的消息会在进入课堂时自动清理；也可手动立即清理。</span>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">课堂历史保留周期</span>
          <span class="panel-hint">默认 {{ retentionDefault }} 天，可设置 1-365 天</span>
        </div>
        <div class="panel-body">
          <div v-if="retentionLoading" class="loading-state">
            <div class="spinner"></div>
            <span>加载中…</span>
          </div>
          <div v-else class="retention-form">
            <div class="retention-row">
              <label class="retention-label">保留天数</label>
              <div class="retention-input-row">
                <input
                  type="number"
                  v-model.number="retentionDays"
                  min="1"
                  max="365"
                  class="retention-input"
                />
                <span class="retention-unit">天</span>
              </div>
            </div>
            <div class="retention-presets">
              <button
                v-for="d in [7, 14, 30, 60, 90, 180]"
                :key="d"
                class="preset-chip"
                :class="{ active: retentionDays === d }"
                @click="retentionDays = d"
              >
                {{ d }} 天
              </button>
            </div>
            <div class="retention-actions">
              <button class="btn" :disabled="retentionSaving" @click="saveRetention">
                <span v-if="retentionSaving" class="spinner mini"></span>
                保存设置
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">手动清理</span>
          <span class="panel-hint">立即清理所有科目中超过保留天数的历史消息</span>
        </div>
        <div class="panel-body">
          <div class="cleanup-row">
            <div class="cleanup-info">
              <div class="cleanup-title">清理过期课堂历史</div>
              <div class="cleanup-desc">将删除所有科目课堂中超过 {{ retentionDays }} 天的消息记录，此操作不可恢复。</div>
            </div>
            <button class="btn danger" :disabled="cleanupLoading" @click="runCleanup">
              <span v-if="cleanupLoading" class="spinner mini"></span>
              {{ cleanupLoading ? '清理中…' : '立即清理' }}
            </button>
          </div>

          <div v-if="cleanupResult" class="cleanup-result">
            <div class="cleanup-result-head">
              <span class="result-icon">✅</span>
              <span>清理完成</span>
              <span class="result-tag">共删除 {{ cleanupResult.total_deleted }} 条</span>
            </div>
            <div v-if="cleanupResult.details && cleanupResult.details.length" class="cleanup-details">
              <div v-for="d in cleanupResult.details" :key="d.conversation_id" class="cleanup-detail-item">
                <span class="detail-course">{{ d.course_name || '未分类' }}</span>
                <span class="detail-count">删除 {{ d.deleted }} 条</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加/编辑模态框 -->
    <div v-if="showModal" class="overlay" @click.self="showModal = false">
      <div class="modal wide">
        <div class="modal-head">
          <h3>{{ editingId === null ? '添加渠道' : '编辑渠道' }}</h3>
          <button class="icon-btn" @click="showModal = false">✕</button>
        </div>

        <!-- Tab 切换 -->
        <div class="modal-tabs">
          <button class="tab" :class="{ active: modalTab === 'basic' }" @click="modalTab = 'basic'">基本配置</button>
          <button class="tab" :class="{ active: modalTab === 'models' }" @click="modalTab = 'models'">模型设置</button>
          <button class="tab" :class="{ active: modalTab === 'advanced' }" @click="modalTab = 'advanced'">高级参数</button>
        </div>

        <!-- 基本配置 -->
        <div v-if="modalTab === 'basic'" class="modal-body">
          <!-- 预设快捷选择 -->
          <div class="form-group">
            <label>快捷预设</label>
            <div class="preset-grid">
              <button v-for="p in PRESETS" :key="p.name" class="preset-btn" @click="applyPreset(p)">
                {{ p.name }}
              </button>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>渠道名称 <span class="req">*</span></label>
              <input v-model="form.name" placeholder="如：DeepSeek 主力" />
            </div>
            <div class="form-group">
              <label>渠道类型</label>
              <select v-model="form.type">
                <option v-for="(t, key) in channelTypes" :key="key" :value="key">{{ t.label }}</option>
              </select>
            </div>
          </div>

          <div class="form-group">
            <label>Base URL <span class="req">*</span></label>
            <input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" class="mono" />
          </div>

          <div class="form-group">
            <label>API Key <span class="req">*</span></label>
            <input v-model="form.api_key" type="password"
                   :placeholder="editingId !== null ? '留空则不修改' : 'sk-...'"
                   class="mono" />
            <p class="form-hint">Key 仅存储在本地数据库，任何接口都不会回显明文</p>
          </div>
        </div>

        <!-- 模型设置 -->
        <div v-if="modalTab === 'models'" class="modal-body">
          <div class="form-group">
            <div class="field-head">
              <label>可用模型列表</label>
              <button class="btn ghost mini" @click="fetchModels({ id: editingId })">从 API 获取</button>
            </div>
            <div v-if="form.models.length" class="model-list-box">
              <div v-for="(m, i) in form.models" :key="i" class="model-list-item">
                <span class="mono">{{ m }}</span>
                <button class="icon-btn tiny" @click="form.models.splice(i, 1)">✕</button>
              </div>
            </div>
            <div class="model-add-row">
              <input v-model="newModel" placeholder="输入模型名后回车添加" @keyup.enter="addModel" />
              <button class="btn ghost mini" @click="addModel">添加</button>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>默认模型</label>
              <select v-model="form.default_model">
                <option value="">— 不指定 —</option>
                <option v-for="m in form.models" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>视觉模型（可选）</label>
              <select v-model="form.vision_model">
                <option value="">— 不使用 —</option>
                <option v-for="m in form.models" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
          </div>
        </div>

        <!-- 高级参数 -->
        <div v-if="modalTab === 'advanced'" class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label>优先级 <span class="hint-i" title="数字越小越优先，故障转移时按优先级顺序尝试">?</span></label>
              <input v-model.number="form.priority" type="number" min="1" max="10" />
            </div>
            <div class="form-group">
              <label>负载权重 <span class="hint-i" title="同优先级内按权重比例分配请求">?</span></label>
              <input v-model.number="form.weight" type="number" min="1" max="100" />
            </div>
          </div>

          <div class="form-group">
            <label>Temperature（采样温度）</label>
            <div class="slider-row">
              <input v-model.number="form.temperature" type="range" min="0" max="2" step="0.1" class="range-input" />
              <span class="range-value">{{ form.temperature }}</span>
            </div>
            <p class="form-hint">0 = 确定性输出，2 = 最大随机性，对话推荐 0.7</p>
          </div>

          <div class="form-group">
            <label class="checkbox-label">
              <input type="checkbox" v-model="form.enabled" />
              <span>启用此渠道</span>
            </label>
          </div>
        </div>

        <!-- 模态框底部 -->
        <div class="modal-actions">
          <button class="btn ghost" @click="showModal = false">取消</button>
          <button class="btn" :disabled="busy" @click="saveChannel">
            <span v-if="busy" class="spinner mini"></span>
            {{ editingId === null ? '创建' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 一键配置确认弹窗 -->
    <div v-if="showAutoConfigConfirm" class="overlay" @click.self="showAutoConfigConfirm = false">
      <div class="modal wide">
        <div class="modal-head">
          <h3>⚡ AI 一键配置建议</h3>
          <button class="icon-btn" @click="showAutoConfigConfirm = false">✕</button>
        </div>
        <div class="modal-body" style="max-height: 60vh; overflow-y: auto;">
          <div v-if="autoConfigResult" class="auto-config-result">
            <div class="auto-config-summary">
              <div class="summary-item">
                <span class="summary-num">{{ autoConfigResult.configured_count }}</span>
                <span class="summary-label">已生成配置</span>
              </div>
              <div class="summary-item">
                <span class="summary-num">{{ autoConfigResult.total_functions }}</span>
                <span class="summary-label">总功能数</span>
              </div>
              <div v-if="autoConfigResult.warnings?.length" class="summary-item warn">
                <span class="summary-num">{{ autoConfigResult.warnings.length }}</span>
                <span class="summary-label">警告</span>
              </div>
            </div>

            <div v-if="autoConfigResult.warnings?.length" class="warnings-box">
              <div class="warnings-title">⚠️ 警告信息</div>
              <ul>
                <li v-for="(w, i) in autoConfigResult.warnings" :key="i">{{ w }}</li>
              </ul>
            </div>

            <div class="config-list">
              <div v-for="(cfg, key) in autoConfigResult.suggestions" :key="key" class="config-item">
                <div class="config-item-head">
                  <span class="config-icon">{{ getFuncIcon(key) }}</span>
                  <span class="config-name">{{ funcConfig[key]?.label || key }}</span>
                </div>
                <div class="config-item-body">
                  <div class="config-field">
                    <span class="config-label">渠道</span>
                    <span class="config-value">{{ funcChannels.find(c => c.id === cfg.channel_id)?.name || cfg.channel_id }}</span>
                  </div>
                  <div class="config-field">
                    <span class="config-label">模型</span>
                    <span class="config-value mono">{{ cfg.model || '默认' }}</span>
                  </div>
                  <div class="config-field">
                    <span class="config-label">Temperature</span>
                    <span class="config-value">{{ cfg.temperature }}</span>
                  </div>
                </div>
                <div v-if="cfg.reason" class="config-reason">💡 {{ cfg.reason }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" @click="showAutoConfigConfirm = false">取消</button>
          <button class="btn" @click="applyAutoConfig">应用全部配置</button>
        </div>
      </div>
    </div>

    <!-- 设置弹窗 -->
    <div v-if="showSettingsModal" class="overlay" @click.self="showSettingsModal = false">
      <div class="modal">
        <div class="modal-head">
          <h3>⚙️ 一键配置设置</h3>
          <button class="icon-btn" @click="showSettingsModal = false">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="settingsLoading" class="loading-state">
            <div class="spinner"></div>
            <span>加载中…</span>
          </div>
          <div v-else class="settings-form">
            <div class="form-group">
              <label>决策用 AI 渠道</label>
              <select v-model="settingsData.channel_id" @change="settingsData.model = ''">
                <option :value="null">— 自动选择（默认渠道）—</option>
                <option v-for="ch in settingsChannels" :key="ch.id" :value="ch.id">{{ ch.name }}</option>
              </select>
              <p class="form-hint">用于执行"一键配置"决策的 AI 渠道。留空则使用默认渠道。</p>
            </div>

            <div class="form-group">
              <label>决策用 AI 模型</label>
              <select v-model="settingsData.model" :disabled="!settingsData.channel_id">
                <option value="">— 渠道默认模型 —</option>
                <option v-for="m in getSettingsModels()" :key="m" :value="m">{{ m }}</option>
              </select>
              <p class="form-hint">从所选渠道的模型列表中选择。建议使用推理能力较强的模型。</p>
            </div>

            <div class="form-group">
              <div class="form-group-head">
                <label>自定义提示词</label>
                <label class="checkbox-label">
                  <input type="checkbox" v-model="settingsEditPrompt" />
                  启用自定义
                </label>
              </div>
              <textarea
                v-model="settingsData.prompt"
                :disabled="!settingsEditPrompt"
                rows="10"
                placeholder="留空使用默认提示词。启用后可自定义 AI 决策逻辑。"
              ></textarea>
              <div class="form-actions">
                <button class="btn ghost small" @click="resetPromptToDefault" :disabled="!settingsEditPrompt">恢复默认提示词</button>
              </div>
              <p class="form-hint">提示词中可用变量：{channels_info}（渠道和模型价格信息）、{functions_info}（功能列表）。AI 需返回 JSON 格式的 configs。</p>
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" @click="showSettingsModal = false">取消</button>
          <button class="btn" :disabled="settingsSaving" @click="saveSettings">
            <span v-if="settingsSaving" class="spinner mini"></span>
            保存设置
          </button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast.msg" class="toast" :class="{ error: !toast.ok }">{{ toast.msg }}</div>
  </div>
</template>

<style scoped>
.ai-channel-page { padding: 0; }

/* 页头 */
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; gap: 16px; flex-wrap: wrap; }
.page-head h2 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.page-head .sub { font-size: 13px; color: var(--text-muted); }
.head-actions { display: flex; gap: 8px; }

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.stat-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; display: flex; align-items: center; gap: 12px;
  transition: transform .15s, box-shadow .15s; position: relative; overflow: hidden;
}
.stat-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-card); }
.stat-icon { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }
.stat-icon.blue { background: linear-gradient(135deg, #E9EEFB, #D6E0F8); }
.stat-icon.green { background: linear-gradient(135deg, #E8F5EC, #D0EBD8); }
.stat-icon.purple { background: linear-gradient(135deg, #F1EBF9, #E2D5F3); }
.stat-icon.orange { background: linear-gradient(135deg, #FFF3DC, #FFE4B8); }
.stat-body { flex: 1; min-width: 0; }
.stat-num { font-size: 24px; font-weight: 700; color: var(--text); line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat-label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.stat-sub { position: absolute; bottom: 8px; right: 12px; font-size: 11px; color: var(--text-muted); }

/* 面板 */
.panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.panel-head { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--border); background: var(--bg-sunken); }
.panel-title { font-size: 14px; font-weight: 600; }
.panel-hint { font-size: 12px; color: var(--text-muted); }

/* 加载 / 空状态 */
.loading-state, .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 48px 24px; gap: 12px; }
.empty-icon { font-size: 48px; opacity: .6; }
.empty-title { font-size: 16px; font-weight: 600; }
.empty-desc { font-size: 13px; color: var(--text-muted); text-align: center; max-width: 420px; }

/* 渠道卡片网格 */
.channel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; padding: 16px; }
.channel-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; transition: border-color .15s, box-shadow .15s; display: flex; flex-direction: column; gap: 12px;
}
.channel-card:hover { border-color: var(--primary); box-shadow: 0 2px 12px rgba(62,99,221,.1); }
.channel-card.disabled { opacity: .55; }
.channel-card.disabled:hover { border-color: var(--border); box-shadow: none; }

/* 卡片头部 */
.ch-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.ch-name-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.ch-name { font-size: 15px; font-weight: 600; }
.ch-actions { display: flex; gap: 4px; flex-shrink: 0; }

/* 图标按钮 */
.icon-btn {
  width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); display: flex; align-items: center; justify-content: center;
  font-size: 14px; cursor: pointer; transition: all .12s; padding: 0;
}
.icon-btn:hover { background: var(--primary-weak); border-color: var(--primary); }
.icon-btn.danger:hover { background: #FDECEA; border-color: var(--danger); }
.icon-btn.tiny { width: 24px; height: 24px; font-size: 12px; }
.icon-btn:disabled { opacity: .5; cursor: not-allowed; }

/* 卡片内容 */
.ch-body { display: flex; flex-direction: column; gap: 6px; }
.ch-field { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.ch-field-label { font-size: 11px; color: var(--text-muted); flex-shrink: 0; min-width: 60px; }
.ch-field-value { font-size: 12.5px; color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.mono { font-family: var(--font-mono); }
.key-dots { letter-spacing: 2px; color: var(--text-secondary); }
.text-muted { color: var(--text-muted); }

/* 模型区域 */
.ch-models { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 10px; border-top: 1px solid var(--border); }
.ch-models-label { font-size: 11px; color: var(--text-muted); }
.ch-model-tags { display: flex; gap: 4px; flex-wrap: wrap; flex: 1; min-width: 0; }
.model-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 6px; background: var(--bg-sunken);
  color: var(--text-secondary); font-family: var(--font-mono); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.model-tag.more { background: var(--primary-weak); color: var(--primary); }

/* 卡片底部 */
.ch-foot { display: flex; align-items: center; gap: 10px; padding-top: 10px; border-top: 1px solid var(--border); flex-wrap: wrap; }
.ch-param { display: flex; flex-direction: column; gap: 1px; }
.param-label { font-size: 10px; color: var(--text-muted); }
.param-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.param-value.ok { color: var(--success); }
.param-value.bad { color: var(--danger); }

/* 开关 */
.switch { position: relative; display: inline-block; width: 38px; height: 22px; margin-left: auto; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: var(--border); border-radius: 22px; transition: .2s; }
.slider:before { content: ''; position: absolute; height: 16px; width: 16px; left: 3px; bottom: 3px; background: #fff; border-radius: 50%; transition: .2s; box-shadow: 0 1px 3px rgba(0,0,0,.2); }
.switch input:checked + .slider { background: var(--primary); }
.switch input:checked + .slider:before { transform: translateX(16px); }

/* 错误信息 */
.ch-error { display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; background: #FDECEA; border-radius: 8px; font-size: 12px; color: var(--danger); }
.error-text { word-break: break-all; line-height: 1.4; }

/* 模态框 */
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.modal-head h3 { font-size: 17px; font-weight: 600; }
.modal.wide { width: 520px; }

/* Tab */
.modal-tabs { display: flex; gap: 4px; margin-bottom: 16px; padding: 4px; background: var(--bg-sunken); border-radius: 10px; }
.tab { flex: 1; padding: 8px 12px; border: none; background: transparent; border-radius: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; transition: all .15s; font-weight: 500; }
.tab:hover { color: var(--text); }
.tab.active { background: var(--bg-card); color: var(--primary); box-shadow: 0 1px 3px rgba(0,0,0,.08); }

/* 表单 */
.modal-body { display: flex; flex-direction: column; gap: 14px; }
.form-row { display: flex; gap: 12px; }
.form-row .form-group { flex: 1; }
.form-group { display: flex; flex-direction: column; gap: 5px; }
.form-group label { font-size: 12px; color: var(--text-secondary); font-weight: 500; }
.form-group .req { color: var(--danger); }
.form-group input, .form-group select { width: 100%; }
.form-hint { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.hint-i { display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px; border-radius: 50%; background: var(--bg-sunken); color: var(--text-muted); font-size: 10px; cursor: help; }
.field-head { display: flex; justify-content: space-between; align-items: center; }

/* 预设 */
.preset-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.preset-btn {
  padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); font-size: 12px; cursor: pointer; transition: all .12s;
}
.preset-btn:hover { border-color: var(--primary); background: var(--primary-weak); color: var(--primary); }

/* 模型列表 */
.model-list-box { max-height: 160px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
.model-list-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
.model-list-item:last-child { border-bottom: none; }
.model-add-row { display: flex; gap: 6px; }
.model-add-row input { flex: 1; }

/* 滑块 */
.slider-row { display: flex; align-items: center; gap: 12px; }
.range-input { flex: 1; height: auto; padding: 0; accent-color: var(--primary); }
.range-value { font-size: 14px; font-weight: 600; color: var(--primary); min-width: 30px; text-align: center; }

/* 复选框标签 */
.checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--text); }
.checkbox-label input { width: auto; height: auto; }

/* 小 spinner */
.spinner.mini { width: 12px; height: 12px; border-width: 2px; }

/* Tab 切换 */
.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; padding: 4px; background: var(--bg-sunken); border-radius: 10px; }
.tab-btn { flex: 0 0 auto; padding: 8px 18px; border: none; background: transparent; border-radius: 7px; font-size: 13px; color: var(--text-secondary); cursor: pointer; transition: all .15s; font-weight: 500; }
.tab-btn:hover { color: var(--text); }
.tab-btn.active { background: var(--bg-card); color: var(--primary); box-shadow: 0 1px 3px rgba(0,0,0,.08); }

/* 功能配置 */
.func-config-panel { }
.func-config-hint { display: flex; align-items: flex-start; gap: 8px; padding: 12px 16px; background: var(--primary-weak); border-radius: 10px; margin-bottom: 16px; font-size: 12.5px; color: var(--primary); line-height: 1.5; }
.hint-icon { font-size: 16px; flex-shrink: 0; }

.func-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.func-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; transition: border-color .15s, box-shadow .15s; }
.func-card:hover { border-color: var(--primary); box-shadow: 0 2px 10px rgba(62,99,221,.08); }
.func-card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.func-card-title { display: flex; align-items: center; gap: 8px; }
.func-icon { font-size: 18px; }
.func-name { font-size: 14px; font-weight: 600; }
.func-card-desc { font-size: 12px; color: var(--text-muted); margin-bottom: 14px; line-height: 1.5; }

.func-config-row { display: flex; gap: 10px; margin-bottom: 10px; }
.func-config-field { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.func-config-field label { font-size: 11px; color: var(--text-secondary); font-weight: 500; }
.func-config-field select { width: 100%; height: 32px; font-size: 12px; padding: 0 8px; }
.func-config-field select:disabled { background: var(--bg-sunken); cursor: not-allowed; color: var(--text-muted); }

.temp-row { display: flex; align-items: center; gap: 10px; }
.range-input { flex: 1; height: auto; padding: 0; accent-color: var(--primary); }
.temp-value { font-size: 13px; font-weight: 600; color: var(--primary); min-width: 28px; text-align: center; }

/* 功能配置工具栏 */
.func-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.func-toolbar-left { display: flex; gap: 8px; align-items: center; }
.btn.icon-only { padding: 8px 12px; font-size: 16px; }
.detect-summary { display: flex; gap: 6px; }
.tag.warn { background: #fff7e6; color: #d48806; border-color: #ffd591; }
.tag.red { background: #fff1f0; color: #cf1322; border-color: #ffa39e; }

/* 一键配置进度提示 */
.auto-config-progress { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: var(--primary-weak); border-radius: 8px; margin-bottom: 16px; font-size: 13px; color: var(--primary); }

/* 检测状态 */
.func-card.detect-ok { border-color: #b7eb8f; }
.func-card.detect-warning { border-color: #ffd591; }
.func-card.detect-error { border-color: #ffa39e; }
.detect-dot { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; font-size: 11px; font-weight: 700; }
.detect-dot.ok { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.detect-dot.warn { background: #fffbe6; color: #faad14; border: 1px solid #ffe58f; }
.detect-dot.error { background: #fff1f0; color: #f5222d; border: 1px solid #ffa39e; }
.detect-msg { font-size: 11.5px; padding: 6px 10px; border-radius: 6px; margin-bottom: 8px; line-height: 1.4; }
.detect-msg.ok { background: #f6ffed; color: #389e0d; }
.detect-msg.warning { background: #fffbe6; color: #d48806; }
.detect-msg.error { background: #fff1f0; color: #cf1322; }

/* 一键配置结果 */
.auto-config-result { }
.auto-config-summary { display: flex; gap: 16px; margin-bottom: 16px; padding: 14px; background: var(--bg-sunken); border-radius: 10px; }
.summary-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.summary-item.warn .summary-num { color: #faad14; }
.summary-num { font-size: 24px; font-weight: 700; color: var(--primary); }
.summary-label { font-size: 11px; color: var(--text-muted); }
.warnings-box { background: #fffbe6; border: 1px solid #ffe58f; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.warnings-title { font-size: 12px; font-weight: 600; color: #d48806; margin-bottom: 6px; }
.warnings-box ul { margin: 0; padding-left: 18px; font-size: 12px; color: #874d00; line-height: 1.6; }
.config-list { display: flex; flex-direction: column; gap: 10px; }
.config-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.config-item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.config-icon { font-size: 16px; }
.config-name { font-size: 13px; font-weight: 600; }
.config-item-body { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 6px; }
.config-field { display: flex; flex-direction: column; gap: 2px; }
.config-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.config-value { font-size: 12px; font-weight: 500; }
.config-value.mono { font-family: 'SF Mono', 'Consolas', monospace; font-size: 11.5px; }
.config-reason { font-size: 11.5px; color: var(--text-secondary); background: var(--bg-sunken); padding: 6px 10px; border-radius: 6px; line-height: 1.5; }

/* 设置表单 */
.settings-form { display: flex; flex-direction: column; gap: 16px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 12px; font-weight: 600; color: var(--text); }
.form-group select, .form-group textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; background: var(--bg-card); color: var(--text); font-family: inherit; }
.form-group textarea { resize: vertical; font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; line-height: 1.6; }
.form-group select:disabled, .form-group textarea:disabled { background: var(--bg-sunken); cursor: not-allowed; color: var(--text-muted); }
.form-hint { font-size: 11px; color: var(--text-muted); margin: 0; line-height: 1.5; }
.form-group-head { display: flex; justify-content: space-between; align-items: center; }
.form-actions { display: flex; justify-content: flex-end; margin-top: 4px; }
.btn.small { padding: 5px 12px; font-size: 12px; }

/* 响应式 */
@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .func-grid { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .stat-grid { grid-template-columns: 1fr; }
  .channel-grid { grid-template-columns: 1fr; }
  .modal.wide { width: 92vw; }
  .preset-grid { grid-template-columns: repeat(2, 1fr); }
  .form-row { flex-direction: column; }
  .tab-btn { padding: 8px 12px; font-size: 12px; }
  .func-config-row { flex-direction: column; }
}

/* 数据管理 */
.data-manage-panel { display: flex; flex-direction: column; gap: 16px; }
.panel-body { padding: 18px; }
.retention-form { display: flex; flex-direction: column; gap: 16px; }
.retention-row { display: flex; align-items: center; gap: 16px; }
.retention-label { font-size: 14px; font-weight: 500; color: var(--text); min-width: 80px; }
.retention-input-row { display: flex; align-items: center; gap: 8px; }
.retention-input {
  width: 100px; height: 36px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: 8px;
  font-size: 14px; background: var(--bg-card); color: var(--text);
}
.retention-input:focus { outline: none; border-color: var(--primary); }
.retention-unit { font-size: 14px; color: var(--text-secondary); }
.retention-presets { display: flex; gap: 6px; flex-wrap: wrap; }
.preset-chip {
  padding: 6px 14px; border: 1px solid var(--border); border-radius: 20px;
  background: var(--bg-card); font-size: 12px; color: var(--text-secondary);
  cursor: pointer; transition: all .15s;
}
.preset-chip:hover { border-color: var(--primary); color: var(--primary); }
.preset-chip.active { background: var(--primary-weak); border-color: var(--primary); color: var(--primary); font-weight: 500; }
.retention-actions { display: flex; justify-content: flex-end; }

.cleanup-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
.cleanup-info { flex: 1; min-width: 200px; }
.cleanup-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.cleanup-desc { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.btn.danger {
  background: var(--danger); color: #fff; border: none;
  padding: 8px 18px; border-radius: 8px; font-size: 13px;
  cursor: pointer; transition: opacity .15s;
}
.btn.danger:hover { opacity: .9; }
.btn.danger:disabled { opacity: .5; cursor: not-allowed; }

.cleanup-result {
  margin-top: 16px; padding: 14px 16px;
  background: var(--success-weak); border: 1px solid var(--success);
  border-radius: 10px;
}
.cleanup-result-head {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: var(--success-deep);
  margin-bottom: 10px;
}
.result-icon { font-size: 16px; }
.result-tag {
  margin-left: auto; font-size: 12px; font-weight: 500;
  background: var(--success); color: #fff; padding: 2px 10px; border-radius: 12px;
}
.cleanup-details { display: flex; flex-direction: column; gap: 4px; }
.cleanup-detail-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 4px 0; font-size: 12px; color: var(--text-secondary);
  border-bottom: 1px solid rgba(0,0,0,.05);
}
.cleanup-detail-item:last-child { border-bottom: none; }
.detail-course { font-weight: 500; }
.detail-count { color: var(--text-muted); }

/* 通道范围切换器 */
.scope-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 16px;
}
.scope-btn {
  padding: 6px 14px;
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.2s;
}
.scope-btn:hover {
  border-color: var(--accent);
}
.scope-btn.active {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}
.user-select {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
}
</style>
