<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import CoursesView from './views/CoursesView.vue'
import ScheduleView from './views/ScheduleView.vue'
import ExceptionsView from './views/ExceptionsView.vue'
import AiSettingsView from './views/AiSettingsView.vue'
import AiCallsView from './views/AiCallsView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import ReviewView from './views/ReviewView.vue'
import MessagesView from './views/MessagesView.vue'
import LogsView from './views/LogsView.vue'
import StatsView from './views/StatsView.vue'
import QuizImportView from './views/QuizImportView.vue'
import QuizGeneratorView from './views/QuizGeneratorView.vue'
import KnowledgeGraphView from './views/KnowledgeGraphView.vue'
import MathVerifierView from './views/MathVerifierView.vue'
import WrongBookView from './views/WrongBookView.vue'
import SettingsView from './views/SettingsView.vue'
import UserManageView from './views/UserManageView.vue'
import TaskFloatingPanel from './components/TaskFloatingPanel.vue'
import { api, setCurrentUserKey, getCurrentUserKey } from './api.js'

const tab = ref('courses')
const sidebarOpen = ref(false)
const isMobile = ref(false)
const backendUrl = window.location.origin

// 用户切换
const userList = ref([])
const currentUserKey = ref(getCurrentUserKey())
const userSwitcherOpen = ref(false)

const tabs = [
  { key: 'courses', label: '科目', icon: '📚' },
  { key: 'schedule', label: '周课表', icon: '📅' },
  { key: 'exceptions', label: '日期例外', icon: '⚠️' },
  { key: 'knowledge', label: '知识树', icon: '🌳' },
  { key: 'knowledge-graph', label: '知识图谱', icon: '🕸️' },
  { key: 'math-verifier', label: '数学验证', icon: '🔢' },
  { key: 'wrong-book', label: '错题本', icon: '📕' },
  { key: 'quiz-import', label: '题目导入', icon: '📥' },
  { key: 'quiz-generator', label: '智能出题', icon: '🤖' },
  { key: 'review', label: '复习队列', icon: '🔄' },
  { key: 'messages', label: '课堂消息', icon: '💬' },
  { key: 'ai', label: 'AI 设置', icon: '🤖' },
  { key: 'ai-calls', label: '调用记录', icon: '📋' },
  { key: 'logs', label: '日志中心', icon: '📜' },
  { key: 'stats', label: '数据看板', icon: '📊' },
  { key: 'users', label: '用户管理', icon: '👥' },
  { key: 'settings', label: '系统设置', icon: '⚙️' },
]

async function loadUsers() {
  try {
    userList.value = await api.adminUsers()
  } catch (e) {
    console.error('加载用户列表失败:', e)
  }
}

function switchUser(dbKey) {
  currentUserKey.value = dbKey
  setCurrentUserKey(dbKey)
  userSwitcherOpen.value = false
  // 触发当前视图刷新（通过改变 key 强制重新渲染）
  const currentTab = tab.value
  tab.value = ''
  setTimeout(() => { tab.value = currentTab }, 10)
  if (isMobile.value) sidebarOpen.value = false
}

function getCurrentUserLabel() {
  const u = userList.value.find(u => u.db_key === currentUserKey.value)
  return u ? u.nickname || u.username : currentUserKey.value
}

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
  if (!isMobile.value) sidebarOpen.value = false
}

function switchTab(key) {
  tab.value = key
  if (isMobile.value) sidebarOpen.value = false
}

function toggleUserSwitcher() {
  userSwitcherOpen.value = !userSwitcherOpen.value
}

