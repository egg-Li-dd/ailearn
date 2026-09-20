<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['user-changed'])

const users = ref([])
const loading = ref(false)
const showCreateModal = ref(false)
const showEditModal = ref(false)
const showResetPinModal = ref(false)
const editingUser = ref(null)
const statsCache = ref({})

// 创建用户表单
const createForm = ref({
  username: '',
  nickname: '',
  pin: '',
  role: 'user',
})

// 编辑用户表单
const editForm = ref({
  nickname: '',
  role: 'user',
  is_active: true,
})

// 重置 PIN 表单
const resetPinForm = ref({ pin: '' })

const errorMsg = ref('')
const successMsg = ref('')

function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = '' }, 5000)
}
function showSuccess(msg) {
  successMsg.value = msg
  setTimeout(() => { successMsg.value = '' }, 3000)
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await api.adminUsers()
    // 加载每个用户的统计
    for (const u of users.value) {
      if (!statsCache.value[u.id]) {
        try {
          statsCache.value[u.id] = await api.adminUserStats(u.id)
        } catch (e) {
          statsCache.value[u.id] = null
        }
      }
    }
  } catch (e) {
    showError('加载用户列表失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  createForm.value = { username: '', nickname: '', pin: '', role: 'user' }
  showCreateModal.value = true
}

async function createUser() {
  if (!createForm.value.username || !createForm.value.nickname || !createForm.value.pin) {
    showError('请填写用户名、昵称和 PIN')
    return
  }
  if (!/^\d{4,6}$/.test(createForm.value.pin)) {
    showError('PIN 必须为 4-6 位数字')
    return
  }
  try {
    await api.adminCreateUser(createForm.value)
    showCreateModal.value = false
    showSuccess('用户创建成功')
    await loadUsers()
    emit('user-changed')
  } catch (e) {
    showError('创建失败: ' + (e.message || e))
  }
}

function openEditModal(user) {
  editingUser.value = user
  editForm.value = {
    nickname: user.nickname,
    role: user.role,
    is_active: user.is_active,
  }
  showEditModal.value = true
}

async function saveEdit() {
  try {
    await api.adminUpdateUser(editingUser.value.id, editForm.value)
    showEditModal.value = false
    showSuccess('用户更新成功')
    await loadUsers()
    emit('user-changed')
  } catch (e) {
    showError('更新失败: ' + (e.message || e))
  }
}

function openResetPinModal(user) {
  editingUser.value = user
  resetPinForm.value = { pin: '' }
  showResetPinModal.value = true
}

async function confirmResetPin() {
  if (!/^\d{4,6}$/.test(resetPinForm.value.pin)) {
    showError('PIN 必须为 4-6 位数字')
    return
  }
  try {
    await api.adminResetPin(editingUser.value.id, resetPinForm.value.pin)
    showResetPinModal.value = false
    showSuccess('PIN 已重置，原有登录态已失效')
  } catch (e) {
    showError('重置失败: ' + (e.message || e))
  }
}

async function deleteUser(user) {
  if (!confirm(`确定要删除用户「${user.nickname || user.username}」吗？\n该用户的所有业务数据将被永久删除，此操作不可恢复！`)) {
    return
  }
  try {
    await api.adminDeleteUser(user.id)
    showSuccess('用户已删除')
    await loadUsers()
    emit('user-changed')
  } catch (e) {
    showError('删除失败: ' + (e.message || e))
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

onMounted(() => {
  loadUsers()
})
</script>

<template>
  <div class="user-manage">
    <div class="page-header">
      <h2>👥 用户管理</h2>
      <p class="page-desc">管理系统用户，每个用户拥有独立的业务数据库（物理隔离）</p>
      <button class="btn-primary" @click="openCreateModal">+ 新建用户</button>
    </div>

    <!-- 消息提示 -->
    <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
    <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>

    <!-- 用户列表 -->
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else class="user-grid">
      <div v-for="user in users" :key="user.id" class="user-card" :class="{ disabled: !user.is_active }">
        <div class="user-card-header">
          <div class="user-card-avatar" :class="{ admin: user.role === 'admin' }">
            {{ (user.nickname || user.username).charAt(0).toUpperCase() }}
          </div>
          <div class="user-card-info">
            <div class="user-card-name">
              {{ user.nickname || user.username }}
              <span v-if="user.role === 'admin'" class="badge badge-admin">管理员</span>
              <span v-if="!user.is_active" class="badge badge-disabled">已禁用</span>
            </div>
            <div class="user-card-sub">@{{ user.username }} · db: {{ user.db_key }}</div>
          </div>
        </div>

        <!-- 数据统计 -->
        <div v-if="statsCache[user.id]" class="user-stats">
          <div class="stat-item">
            <span class="stat-num">{{ statsCache[user.id].courses }}</span>
            <span class="stat-label">科目</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ statsCache[user.id].knowledge_nodes }}</span>
            <span class="stat-label">知识点</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ statsCache[user.id].tasks }}</span>
            <span class="stat-label">任务</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ statsCache[user.id].study_sessions }}</span>
            <span class="stat-label">学习</span>
          </div>
        </div>

        <div class="user-card-meta">
          <span>注册: {{ formatDate(user.created_at) }}</span>
          <span v-if="user.last_login_at">最后登录: {{ formatDate(user.last_login_at) }}</span>
        </div>

        <div class="user-card-actions">
          <button class="btn-sm" @click="openEditModal(user)">编辑</button>
          <button class="btn-sm" @click="openResetPinModal(user)">重置PIN</button>
          <button class="btn-sm btn-danger" @click="deleteUser(user)">删除</button>
        </div>
      </div>
    </div>

    <!-- 新建用户弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal">
        <h3>新建用户</h3>
        <div class="form-group">
          <label>登录用户名 *</label>
          <input v-model="createForm.username" type="text" placeholder="唯一用户名，如 dangdang" />
        </div>
        <div class="form-group">
          <label>显示昵称 *</label>
          <input v-model="createForm.nickname" type="text" placeholder="如 当当" />
        </div>
        <div class="form-group">
          <label>PIN 码 *</label>
          <input v-model="createForm.pin" type="password" placeholder="4-6位数字" maxlength="6" />
        </div>
        <div class="form-group">
          <label>角色</label>
          <select v-model="createForm.role">
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showCreateModal = false">取消</button>
          <button class="btn-primary" @click="createUser">创建</button>
        </div>
      </div>
    </div>

    <!-- 编辑用户弹窗 -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal">
        <h3>编辑用户 - {{ editingUser?.nickname || editingUser?.username }}</h3>
        <div class="form-group">
          <label>显示昵称</label>
          <input v-model="editForm.nickname" type="text" />
        </div>
        <div class="form-group">
          <label>角色</label>
          <select v-model="editForm.role">
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </div>
        <div class="form-group">
          <label class="checkbox-label">
            <input v-model="editForm.is_active" type="checkbox" />
            启用账号
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showEditModal = false">取消</button>
          <button class="btn-primary" @click="saveEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- 重置 PIN 弹窗 -->
    <div v-if="showResetPinModal" class="modal-overlay" @click.self="showResetPinModal = false">
      <div class="modal">
        <h3>重置 PIN - {{ editingUser?.nickname || editingUser?.username }}</h3>
        <p class="modal-warning">重置后该用户的所有现有登录态将失效，需要重新登录。</p>
        <div class="form-group">
          <label>新 PIN 码 *</label>
          <input v-model="resetPinForm.pin" type="password" placeholder="4-6位数字" maxlength="6" />
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showResetPinModal = false">取消</button>
          <button class="btn-primary" @click="confirmResetPin">确认重置</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.user-manage { max-width: 1200px; margin: 0 auto; }

