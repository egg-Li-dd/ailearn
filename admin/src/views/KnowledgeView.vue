<template>
  <div class="knowledge-view">
    <div class="page-head">
      <div>
        <h2>🌳 知识树</h2>
        <p class="page-desc">无限层级 · 拖拽排序 · 掌握度热力图 · AI 自动建树</p>
      </div>
      <div class="head-actions">
        <button class="btn ghost" @click="showImport = true">🤖 AI 建树</button>
        <button class="btn" @click="openCreate(null)">+ 添加节点</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard icon="🌳" :value="totalNodes" label="节点总数" theme="blue" />
      <StatCard icon="✅" :value="masteredCount" label="已掌握" theme="green" />
      <StatCard icon="📝" :value="hasQuizCount" label="有题目" theme="orange" />
      <StatCard icon="📊" :value="avgMastery + '%'" label="平均掌握度" theme="purple" />
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <select v-model="selectedSubject" class="toolbar-select" @change="loadTree">
          <option value="">全部科目</option>
          <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <div class="view-toggle">
          <button :class="{ active: viewMode === 'tree' }" @click="viewMode = 'tree'">🌲 树视图</button>
          <button :class="{ active: viewMode === 'mindmap' }" @click="viewMode = 'mindmap'">🧠 思维导图</button>
        </div>
      </div>
      <div class="toolbar-right">
        <input v-model="searchText" class="search-input" placeholder="搜索知识点..." @input="onSearch" />
        <select v-model="filterMastery" class="toolbar-select">
          <option value="">全部掌握度</option>
          <option value="0-39">未掌握</option>
          <option value="40-69">学习中</option>
          <option value="70-100">已掌握</option>
        </select>
        <button class="btn ghost mini" @click="exportParamsCsv">📥 导出参数</button>
        <button class="btn ghost mini" @click="triggerImportCsv">📤 导入参数</button>
        <input ref="csvFileInput" type="file" accept=".csv" style="display:none" @change="onImportCsv" />
        <button class="btn ghost mini" @click="expandAll = !expandAll">{{ expandAll ? '折叠全部' : '展开全部' }}</button>
      </div>
    </div>

    <!-- 树视图 -->
    <div v-if="viewMode === 'tree'" class="tree-container">
      <EmptyState v-if="!filteredTree.length" icon="🌳" title="暂无知识节点" desc="选择科目或点击 AI 建树开始构建知识体系" />
      <div v-else class="tree-list">
        <TreeNode
          v-for="node in filteredTree"
          :key="node.id"
          :node="node"
          :depth="0"
          :expand-all="expandAll"
          @edit="openEdit"
          @add-child="openCreate"
          @delete="onDelete"
          @click="openDetail"
          @move="onMoveNode"
        />
      </div>
    </div>

    <!-- 思维导图视图（markmap） -->
    <div v-else class="mindmap-container" :class="{ fullscreen: isFullscreen }">
      <div v-if="!tree.length" class="mindmap-empty">
        <EmptyState icon="🧠" title="暂无知识节点" desc="选择科目或点击 AI 建树开始构建知识体系" />
      </div>
      <div v-else class="mindmap-wrapper">
        <div class="mindmap-toolbar">
          <button class="btn ghost mini" @click="zoomMindmap(0.8)" title="缩小">➖</button>
          <button class="btn ghost mini" @click="zoomMindmap(1.25)" title="放大">➕</button>
          <button class="btn ghost mini" @click="resetMindmap" title="重置视图">↺</button>
          <button class="btn ghost mini" @click="toggleFullscreen" :title="isFullscreen ? '退出全屏' : '全屏'">{{ isFullscreen ? '🗗' : '⛶' }}</button>
          <button class="btn ghost mini" @click="downloadMindmap('svg')" title="导出SVG">📥</button>
          <button class="btn ghost mini" @click="downloadMindmap('png')" title="导出PNG">🖼️</button>
        </div>
        <div class="mindmap-legend">
          <span class="legend-item"><i class="legend-dot" style="background:#22c55e"></i>已掌握≥70</span>
          <span class="legend-item"><i class="legend-dot" style="background:#f59e0b"></i>学习中40-69</span>
          <span class="legend-item"><i class="legend-dot" style="background:#ef4444"></i>未掌握&lt;40</span>
        </div>
        <svg ref="mindmapSvg" class="mindmap-svg"></svg>
        <div v-if="tooltipNode" class="mindmap-tooltip" :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }">
          <div class="tooltip-title">{{ tooltipNode.name }}</div>
          <div class="tooltip-row"><span>掌握度</span><span :class="masteryClass(tooltipNode.mastery)">{{ tooltipNode.mastery }}%</span></div>
          <div class="tooltip-row"><span>层级</span><span>L{{ tooltipNode.level }}</span></div>
          <div class="tooltip-row"><span>子节点</span><span>{{ tooltipNode.childCount }}</span></div>
          <div v-if="tooltipNode.summary" class="tooltip-summary">{{ tooltipNode.summary }}</div>
        </div>
      </div>
    </div>

    <!-- 新建/编辑模态框 -->
    <FormModal v-model="showForm" :title="editingId ? '编辑知识点' : '添加知识点'" icon="🌳" size="md" :loading="saving" @confirm="onSave">
      <div class="form-grid">
        <label class="f full">
          <span>节点名称 *</span>
          <input v-model="form.name" placeholder="如：单链表的插入操作" />
        </label>
        <label class="f" v-if="!editingId">
          <span>父节点</span>
          <select v-model="form.parent_id">
            <option :value="null">根节点（需选择科目）</option>
            <option v-for="n in flatNodes" :key="n.id" :value="n.id">{{ '—'.repeat(n.level - 1) }} {{ n.name }}</option>
          </select>
        </label>
        <label class="f" v-if="!form.parent_id">
          <span>所属科目</span>
          <select v-model="form.subject_id">
            <option value="">请选择</option>
            <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">
          <span>难度 (1-5)</span>
          <input type="number" v-model.number="form.difficulty" min="1" max="5" />
        </label>
        <label class="f">
          <span>掌握度 (0-100)</span>
          <input type="number" v-model.number="form.mastery" min="0" max="100" />
        </label>
        <label class="f">
          <span>图标 (emoji)</span>
          <input v-model="form.icon" placeholder="如：📝" maxlength="4" />
        </label>
        <label class="f">
          <span>排序</span>
          <input type="number" v-model.number="form.sort" min="0" />
        </label>
        <label class="f full">
          <span>摘要</span>
          <textarea v-model="form.summary" rows="2" placeholder="简要描述这个知识点"></textarea>
        </label>
        <label class="f full">
          <span>学习笔记/要点</span>
          <textarea v-model="form.notes" rows="3" placeholder="学习要点、常见误区等"></textarea>
        </label>
      </div>
    </FormModal>

    <!-- 节点详情侧滑 -->
    <DetailPanel v-model="showDetail" :title="detailNode?.name" :icon="detailNode?.icon" width="md">
      <div v-if="detailNode" class="detail-content">
        <div class="detail-section">
          <div class="detail-mastery">
            <div class="mastery-header">
              <span>掌握度</span>
              <span class="mastery-value">{{ detailNode.mastery }}%</span>
            </div>
            <div class="mastery-bar-large">
              <div class="mastery-fill" :class="masteryClass(detailNode.mastery)" :style="{ width: detailNode.mastery + '%' }"></div>
            </div>
          </div>
        </div>
        <div class="detail-section">
          <h4>基本信息</h4>
          <div class="detail-info-grid">
            <div><span class="info-label">层级</span><span class="info-value">L{{ detailNode.level }}</span></div>
            <div><span class="info-label">难度</span><span class="info-value">{{ '⭐'.repeat(detailNode.difficulty) }}</span></div>
            <div><span class="info-label">题目数</span><span class="info-value">{{ detailNode.question_count || 0 }}</span></div>
          </div>
          <p v-if="detailNode.summary" class="detail-desc">{{ detailNode.summary }}</p>
          <div v-if="detailNode.notes" class="detail-notes">
            <h5>📝 学习笔记</h5>
            <p>{{ detailNode.notes }}</p>
          </div>
        </div>
        <!-- 知识点参数表（细化结果） -->
        <div class="detail-section">
          <div class="params-header">
            <h4>📋 知识点参数表</h4>
            <div class="params-actions">
              <button v-if="nodeParams?.refined && !editingParams" class="btn ghost mini" @click="toggleEditParams">编辑</button>
              <button v-if="editingParams" class="btn ghost mini" @click="toggleEditParams">取消编辑</button>
              <button class="btn ghost mini" :disabled="refining" @click="doRefine">
                {{ refining ? '细化中…' : (nodeParams?.refined ? '重新细化' : '✨ AI 细化') }}
              </button>
            </div>
          </div>
          <div v-if="!nodeParams?.refined && !editingParams" class="params-empty">
            <p>该知识点尚未细化，AI 出题将基于名称自由生成（可能超纲）。</p>
            <p class="hint">点击「AI 细化」生成结构化参数表，用于模板驱动出题，确保不超纲、零 token。</p>
          </div>
          <div v-else-if="editingParams" class="params-edit">
            <label class="f full"><span>核心定义 *</span><textarea v-model="paramsForm.definition" rows="2"></textarea></label>
            <label class="f full"><span>核心要素（每行一个，至少2个）*</span><textarea v-model="paramsForm.core_elements_text" rows="3"></textarea></label>
            <label class="f full"><span>关键术语（每行一个，至少1个）*</span><textarea v-model="paramsForm.key_terms_text" rows="2"></textarea></label>
            <label class="f full"><span>公式（每行一个，可选）</span><textarea v-model="paramsForm.formulas_text" rows="2"></textarea></label>
            <label class="f full"><span>常见错误（每行一个，可选）</span><textarea v-model="paramsForm.common_mistakes_text" rows="2"></textarea></label>
            <label class="f full"><span>范围边界（防超纲）*</span><textarea v-model="paramsForm.scope_boundary" rows="2"></textarea></label>
            <label class="f full"><span>前置知识简述（可选）</span><textarea v-model="paramsForm.prerequisites_desc" rows="2"></textarea></label>
            <div class="params-edit-actions">
              <button class="btn" :disabled="savingParams" @click="saveParams">{{ savingParams ? '保存中…' : '💾 保存参数' }}</button>
            </div>
          </div>
          <div v-else class="params-view">
            <div class="param-row"><span class="param-label">定义</span><span class="param-value">{{ nodeParams.params.definition }}</span></div>
            <div class="param-row" v-if="nodeParams.params.core_elements?.length">
              <span class="param-label">核心要素</span>
              <span class="param-value"><span v-for="(e,i) in nodeParams.params.core_elements" :key="i" class="param-tag">{{ e }}</span></span>
            </div>
            <div class="param-row" v-if="nodeParams.params.key_terms?.length">
              <span class="param-label">关键术语</span>
              <span class="param-value"><span v-for="(t,i) in nodeParams.params.key_terms" :key="i" class="param-tag term">{{ t }}</span></span>
            </div>
            <div class="param-row" v-if="nodeParams.params.formulas?.length">
              <span class="param-label">公式</span>
              <span class="param-value"><span v-for="(f,i) in nodeParams.params.formulas" :key="i" class="param-tag formula">{{ f }}</span></span>
            </div>
            <div class="param-row" v-if="nodeParams.params.common_mistakes?.length">
              <span class="param-label">常见错误</span>
              <span class="param-value"><span v-for="(m,i) in nodeParams.params.common_mistakes" :key="i" class="param-tag mistake">{{ m }}</span></span>
            </div>
            <div class="param-row" v-if="nodeParams.params.scope_boundary">
              <span class="param-label">范围边界</span><span class="param-value scope">{{ nodeParams.params.scope_boundary }}</span>
            </div>
            <div class="param-row" v-if="nodeParams.params.prerequisites_desc">
              <span class="param-label">前置知识</span><span class="param-value">{{ nodeParams.params.prerequisites_desc }}</span>
            </div>
          </div>
        </div>
        <div class="detail-section" v-if="detailNode.children?.length">
          <h4>子节点 ({{ detailNode.children.length }})</h4>
          <div class="child-list">
            <div v-for="c in detailNode.children" :key="c.id" class="child-item" @click="openDetail(c)">
              <span class="child-icon">{{ c.icon || '📄' }}</span>
              <span class="child-name">{{ c.name }}</span>
              <span class="child-mastery">{{ c.mastery }}%</span>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn ghost" @click="showDetail = false">关闭</button>
        <button class="btn ghost" @click="openCreate(detailNode); showDetail = false">+ 子节点</button>
        <button class="btn" @click="openEdit(detailNode); showDetail = false">编辑</button>
      </template>
    </DetailPanel>

    <!-- AI 建树模态框 -->
    <FormModal v-model="showImport" title="🤖 AI 自动建树" icon="🤖" size="lg" :loading="importing">
      <div class="import-area">
        <label class="f">
          <span>选择科目 *</span>
          <select v-model="importSubject">
            <option value="">请选择</option>
            <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">
          <span>粘贴课程大纲/目录（AI 将解析为知识树）</span>
          <textarea v-model="importText" rows="10" placeholder="第一章 线性表&#10;1.1 顺序表&#10;1.2 链表&#10;  1.2.1 单链表&#10;  1.2.2 双链表&#10;第二章 栈与队列..."></textarea>
        </label>
        <div class="import-preview" v-if="previewItems.length">
          <h4>预览（{{ previewTotal }} 个节点）</h4>
          <div class="preview-tree">
            <div v-for="item in previewItems.slice(0, 10)" :key="item.name" class="preview-node">
              {{ item.name }}
              <div v-if="item.children?.length" class="preview-children">
                <div v-for="c in item.children.slice(0, 3)" :key="c.name" class="preview-child">└ {{ c.name }}</div>
                <div v-if="item.children.length > 3" class="preview-more">└ ...还有 {{ item.children.length - 3 }} 个</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn ghost" @click="showImport = false">取消</button>
        <button v-if="!previewItems.length" class="btn" :disabled="!importSubject || !importText" @click="doPreview">生成预览</button>
        <button v-else class="btn" @click="doConfirmImport">确认导入</button>
      </template>
    </FormModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, defineComponent, h } from 'vue'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'
