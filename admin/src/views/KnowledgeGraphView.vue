<template>
  <div class="kg-view">
    <div class="page-head">
      <div>
        <h2>🕸️ 知识图谱</h2>
        <p class="page-desc">前置依赖分析 · AI 笔记生成 · 薄弱点诊断 · 关联可视化</p>
      </div>
      <div class="head-actions">
        <select v-model="selectedSubject" class="toolbar-select" @change="loadGraph">
          <option value="">选择科目</option>
          <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row" v-if="stats">
      <StatCard icon="🕸️" :value="stats.total_nodes" label="图谱节点" theme="blue" />
      <StatCard icon="🔗" :value="stats.prerequisite_edges" label="依赖关系" theme="purple" />
      <StatCard icon="📝" :value="stats.nodes_with_notes" label="有笔记" theme="green" />
      <StatCard icon="📊" :value="stats.avg_mastery + '%'" label="平均掌握度" theme="orange" />
    </div>

    <div class="kg-main">
      <!-- 左侧：章节列表 + 操作 -->
      <div class="kg-sidebar">
        <div class="sidebar-section">
          <h3>📚 章节</h3>
          <div class="chapter-list">
            <div
              v-for="ch in chapters"
              :key="ch.id"
              class="chapter-item"
              :class="{ active: selectedChapter === ch.id }"
              @click="selectChapter(ch)"
            >
              <span class="chapter-name">{{ ch.name }}</span>
              <span class="chapter-meta">{{ countChapterNodes(ch.id) }} 知识点</span>
            </div>
          </div>
        </div>

        <div class="sidebar-section" v-if="selectedChapter">
          <h3>🤖 AI 增强</h3>
          <button class="btn full" :disabled="loading" @click="onAnalyzePrereq">
            🔗 分析本章前置依赖
          </button>
          <button class="btn full ghost" :disabled="loading || !selectedNode" @click="onGenerateNotes">
            📝 为选中节点生成笔记
          </button>
          <button class="btn full ghost" :disabled="loading" @click="onBatchNotes">
            📚 批量生成本章笔记
          </button>
          <p class="hint" v-if="loading">{{ loadingText }}</p>
        </div>

        <div class="sidebar-section">
          <h3>⚠️ 薄弱点</h3>
          <div v-if="weakPoints.length" class="weak-list">
            <div
              v-for="w in weakPoints.slice(0, 10)"
              :key="w.node_id"
              class="weak-item"
              :class="'level-' + w.level"
              @click="focusNode(w.node_id)"
            >
              <span class="weak-name">{{ w.name }}</span>
              <span class="weak-score">掌握度 {{ w.mastery }}%</span>
            </div>
          </div>
          <p v-else class="empty-text">暂无薄弱点数据</p>
        </div>
      </div>

      <!-- 中间：图谱可视化 -->
      <div class="kg-canvas-wrap">
        <div class="kg-toolbar">
          <button class="btn mini" @click="zoomIn">➕</button>
          <button class="btn mini" @click="zoomOut">➖</button>
          <button class="btn mini" @click="resetView">↺ 重置</button>
          <span class="view-info">缩放: {{ (scale * 100).toFixed(0) }}%</span>
        </div>
        <div class="kg-canvas" ref="canvasRef" @wheel="onWheel">
          <svg :width="canvasWidth" :height="canvasHeight" :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`">
            <defs>
              <marker id="arrow-h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
              </marker>
              <marker id="arrow-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#8b5cf6" />
              </marker>
            </defs>
            <g :transform="`translate(${offsetX}, ${offsetY}) scale(${scale})`">
              <!-- 边 -->
              <line
                v-for="(edge, i) in visibleEdges"
                :key="'e' + i"
                :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2"
                :stroke="edge.type === 'prerequisite' ? '#8b5cf6' : '#cbd5e1'"
                :stroke-width="edge.type === 'prerequisite' ? 2 : 1.5"
                :stroke-dasharray="edge.type === 'prerequisite' ? '6,3' : 'none'"
                :marker-end="edge.type === 'prerequisite' ? 'url(#arrow-p)' : 'url(#arrow-h)'"
                :opacity="edge.type === 'prerequisite' ? 0.8 : 0.4"
              />
              <!-- 节点 -->
              <g
                v-for="node in visibleNodes"
                :key="node.id"
                :transform="`translate(${node.x}, ${node.y})`"
                class="kg-node"
                :class="{ selected: selectedNode === node.id, focused: focusedNode === node.id }"
                @click.stop="onNodeClick(node)"
              >
                <rect
                  :width="node.width" :height="node.height" :rx="6"
                  :fill="getNodeColor(node)"
                  :stroke="selectedNode === node.id ? '#3b82f6' : focusedNode === node.id ? '#f59e0b' : '#e2e8f0'"
                  :stroke-width="selectedNode === node.id || focusedNode === node.id ? 2.5 : 1"
                />
                <text
                  :x="node.width / 2" :y="node.height / 2 - 4"
                  text-anchor="middle" dominant-baseline="middle"
                  class="node-label"
                  :fill="node.mastery >= 70 ? '#fff' : '#1e293b'"
                >{{ truncateName(node.name) }}</text>
                <text
                  :x="node.width / 2" :y="node.height / 2 + 12"
                  text-anchor="middle" dominant-baseline="middle"
                  class="node-sub"
                  :fill="node.mastery >= 70 ? 'rgba(255,255,255,0.8)' : '#64748b'"
                >{{ node.mastery }}%{{ node.has_notes ? ' 📝' : '' }}{{ node.has_prerequisites ? ' 🔗' : '' }}</text>
              </g>
            </g>
          </svg>
        </div>
      </div>

      <!-- 右侧：节点详情 -->
      <div class="kg-detail" v-if="detailNode">
        <div class="detail-head">
          <h3>{{ detailNode.name }}</h3>
          <button class="btn mini ghost" @click="detailNode = null">✕</button>
        </div>
        <div class="detail-meta">
          <span class="tag" :style="{ background: getMasteryColor(detailNode.mastery) }">
            掌握度 {{ detailNode.mastery }}%
          </span>
          <span class="tag">难度 {{ detailNode.difficulty }}/5</span>
          <span class="tag" v-if="detailNode.has_notes">📝 有笔记</span>
          <span class="tag" v-if="detailNode.has_prerequisites">🔗 有依赖</span>
        </div>

        <!-- 前置依赖 -->
        <div class="detail-section" v-if="prereqNames.length">
          <h4>🔗 前置依赖</h4>
          <div class="prereq-list">
            <span v-for="p in prereqNames" :key="p.id" class="prereq-tag" @click="focusNode(p.id)">
              {{ p.name }}
            </span>
          </div>
        </div>

        <!-- 笔记 -->
        <div class="detail-section" v-if="nodeNotes">
          <h4>📝 AI 笔记</h4>
          <div class="notes-content">
            <div class="note-block">
              <strong>核心概念：</strong>{{ nodeNotes.core_concept }}
            </div>
            <div class="note-block" v-if="nodeNotes.key_formulas?.length">
              <strong>关键公式：</strong>
              <ul><li v-for="(f, i) in nodeNotes.key_formulas" :key="i">{{ f }}</li></ul>
            </div>
            <div class="note-block" v-if="nodeNotes.common_question_types?.length">
              <strong>常见题型：</strong>
              <ul><li v-for="(q, i) in nodeNotes.common_question_types" :key="i">{{ q }}</li></ul>
            </div>
            <div class="note-block" v-if="nodeNotes.solution_methods?.length">
              <strong>解题方法：</strong>
              <ul><li v-for="(m, i) in nodeNotes.solution_methods" :key="i">{{ m }}</li></ul>
            </div>
            <div class="note-block" v-if="nodeNotes.error_points?.length">
              <strong>易错点：</strong>
              <ul><li v-for="(e, i) in nodeNotes.error_points" :key="i">{{ e }}</li></ul>
            </div>
            <div class="note-block" v-if="nodeNotes.memory_tips">
              <strong>记忆技巧：</strong>{{ nodeNotes.memory_tips }}
            </div>
          </div>
        </div>
        <p v-else class="empty-text">暂无笔记，点击左侧「生成笔记」按钮</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { api } from '../api'
import StatCard from '../components/StatCard.vue'

const courses = ref([])
const selectedSubject = ref('')
const selectedChapter = ref(null)
const selectedNode = ref(null)
const focusedNode = ref(null)
const detailNode = ref(null)
const graphData = ref({ nodes: [], edges: [], stats: null })
const weakPoints = ref([])
const loading = ref(false)
const loadingText = ref('')
const scale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const canvasWidth = ref(900)
const canvasHeight = ref(700)
const canvasRef = ref(null)

const stats = computed(() => graphData.value.stats)
const chapters = computed(() =>
  graphData.value.nodes.filter(n => n.level === 2).sort((a, b) => a.id - b.id)
)

const visibleNodes = computed(() => {
  if (!selectedChapter.value) return graphData.value.nodes.filter(n => n.level >= 3)
  // 只显示选中章节及其子节点
  const sectionIds = graphData.value.nodes
    .filter(n => n.parent_id === selectedChapter.value)
    .map(n => n.id)
  return graphData.value.nodes.filter(
    n => n.id === selectedChapter.value ||
         n.parent_id === selectedChapter.value ||
         sectionIds.includes(n.parent_id)
  )
})

const visibleEdges = computed(() => {
  const nodeIds = new Set(visibleNodes.value.map(n => n.id))
  return graphData.value.edges.filter(
    e => nodeIds.has(e.source) && nodeIds.has(e.target)
  ).map(e => {
    const src = nodeMap.value.get(e.source)
    const tgt = nodeMap.value.get(e.target)
    if (!src || !tgt) return null
    return {
      ...e,
      x1: src.x + src.width / 2,
      y1: src.y + src.height / 2,
      x2: tgt.x + tgt.width / 2,
      y2: tgt.y + tgt.height / 2,
    }
  }).filter(Boolean)
})

const nodeMap = computed(() => {
  const m = new Map()
  visibleNodes.value.forEach(n => m.set(n.id, n))
  return m
})

const prereqNames = computed(() => {
  if (!detailNode.value?.has_prerequisites) return []
  // 从原始数据中找前置依赖
  const raw = graphData.value.nodes.find(n => n.id === detailNode.value.id)
  if (!raw?.prerequisites) return []
  try {
    const ids = JSON.parse(raw.prerequisites)
    return ids.map(id => {
      const n = graphData.value.nodes.find(x => x.id === id)
      return n ? { id, name: n.name } : null
    }).filter(Boolean)
  } catch { return [] }
})

const nodeNotes = computed(() => {
  if (!detailNode.value) return null
  const raw = graphData.value.nodes.find(n => n.id === detailNode.value.id)
  if (!raw?.notes) return null
  try { return JSON.parse(raw.notes) } catch { return null }
})

onMounted(async () => {
  try {
    courses.value = await api.courses()
    // 自动选择第一个科目并加载图谱
    if (courses.value.length > 0) {
      selectedSubject.value = courses.value[0].id
      await loadGraph()
    }
  } catch (e) {
    console.error('加载科目失败', e)
  }
  // 自适应画布大小
  await nextTick()
  if (canvasRef.value) {
    canvasWidth.value = canvasRef.value.clientWidth
    canvasHeight.value = canvasRef.value.clientHeight
  }
})

async function loadGraph() {
  if (!selectedSubject.value) return
  try {
    const data = await api.getKnowledgeGraph(selectedSubject.value)
    // 布局计算
    layoutNodes(data.nodes)
    graphData.value = data
    // 加载薄弱点
    const weak = await api.getWeakPoints(selectedSubject.value)
    weakPoints.value = weak.weak_points || []
  } catch (e) {
    console.error('加载知识图谱失败', e)
  }
}

function layoutNodes(nodes) {
  // 按层级布局：level 2 在左，level 3 在中，level 4 在右
  const levels = { 2: [], 3: [], 4: [] }
  nodes.forEach(n => { if (levels[n.level]) levels[n.level].push(n) })

  const colX = { 2: 40, 3: 260, 4: 520 }
  const nodeW = { 2: 160, 3: 180, 4: 200 }
  const nodeH = 44
  const gapY = 12

  Object.keys(levels).forEach(level => {
    const arr = levels[level]
    // 按 parent_id 分组
    const groups = {}
    arr.forEach(n => {
      const key = n.parent_id || 'root'
      if (!groups[key]) groups[key] = []
      groups[key].push(n)
    })
    let y = 30
    Object.values(groups).forEach(group => {
      group.forEach((n, i) => {
        n.x = colX[level]
        n.y = y
        n.width = nodeW[level]
        n.height = nodeH
        y += nodeH + gapY
      })
      y += 20 // 组间距
    })
  })
}

function countChapterNodes(chapterId) {
  const sectionIds = graphData.value.nodes.filter(n => n.parent_id === chapterId).map(n => n.id)
  return graphData.value.nodes.filter(n => sectionIds.includes(n.parent_id)).length
}

function selectChapter(ch) {
  selectedChapter.value = selectedChapter.value === ch.id ? null : ch.id
  selectedNode.value = null
  detailNode.value = null
}

function onNodeClick(node) {
  selectedNode.value = node.id
  detailNode.value = node
}

function focusNode(nodeId) {
  focusedNode.value = nodeId
  const node = graphData.value.nodes.find(n => n.id === nodeId)
  if (node) {
    detailNode.value = node
    selectedNode.value = nodeId
  }
  setTimeout(() => { focusedNode.value = null }, 2000)
}

function getNodeColor(node) {
  if (node.level === 2) return '#1e293b'
  if (node.level === 3) return '#334155'
  // level 4 按掌握度着色
  if (node.mastery >= 70) return '#10b981'
  if (node.mastery >= 40) return '#f59e0b'
  return '#ef4444'
}

function getMasteryColor(mastery) {
  if (mastery >= 70) return '#10b981'
  if (mastery >= 40) return '#f59e0b'
  return '#ef4444'
}

function truncateName(name) {
  if (!name) return ''
  // 去掉编号前缀
  const clean = name.replace(/^\d+(\.\d+)*\s*/, '')
  return clean.length > 12 ? clean.slice(0, 12) + '…' : clean
}

async function onAnalyzePrereq() {
  if (!selectedChapter.value) return
  loading.value = true
  loadingText.value = 'AI 正在分析前置依赖关系...'
  try {
    const result = await api.analyzePrerequisites(selectedChapter.value, true)
    alert(`分析完成：${result.prerequisites?.length || 0} 个知识点的依赖关系已保存`)
    await loadGraph()
  } catch (e) {
    alert('分析失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function onGenerateNotes() {
  if (!selectedNode.value) return
  loading.value = true
  loadingText.value = 'AI 正在生成笔记...'
  try {
    await api.generateNotes(selectedNode.value, true)
    alert('笔记生成完成')
    await loadGraph()
    // 重新选中节点
    const node = graphData.value.nodes.find(n => n.id === selectedNode.value)
    if (node) detailNode.value = node
  } catch (e) {
    alert('笔记生成失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function onBatchNotes() {
  if (!selectedChapter.value) return
  const sectionIds = graphData.value.nodes.filter(n => n.parent_id === selectedChapter.value).map(n => n.id)
  const nodeIds = graphData.value.nodes.filter(n => sectionIds.includes(n.parent_id)).map(n => n.id)
  if (!nodeIds.length) { alert('本章没有知识点'); return }
  if (!confirm(`将为 ${nodeIds.length} 个知识点批量生成笔记，可能需要较长时间，确认继续？`)) return

  loading.value = true
  loadingText.value = `AI 正在批量生成笔记（0/${nodeIds.length}）...`
  try {
    const result = await api.generateNotesBatch(nodeIds, true)
    alert(`批量生成完成：成功 ${result.success}/${result.total}`)
    await loadGraph()
  } catch (e) {
    alert('批量生成失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

function onWheel(e) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  scale.value = Math.max(0.3, Math.min(3, scale.value * delta))
}
function zoomIn() { scale.value = Math.min(3, scale.value * 1.2) }
function zoomOut() { scale.value = Math.max(0.3, scale.value * 0.8) }
function resetView() { scale.value = 1; offsetX.value = 0; offsetY.value = 0 }
</script>

<style scoped>
.kg-view { padding: 20px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-head h2 { margin: 0 0 4px; font-size: 22px; }
.page-desc { margin: 0; color: #64748b; font-size: 13px; }
.head-actions { display: flex; gap: 8px; }
.toolbar-select { padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; background: #fff; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }

.kg-main { display: grid; grid-template-columns: 240px 1fr 300px; gap: 16px; height: calc(100vh - 280px); min-height: 500px; }

.kg-sidebar { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; overflow-y: auto; }
.sidebar-section { margin-bottom: 20px; }
.sidebar-section h3 { margin: 0 0 10px; font-size: 14px; color: #1e293b; }
.chapter-list { display: flex; flex-direction: column; gap: 4px; }
.chapter-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; transition: background 0.15s; }
.chapter-item:hover { background: #f1f5f9; }
.chapter-item.active { background: #eff6ff; border-left: 3px solid #3b82f6; }
.chapter-name { font-size: 13px; font-weight: 500; color: #1e293b; }
.chapter-meta { font-size: 11px; color: #94a3b8; }

.btn { padding: 8px 14px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; background: #3b82f6; color: #fff; transition: opacity 0.15s; }
.btn:hover { opacity: 0.9; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.ghost { background: #f1f5f9; color: #475569; }
.btn.full { width: 100%; margin-bottom: 8px; }
.btn.mini { padding: 4px 10px; font-size: 12px; }
.hint { font-size: 12px; color: #f59e0b; margin: 8px 0 0; }

.weak-list { display: flex; flex-direction: column; gap: 4px; }
.weak-item { padding: 6px 10px; border-radius: 6px; cursor: pointer; border-left: 3px solid; }
.weak-item.level-high { border-color: #ef4444; background: #fef2f2; }
.weak-item.level-medium { border-color: #f59e0b; background: #fffbeb; }
.weak-item.level-low { border-color: #10b981; background: #f0fdf4; }
.weak-name { font-size: 12px; font-weight: 500; color: #1e293b; display: block; }
.weak-score { font-size: 11px; color: #64748b; }

.kg-canvas-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
.kg-toolbar { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; display: flex; gap: 6px; align-items: center; }
.view-info { margin-left: auto; font-size: 12px; color: #94a3b8; }
.kg-canvas { flex: 1; overflow: auto; background: #f8fafc; }
.kg-canvas svg { display: block; }

.kg-node { cursor: pointer; }
.kg-node rect { transition: stroke 0.15s, stroke-width 0.15s; }
.kg-node:hover rect { stroke: #3b82f6; stroke-width: 2; }
.node-label { font-size: 11px; font-weight: 500; pointer-events: none; }
.node-sub { font-size: 9px; pointer-events: none; }

.kg-detail { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; overflow-y: auto; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.detail-head h3 { margin: 0; font-size: 16px; color: #1e293b; }
.detail-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.tag { padding: 3px 8px; border-radius: 4px; font-size: 11px; color: #fff; background: #64748b; }
.detail-section { margin-bottom: 16px; }
.detail-section h4 { margin: 0 0 8px; font-size: 13px; color: #1e293b; }
.prereq-list { display: flex; flex-wrap: wrap; gap: 4px; }
.prereq-tag { padding: 4px 8px; background: #f3e8ff; color: #7c3aed; border-radius: 4px; font-size: 11px; cursor: pointer; }
.prereq-tag:hover { background: #e9d5ff; }
.notes-content { font-size: 13px; line-height: 1.6; color: #334155; }
.note-block { margin-bottom: 10px; }
.note-block ul { margin: 4px 0; padding-left: 18px; }
.note-block li { margin-bottom: 2px; }
.empty-text { font-size: 12px; color: #94a3b8; text-align: center; padding: 20px 0; }
</style>
