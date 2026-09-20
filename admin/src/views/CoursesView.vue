<template>
  <div class="courses-view">
    <div class="page-head">
      <div>
        <h2>📚 科目管理</h2>
        <p class="page-desc">科目是知识树与课表的根，支持配色、图标、归档</p>
      </div>
      <button class="btn" @click="openCreate">+ 新建科目</button>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard icon="📚" :value="courses.length" label="科目总数" theme="blue" />
      <StatCard icon="📅" :value="totalSchedule" label="课表项数" theme="green" />
      <StatCard icon="🌳" :value="totalKnowledge" label="知识点数" theme="orange" />
      <StatCard icon="✅" :value="avgMastery + '%'" label="平均掌握度" theme="purple" />
    </div>

    <!-- 搜索栏 -->
    <SearchBar
      v-model="searchText"
      placeholder="搜索科目名称或代码..."
      :filters="filterOptions"
      show-export
      primary-label="+ 新建科目"
      @search="onSearch"
      @filter-change="onFilterChange"
      @export="onExport"
      @primary="openCreate"
    />

    <!-- 批量操作栏 -->
    <div v-if="selectedIds.length" class="batch-bar">
      <span class="batch-info">已选 {{ selectedIds.length }} 项</span>
      <button class="btn ghost mini" @click="toggleArchiveSelected">{{ allSelectedArchived ? '取消归档' : '归档' }}</button>
      <button class="btn danger mini" @click="batchDelete">批量删除</button>
      <button class="btn ghost mini" @click="selectedIds = []">取消选择</button>
    </div>

    <!-- 科目卡片网格 -->
    <div v-if="filteredCourses.length" class="course-grid">
      <div
        v-for="course in filteredCourses"
        :key="course.id"
        class="course-card"
        :class="{ archived: course.is_archived, selected: selectedIds.includes(course.id) }"
        :style="{ '--card-accent': course.color || '#3E63DD' }"
        @click="openDetail(course)"
      >
        <div class="card-select" @click.stop>
          <input type="checkbox" :checked="selectedIds.includes(course.id)" @change="toggleSelect(course.id)" />
        </div>
        <div class="card-color-bar"></div>
        <div class="card-head">
          <span class="card-icon">{{ course.icon || '📖' }}</span>
          <div class="card-title-group">
            <h3 class="card-title">{{ course.name }}</h3>
            <span class="card-code">{{ course.subject_code || '—' }}</span>
          </div>
          <div class="card-ops" @click.stop>
            <button class="btn ghost mini" @click="toggleArchive(course)">{{ course.is_archived ? '取消归档' : '归档' }}</button>
            <button class="btn ghost mini" @click="openEdit(course)">编辑</button>
            <button class="btn danger mini" @click="onDelete(course)">删除</button>
          </div>
        </div>
        <p class="card-desc" v-if="course.description">{{ course.description }}</p>
        <div class="card-stats">
          <div class="stat-item">
            <span class="stat-num">{{ courseScheduleCount(course.id) }}</span>
            <span class="stat-label">课表项</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ courseKnowledgeCount(course.id) }}</span>
            <span class="stat-label">知识点</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ courseMastery(course.id) }}%</span>
            <span class="stat-label">掌握度</span>
          </div>
          <div class="stat-item" v-if="course.target_days && course.days_remaining !== null">
            <span class="stat-num" :class="{ 'countdown-urgent': course.days_remaining <= 7, 'countdown-over': course.days_remaining === 0 }">{{ course.days_remaining }}天</span>
            <span class="stat-label">剩余</span>
          </div>
        </div>
        <div class="card-mastery-bar">
          <div class="mastery-fill" :style="{ width: courseMastery(course.id) + '%' }"></div>
        </div>
        <div v-if="course.is_archived" class="archived-badge">已归档</div>
      </div>
    </div>

    <!-- 空状态 -->
    <EmptyState
      v-else
      icon="📚"
      title="暂无科目"
      desc="创建第一个科目，开始构建你的知识体系和课表"
      action-label="+ 新建科目"
      @action="openCreate"
    />

    <!-- 新建/编辑模态框 -->
    <FormModal
      v-model="showForm"
      :title="editingId ? '编辑科目' : '新建科目'"
      icon="📚"
      size="md"
      :loading="saving"
      @confirm="onSave"
    >
      <div class="form-grid">
        <label class="f">
          <span>科目名称 *</span>
          <input v-model="form.name" placeholder="如：数据结构" />
        </label>
        <label class="f">
          <span>科目代码</span>
          <input v-model="form.subject_code" placeholder="如：ds" />
        </label>
        <label class="f">
          <span>图标 (emoji)</span>
          <input v-model="form.icon" placeholder="如：🗂️" maxlength="4" />
        </label>
        <label class="f">
          <span>排序</span>
          <input type="number" v-model.number="form.sort" min="0" />
        </label>
        <label class="f full">
          <span>科目描述</span>
          <textarea v-model="form.description" rows="2" placeholder="简要描述这个科目"></textarea>
        </label>
        <div class="f full">
          <span>配色</span>
          <ColorPicker v-model="form.color" />
        </div>
        <label class="f">
          <span>目标学习天数</span>
          <input type="number" v-model.number="form.target_days" min="1" max="3650" placeholder="如：60" />
        </label>
        <label class="f">
          <span>目标开始日期</span>
          <input type="date" v-model="form.goal_start_date" :min="todayStr" />
        </label>
        <div class="f full" v-if="editingId && form.target_days">
          <button class="btn ghost" style="width:100%;color:var(--danger);border-color:var(--danger)" @click="clearGoal">清除学习目标</button>
        </div>
        <label class="f checkbox-row" v-if="editingId">
          <input type="checkbox" v-model="form.is_archived" />
          <span>归档此科目（不删除数据，列表默认不显示）</span>
        </label>
      </div>
    </FormModal>

    <!-- 科目详情侧滑面板 -->
    <DetailPanel v-model="showDetail" :title="detailCourse?.name" :icon="detailCourse?.icon" width="md">
      <div v-if="detailCourse" class="detail-content">
        <div class="detail-section">
          <h4>基本信息</h4>
          <div class="detail-info-grid">
            <div><span class="info-label">代码</span><span class="info-value">{{ detailCourse.subject_code || '—' }}</span></div>
            <div><span class="info-label">排序</span><span class="info-value">{{ detailCourse.sort }}</span></div>
            <div><span class="info-label">归档</span><span class="info-value">{{ detailCourse.is_archived ? '是' : '否' }}</span></div>
          </div>
          <p v-if="detailCourse.description" class="detail-desc">{{ detailCourse.description }}</p>
        </div>
        <div class="detail-section">
          <h4>学习概览</h4>
          <div class="detail-stats">
            <div class="detail-stat"><span class="num">{{ courseScheduleCount(detailCourse.id) }}</span><span class="lbl">课表项</span></div>
            <div class="detail-stat"><span class="num">{{ courseKnowledgeCount(detailCourse.id) }}</span><span class="lbl">知识点</span></div>
            <div class="detail-stat"><span class="num">{{ courseMastery(detailCourse.id) }}%</span><span class="lbl">掌握度</span></div>
          </div>
        </div>
        <div class="detail-section" v-if="detailCourse.target_days">
          <h4>学习目标</h4>
          <div class="detail-stats">
            <div class="detail-stat">
              <span class="num" :class="{ 'countdown-urgent': detailCourse.days_remaining <= 7, 'countdown-over': detailCourse.days_remaining === 0 }">{{ detailCourse.days_remaining }}</span>
              <span class="lbl">剩余天数</span>
            </div>
            <div class="detail-stat"><span class="num">{{ detailCourse.target_days }}</span><span class="lbl">目标总天数</span></div>
            <div class="detail-stat"><span class="num">{{ detailCourse.goal_start_date || '—' }}</span><span class="lbl">开始日期</span></div>
          </div>
          <div class="goal-progress-bar">
            <div class="goal-progress-fill" :style="{ width: goalProgressPercent(detailCourse) + '%' }"></div>
          </div>
          <p class="goal-progress-text">时间进度 {{ goalProgressPercent(detailCourse) }}%</p>
        </div>
        <div class="detail-section" v-if="detailScheduleItems.length">
          <h4>关联课表项 ({{ detailScheduleItems.length }})</h4>
          <div class="related-list">
            <div v-for="item in detailScheduleItems" :key="item.id" class="related-item">
              <span class="related-dot" :style="{ background: detailCourse.color }"></span>
              <span class="related-main">{{ weekdays[item.weekday] }} {{ item.start_time }}-{{ item.end_time }}</span>
              <span class="related-sub">{{ item.classroom || item.location || '—' }}</span>
            </div>
          </div>
        </div>
        <div class="detail-section" v-if="detailKnowledgeNodes.length">
          <h4>关联知识点 ({{ detailKnowledgeNodes.length }})</h4>
          <div class="related-list">
            <div v-for="node in detailKnowledgeNodes.slice(0, 10)" :key="node.id" class="related-item">
              <span class="related-dot" :class="masteryClass(node.mastery)"></span>
              <span class="related-main">{{ node.name }}</span>
              <span class="related-sub">{{ node.mastery }}%</span>
            </div>
            <div v-if="detailKnowledgeNodes.length > 10" class="related-more">...还有 {{ detailKnowledgeNodes.length - 10 }} 个知识点</div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn ghost" @click="showDetail = false">关闭</button>
        <button class="btn" @click="openEdit(detailCourse); showDetail = false">编辑</button>
      </template>
    </DetailPanel>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api'
