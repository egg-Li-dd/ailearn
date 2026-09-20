<template>
  <div class="schedule-view">
    <div class="page-head">
      <div>
        <h2>📅 周课表</h2>
        <p class="page-desc">可视化周视图 · 冲突自动检测 · 拖拽调整 · 单双周支持</p>
      </div>
      <div class="head-actions">
        <button class="btn ghost" @click="showTemplates = true">📋 模板</button>
        <button class="btn" @click="openCreate">+ 添加课表项</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard icon="📅" :value="items.length" label="课表项总数" theme="blue" />
      <StatCard icon="✅" :value="activeCount" label="启用中" theme="green" />
      <StatCard icon="⚠️" :value="conflicts.length" label="时间冲突" theme="orange" />
      <StatCard icon="📖" :value="courseCount" label="涉及科目" theme="purple" />
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <select v-model="weekType" class="toolbar-select" @change="loadGrid">
          <option value="all">全周</option>
          <option value="odd">单周</option>
          <option value="even">双周</option>
        </select>
        <div class="view-toggle">
          <button :class="{ active: viewMode === 'grid' }" @click="viewMode = 'grid'">⊞ 网格</button>
          <button :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'">☰ 列表</button>
        </div>
      </div>
      <div class="toolbar-right">
        <select v-model="filterCourse" class="toolbar-select">
          <option value="">全部科目</option>
          <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
    </div>

    <!-- 网格视图 -->
    <div v-if="viewMode === 'grid'" class="grid-container">
      <div class="grid-header">
        <div class="grid-corner">时段</div>
        <div v-for="(day, idx) in weekdays" :key="idx" class="grid-day-head" :class="{ today: idx === todayWeekday }">
          {{ day }}
        </div>
      </div>
      <div class="grid-body">
        <div v-for="slot in timeSlots" :key="slot" class="grid-row">
          <div class="grid-time">{{ slot }}</div>
          <div
            v-for="(day, dayIdx) in weekdays"
            :key="dayIdx"
            class="grid-cell"
            :class="{ today: dayIdx === todayWeekday }"
            @dragover.prevent
            @drop="onDrop($event, dayIdx, slot)"
          >
            <div
              v-for="item in getCellItems(dayIdx, slot)"
              :key="item.id"
              class="grid-item"
              :class="{ conflict: item.has_conflict }"
              :style="{ background: item.color_override || getCourseColor(item.course_id) }"
              draggable="true"
              @dragstart="onDragStart($event, item)"
              @click="openEdit(item)"
            >
              <div class="item-name">{{ getCourseName(item.course_id) }}</div>
              <div class="item-time">{{ (item.start_time || '').slice(0, 5) }}-{{ (item.end_time || '').slice(0, 5) }}</div>
              <div class="item-loc" v-if="item.classroom || item.location">{{ item.classroom || item.location }}</div>
              <div v-if="item.has_conflict" class="conflict-badge">⚠️</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表视图 -->
    <div v-else class="list-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>星期</th><th>时间</th><th>科目</th><th>教室</th><th>教师</th>
            <th>单双周</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filteredListItems" :key="item.id" :class="{ inactive: !item.is_active }">
            <td>{{ weekdays[item.weekday] }}</td>
            <td>{{ (item.start_time || '').slice(0, 5) }}-{{ (item.end_time || '').slice(0, 5) }}</td>
            <td><span class="course-tag" :style="{ background: getCourseColor(item.course_id) }">{{ getCourseName(item.course_id) }}</span></td>
            <td>{{ item.classroom || item.location || '—' }}</td>
            <td>{{ item.teacher || '—' }}</td>
            <td>{{ weekTypeLabel(item.week_type) }}</td>
            <td><span :class="['status-tag', item.is_active ? 'active' : 'inactive']">{{ item.is_active ? '启用' : '停用' }}</span></td>
            <td class="row-ops">
              <button class="btn ghost mini" @click="openEdit(item)">编辑</button>
              <button class="btn danger mini" @click="onDelete(item)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!filteredListItems.length" icon="📅" title="暂无课表项" desc="点击右上角添加课表项" />
    </div>

    <!-- 新建/编辑模态框 -->
    <FormModal v-model="showForm" :title="editingId ? '编辑课表项' : '添加课表项'" icon="📅" size="md" :loading="saving" @confirm="onSave">
      <div class="form-grid">
        <label class="f">
          <span>科目 *</span>
          <select v-model="form.course_id">
            <option value="">请选择</option>
            <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">
          <span>星期 *</span>
          <select v-model.number="form.weekday">
            <option v-for="(d, i) in weekdays" :key="i" :value="i">{{ d }}</option>
          </select>
        </label>
        <label class="f">
          <span>开始时间 *</span>
          <input type="time" v-model="form.start_time" />
        </label>
        <label class="f">
          <span>结束时间 *</span>
          <input type="time" v-model="form.end_time" />
        </label>
        <label class="f">
          <span>教室</span>
          <input v-model="form.classroom" placeholder="如：A101" />
        </label>
        <label class="f">
          <span>教师</span>
          <input v-model="form.teacher" placeholder="如：张老师" />
        </label>
        <label class="f">
          <span>单双周</span>
          <select v-model="form.week_type">
            <option value="all">全周</option>
            <option value="odd">单周</option>
            <option value="even">双周</option>
          </select>
        </label>
        <label class="f">
          <span>状态</span>
          <select v-model="form.is_active">
            <option :value="true">启用</option>
            <option :value="false">停用</option>
          </select>
        </label>
        <label class="f full">
          <span>地点（兼容旧字段）</span>
          <input v-model="form.location" placeholder="如：教学楼A座" />
        </label>
      </div>
    </FormModal>

    <!-- 模板管理模态框 -->
    <FormModal v-model="showTemplates" title="课表模板" icon="📋" size="md">
      <div class="template-list">
        <div v-if="!templates.length" class="empty-tip">暂无模板，保存当前课表为模板可快速切换</div>
        <div v-for="t in templates" :key="t.id" class="template-item">
          <div class="tpl-info">
            <div class="tpl-name">{{ t.name }}</div>
            <div class="tpl-desc">{{ t.description || '无描述' }}</div>
            <div class="tpl-date">{{ formatDate(t.created_at) }}</div>
          </div>
          <div class="tpl-ops">
            <button class="btn ghost mini" @click="applyTemplate(t)">应用</button>
            <button class="btn danger mini" @click="deleteTemplate(t)">删除</button>
          </div>
        </div>
      </div>
      <div class="template-save">
        <input v-model="newTplName" placeholder="模板名称" class="tpl-input" />
        <input v-model="newTplDesc" placeholder="描述（可选）" class="tpl-input" />
        <button class="btn" @click="saveTemplate">保存当前课表</button>
      </div>
    </FormModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api'