.page-header { margin-bottom: 20px; }
.page-header h2 { margin: 0 0 4px 0; font-size: 20px; }
.page-desc { margin: 0 0 12px 0; color: var(--text-muted); font-size: 13px; }

.btn-primary {
  padding: 8px 16px; background: var(--primary); color: #fff;
  border: none; border-radius: 8px; cursor: pointer; font-size: 13px;
}
.btn-primary:hover { opacity: 0.9; }
.btn-secondary {
  padding: 8px 16px; background: var(--bg-sunken); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; cursor: pointer; font-size: 13px;
}
.btn-sm {
  padding: 4px 10px; background: var(--bg-sunken); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px; cursor: pointer; font-size: 12px;
}
.btn-sm:hover { background: var(--primary-weak); border-color: var(--primary); color: var(--primary); }
.btn-danger { color: #e74c3c; border-color: #e74c3c; }
.btn-danger:hover { background: #fde8e8; }

.alert {
  padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; font-size: 13px;
}
.alert-error { background: #fde8e8; color: #c0392b; border: 1px solid #f5c6c6; }
.alert-success { background: #e8f8f0; color: #27ae60; border: 1px solid #b8e6cc; }

.loading { text-align: center; padding: 40px; color: var(--text-muted); }

.user-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.user-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  transition: all .15s ease;
}
.user-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.user-card.disabled { opacity: 0.6; }

.user-card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.user-card-avatar {
  width: 44px; height: 44px; border-radius: 50%;
  background: var(--bg-sunken); color: var(--text);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 600; flex-shrink: 0;
}
.user-card-avatar.admin { background: var(--primary-weak); color: var(--primary); }
.user-card-info { flex: 1; min-width: 0; }
.user-card-name {
  font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 6px;
}
.user-card-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

.badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500;
}
.badge-admin { background: var(--primary-weak); color: var(--primary); }
.badge-disabled { background: #f0f0f0; color: #999; }

.user-stats {
  display: flex; gap: 8px; padding: 10px;
  background: var(--bg-sunken); border-radius: 8px; margin-bottom: 10px;
}
.stat-item { flex: 1; text-align: center; }
.stat-num { display: block; font-size: 16px; font-weight: 600; color: var(--text); }
.stat-label { display: block; font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.user-card-meta {
  font-size: 11px; color: var(--text-muted); margin-bottom: 10px;
  display: flex; flex-direction: column; gap: 2px;
}

.user-card-actions {
  display: flex; gap: 6px; padding-top: 10px;
  border-top: 1px solid var(--border);
}

/* 弹窗 */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 20px;
}
.modal {
  background: var(--bg-card); border-radius: 12px;
  padding: 24px; width: 100%; max-width: 420px;
  box-shadow: 0 8px 32px rgba(0,0,0,.2);
}
.modal h3 { margin: 0 0 16px 0; font-size: 17px; }
.modal-warning {
  font-size: 12px; color: #e67e22; background: #fef5e7;
  padding: 8px 12px; border-radius: 6px; margin-bottom: 16px;
}

.form-group { margin-bottom: 14px; }
.form-group label {
  display: block; font-size: 12px; color: var(--text-muted);
  margin-bottom: 6px; font-weight: 500;
}
.form-group input, .form-group select {
  width: 100%; padding: 8px 12px;
  border: 1px solid var(--border); border-radius: 8px;
  font-size: 13px; background: var(--bg-card); color: var(--text);
  box-sizing: border-box;
}
.form-group input:focus, .form-group select:focus {
  outline: none; border-color: var(--primary);
}
.checkbox-label {
  display: flex !important; align-items: center; gap: 8px;
  font-size: 13px !important; color: var(--text) !important;
}
.checkbox-label input { width: auto !important; }

.modal-actions {
  display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px;
}
</style>
