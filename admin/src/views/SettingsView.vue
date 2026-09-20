<template>
  <div class="settings-page">
    <h2>⚙️ 系统设置</h2>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>

    <div v-else class="settings-grid">
      <!-- 后端连接配置 -->
      <div class="settings-card">
        <h3>🔗 后端连接</h3>
        <div class="setting-row">
          <label>后端地址</label>
          <div class="input-group">
            <input v-model="backendUrl" class="form-input" placeholder="http://192.168.3.4:8000" />
            <button class="btn ghost mini" @click="copyBackendUrl">复制</button>
            <button class="btn primary mini" :disabled="testing" @click="testConnection">
              {{ testing ? '检测中...' : '检测连接' }}
            </button>
          </div>
          <p class="hint">App 端「我的 → 设置」中填写此地址</p>
          <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
            {{ testResult.ok ? '✅ 连接正常' : '❌ 连接失败' }}
            <span v-if="testResult.latency" class="latency">（{{ testResult.latency }}ms）</span>
            <span v-if="testResult.error" class="error-msg">{{ testResult.error }}</span>
          </div>
        </div>
        <div class="setting-row">
          <label>管理台地址</label>
          <div class="input-group">
            <input :value="settings?.system?.admin_url" class="form-input" readonly />
            <button class="btn ghost mini" @click="copyText(settings?.system?.admin_url)">复制</button>
          </div>
        </div>
        <div class="setting-row">
          <label>API 文档</label>
          <div class="input-group">
            <input :value="settings?.system?.docs_url" class="form-input" readonly />
            <button class="btn ghost mini" @click="openUrl(settings?.system?.docs_url)">打开</button>
          </div>
        </div>
      </div>

      <!-- 认证状态 -->
      <div class="settings-card">
        <h3>🔐 认证状态</h3>
        <div class="status-badge" :class="settings?.auth?.enabled ? 'on' : 'off'">
          {{ settings?.auth?.enabled ? '认证已开启' : '认证已关闭' }}
        </div>
        <p class="auth-note">{{ settings?.auth?.note }}</p>
        <div v-if="settings?.auth?.enabled" class="setting-row">
          <label>用户名</label>
          <input :value="settings?.auth?.username" class="form-input" readonly />
        </div>
        <div class="setting-row">
          <label>App 认证配置</label>
          <p class="hint">
            {{ settings?.auth?.enabled ? 'App 需填写用户名和密码' : 'App 无需填写用户名和密码，留空即可' }}
          </p>
        </div>
      </div>

      <!-- 系统统计 -->
      <div class="settings-card">
        <h3>📊 数据统计</h3>
        <div class="stats-grid">
          <div class="stat-item">
            <span class="stat-value">{{ settings?.stats?.courses }}</span>
            <span class="stat-label">科目</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ settings?.stats?.knowledge_nodes }}</span>
            <span class="stat-label">知识点</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ settings?.stats?.questions }}</span>
            <span class="stat-label">题目</span>
          </div>
        </div>
      </div>

      <!-- 系统信息 -->
      <div class="settings-card">
        <h3>💻 系统信息</h3>
        <div class="info-list">
          <div class="info-row">
            <span class="info-label">版本</span>
            <span class="info-value">{{ settings?.system?.version }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">数据库</span>
            <span class="info-value">{{ settings?.database?.type }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">数据库路径</span>
            <span class="info-value mono">{{ settings?.database?.path }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Python</span>
            <span class="info-value">{{ settings?.runtime?.python_version }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">平台</span>
            <span class="info-value">{{ settings?.runtime?.platform }}</span>
          </div>
        </div>
      </div>

      <!-- App 配置指引 -->
      <div class="settings-card full-width">
        <h3>📱 App 配置指引</h3>
        <ol class="guide-list">
          <li>打开 App → 底部「我的」→「设置」</li>
          <li>后端地址填写：<code>{{ backendUrl }}</code> <button class="btn ghost mini" @click="copyBackendUrl">复制</button></li>
          <li v-if="settings?.auth?.enabled">认证用户名：<code>admin</code>，认证密码：<code>ailearn2026</code></li>
          <li v-else>认证用户名和密码<strong>留空即可</strong>（当前认证已关闭）</li>
          <li>点击保存，提示「连接正常」即配置成功</li>
        </ol>
        <div class="tip-box">
          <strong>💡 提示：</strong>手机和电脑需连接同一个 WiFi。若电脑 IP 变化，需更新此地址。
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api'

const loading = ref(true)
const error = ref(null)
const settings = ref(null)
const backendUrl = ref('')
const testing = ref(false)
const testResult = ref(null)

onMounted(async () => {
  try {
    settings.value = await api.getSettings()
    backendUrl.value = settings.value?.system?.backend_url || ''
    loading.value = false
  } catch (e) {
    error.value = '加载设置失败: ' + e.message
    loading.value = false
  }
})

async function testConnection() {
  if (!backendUrl.value) {
    testResult.value = { ok: false, error: '请先填写后端地址' }
    return
  }
  testing.value = true
  testResult.value = null
  const start = Date.now()
  try {
    const url = backendUrl.value.replace(/\/$/, '') + '/api/v1/settings/test'
    const resp = await fetch(url, { method: 'POST' })
    const latency = Date.now() - start
    if (resp.ok) {
      testResult.value = { ok: true, latency }
    } else {
      testResult.value = { ok: false, error: `HTTP ${resp.status}` }
    }
  } catch (e) {
    testResult.value = { ok: false, error: e.message }
  } finally {
    testing.value = false
  }
}

function copyBackendUrl() {
  copyText(backendUrl.value)
}

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => {
    alert('已复制到剪贴板')
  }).catch(() => {
    // 降级方案
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    alert('已复制到剪贴板')
  })
}

function openUrl(url) {
  if (url) window.open(url, '_blank')
}
</script>

<style scoped>
.settings-page {
  padding: 20px;
}

.settings-page h2 {
  margin: 0 0 20px 0;
  font-size: 22px;
}

.loading, .error {
  padding: 40px;
  text-align: center;
  color: #666;
}

.error {
  color: #e74c3c;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.settings-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #e8e8e8;
}

.settings-card.full-width {
  grid-column: 1 / -1;
}

.settings-card h3 {
  margin: 0 0 16px 0;
  font-size: 16px;
  color: #333;
}

.setting-row {
  margin-bottom: 14px;
}

.setting-row:last-child {
  margin-bottom: 0;
}

.setting-row label {
  display: block;
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
  font-weight: 500;
}

.input-group {
  display: flex;
  gap: 8px;
}

.input-group .form-input {
  flex: 1;
}

.hint {
  font-size: 12px;
  color: #999;
  margin: 4px 0 0 0;
}

.test-result {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
}

.test-result.ok {
  background: #e8f5e9;
  color: #2e7d32;
}

.test-result.fail {
  background: #ffebee;
  color: #c62828;
}

.test-result .latency {
  color: #666;
  font-weight: 400;
  margin-left: 4px;
}

.test-result .error-msg {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  font-weight: 400;
}

.status-badge {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.status-badge.on {
  background: #e8f5e9;
  color: #2e7d32;
}

.status-badge.off {
  background: #fff3e0;
  color: #e65100;
}

.auth-note {
  font-size: 13px;
  color: #666;
  margin: 0 0 12px 0;
  line-height: 1.5;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  text-align: center;
}

.stat-item {
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.stat-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: #3e63dd;
}

.stat-label {
  display: block;
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.info-label {
  font-size: 13px;
  color: #999;
  flex-shrink: 0;
}

.info-value {
  font-size: 13px;
  color: #333;
  text-align: right;
  word-break: break-all;
}

.info-value.mono {
  font-family: monospace;
  font-size: 12px;
}

.guide-list {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
  font-size: 14px;
  color: #333;
}

.guide-list code {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  margin: 0 4px;
}

.tip-box {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fff8e1;
  border-radius: 8px;
  font-size: 13px;
  color: #795548;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