import { api, ApiError } from '../api'
import StatCard from '../components/StatCard.vue'
import EmptyState from '../components/EmptyState.vue'
import FormModal from '../components/FormModal.vue'
import DetailPanel from '../components/DetailPanel.vue'

// 递归树节点组件
const TreeNode = defineComponent({
  name: 'TreeNode',
  props: { node: Object, depth: Number, expandAll: Boolean },
  emits: ['edit', 'add-child', 'delete', 'click', 'move'],
  setup(props, { emit }) {
    const expanded = ref(true)
    const dragOver = ref(false)

    function toggle() { expanded.value = !expanded.value }
    function onDragStart(e) {
      e.dataTransfer.setData('text/plain', props.node.id)
      e.dataTransfer.effectAllowed = 'move'
    }
    function onDragOver(e) { e.preventDefault(); dragOver.value = true }
    function onDragLeave() { dragOver.value = false }
    function onDrop(e) {
      e.preventDefault()
      dragOver.value = false
      const draggedId = parseInt(e.dataTransfer.getData('text/plain'))
      if (draggedId && draggedId !== props.node.id) {
        emit('move', { draggedId, targetParentId: props.node.id, sort: 0 })
      }
    }

    return () => {
      const node = props.node
      const hasChildren = node.children && node.children.length > 0
      const isExpanded = props.expandAll !== undefined ? props.expandAll : expanded.value
      const masteryColor = node.mastery >= 70 ? '#3E8E58' : node.mastery >= 40 ? '#C77E1E' : '#C24238'

      return h('div', { class: 'tree-node-wrapper' }, [
        h('div', {
          class: ['tree-node', { 'drag-over': dragOver.value }],
          style: { paddingLeft: (props.depth * 24 + 8) + 'px' },
          draggable: 'true',
          onDragstart: onDragStart,
          onDragover: onDragOver,
          onDragleave: onDragLeave,
          onDrop: onDrop,
          onClick: () => emit('click', node),
        }, [
          h('div', {
            class: 'expand-trigger',
            onClick: (e) => { e.stopPropagation(); if (hasChildren) toggle() },
          }, [
            h('span', { class: 'caret' },
              hasChildren ? (isExpanded ? '▼' : '▶') : ''
            ),
            h('span', { class: 'node-icon' }, node.icon || '📄'),
          ]),
          h('span', { class: 'node-name' }, node.name),
          h('span', { class: 'node-level' }, `L${node.level}`),
          h('div', { class: 'mastery-bar' }, [
            h('div', { class: 'mastery-fill', style: { width: node.mastery + '%', background: masteryColor } })
          ]),
          h('span', { class: 'mastery-text', style: { color: masteryColor } }, node.mastery + '%'),
          h('span', { class: 'quiz-count', title: '题目数' }, node.question_count ? `📝${node.question_count}` : ''),
          h('div', { class: 'node-ops', onClick: (e) => e.stopPropagation() }, [
            h('button', { class: 'btn ghost mini', onClick: () => emit('edit', node) }, '编辑'),
            h('button', { class: 'btn ghost mini', onClick: () => emit('add-child', node) }, '+子'),
            h('button', { class: 'btn danger mini', onClick: () => emit('delete', node) }, '删'),
          ]),
        ]),
        hasChildren && isExpanded && h('div', { class: 'tree-children' },
          node.children.map(child => h(TreeNode, {
            key: child.id, node: child, depth: props.depth + 1,
            expandAll: props.expandAll,
            onEdit: (n) => emit('edit', n),
            onAddChild: (n) => emit('add-child', n),
            onDelete: (n) => emit('delete', n),
            onClick: (n) => emit('click', n),
            onMove: (data) => emit('move', data),
          }))
        ),
      ])
    }
  },
})