import StatCard from '../components/StatCard.vue'
import EmptyState from '../components/EmptyState.vue'
import FormModal from '../components/FormModal.vue'

const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const items = ref([])
const courses = ref([])
const gridData = ref({ grid: {}, conflicts: [] })
const viewMode = ref('grid')
const weekType = ref('all')
const filterCourse = ref('')
const showForm = ref(false)
const showTemplates = ref(false)
const editingId = ref(null)
const saving = ref(false)
const templates = ref([])
const newTplName = ref('')
const newTplDesc = ref('')
const dragItem = ref(null)

const todayWeekday = computed(() => {
  const d = new Date()
  return (d.getDay() + 6) % 7 // 周日=0 -> 6
})

const form = ref({
  course_id: '', weekday: 0, start_time: '08:00', end_time: '09:40',
  location: '', classroom: '', teacher: '', week_type: 'all', is_active: true,
})

const activeCount = computed(() => items.value.filter(i => i.is_active).length)
const courseCount = computed(() => new Set(items.value.map(i => i.course_id)).size)
const conflicts = computed(() => gridData.value.conflicts || [])

const timeSlots = computed(() => {
  const slots = new Set()
  items.value.forEach(i => slots.add((i.start_time || '').slice(0, 5)))
  return Array.from(slots).sort()
})

const filteredListItems = computed(() => {
  let list = items.value
  if (filterCourse.value) list = list.filter(i => i.course_id === filterCourse.value)
  return list.sort((a, b) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time))
})

function getCourseName(id) {
  const c = courses.value.find(c => c.id === id)
  return c ? c.name : '未知'
}
function getCourseColor(id) {
  const c = courses.value.find(c => c.id === id)
  return c?.color || '#3E63DD'
}
function weekTypeLabel(t) {
  return { all: '全周', odd: '单周', even: '双周' }[t] || t
}
function formatDate(d) {
  return new Date(d).toLocaleString('zh-CN')
}

function getCellItems(dayIdx, slot) {
  const dayItems = gridData.value.grid?.[String(dayIdx)]?.[slot] || []
  return dayItems
}

async function loadData() {
  const [c, s] = await Promise.all([api.courses(), api.schedule()])
  courses.value = c
  items.value = s
  await loadGrid()
}
async function loadGrid() {
  try {
    gridData.value = await api.scheduleGrid(weekType.value)
  } catch (e) { console.error('网格加载失败', e) }
}

function openCreate() {
  editingId.value = null
  form.value = { course_id: courses.value[0]?.id || '', weekday: 0, start_time: '08:00', end_time: '09:40', location: '', classroom: '', teacher: '', week_type: 'all', is_active: true }
  showForm.value = true
}
function openEdit(item) {
  editingId.value = item.id
  form.value = { ...item }
  showForm.value = true
}