import StatCard from '../components/StatCard.vue'
import SearchBar from '../components/SearchBar.vue'
import EmptyState from '../components/EmptyState.vue'
import ColorPicker from '../components/ColorPicker.vue'
import FormModal from '../components/FormModal.vue'
import DetailPanel from '../components/DetailPanel.vue'

const courses = ref([])
const scheduleItems = ref([])
const knowledgeTree = ref([])
const searchText = ref('')
const filterArchived = ref('active') // active/all/archived
const showForm = ref(false)
const showDetail = ref(false)
const editingId = ref(null)
const saving = ref(false)
const detailCourse = ref(null)
const selectedIds = ref([])

const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const detailScheduleItems = computed(() => {
  if (!detailCourse.value) return []
  return scheduleItems.value.filter(s => s.course_id === detailCourse.value.id)
})
const detailKnowledgeNodes = computed(() => {
  if (!detailCourse.value) return []
  const roots = knowledgeTree.value.filter(n => n.subject_id === detailCourse.value.id)
  return flattenNodes(roots)
})
const allSelectedArchived = computed(() => {
  if (!selectedIds.value.length) return false
  return selectedIds.value.every(id => courses.value.find(c => c.id === id)?.is_archived)
})

const form = ref({ name: '', subject_code: '', color: '#3E63DD', sort: 0, icon: '', description: '', is_archived: false, target_days: null, goal_start_date: null })