const courses = ref([])
const tree = ref([])
const selectedSubject = ref('')
const searchText = ref('')
const filterMastery = ref('')
const viewMode = ref('tree')
const expandAll = ref(null)
const showForm = ref(false)
const showDetail = ref(false)
const showImport = ref(false)
const editingId = ref(null)
const saving = ref(false)
const importing = ref(false)
const detailNode = ref(null)
const nodeParams = ref(null)
const refining = ref(false)
const editingParams = ref(false)
const savingParams = ref(false)
const paramsForm = ref({})
const csvFileInput = ref(null)
const importingCsv = ref(false)
const importSubject = ref('')
const importText = ref('')
const previewItems = ref([])
const previewTotal = ref(0)
const mindmapSvg = ref(null)
const isFullscreen = ref(false)
const tooltipNode = ref(null)
const tooltipX = ref(0)
const tooltipY = ref(0)
let markmapInstance = null
const transformer = new Transformer()
let nodeMasteryMap = {}  // 节点文本 -> { mastery, level, summary, childCount, id }

const form = ref({
  name: '', parent_id: null, subject_id: '', difficulty: 1, mastery: 0,
  icon: '', sort: 0, summary: '', notes: '',
})

const totalNodes = computed(() => countNodes(tree.value))
const masteredCount = computed(() => flattenNodes(tree.value).filter(n => n.mastery >= 70).length)
const hasQuizCount = computed(() => flattenNodes(tree.value).filter(n => n.question_count > 0).length)
const avgMastery = computed(() => {
  const all = flattenNodes(tree.value)
  return all.length ? Math.round(all.reduce((s, n) => s + n.mastery, 0) / all.length) : 0
})
const flatNodes = computed(() => flattenNodes(tree.value))