async function onSave() {
  if (!form.value.course_id) { alert('请选择科目'); return }
  saving.value = true
  try {
    const payload = { ...form.value }
    if (editingId.value) {
      await api.updateScheduleItem(editingId.value, payload)
    } else {
      await api.createScheduleItem(payload)
    }
    showForm.value = false
    await loadData()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(item) {
  if (!confirm(`确定删除「${getCourseName(item.course_id)}」的课表项吗？`)) return
  try {
    await api.deleteScheduleItem(item.id)
    await loadData()
  } catch (e) { alert('删除失败') }
}

// 拖拽
function onDragStart(e, item) {
  dragItem.value = item
  e.dataTransfer.effectAllowed = 'move'
}
async function onDrop(e, dayIdx, slot) {
  if (!dragItem.value) return
  const [h, m] = slot.split(':').map(Number)
  const duration = (new Date(`2000-01-01T${dragItem.value.end_time}`) - new Date(`2000-01-01T${dragItem.value.start_time}`))
  const end = new Date(2000, 0, 1, h, m) + duration
  const endTime = new Date(end).toTimeString().slice(0, 5)
  try {
    await api.moveScheduleItem(dragItem.value.id, { weekday: dayIdx, start_time: slot, end_time: endTime, sort: 0 })
    await loadData()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '移动失败（可能时间冲突）')
  }
  dragItem.value = null
}

// 模板
async function loadTemplates() { templates.value = await api.scheduleTemplates() }
async function saveTemplate() {
  if (!newTplName.value.trim()) { alert('请输入模板名称'); return }
  try {
    await api.saveScheduleTemplate({ name: newTplName.value, description: newTplDesc.value })
    newTplName.value = ''; newTplDesc.value = ''
    await loadTemplates()
  } catch (e) { alert('保存失败') }
}
async function applyTemplate(t) {
  if (!confirm(`应用模板「${t.name}」将覆盖当前课表，确定吗？`)) return
  try {
    await api.applyScheduleTemplate(t.id)
    showTemplates.value = false
    await loadData()
  } catch (e) { alert('应用失败') }
}
async function deleteTemplate(t) {
  if (!confirm(`删除模板「${t.name}」？`)) return
  try { await api.deleteScheduleTemplate(t.id); await loadTemplates() } catch (e) { alert('删除失败') }
}

onMounted(async () => { await loadData(); await loadTemplates() })
</script>

<style scoped>
.schedule-view { padding: 20px 24px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
.head-actions { display: flex; gap: 10px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }

.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; }
.toolbar-select { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; background: var(--bg-card); cursor: pointer; }
.view-toggle { display: flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.view-toggle button { padding: 6px 14px; border: none; background: var(--bg-card); font-size: 13px; cursor: pointer; color: var(--text-secondary); }
.view-toggle button.active { background: var(--primary); color: #fff; }

/* 网格视图 */
.grid-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.grid-header { display: grid; grid-template-columns: 70px repeat(7, 1fr); background: var(--bg-sunken); border-bottom: 1px solid var(--border); }
.grid-corner, .grid-day-head { padding: 10px 8px; text-align: center; font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.grid-day-head.today { background: var(--primary-weak); color: var(--primary); }
.grid-body { display: grid; grid-template-columns: 70px repeat(7, 1fr); }
.grid-row { display: contents; }
.grid-time { padding: 8px 6px; text-align: center; font-size: 11px; color: var(--text-muted); border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: center; }
.grid-cell { min-height: 70px; padding: 4px; border-right: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); display: flex; flex-direction: column; gap: 4px; }
.grid-cell.today { background: rgba(62,99,221,.03); }
.grid-item { background: var(--primary); color: #fff; padding: 6px 8px; border-radius: 6px; font-size: 11px; cursor: pointer; position: relative; transition: transform .1s, box-shadow .1s; }
.grid-item:hover { transform: scale(1.02); box-shadow: 0 2px 8px rgba(0,0,0,.15); }
.grid-item.conflict { outline: 2px solid var(--danger); outline-offset: 1px; }
.item-name { font-weight: 600; margin-bottom: 2px; }
.item-time { opacity: 0.85; font-size: 10px; }
.item-loc { opacity: 0.75; font-size: 10px; margin-top: 1px; }
.conflict-badge { position: absolute; top: 2px; right: 4px; font-size: 12px; }

/* 列表视图 */
.list-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { background: var(--bg-sunken); padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border); }
.data-table td { padding: 10px 12px; font-size: 13px; border-bottom: 1px solid var(--border-light); }
.data-table tr:hover { background: var(--bg-sunken); }
.data-table tr.inactive { opacity: 0.5; }
.course-tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; color: #fff; font-weight: 500; }
.status-tag { padding: 2px 8px; border-radius: 10px; font-size: 11px; }
.status-tag.active { background: #e6f7ec; color: #3E8E58; }
.status-tag.inactive { background: var(--bg-sunken); color: var(--text-muted); }
.row-ops { display: flex; gap: 6px; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid .f.full { grid-column: 1 / -1; }

/* 模板 */
.template-list { max-height: 300px; overflow-y: auto; margin-bottom: 16px; }
.template-item { display: flex; justify-content: space-between; align-items: center; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
.tpl-name { font-weight: 600; font-size: 14px; }
.tpl-desc { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.tpl-date { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.tpl-ops { display: flex; gap: 6px; }
.template-save { display: flex; gap: 8px; padding-top: 12px; border-top: 1px solid var(--border); }
.tpl-input { flex: 1; height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.empty-tip { text-align: center; padding: 24px; color: var(--text-muted); font-size: 13px; }
</style>