const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})

const filterOptions = [
  { key: 'archived', label: '状态', options: [
    { value: 'active', label: '未归档' },
    { value: 'all', label: '全部' },
    { value: 'archived', label: '已归档' },
  ]},
]

const filteredCourses = computed(() => {
  let list = courses.value
  if (filterArchived.value === 'active') list = list.filter(c => !c.is_archived)
  else if (filterArchived.value === 'archived') list = list.filter(c => c.is_archived)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(c => c.name.toLowerCase().includes(q) || (c.subject_code || '').toLowerCase().includes(q))
  }
  return list.sort((a, b) => (a.sort || 0) - (b.sort || 0))
})

const totalSchedule = computed(() => scheduleItems.value.length)
const totalKnowledge = computed(() => countNodes(knowledgeTree.value))
const avgMastery = computed(() => {
  const all = flattenNodes(knowledgeTree.value)
  if (!all.length) return 0
  return Math.round(all.reduce((s, n) => s + (n.mastery || 0), 0) / all.length)
})

function countNodes(nodes) {
  return nodes.reduce((s, n) => s + 1 + countNodes(n.children || []), 0)
}
function flattenNodes(nodes) {
  return nodes.flatMap(n => [n, ...flattenNodes(n.children || [])])
}
function courseScheduleCount(courseId) {
  return scheduleItems.value.filter(s => s.course_id === courseId).length
}
function courseKnowledgeCount(courseId) {
  const roots = knowledgeTree.value.filter(n => n.subject_id === courseId)
  return countNodes(roots)
}
function courseMastery(courseId) {
  const roots = knowledgeTree.value.filter(n => n.subject_id === courseId)
  const all = flattenNodes(roots)
  if (!all.length) return 0
  return Math.round(all.reduce((s, n) => s + (n.mastery || 0), 0) / all.length)
}

