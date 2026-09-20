<template>
  <div class="exceptions-view">
    <div class="page-head">
      <div>
        <h2>⚠️ 日期例外</h2>
        <p class="page-desc">停课/加课/调休 · 月历视图 · 支持重复规则</p>
      </div>
      <div class="head-actions">
        <button class="btn ghost" @click="showImport = true">📥 批量导入</button>
        <button class="btn" @click="openCreate">+ 添加例外</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard icon="📊" :value="exceptions.length" label="例外总数" theme="blue" />
      <StatCard icon="🚫" :value="removeCount" label="停课" theme="red" />
      <StatCard icon="➕" :value="addCount" label="加课" theme="green" />
      <StatCard icon="📅" :value="thisMonthCount" label="本月" theme="orange" />
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="month-nav">
          <button class="nav-btn" @click="prevMonth">◀</button>
          <span class="month-label">{{ currentYear }}年{{ currentMonth + 1 }}月</span>
          <button class="nav-btn" @click="nextMonth">▶</button>
          <button class="btn ghost mini" @click="goToday">今天</button>
        </div>
        <div class="view-toggle">
          <button :class="{ active: viewMode === 'calendar' }" @click="viewMode = 'calendar'">📅 月历</button>
          <button :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'">☰ 列表</button>
        </div>
      </div>
      <div class="toolbar-right">
        <select v-model="filterAction" class="toolbar-select">
          <option value="">全部类型</option>
          <option value="remove">停课</option>
          <option value="add">加课</option>
        </select>
      </div>
    </div>

    <!-- 月历视图 -->
    <div v-if="viewMode === 'calendar'" class="calendar-container">
      <div class="calendar-header">
        <div v-for="d in weekDays" :key="d" class="cal-day-head">{{ d }}</div>
      </div>
      <div class="calendar-body">
        <div
          v-for="(day, idx) in calendarDays"
          :key="idx"
          class="cal-cell"
          :class="{ other: !day.inMonth, today: day.isToday, has: day.exceptions.length }"
          @click="day.inMonth && selectDay(day)"
        >
          <div class="cal-date">{{ day.date }}</div>
          <div class="cal-badges" v-if="day.exceptions.length">
            <span v-for="e in day.exceptions.slice(0, 2)" :key="e.id" class="cal-badge" :class="e.action">
              {{ e.action === 'remove' ? '🚫' : '➕' }} {{ e.course_name || '全部' }}
            </span>
            <span v-if="day.exceptions.length > 2" class="cal-more">+{{ day.exceptions.length - 2 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 列表视图 -->
    <div v-else class="list-container">
      <table class="data-table">
        <thead>
          <tr><th>日期</th><th>星期</th><th>类型</th><th>科目</th><th>时间</th><th>原因</th><th>重复</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in filteredList" :key="e.id">
            <td>{{ e.date }}</td>
            <td>{{ weekDays[new Date(e.date).getDay()] }}</td>
            <td><span :class="['type-tag', e.action]">{{ e.action === 'remove' ? '停课' : '加课' }}</span></td>
            <td>{{ getCourseName(e.course_id) }}</td>
            <td>{{ e.start_time ? `${e.start_time}-${e.end_time}` : '全天' }}</td>
            <td>{{ e.reason || '—' }}</td>
            <td>{{ repeatLabel(e) }}</td>
            <td class="row-ops">
              <button class="btn ghost mini" @click="openEdit(e)">编辑</button>
              <button class="btn danger mini" @click="onDelete(e)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="!filteredList.length" icon="⚠️" title="暂无例外" desc="点击右上角添加日期例外" />
    </div>

    <!-- 新建/编辑模态框 -->
    <FormModal v-model="showForm" :title="editingId ? '编辑例外' : '添加例外'" icon="⚠️" size="md" :loading="saving" @confirm="onSave">
      <div class="form-grid">
        <label class="f">
          <span>日期 *</span>
          <input type="date" v-model="form.date" />
        </label>
        <label class="f">
          <span>类型 *</span>
          <select v-model="form.action">
            <option value="remove">🚫 停课</option>
            <option value="add">➕ 加课</option>
          </select>
        </label>
        <label class="f">
          <span>科目</span>
          <select v-model="form.course_id">
            <option :value="null">全部科目</option>
            <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">
          <span>开始时间</span>
          <input type="time" v-model="form.start_time" />
        </label>
        <label class="f">
          <span>结束时间</span>
          <input type="time" v-model="form.end_time" />
        </label>
        <label class="f">
          <span>重复类型</span>
          <select v-model="form.repeat_type">
            <option value="none">不重复</option>
            <option value="daily">每天</option>
            <option value="weekly">每周</option>
            <option value="biweekly">每两周</option>
            <option value="monthly">每月</option>
          </select>
        </label>
        <label class="f full">
          <span>原因/备注</span>
          <input v-model="form.reason" placeholder="如：国庆放假、校运动会、教师出差" />
        </label>
        <label class="f checkbox-row" v-if="editingId">
          <input type="checkbox" v-model="form.is_active" />
          <span>启用此例外</span>
        </label>
      </div>
    </FormModal>

    <!-- 日期详情侧滑 -->
    <DetailPanel v-model="showDayDetail" :title="`${selectedDay?.date}`" icon="📅" width="sm">
      <div v-if="selectedDay" class="day-detail">
        <div class="day-info">{{ weekDays[new Date(selectedDay.date).getDay()] }}</div>
        <div v-if="!selectedDay.exceptions.length" class="empty-day">当天无例外</div>
        <div v-for="e in selectedDay.exceptions" :key="e.id" class="exc-item" :class="e.action">
          <div class="exc-head">
            <span class="exc-type">{{ e.action === 'remove' ? '🚫 停课' : '➕ 加课' }}</span>
            <span class="exc-time">{{ e.start_time ? `${e.start_time}-${e.end_time}` : '全天' }}</span>
          </div>
          <div class="exc-course">{{ e.course_name || '全部科目' }}</div>
          <div class="exc-reason" v-if="e.reason">{{ e.reason }}</div>
          <div class="exc-ops">
            <button class="btn ghost mini" @click="openEdit(e); showDayDetail = false">编辑</button>
            <button class="btn danger mini" @click="onDelete(e)">删除</button>
          </div>
        </div>
      </div>
    </DetailPanel>

    <!-- 批量导入模态框 -->
    <FormModal v-model="showImport" title="批量导入例外" icon="📥" size="lg">
      <div class="import-area">
        <p class="import-tip">粘贴 CSV 格式数据（日期,类型,科目ID,开始时间,结束时间,原因），每行一条：</p>
        <textarea v-model="importText" rows="10" placeholder="2026-10-01,remove,,08:00,18:00,国庆放假&#10;2026-10-08,add,1,14:00,15:40,补课"></textarea>
        <div class="import-preview" v-if="parsedImport.length">
          <h4>预览（{{ parsedImport.length }}条）</h4>
          <div class="preview-list">
            <div v-for="(row, i) in parsedImport.slice(0, 5)" :key="i" class="preview-row">
              {{ row.date }} | {{ row.action === 'remove' ? '停课' : '加课' }} | {{ row.course_id || '全部' }} | {{ row.reason || '' }}
            </div>
            <div v-if="parsedImport.length > 5" class="preview-more">...还有 {{ parsedImport.length - 5 }} 条</div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn ghost" @click="showImport = false">取消</button>
        <button class="btn" :disabled="!parsedImport.length" @click="doImport">确认导入</button>
      </template>
    </FormModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api'
import StatCard from '../components/StatCard.vue'
import EmptyState from '../components/EmptyState.vue'
import FormModal from '../components/FormModal.vue'
import DetailPanel from '../components/DetailPanel.vue'

const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const exceptions = ref([])
const courses = ref([])
const calendarData = ref({ days: {} })
const viewMode = ref('calendar')
const filterAction = ref('')
const currentYear = ref(new Date().getFullYear())
const currentMonth = ref(new Date().getMonth())
const showForm = ref(false)
const showDayDetail = ref(false)
const showImport = ref(false)
const editingId = ref(null)
const saving = ref(false)
const selectedDay = ref(null)
const importText = ref('')

const form = ref({
  date: new Date().toISOString().slice(0, 10),
  action: 'remove', course_id: null,
  start_time: '', end_time: '',
  reason: '', repeat_type: 'none', is_active: true,
})

const removeCount = computed(() => exceptions.value.filter(e => e.action === 'remove').length)
const addCount = computed(() => exceptions.value.filter(e => e.action === 'add').length)
const thisMonthCount = computed(() => {
  return exceptions.value.filter(e => {
    const d = new Date(e.date)
    return d.getFullYear() === currentYear.value && d.getMonth() === currentMonth.value
  }).length
})

const filteredList = computed(() => {
  let list = exceptions.value
  if (filterAction.value) list = list.filter(e => e.action === filterAction.value)
  return list.sort((a, b) => a.date.localeCompare(b.date))
})

const calendarDays = computed(() => {
  const firstDay = new Date(currentYear.value, currentMonth.value, 1)
  const lastDay = new Date(currentYear.value, currentMonth.value + 1, 0)
  const startWeekday = firstDay.getDay()
  const daysInMonth = lastDay.getDate()
  const today = new Date()
  const days = []
  // 上月填充
  const prevMonthLast = new Date(currentYear.value, currentMonth.value, 0).getDate()
  for (let i = startWeekday - 1; i >= 0; i--) {
    days.push({ date: prevMonthLast - i, inMonth: false, isToday: false, exceptions: [] })
  }
  // 本月
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${currentYear.value}-${String(currentMonth.value + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const dayExcs = calendarData.value.days[d]?.exceptions || []
    days.push({
      date: d, dateStr, inMonth: true,
      isToday: today.getFullYear() === currentYear.value && today.getMonth() === currentMonth.value && today.getDate() === d,
      exceptions: dayExcs,
    })
  }
  // 下月填充
  while (days.length % 7 !== 0) {
    days.push({ date: days.length - daysInMonth - startWeekday + 1, inMonth: false, isToday: false, exceptions: [] })
  }
  return days
})

const parsedImport = computed(() => {
  if (!importText.value.trim()) return []
  return importText.value.trim().split('\n').map(line => {
    const parts = line.split(',').map(s => s.trim())
    return {
      date: parts[0], action: parts[1] || 'remove',
      course_id: parts[2] ? parseInt(parts[2]) : null,
      start_time: parts[3] || null, end_time: parts[4] || null,
      reason: parts[5] || '',
    }
  }).filter(r => r.date)
})

function getCourseName(id) {
  if (!id) return '全部科目'
  const c = courses.value.find(c => c.id === id)
  return c ? c.name : '未知'
}
function repeatLabel(e) {
  return { none: '不重复', daily: '每天', weekly: '每周', biweekly: '每两周', monthly: '每月' }[e.repeat_type] || '不重复'
}

async function loadData() {
  const [c, e] = await Promise.all([api.courses(), api.exceptions({ active_only: true })])
  courses.value = c
  exceptions.value = e
  await loadCalendar()
}
async function loadCalendar() {
  try {
    calendarData.value = await api.exceptionsCalendar(currentYear.value, currentMonth.value + 1)
  } catch (e) { console.error('月历加载失败', e) }
}

function prevMonth() {
  if (currentMonth.value === 0) { currentMonth.value = 11; currentYear.value-- }
  else currentMonth.value--
  loadCalendar()
}
function nextMonth() {
  if (currentMonth.value === 11) { currentMonth.value = 0; currentYear.value++ }
  else currentMonth.value++
  loadCalendar()
}
function goToday() {
  const t = new Date()
  currentYear.value = t.getFullYear()
  currentMonth.value = t.getMonth()
  loadCalendar()
}

function selectDay(day) {
  selectedDay.value = day
  showDayDetail.value = true
}

function openCreate() {
  editingId.value = null
  form.value = { date: new Date().toISOString().slice(0, 10), action: 'remove', course_id: null, start_time: '', end_time: '', reason: '', repeat_type: 'none', is_active: true }
  showForm.value = true
}
function openEdit(e) {
  editingId.value = e.id
  form.value = { ...e }
  showForm.value = true
}

async function onSave() {
  if (!form.value.date) { alert('请选择日期'); return }
  saving.value = true
  try {
    const payload = { ...form.value }
    if (editingId.value) await api.updateException(editingId.value, payload)
    else await api.createException(payload)
    showForm.value = false
    await loadData()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '保存失败')
  } finally { saving.value = false }
}

async function onDelete(e) {
  if (!confirm('确定删除此例外吗？')) return
  try { await api.deleteException(e.id); await loadData() } catch (e) { alert('删除失败') }
}

async function doImport() {
  try {
    const result = await api.batchImportExceptions(parsedImport.value)
    alert(`成功导入 ${result.created} 条`)
    showImport.value = false
    importText.value = ''
    await loadData()
  } catch (e) { alert('导入失败') }
}

onMounted(loadData)
</script>

<style scoped>
.exceptions-view { padding: 20px 24px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
.head-actions { display: flex; gap: 10px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }

.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; }
.month-nav { display: flex; align-items: center; gap: 8px; }
.nav-btn { width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-card); cursor: pointer; font-size: 12px; }
.nav-btn:hover { background: var(--bg-sunken); }
.month-label { font-size: 15px; font-weight: 600; min-width: 100px; text-align: center; }
.toolbar-select { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; background: var(--bg-card); cursor: pointer; }
.view-toggle { display: flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.view-toggle button { padding: 6px 14px; border: none; background: var(--bg-card); font-size: 13px; cursor: pointer; color: var(--text-secondary); }
.view-toggle button.active { background: var(--primary); color: #fff; }

/* 月历 */
.calendar-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.calendar-header { display: grid; grid-template-columns: repeat(7, 1fr); background: var(--bg-sunken); border-bottom: 1px solid var(--border); }
.cal-day-head { padding: 10px; text-align: center; font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.calendar-body { display: grid; grid-template-columns: repeat(7, 1fr); }
.cal-cell { min-height: 90px; padding: 6px; border-right: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); cursor: pointer; transition: background .1s; }
.cal-cell:hover { background: var(--primary-weak); }
.cal-cell.other { background: var(--bg-sunken); opacity: 0.4; cursor: default; }
.cal-cell.today { background: var(--primary-weak); }
.cal-cell.today .cal-date { background: var(--primary); color: #fff; }
.cal-date { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; font-size: 12px; font-weight: 600; }
.cal-badges { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.cal-badge { font-size: 10px; padding: 2px 4px; border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cal-badge.remove { background: #fdecea; color: #C24238; }
.cal-badge.add { background: #e6f7ec; color: #3E8E58; }
.cal-more { font-size: 10px; color: var(--text-muted); }

/* 列表 */
.list-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table th { background: var(--bg-sunken); padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; color: var(--text-secondary); border-bottom: 1px solid var(--border); }
.data-table td { padding: 10px 12px; font-size: 13px; border-bottom: 1px solid var(--border-light); }
.data-table tr:hover { background: var(--bg-sunken); }
.type-tag { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.type-tag.remove { background: #fdecea; color: #C24238; }
.type-tag.add { background: #e6f7ec; color: #3E8E58; }
.row-ops { display: flex; gap: 6px; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid .f.full { grid-column: 1 / -1; }
.checkbox-row { flex-direction: row !important; align-items: center; gap: 8px; }
.checkbox-row input { width: auto; height: auto; }

/* 详情 */
.day-detail { display: flex; flex-direction: column; gap: 12px; }
.day-info { font-size: 14px; color: var(--text-secondary); margin-bottom: 8px; }
.empty-day { text-align: center; padding: 24px; color: var(--text-muted); }
.exc-item { padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.exc-item.remove { border-left: 3px solid #C24238; }
.exc-item.add { border-left: 3px solid #3E8E58; }
.exc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.exc-type { font-weight: 600; font-size: 13px; }
.exc-time { font-size: 12px; color: var(--text-muted); }
.exc-course { font-size: 13px; color: var(--text); margin-bottom: 4px; }
.exc-reason { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
.exc-ops { display: flex; gap: 6px; }

/* 导入 */
.import-area { display: flex; flex-direction: column; gap: 12px; }
.import-tip { font-size: 13px; color: var(--text-secondary); }
.import-area textarea { width: 100%; min-height: 150px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; font-family: var(--font-mono); font-size: 12px; resize: vertical; }
.import-preview h4 { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.preview-list { display: flex; flex-direction: column; gap: 4px; }
.preview-row { font-size: 12px; padding: 6px 10px; background: var(--bg-sunken); border-radius: 4px; font-family: var(--font-mono); }
.preview-more { font-size: 11px; color: var(--text-muted); text-align: center; }
</style>