const filteredTree = computed(() => {
  let result = tree.value
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    result = filterTree(result, (n) => n.name.toLowerCase().includes(q))
  }
  if (filterMastery.value) {
    const [min, max] = filterMastery.value.split('-').map(Number)
    result = filterTree(result, (n) => n.mastery >= min && n.mastery <= max)
  }
  return result
})

function countNodes(nodes) { return nodes.reduce((s, n) => s + 1 + countNodes(n.children || []), 0) }
function flattenNodes(nodes) { return nodes.flatMap(n => [n, ...flattenNodes(n.children || [])]) }
function filterTree(nodes, predicate) {
  return nodes.map(n => {
    const children = filterTree(n.children || [], predicate)
    if (predicate(n) || children.length) {
      return { ...n, children }
    }
    return null
  }).filter(Boolean)
}
function masteryClass(m) { return m >= 70 ? 'success' : m >= 40 ? 'warning' : 'danger' }

async function loadTree() {
  try {
    const params = {}
    if (selectedSubject.value) params.subject_id = selectedSubject.value
    tree.value = await api.knowledgeTree(params)
  } catch (e) { console.error('加载失败', e) }
}
async function loadCourses() { courses.value = await api.courses() }

function onSearch() { /* 响应式自动过滤 */ }

function openCreate(parent) {
  editingId.value = null
  form.value = {
    name: '', parent_id: parent?.id || null,
    subject_id: parent?.subject_id || selectedSubject.value || '',
    difficulty: 1, mastery: 0, icon: '', sort: 0, summary: '', notes: '',
  }
  showForm.value = true
}
function openEdit(node) {
  editingId.value = node.id
  form.value = { ...node }
  showForm.value = true
}
function openDetail(node) {
  detailNode.value = node
  showDetail.value = true
  nodeParams.value = null
  editingParams.value = false
  loadNodeParams(node.id)
}