async function loadData() {
  try {
    const [c, s, k] = await Promise.all([
      api.courses({ archived: 'all' }),
      api.schedule(),
      api.knowledgeTree({}),
    ])
    courses.value = c
    scheduleItems.value = s
    knowledgeTree.value = k
  } catch (e) {
    console.error('加载失败', e)
  }
}

function openCreate() {
  editingId.value = null
  form.value = { name: '', subject_code: '', color: '#3E63DD', sort: courses.value.length, icon: '', description: '', is_archived: false, target_days: null, goal_start_date: null }
  showForm.value = true
}
function openEdit(course) {
  editingId.value = course.id
  form.value = { ...course }
  showForm.value = true
}
function openDetail(course) {
  detailCourse.value = course
  showDetail.value = true
}

async function onSave() {
  if (!form.value.name.trim()) { alert('请输入科目名称'); return }
  saving.value = true
  try {
    if (editingId.value) {
      await api.updateCourse(editingId.value, form.value)
    } else {
      await api.createCourse(form.value)
    }
    showForm.value = false
    await loadData()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function clearGoal() {
  if (!confirm('确定清除当前科目的学习目标吗？')) return
  form.value.target_days = null
  form.value.goal_start_date = null
}

async function onDelete(course) {
  if (!confirm(`确定删除科目「${course.name}」吗？`)) return
  try {
    await api.deleteCourse(course.id)
    await loadData()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '删除失败')
  }
}

function onSearch(val) { searchText.value = val }
function onFilterChange({ key, value }) {
  if (key === 'archived') filterArchived.value = value
}
function onExport() {
  const data = filteredCourses.value.map(c => ({
    名称: c.name, 代码: c.subject_code, 配色: c.color, 图标: c.icon, 描述: c.description, 排序: c.sort,
  }))
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'courses.json'; a.click()
  URL.revokeObjectURL(url)
}

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

async function toggleArchive(course) {
  try {
    await api.archiveCourse(course.id, { is_archived: !course.is_archived })
    await loadData()
  } catch (e) { alert('操作失败') }
}

async function toggleArchiveSelected() {
  const targetArchived = !allSelectedArchived.value
  for (const id of selectedIds.value) {
    try { await api.archiveCourse(id, { is_archived: targetArchived }) } catch (e) {}
  }
  selectedIds.value = []
  await loadData()
}

async function batchDelete() {
  if (!confirm(`确定删除选中的 ${selectedIds.value.length} 个科目吗？`)) return
  try {
    await api.batchDeleteCourses({ ids: selectedIds.value })
    selectedIds.value = []
    await loadData()
  } catch (e) { alert('批量删除失败（部分科目可能有关联课表）') }
}

function masteryClass(m) { return m >= 70 ? 'success' : m >= 40 ? 'warning' : 'danger' }

function goalProgressPercent(course) {
  if (!course.target_days || !course.goal_start_date) return 0
  const start = new Date(course.goal_start_date)
  const now = new Date()
  const elapsed = Math.floor((now - start) / (1000 * 60 * 60 * 24))
  return Math.min(100, Math.max(0, Math.round(elapsed / course.target_days * 100)))
}

onMounted(loadData)
</script>

<style scoped>
.courses-view { padding: 20px 24px; }
.page-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.page-head h2 { font-size: 20px; font-weight: 700; color: var(--text); }
.page-desc { font-size: 13px; color: var(--text-muted); margin-top: 4px; }

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.course-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
  position: relative;
  overflow: hidden;
}
.course-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,.1);
  border-color: var(--card-accent);
}
.course-card.archived { opacity: 0.6; }
.card-color-bar {
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 4px; background: var(--card-accent);
}
.card-head {
  display: flex; align-items: flex-start; gap: 12px;
  margin-bottom: 10px;
}
.card-icon {
  font-size: 28px; line-height: 1; flex-shrink: 0;
  width: 44px; height: 44px;
  display: flex; align-items: center; justify-content: center;
  background: var(--card-accent); border-radius: 10px; opacity: 0.9;
}
.card-title-group { flex: 1; min-width: 0; }
.card-title { font-size: 15px; font-weight: 600; color: var(--text); margin: 0; }
.card-code { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.card-ops { display: flex; gap: 6px; flex-shrink: 0; opacity: 0; transition: opacity .15s; }
.course-card:hover .card-ops { opacity: 1; }
.card-desc {
  font-size: 12px; color: var(--text-secondary);
  margin-bottom: 12px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.card-stats {
  display: flex; gap: 12px; margin-bottom: 8px;
}
.stat-item { display: flex; flex-direction: column; }
.stat-num { font-size: 16px; font-weight: 700; color: var(--text); }
.stat-label { font-size: 11px; color: var(--text-muted); }
.card-mastery-bar {
  height: 4px; background: var(--bg-sunken); border-radius: 2px; overflow: hidden;
}
.mastery-fill {
  height: 100%; background: var(--card-accent); border-radius: 2px;
  transition: width .3s ease;
}
.archived-badge {
  position: absolute; top: 10px; right: 10px;
  background: var(--bg-sunken); color: var(--text-muted);
  font-size: 10px; padding: 2px 8px; border-radius: 10px;
}

.form-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
.form-grid .f.full { grid-column: 1 / -1; }
.checkbox-row {
  flex-direction: row !important; align-items: center; gap: 8px;
}
.checkbox-row input { width: auto; height: auto; }

.detail-content { display: flex; flex-direction: column; gap: 20px; }
.detail-section h4 {
  font-size: 13px; font-weight: 600; color: var(--text-secondary);
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border);
}
.detail-info-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;
}
.detail-info-grid > div { display: flex; flex-direction: column; gap: 2px; }
.info-label { font-size: 11px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text); font-weight: 500; }
.detail-desc { font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.6; }
.detail-stats { display: flex; gap: 16px; }
.detail-stat { display: flex; flex-direction: column; }
.detail-stat .num { font-size: 22px; font-weight: 700; color: var(--primary); }
.detail-stat .lbl { font-size: 11px; color: var(--text-muted); }