// 点击外部关闭下拉
function handleClickOutside(e) {
  if (!e.target.closest('.user-switcher')) {
    userSwitcherOpen.value = false
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  window.addEventListener('click', handleClickOutside)
  loadUsers()
})
onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  window.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="layout">
    <!-- 移动端顶栏 -->
    <header v-if="isMobile" class="mobile-header">
      <button class="menu-btn" @click="sidebarOpen = !sidebarOpen" aria-label="菜单">
        <span v-if="!sidebarOpen">☰</span>
        <span v-else>✕</span>
      </button>
      <span class="mobile-title">ai学 管理台</span>
    </header>

    <!-- 遮罩层 -->
    <div v-if="isMobile && sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false"></div>

    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand">ai学<span>管理台</span></div>

      <!-- 用户切换器 -->
      <div class="user-switcher">
        <button class="user-switcher-btn" @click.stop="toggleUserSwitcher">
          <span class="user-avatar">👤</span>
          <span class="user-label">{{ getCurrentUserLabel() }}</span>
          <span class="user-arrow">{{ userSwitcherOpen ? '▲' : '▼' }}</span>
        </button>
        <div v-if="userSwitcherOpen" class="user-dropdown">
          <div class="user-dropdown-title">切换查看用户</div>
          <button
            v-for="u in userList.filter(u => u.is_active)"
            :key="u.id"
            class="user-dropdown-item"
            :class="{ active: u.db_key === currentUserKey }"
            @click="switchUser(u.db_key)"
          >
            <span class="user-dot" :class="{ admin: u.role === 'admin' }"></span>
            <span class="user-name">{{ u.nickname || u.username }}</span>
            <span v-if="u.role === 'admin'" class="user-role-badge">管理员</span>
          </button>
          <div class="user-dropdown-footer">
            <button class="user-manage-link" @click="switchTab('users'); userSwitcherOpen = false">
              ⚙️ 管理用户
            </button>
          </div>
        </div>
      </div>

      <nav>
        <button v-for="t in tabs" :key="t.key"
          class="nav-item" :class="{ active: tab === t.key }"
          @click="switchTab(t.key)">
          <span class="nav-icon">{{ t.icon }}</span>
          <span class="nav-label">{{ t.label }}</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <div class="backend-info">
          <span class="backend-label">后端</span>
          <span class="backend-url" :title="backendUrl">{{ backendUrl.replace('http://', '').replace('https://', '') }}</span>
        </div>
        <span class="version">v0.1.0 · 多用户版</span>
      </div>
    </aside>

    <main class="content">
      <CoursesView v-if="tab === 'courses'" />
      <ScheduleView v-else-if="tab === 'schedule'" />
      <ExceptionsView v-else-if="tab === 'exceptions'" />
      <KnowledgeView v-else-if="tab === 'knowledge'" />
      <KnowledgeGraphView v-else-if="tab === 'knowledge-graph'" />
      <MathVerifierView v-else-if="tab === 'math-verifier'" />
      <WrongBookView v-else-if="tab === 'wrong-book'" />
      <QuizImportView v-else-if="tab === 'quiz-import'" />
      <QuizGeneratorView v-else-if="tab === 'quiz-generator'" />
      <ReviewView v-else-if="tab === 'review'" />
      <MessagesView v-else-if="tab === 'messages'" />
      <AiSettingsView v-else-if="tab === 'ai'" />
      <AiCallsView v-else-if="tab === 'ai-calls'" />
      <LogsView v-else-if="tab === 'logs'" />
      <StatsView v-else-if="tab === 'stats'" />
      <UserManageView v-else-if="tab === 'users'" @user-changed="loadUsers" />
      <SettingsView v-else-if="tab === 'settings'" />
    </main>

    <!-- 全局任务悬浮窗 -->
    <TaskFloatingPanel />
  </div>
</template>

<style scoped>
.layout { display: flex; min-height: 100vh; }

.mobile-header {
  display: none;
  position: fixed; top: 0; left: 0; right: 0;
  height: 48px; background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  align-items: center; padding: 0 12px; z-index: 150;
}
.menu-btn {
  background: none; border: none; font-size: 20px;
  padding: 4px 8px; color: var(--text); cursor: pointer;
}
.mobile-title { font-size: 15px; font-weight: 600; margin-left: 8px; }