async function onSave() {
  if (!form.value.name.trim()) { alert('请输入节点名称'); return }
  if (!form.value.parent_id && !form.value.subject_id) { alert('根节点必须选择科目'); return }
  saving.value = true
  try {
    const payload = { ...form.value }
    if (editingId.value) await api.updateNode(editingId.value, payload)
    else await api.createNode(payload)
    showForm.value = false
    await loadTree()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '保存失败')
  } finally { saving.value = false }
}

async function onDelete(node) {
  const hasChildren = node.children && node.children.length
  const msg = hasChildren ? `「${node.name}」有 ${countNodes(node.children)} 个子节点，确定级联删除吗？` : `确定删除「${node.name}」吗？`
  if (!confirm(msg)) return
  try {
    await api.deleteNode(node.id, hasChildren)
    await loadTree()
    if (detailNode.value?.id === node.id) showDetail.value = false
  } catch (e) { alert('删除失败') }
}

async function onMoveNode({ draggedId, targetParentId, sort }) {
  try {
    await api.moveNode(draggedId, { parent_id: targetParentId, sort })
    await loadTree()
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '移动失败（可能循环引用）')
  }
}

// ==================== 知识点参数表（细化）====================
async function loadNodeParams(nodeId) {
  try {
    nodeParams.value = await api.getNodeParams(nodeId)
  } catch (e) {
    nodeParams.value = null
  }
}

async function doRefine() {
  if (!detailNode.value) return
  refining.value = true
  try {
    const result = await api.refineNodeParams(detailNode.value.id, false)
    // 后台任务模式：立即返回 task_id，通过任务悬浮窗查看进度
    const taskId = result.task_id
    alert(`知识点细化任务已创建，可在右下角任务悬浮窗查看进度。\n完成后请点击「刷新参数」查看结果。`)
    // 后台轮询任务状态，完成后自动刷新
    const poll = setInterval(async () => {
      try {
        const task = await api.taskDetail(taskId)
        if (task.status === 'completed') {
          clearInterval(poll)
          await loadNodeParams(detailNode.value.id)
          refining.value = false
        } else if (task.status === 'failed' || task.status === 'cancelled') {
          clearInterval(poll)
          alert(`知识点细化失败：${task.error || '未知错误'}`)
          refining.value = false
        }
      } catch (e) {
        // 轮询出错不中断
      }
    }, 2000)
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '创建细化任务失败')
    refining.value = false
  }
}

function toggleEditParams() {
  if (editingParams.value) {
    editingParams.value = false
    return
  }
  const p = nodeParams.value?.params || {}
  paramsForm.value = {
    definition: p.definition || '',
    core_elements_text: (p.core_elements || []).join('\n'),
    key_terms_text: (p.key_terms || []).join('\n'),
    formulas_text: (p.formulas || []).join('\n'),
    common_mistakes_text: (p.common_mistakes || []).join('\n'),
    scope_boundary: p.scope_boundary || '',
    prerequisites_desc: p.prerequisites_desc || '',
  }
  editingParams.value = true
}

async function saveParams() {
  if (!detailNode.value) return
  const f = paramsForm.value
  if (!f.definition.trim()) { alert('请填写核心定义'); return }
  const core_elements = f.core_elements_text.split('\n').map(s => s.trim()).filter(Boolean)
  if (core_elements.length < 2) { alert('核心要素至少2个'); return }
  const key_terms = f.key_terms_text.split('\n').map(s => s.trim()).filter(Boolean)
  if (key_terms.length < 1) { alert('关键术语至少1个'); return }
  if (!f.scope_boundary.trim()) { alert('请填写范围边界（防超纲）'); return }

  const params = {
    definition: f.definition.trim(),
    core_elements,
    key_terms,
    formulas: f.formulas_text.split('\n').map(s => s.trim()).filter(Boolean),
    common_mistakes: f.common_mistakes_text.split('\n').map(s => s.trim()).filter(Boolean),
    scope_boundary: f.scope_boundary.trim(),
  }
  if (f.prerequisites_desc.trim()) params.prerequisites_desc = f.prerequisites_desc.trim()

  savingParams.value = true
  try {
    await api.updateNodeParams(detailNode.value.id, params)
    nodeParams.value = { refined: true, is_valid: true, params }
    editingParams.value = false
    detailNode.value.summary = params.definition
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '保存失败')
  } finally {
    savingParams.value = false
  }
}