/* 批量操作 */
.batch-bar {
  display: flex; align-items: center; gap: 10px;
  background: var(--primary-weak); border: 1px solid var(--primary);
  border-radius: var(--radius-sm); padding: 8px 14px; margin-bottom: 14px;
}
.batch-info { font-size: 13px; font-weight: 600; color: var(--primary); margin-right: auto; }
.course-card.selected { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-weak); }
.card-select { position: absolute; top: 10px; right: 10px; z-index: 2; }
.card-select input { width: 16px; height: 16px; cursor: pointer; }

/* 关联列表 */
.related-list { display: flex; flex-direction: column; gap: 6px; }
.related-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; background: var(--bg-sunken); border-radius: 6px; font-size: 12px;
}
.related-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.related-dot.success { background: #22c55e; }
.related-dot.warning { background: #f59e0b; }
.related-dot.danger { background: #ef4444; }
.related-main { flex: 1; color: var(--text); }
.related-sub { color: var(--text-muted); font-size: 11px; }
.related-more { font-size: 11px; color: var(--text-muted); text-align: center; padding: 4px; }

/* 倒计时 */
.countdown-urgent { color: #f59e0b !important; }
.countdown-over { color: #ef4444 !important; }
.goal-progress-bar {
  height: 6px; background: var(--bg-sunken); border-radius: 3px;
  overflow: hidden; margin-top: 12px;
}
.goal-progress-fill {
  height: 100%; background: linear-gradient(90deg, var(--primary), #6366f1);
  border-radius: 3px; transition: width .3s ease;
}
.goal-progress-text {
  font-size: 11px; color: var(--text-muted); margin-top: 6px; text-align: right;
}
</style>