.sidebar-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,.3);
  z-index: 140; animation: fadeIn .15s ease;
}

.sidebar {
  width: 180px; background: var(--bg-card);
  border-right: 1px solid var(--border);
  padding: 20px 12px; flex-shrink: 0;
  display: flex; flex-direction: column;
  transition: transform .2s ease;
}
.brand { font-size: 18px; font-weight: 600; margin-bottom: 12px; padding: 0 8px; }
.brand span { font-size: 12px; color: var(--text-muted); margin-left: 6px; font-weight: 400; }

/* 用户切换器 */
.user-switcher {
  position: relative;
  margin-bottom: 16px;
  padding: 0 4px;
}
.user-switcher-btn {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 8px 10px;
  background: var(--bg-sunken);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px; color: var(--text);
  transition: all .15s ease;
}
.user-switcher-btn:hover {
  background: var(--primary-weak);
  border-color: var(--primary);
}
.user-avatar { font-size: 16px; }
.user-label { flex: 1; text-align: left; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-arrow { font-size: 10px; color: var(--text-muted); }

.user-dropdown {
  position: absolute; top: 100%; left: 4px; right: 4px;
  margin-top: 4px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,.15);
  z-index: 200;
  overflow: hidden;
}
.user-dropdown-title {
  padding: 8px 12px;
  font-size: 11px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border);
  background: var(--bg-sunken);
}
.user-dropdown-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 8px 12px;
  background: none; border: none;
  cursor: pointer;
  font-size: 13px; color: var(--text);
  text-align: left;
  transition: background .15s ease;
}
.user-dropdown-item:hover { background: var(--bg-sunken); }
.user-dropdown-item.active { background: var(--primary-weak); color: var(--primary); }
.user-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--text-muted); flex-shrink: 0;
}
.user-dot.admin { background: var(--primary); }
.user-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-role-badge {
  font-size: 10px; padding: 1px 6px;
  background: var(--primary-weak); color: var(--primary);
  border-radius: 4px; flex-shrink: 0;
}
.user-dropdown-footer {
  border-top: 1px solid var(--border);
  padding: 4px;
}
.user-manage-link {
  display: block; width: 100%;
  padding: 8px 12px;
  background: none; border: none;
  cursor: pointer;
  font-size: 12px; color: var(--text-muted);
  text-align: left;
  border-radius: 6px;
}
.user-manage-link:hover { background: var(--bg-sunken); color: var(--text); }

nav { flex: 1; overflow-y: auto; }
.nav-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%; text-align: left;
  padding: 10px 12px; margin-bottom: 4px;
  border: none; border-radius: 8px;
  background: transparent; color: var(--text-secondary);
  font-size: 14px; transition: all .15s ease;
}
.nav-item:hover { background: var(--bg-sunken); }
.nav-item.active { background: var(--primary-weak); color: var(--primary); font-weight: 500; }
.nav-icon { font-size: 15px; width: 20px; text-align: center; }

.sidebar-footer { padding: 10px 12px; border-top: 1px solid var(--border); margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.sidebar-footer .backend-info { display: flex; align-items: center; gap: 6px; font-size: 11px; }
.sidebar-footer .backend-label { color: var(--text-muted); background: var(--bg-sunken); padding: 1px 6px; border-radius: 4px; }
.sidebar-footer .backend-url { color: var(--text-secondary); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
.version { font-size: 11px; color: var(--text-muted); }

.content { flex: 1; padding: 24px 28px; overflow-x: hidden; }

@media (max-width: 768px) {
  .mobile-header { display: flex; }
  .sidebar {
    position: fixed; top: 0; left: 0; bottom: 0;
    width: 220px; z-index: 160;
    transform: translateX(-100%);
    box-shadow: 2px 0 12px rgba(0,0,0,.1);
    padding-top: 60px;
  }
  .sidebar.open { transform: translateX(0); }
  .content { padding: 60px 14px 20px; }
}
</style>
