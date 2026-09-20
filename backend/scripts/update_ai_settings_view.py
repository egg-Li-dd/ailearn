file_path = r'C:\creategame\AI学\admin\src\views\AiSettingsView.vue'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 添加状态变量（在 loading 状态后面）
old_state = '''const loading = ref(false)
const busy = ref(false)
const toast = ref({ msg: '', ok: true })'''
new_state = '''const loading = ref(false)
const busy = ref(false)
const toast = ref({ msg: '', ok: true })
// 通道范围：global=全局通道, private=用户私有通道
const channelScope = ref('global')
const selectedUserKey = ref('')
const userList = ref([])'''
content = content.replace(old_state, new_state)

# 2. 修改 loadAll 函数，根据 scope 加载通道
old_load = '''async function loadAll() {
  loading.value = true
  try {
    const [r, s] = await Promise.all([api.aiChannels(), api.aiChannelStats()])
    channels.value = r.channels || []
    channelTypes.value = r.types || {}
    stats.value = s
  } catch (e) {
    showToast(e.message, false)'''
new_load = '''async function loadUsers() {
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
    showToast(e.message, false)'''
content = content.replace(old_load, new_load)

# 3. 修改 onMounted，添加 loadUsers
old_mount = '''onMounted(() => {
  loadAll()
})'''
new_mount = '''onMounted(() => {
  loadUsers()
  loadAll()
})'''
content = content.replace(old_mount, new_mount)

# 4. 修改 openCreate，根据 scope 设置 user_key
old_open_create = '''function openCreate() {
  editingId.value = null
  form.value = defaultForm()
  showModal.value = true
}'''
new_open_create = '''function openCreate() {
  editingId.value = null
  form.value = defaultForm()
  // 创建通道时，根据当前范围设置 user_key
  if (channelScope.value === 'private' && selectedUserKey.value) {
    form.value.user_key = selectedUserKey.value
  } else {
    form.value.user_key = null
  }
  showModal.value = true
}'''
content = content.replace(old_open_create, new_open_create)

# 5. defaultForm 添加 user_key 字段
old_default = '''function defaultForm() {
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
  }
}'''
new_default = '''function defaultForm() {
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
}'''
content = content.replace(old_default, new_default)

# 6. 在模板中添加范围切换器（在 head-actions 前面）
old_head = '''      <div class="head-actions" v-if="activeTab === 'channels'">
        <button class="btn ghost" @click="importFromOpencode">从 OpenCode 导入</button>
        <button class="btn" @click="openCreate">+ 添加渠道</button>
      </div>'''
new_head = '''      <div class="scope-switcher" v-if="activeTab === 'channels'">
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
      </div>'''
content = content.replace(old_head, new_head)

# 7. 添加 CSS 样式（在 </style> 前面）
old_style_end = '</style>'
new_style = '''
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
</style>'''
content = content.replace(old_style_end, new_style)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('AiSettingsView.vue 修改完成')
print('  ✓ 添加 channelScope/selectedUserKey/userList 状态')
print('  ✓ 添加 loadUsers 函数')
print('  ✓ loadAll 支持 scope/user_key 参数')
print('  ✓ openCreate 根据 scope 设置 user_key')
print('  ✓ defaultForm 添加 user_key 字段')
print('  ✓ 模板添加范围切换器 UI')
print('  ✓ 添加 CSS 样式')