// ==================== 知识点参数表 CSV 批量导入导出 ====================
function exportParamsCsv() {
  const url = api.exportParamsCsvUrl(selectedSubject.value || '', false)
  // 用 a 标签触发下载
  const a = document.createElement('a')
  a.href = url
  a.download = `knowledge_params_${selectedSubject.value || 'all'}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function triggerImportCsv() {
  if (csvFileInput.value) csvFileInput.value.click()
}

async function onImportCsv(e) {
  const file = e.target.files?.[0]
  if (!file) return
  importingCsv.value = true
  try {
    const result = await api.importParamsCsv(file)
    const msg = `导入完成：成功 ${result.updated} 个，跳过 ${result.skipped} 个` +
      (result.errors?.length ? `\n前 ${result.errors.length} 条错误：\n` + result.errors.map((er, i) => `${i + 1}. ${er.name || er.node_id}: ${er.error || (er.errors || []).join('; ')}`).join('\n') : '')
    alert(msg)
    await loadTree()
    // 如果当前打开了详情，刷新参数
    if (detailNode.value) await loadNodeParams(detailNode.value.id)
  } catch (e) {
    alert(e instanceof ApiError ? e.message : '导入失败')
  } finally {
    importingCsv.value = false
    // 重置 file input 以便重复选择同一文件
    if (csvFileInput.value) csvFileInput.value.value = ''
  }
}

// AI 建树
async function doPreview() {
  if (!importSubject.value || !importText.value.trim()) return
  importing.value = true
  try {
    const result = await api.importOutlinePreview({ subject_id: parseInt(importSubject.value), text: importText.value })
    previewItems.value = result.items
    previewTotal.value = result.total_nodes
  } catch (e) {
    alert(e instanceof ApiError ? e.message : 'AI 生成失败')
  } finally { importing.value = false }
}
async function doConfirmImport() {
  try {
    await api.confirmImportOutline({ preview_id: '', subject_id: parseInt(importSubject.value) })
    // 由于预览存在内存，直接用旧接口导入
    await api.importOutline({ subject_id: parseInt(importSubject.value), text: importText.value })
    showImport.value = false
    importText.value = ''
    previewItems.value = []
    await loadTree()
    alert('导入成功')
  } catch (e) { alert('导入失败') }
}

// ==================== 思维导图渲染 ====================
function buildNodeMap(nodes, map = {}) {
  for (const node of nodes) {
    map[node.name] = {
      id: node.id, mastery: node.mastery, level: node.level,
      summary: node.summary, childCount: (node.children || []).length,
    }
    if (node.children && node.children.length) {
      buildNodeMap(node.children, map)
    }
  }
  return map
}

function treeToMarkdown(nodes, depth = 0) {
  const lines = []
  for (const node of nodes) {
    const prefix = '#'.repeat(Math.min(depth + 1, 6))
    lines.push(`${prefix} ${node.name}`)
    if (node.summary) lines.push(`\n> ${node.summary}\n`)
    if (node.children && node.children.length) {
      lines.push(treeToMarkdown(node.children, depth + 1))
    }
  }
  return lines.join('\n')
}

function attachMasteryToRoot(root, map) {
  if (!root) return
  const info = map[root.content]
  if (info) {
    root.payload = root.payload || {}
    root.payload.mastery = info.mastery
    root.payload.level = info.level
    root.payload.nodeId = info.id
    root.payload.summary = info.summary
  }
  if (root.children) {
    for (const child of root.children) {
      attachMasteryToRoot(child, map)
    }
  }
}

async function renderMindmap() {
  if (!mindmapSvg.value || !tree.value.length) return
  await nextTick()

  nodeMasteryMap = buildNodeMap(tree.value)
  const markdown = treeToMarkdown(tree.value)
  const { root } = transformer.transform(markdown)
  attachMasteryToRoot(root, nodeMasteryMap)

  if (markmapInstance) {
    markmapInstance.setData(root)
  } else {
    markmapInstance = Markmap.create(mindmapSvg.value, {
      color: (node) => {
        const mastery = node.payload?.mastery ?? 50
        return mastery >= 70 ? '#22c55e' : mastery >= 40 ? '#f59e0b' : '#ef4444'
      },
      duration: 400,
      maxWidth: 280,
      spacingVertical: 10,
      spacingHorizontal: 90,
      paddingX: 14,
    }, root)

    // 节点点击事件（事件委托）
    mindmapSvg.value.addEventListener('click', (e) => {
      const group = e.target.closest('g.markmap-node')
      if (!group) return
      const nodeEl = group.querySelector('.markmap-foreign')
      if (!nodeEl) return
      const text = nodeEl.textContent?.trim()
      if (!text) return
      const info = nodeMasteryMap[text]
      if (info) {
        // 找到树中的节点并打开详情
        const found = findNodeInTree(tree.value, info.id)
        if (found) {
          openDetail(found)
        }
      }
    })

    // 节点 hover 显示 tooltip
    mindmapSvg.value.addEventListener('mouseover', (e) => {
      const group = e.target.closest('g.markmap-node')
      if (!group) return
      const nodeEl = group.querySelector('.markmap-foreign')
      if (!nodeEl) return
      const text = nodeEl.textContent?.trim()
      if (!text) return
      const info = nodeMasteryMap[text]
      if (info) {
        tooltipNode.value = { name: text, ...info }
        const rect = mindmapSvg.value.getBoundingClientRect()
        tooltipX.value = e.clientX - rect.left + 12
        tooltipY.value = e.clientY - rect.top + 12
      }
    })
    mindmapSvg.value.addEventListener('mouseout', (e) => {
      const group = e.target.closest('g.markmap-node')
      if (group && !group.contains(e.relatedTarget)) {
        tooltipNode.value = null
      }
    })
  }
  markmapInstance.fit()
}

function findNodeInTree(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n
    if (n.children) {
      const found = findNodeInTree(n.children, id)
      if (found) return found
    }
  }
  return null
}

function zoomMindmap(factor) {
  if (!markmapInstance) return
  const state = markmapInstance.state
  state.scale *= factor
  markmapInstance.render()
}

function resetMindmap() {
  if (markmapInstance) markmapInstance.fit()
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  nextTick(() => {
    if (markmapInstance) markmapInstance.fit()
  })
}

function downloadMindmap(format = 'svg') {
  if (!mindmapSvg.value) return
  const svgClone = mindmapSvg.value.cloneNode(true)
  svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const bbox = mindmapSvg.value.getBBox()
  svgClone.setAttribute('viewBox', `${bbox.x} ${bbox.y} ${bbox.width} ${bbox.height}`)
  svgClone.setAttribute('width', bbox.width)
  svgClone.setAttribute('height', bbox.height)

  if (format === 'svg') {
    const svgData = new XMLSerializer().serializeToString(svgClone)
    const blob = new Blob([svgData], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `knowledge-mindmap-${Date.now()}.svg`
    a.click()
    URL.revokeObjectURL(url)
  } else if (format === 'png') {
    const svgData = new XMLSerializer().serializeToString(svgClone)
    const canvas = document.createElement('canvas')
    const scale = 2
    canvas.width = bbox.width * scale
    canvas.height = bbox.height * scale
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    const img = new Image()
    const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      canvas.toBlob((pngBlob) => {
        const pngUrl = URL.createObjectURL(pngBlob)
        const a = document.createElement('a')
        a.href = pngUrl
        a.download = `knowledge-mindmap-${Date.now()}.png`
        a.click()
        URL.revokeObjectURL(pngUrl)
      }, 'image/png')
    }
    img.src = url
  }
}

watch([viewMode, tree], async ([mode]) => {
  if (mode === 'mindmap') {
    await nextTick()
    renderMindmap()
  }
})

onMounted(async () => { await loadCourses(); await loadTree() })
</script>

<style scoped>
.knowledge-view { padding: 20px 24px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { font-size: 20px; font-weight: 700; }
.page-desc { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
.head-actions { display: flex; gap: 10px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }

.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.toolbar-left, .toolbar-right { display: flex; gap: 10px; align-items: center; }
.toolbar-select { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; background: var(--bg-card); cursor: pointer; }
.search-input { height: 34px; padding: 0 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; width: 200px; }
.view-toggle { display: flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.view-toggle button { padding: 6px 14px; border: none; background: var(--bg-card); font-size: 13px; cursor: pointer; color: var(--text-secondary); }
.view-toggle button.active { background: var(--primary); color: #fff; }

/* 树 */
.tree-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px; max-height: calc(100vh - 320px); overflow-y: auto; }
.tree-list { display: flex; flex-direction: column; }

/* 树节点（通过全局样式，因为是递归组件） */
:deep(.tree-node-wrapper) { display: flex; flex-direction: column; }
:deep(.tree-node) {
  display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 8px;
  border-radius: 6px; cursor: pointer; transition: background .1s; min-height: 40px;
}
:deep(.tree-node:hover) { background: var(--primary-weak); }
:deep(.tree-node.drag-over) { background: var(--primary-weak); outline: 2px dashed var(--primary); }
:deep(.caret) { width: 16px; text-align: center; font-size: 10px; color: var(--text-muted); flex-shrink: 0; }
:deep(.expand-trigger) {
  display: flex; align-items: center; gap: 4px; cursor: pointer; flex-shrink: 0;
  padding: 6px 8px; margin: -6px -8px; border-radius: 6px; transition: background .1s;
}
:deep(.expand-trigger:hover) { background: rgba(0,0,0,0.05); }
:deep(.node-icon) { font-size: 16px; flex-shrink: 0; }
:deep(.node-name) { font-size: 13px; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
:deep(.node-level) { font-size: 10px; color: var(--text-muted); background: var(--bg-sunken); padding: 1px 6px; border-radius: 8px; flex-shrink: 0; }
:deep(.mastery-bar) { width: 80px; height: 6px; background: var(--bg-sunken); border-radius: 3px; overflow: hidden; flex-shrink: 0; }
:deep(.mastery-fill) { height: 100%; border-radius: 3px; transition: width .3s; }
:deep(.mastery-text) { font-size: 11px; font-weight: 600; width: 36px; text-align: right; flex-shrink: 0; }
:deep(.quiz-count) { font-size: 11px; color: var(--text-muted); flex-shrink: 0; }
:deep(.node-ops) { display: flex; gap: 4px; flex-shrink: 0; opacity: 0; transition: opacity .1s; }
:deep(.tree-node:hover .node-ops) { opacity: 1; }

.mindmap-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 40px; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid .f.full { grid-column: 1 / -1; }

/* 详情 */
.detail-content { display: flex; flex-direction: column; gap: 20px; }
.detail-section h4 { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.detail-mastery { margin-bottom: 8px; }
.mastery-header { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px; }
.mastery-value { font-weight: 700; font-size: 18px; }
.mastery-bar-large { height: 10px; background: var(--bg-sunken); border-radius: 5px; overflow: hidden; }
.mastery-bar-large .mastery-fill { height: 100%; border-radius: 5px; transition: width .3s; }
.mastery-fill.success { background: #3E8E58; }
.mastery-fill.warning { background: #C77E1E; }
.mastery-fill.danger { background: #C24238; }
.detail-info-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.detail-info-grid > div { display: flex; flex-direction: column; gap: 2px; }
.info-label { font-size: 11px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text); font-weight: 500; }
.detail-desc { font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.6; }
.detail-notes { margin-top: 12px; padding: 12px; background: var(--bg-sunken); border-radius: 8px; }
.detail-notes h5 { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.detail-notes p { font-size: 13px; color: var(--text-secondary); line-height: 1.6; white-space: pre-wrap; }
.child-list { display: flex; flex-direction: column; gap: 6px; }
.child-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--bg-sunken); border-radius: 6px; cursor: pointer; transition: background .1s; }
.child-item:hover { background: var(--primary-weak); }
.child-icon { font-size: 14px; }
.child-name { flex: 1; font-size: 13px; }
.child-mastery { font-size: 12px; font-weight: 600; color: var(--text-secondary); }

/* AI 导入 */
.import-area { display: flex; flex-direction: column; gap: 14px; }
.import-area textarea { width: 100%; min-height: 150px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; resize: vertical; font-family: var(--font-mono); }
.import-preview h4 { font-size: 13px; font-weight: 600; margin-bottom: 10px; }
.preview-tree { display: flex; flex-direction: column; gap: 6px; max-height: 200px; overflow-y: auto; }
.preview-node { font-size: 13px; padding: 6px 10px; background: var(--bg-sunken); border-radius: 4px; font-weight: 500; }
.preview-children { margin-top: 4px; padding-left: 16px; }
.preview-child { font-size: 12px; color: var(--text-secondary); padding: 2px 0; }
.preview-more { font-size: 11px; color: var(--text-muted); }
/* 思维导图 */
.mindmap-container { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; position: relative; }
.mindmap-container.fullscreen { position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 9999; border-radius: 0; border: none; }
.mindmap-empty { padding: 60px 20px; }
.mindmap-wrapper { position: relative; height: calc(100vh - 340px); min-height: 400px; }
.mindmap-container.fullscreen .mindmap-wrapper { height: 100vh; }
.mindmap-toolbar { position: absolute; top: 12px; right: 12px; z-index: 10; display: flex; gap: 4px; background: var(--bg-card); padding: 6px; border-radius: var(--radius-sm); border: 1px solid var(--border); box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.mindmap-toolbar .btn { min-width: 28px; padding: 4px 8px; }
.mindmap-legend { position: absolute; top: 12px; left: 12px; z-index: 10; display: flex; gap: 12px; background: var(--bg-card); padding: 6px 12px; border-radius: var(--radius-sm); border: 1px solid var(--border); font-size: 11px; color: var(--text-secondary); }
.legend-item { display: flex; align-items: center; gap: 4px; }
.legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.mindmap-svg { width: 100%; height: 100%; display: block; cursor: grab; }
.mindmap-svg:active { cursor: grabbing; }
.mindmap-svg :deep(.markmap-foreign) { font-family: inherit; font-size: 13px; }
.mindmap-svg :deep(.markmap-link) { stroke: var(--border); stroke-width: 1.5; }
.mindmap-svg :deep(.markmap-node circle) { stroke-width: 2; }
.mindmap-svg :deep(.markmap-node:hover circle) { filter: brightness(1.1); stroke-width: 3; }
.mindmap-tooltip {
  position: absolute; z-index: 100; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 12px; min-width: 180px; max-width: 280px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12); font-size: 12px; pointer-events: none;
}
.tooltip-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text); }
.tooltip-row { display: flex; justify-content: space-between; padding: 2px 0; color: var(--text-secondary); }
.tooltip-row span:last-child { font-weight: 500; color: var(--text); }
.tooltip-row .success { color: #22c55e; }
.tooltip-row .warning { color: #f59e0b; }
.tooltip-row .danger { color: #ef4444; }
.tooltip-summary { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 11px; line-height: 1.4; }

/* 知识点参数表 */
.params-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.params-header h4 { margin: 0; font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
.params-actions { display: flex; gap: 6px; }
.params-empty { padding: 16px; background: var(--bg-sunken); border-radius: 8px; text-align: center; }
.params-empty p { font-size: 13px; color: var(--text-secondary); margin: 0 0 6px; }
.params-empty .hint { font-size: 12px; color: var(--text-muted); }
.params-view { display: flex; flex-direction: column; gap: 10px; }
.param-row { display: flex; gap: 12px; align-items: flex-start; }
.param-label { font-size: 12px; font-weight: 600; color: var(--text-muted); width: 70px; flex-shrink: 0; padding-top: 2px; }
.param-value { font-size: 13px; color: var(--text); line-height: 1.6; flex: 1; }
.param-value.scope { color: #C77E1E; font-weight: 500; }
.param-tag { display: inline-block; padding: 2px 8px; margin: 2px 4px 2px 0; background: var(--primary-weak); border-radius: 4px; font-size: 12px; }
.param-tag.term { background: #e0f2fe; color: #0369a1; }
.param-tag.formula { background: #fef3c7; color: #92400e; font-family: var(--font-mono); }
.param-tag.mistake { background: #fee2e2; color: #991b1b; }
.params-edit { display: flex; flex-direction: column; gap: 10px; }
.params-edit .f { display: flex; flex-direction: column; gap: 4px; }
.params-edit .f.full { grid-column: 1 / -1; }
.params-edit .f span { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
.params-edit textarea { width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; resize: vertical; font-family: inherit; }
.params-edit-actions { display: flex; justify-content: flex-end; margin-top: 4px; }

</style>

