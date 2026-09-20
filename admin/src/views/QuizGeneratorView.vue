<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'

// 加载状态
const loadingNodes = ref(false)
const generating = ref(false)
const saving = ref(false)
const errorMsg = ref('')

// 科目和知识点
const subjects = ref([])
const selectedSubject = ref('')
const selectedNodes = ref([]) // 选中的知识点ID

// 出题配置
const count = ref(5)
const qtype = ref('') // 空=随机
const difficulty = ref('') // 空=随机
const style = ref('kaoyan')
const verify = ref(true)

// 生成结果
const generatedQuestions = ref([])
const generateStats = ref(null)

// 选中要保存的题目
const selectedForSave = ref(new Set())

// 题型选项
const qtypeOptions = [
  { value: '', label: '随机（推荐）' },
  { value: 'short', label: '简答题/计算题' },
  { value: 'fill_single', label: '填空题' },
  { value: 'single_choice', label: '单选题' },
  { value: 'multiple_choice', label: '多选题' },
  { value: 'judge', label: '判断题' },
]

const difficultyOptions = [
  { value: '', label: '随机（推荐）' },
  { value: 1, label: '1 - 基础概念' },
  { value: 2, label: '2 - 简单应用' },
  { value: 3, label: '3 - 中等难度' },
  { value: 4, label: '4 - 较难' },
  { value: 5, label: '5 - 难题' },
]

const styleOptions = [
  { value: 'kaoyan', label: '考研真题风格（推荐）' },
  { value: 'textbook', label: '教材课后题风格' },
  { value: 'basic', label: '基础概念题' },
]

// 加载知识点列表
async function loadNodes() {
  if (!selectedSubject.value) {
    subjects.value = []
    return
  }
  loadingNodes.value = true
  errorMsg.value = ''
  try {
    const data = await api.quizGenerateNodes(selectedSubject.value)
    subjects.value = data.subjects || []
    // 默认选中第一个科目的所有知识点
    if (subjects.value.length > 0) {
      const firstSubject = subjects.value[0]
      selectedNodes.value = firstSubject.nodes.map(n => n.id)
    }
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loadingNodes.value = false
  }
}

// 加载科目列表（用于下拉选择）
const courseList = ref([])
async function loadCourses() {
  try {
    const data = await api.courses()
    courseList.value = data.courses || data || []
  } catch (e) {
    // 静默失败
  }
}

onMounted(() => {
  loadCourses()
})

// 切换科目
function onSubjectChange() {
  selectedNodes.value = []
  generatedQuestions.value = []
  generateStats.value = null
  if (selectedSubject.value) {
    loadNodes()
  } else {
    subjects.value = []
  }
}

// 全选/取消全选
function toggleSelectAll(subject) {
  const nodeIds = subject.nodes.map(n => n.id)
  const allSelected = nodeIds.every(id => selectedNodes.value.includes(id))
  if (allSelected) {
    selectedNodes.value = selectedNodes.value.filter(id => !nodeIds.includes(id))
  } else {
    selectedNodes.value = [...new Set([...selectedNodes.value, ...nodeIds])]
  }
}

function isNodeSelected(nodeId) {
  return selectedNodes.value.includes(nodeId)
}

function toggleNode(nodeId) {
  if (selectedNodes.value.includes(nodeId)) {
    selectedNodes.value = selectedNodes.value.filter(id => id !== nodeId)
  } else {
    selectedNodes.value.push(nodeId)
  }
}

const selectedNodesCount = computed(() => selectedNodes.value.length)

// 生成题目
async function generate() {
  if (selectedNodes.value.length === 0) {
    errorMsg.value = '请至少选择一个知识点'
    return
  }
  generating.value = true
  errorMsg.value = ''
  generatedQuestions.value = []
  generateStats.value = null
  selectedForSave.value = new Set()

  try {
    const body = {
      node_ids: selectedNodes.value,
      count: count.value,
      style: style.value,
      verify: verify.value,
    }
    if (qtype.value) body.qtype = qtype.value
    if (difficulty.value) body.difficulty = parseInt(difficulty.value)

    const result = await api.quizGenerateBatch(body)
    generatedQuestions.value = result.questions || []
    generateStats.value = {
      total: result.total,
      success: result.success,
      failed: result.failed,
      failures: result.failures || [],
    }
    // 默认选中验证通过的题目
    generatedQuestions.value.forEach((q, i) => {
      const v = q.verification
      if (!v || v.is_valid) {
        selectedForSave.value.add(i)
      }
    })
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    generating.value = false
  }
}

// 切换保存选中
function toggleSave(index) {
  if (selectedForSave.value.has(index)) {
    selectedForSave.value.delete(index)
  } else {
    selectedForSave.value.add(index)
  }
}

const selectedForSaveCount = computed(() => selectedForSave.value.size)

// 保存选中的题目
async function saveSelected() {
  if (selectedForSaveCount.value === 0) {
    errorMsg.value = '请至少选择一道题保存'
    return
  }
  saving.value = true
  errorMsg.value = ''
  try {
    const questionsToSave = generatedQuestions.value.filter((_, i) => selectedForSave.value.has(i))
    const result = await api.quizGenerateSave({
      questions: questionsToSave,
      only_valid: false, // 已经人工审核了，不过滤
      min_score: 0,
    })
    alert(`保存成功！共保存 ${result.saved} 道题，题目ID: ${result.question_ids.join(', ')}`)
    // 清空已保存的
    generatedQuestions.value = generatedQuestions.value.filter((_, i) => !selectedForSave.value.has(i))
    selectedForSave.value = new Set()
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    saving.value = false
  }
}

// 题型显示名
const qtypeNames = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  judge: '判断题',
  fill_single: '填空题',
  fill_cloze: '多空填空',
  short: '简答题',
  code: '代码题',
  recite: '背诵题',
}

function formatQtype(t) {
  return qtypeNames[t] || t
}

// 验证状态样式
function verifyClass(q) {
  const v = q.verification
  if (!v) return 'verify-pending'
  if (v.is_valid && v.score >= 7) return 'verify-good'
  if (v.is_valid) return 'verify-warn'
  return 'verify-bad'
}

function verifyText(q) {
  const v = q.verification
  if (!v) return '未验证'
  if (v.is_valid && v.score >= 7) return `✓ 验证通过 (${v.score}/10)`
  if (v.is_valid) return `⚠ 有瑕疵 (${v.score}/10)`
  return `✗ 验证失败 (${v.score}/10)`
}
</script>

<template>
  <div class="quiz-generator-view">
    <div class="page-header">
      <h2>🤖 智能出题</h2>
      <p class="subtitle">AI 根据知识点自动生成题目，支持答案验证和人工审核入库</p>
    </div>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>

    <!-- 出题配置 -->
    <div class="config-panel">
      <h3>📝 出题配置</h3>

      <div class="config-grid">
        <!-- 科目选择 -->
        <div class="config-item">
          <label>选择科目</label>
          <select v-model="selectedSubject" @change="onSubjectChange" class="select-input">
            <option value="">请选择科目</option>
            <option v-for="c in courseList" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <!-- 出题数量 -->
        <div class="config-item">
          <label>出题数量（1-50）</label>
          <input v-model.number="count" type="number" min="1" max="50" class="number-input" />
        </div>

        <!-- 题型 -->
        <div class="config-item">
          <label>题型</label>
          <select v-model="qtype" class="select-input">
            <option v-for="opt in qtypeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <!-- 难度 -->
        <div class="config-item">
          <label>难度</label>
          <select v-model="difficulty" class="select-input">
            <option v-for="opt in difficultyOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <!-- 风格 -->
        <div class="config-item">
          <label>出题风格</label>
          <select v-model="style" class="select-input">
            <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <!-- 验证开关 -->
        <div class="config-item">
          <label>AI 答案验证</label>
          <label class="checkbox-label">
            <input v-model="verify" type="checkbox" />
            生成后自动验证答案正确性
          </label>
        </div>
      </div>

      <!-- 知识点选择 -->
      <div v-if="selectedSubject" class="node-selector">
        <div class="node-selector-header">
          <span>选择知识点（已选 {{ selectedNodesCount }} 个）</span>
          <span v-if="loadingNodes" class="loading-text">加载中...</span>
        </div>

        <div v-for="subject in subjects" :key="subject.subject_id" class="subject-group">
          <div class="subject-header">
            <label class="checkbox-label">
              <input
                type="checkbox"
                :checked="subject.nodes.every(n => isNodeSelected(n.id))"
                @change="toggleSelectAll(subject)"
              />
              <strong>{{ subject.subject_name }}</strong>
              <span class="node-count">（{{ subject.nodes.length }} 个知识点）</span>
            </label>
          </div>
          <div class="node-list">
            <label v-for="node in subject.nodes" :key="node.id" class="node-item checkbox-label">
              <input
                type="checkbox"
                :checked="isNodeSelected(node.id)"
                @change="toggleNode(node.id)"
              />
              <span class="node-name">{{ node.name }}</span>
              <span class="node-meta">难度{{ node.difficulty }} / 掌握{{ node.mastery }}%</span>
            </label>
          </div>
        </div>
      </div>

      <!-- 生成按钮 -->
      <div class="action-row">
        <button
          class="btn btn-primary btn-large"
          :disabled="generating || selectedNodesCount === 0"
          @click="generate"
        >
          <span v-if="generating">⏳ AI 出题中，请稍候（可能需要1-3分钟）...</span>
          <span v-else>🚀 开始生成 {{ count }} 道题</span>
        </button>
      </div>
    </div>

    <!-- 生成统计 -->
    <div v-if="generateStats" class="stats-panel">
      <div class="stats-row">
        <div class="stat-item success">
          <span class="stat-num">{{ generateStats.success }}</span>
          <span class="stat-label">成功</span>
        </div>
        <div class="stat-item failed" v-if="generateStats.failed > 0">
          <span class="stat-num">{{ generateStats.failed }}</span>
          <span class="stat-label">失败</span>
        </div>
        <div class="stat-item total">
          <span class="stat-num">{{ generateStats.total }}</span>
          <span class="stat-label">目标</span>
        </div>
        <div class="stat-item selected">
          <span class="stat-num">{{ selectedForSaveCount }}</span>
          <span class="stat-label">待保存</span>
        </div>
      </div>

      <!-- 失败详情 -->
      <div v-if="generateStats.failures && generateStats.failures.length" class="failures-list">
        <h4>失败详情：</h4>
        <div v-for="f in generateStats.failures" :key="f.attempt" class="failure-item">
          <span class="failure-index">第 {{ f.attempt }} 次尝试（{{ f.node_name }}）：</span>
          <span class="failure-msg">{{ f.error }}</span>
        </div>
      </div>
    </div>

    <!-- 生成结果列表 -->
    <div v-if="generatedQuestions.length > 0" class="results-panel">
      <div class="results-header">
        <h3>📋 生成结果（{{ generatedQuestions.length }} 道）</h3>
        <div class="results-actions">
          <button class="btn btn-secondary" @click="selectedForSave = new Set(generatedQuestions.keys())">全选</button>
          <button class="btn btn-ghost" @click="selectedForSave = new Set()">全不选</button>
          <button
            class="btn btn-primary"
            :disabled="saving || selectedForSaveCount === 0"
            @click="saveSelected"
          >
            <span v-if="saving">保存中...</span>
            <span v-else>💾 保存选中的 {{ selectedForSaveCount }} 道题</span>
          </button>
        </div>
      </div>

      <div v-for="(q, index) in generatedQuestions" :key="index" class="question-card" :class="{ selected: selectedForSave.has(index) }">
        <div class="question-header">
          <label class="checkbox-label">
            <input
              type="checkbox"
              :checked="selectedForSave.has(index)"
              @change="toggleSave(index)"
            />
            <span class="question-num">第 {{ index + 1 }} 题</span>
          </label>
          <div class="question-meta">
            <span class="tag">{{ formatQtype(q.qtype) }}</span>
            <span class="tag tag-difficulty">难度 {{ q.difficulty }}</span>
            <span class="tag tag-node">{{ q.node_name }}</span>
            <span class="verify-badge" :class="verifyClass(q)">{{ verifyText(q) }}</span>
          </div>
        </div>

        <div class="question-body">
          <div class="question-text math-text">{{ q.question }}</div>

          <div v-if="q.options && q.options.length" class="question-options">
            <div v-for="(opt, i) in q.options" :key="i" class="option-item">
              <span class="option-letter">{{ String.fromCharCode(65 + i) }}.</span>
              <span class="option-text math-text">{{ opt }}</span>
            </div>
          </div>

          <div class="question-answer">
            <strong>答案：</strong>
            <span class="math-text answer-text">{{ q.correct_answer }}</span>
          </div>

          <!-- 验证问题 -->
          <div v-if="q.verification && q.verification.issues && q.verification.issues.length" class="verify-issues">
            <strong>⚠ 验证发现的问题：</strong>
            <ul>
              <li v-for="(issue, i) in q.verification.issues" :key="i">{{ issue }}</li>
            </ul>
            <div v-if="q.verification.suggestion">
              <strong>改进建议：</strong>{{ q.verification.suggestion }}
            </div>
          </div>

          <!-- 解析 -->
          <details class="question-analysis">
            <summary>📖 查看解析（{{ q.analysis ? q.analysis.length : 0 }} 步）</summary>
            <div class="analysis-content">
              <div v-if="q.thought_map" class="thought-map">
                <strong>思路要点：</strong>{{ q.thought_map }}
              </div>
              <div v-for="step in q.analysis" :key="step.step" class="analysis-step">
                <span class="step-num">步骤 {{ step.step }}：</span>
                <span class="step-text math-text">{{ step.text }}</span>
              </div>
              <div v-if="q.error_tips" class="error-tips">
                <strong>易错点：</strong>{{ q.error_tips }}
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>

    <!-- 使用说明 -->
    <div class="help-section">
      <h3>💡 使用说明</h3>
      <ul>
        <li><strong>选择知识点</strong>：先选科目，再勾选要出题的知识点（可全选整个科目）</li>
        <li><strong>配置参数</strong>：设置出题数量、题型、难度、风格，建议题型和难度选"随机"以获得多样性</li>
        <li><strong>AI 验证</strong>：开启后每道题生成后会独立调用 AI 验证答案正确性，耗时约翻倍但质量更有保障</li>
        <li><strong>人工审核</strong>：生成结果可逐题查看题干、选项、答案、解析，勾选要保存的题目</li>
        <li><strong>批量入库</strong>：确认无误后点击"保存选中的题目"，题目会关联到对应知识点并进入题库</li>
        <li><strong>出题风格</strong>：考研真题风格最贴近实际考试，教材风格更基础，基础概念题适合第一轮复习</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.quiz-generator-view {
  padding: 20px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header h2 {
  margin: 0 0 4px 0;
  font-size: 22px;
}

.subtitle {
  color: #666;
  margin: 0 0 20px 0;
  font-size: 14px;
}

.alert {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.alert-error {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.config-panel, .results-panel, .stats-panel, .help-section {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  margin-bottom: 20px;
}

.config-panel h3, .results-header h3, .help-section h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.config-item label {
  font-weight: 600;
  font-size: 13px;
  color: #333;
}

.select-input, .number-input {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 14px;
}

.node-selector {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  max-height: 400px;
  overflow-y: auto;
}

.node-selector-header {
  font-weight: 600;
  margin-bottom: 12px;
  font-size: 14px;
}

.loading-text {
  color: #666;
  font-weight: normal;
}

.subject-group {
  margin-bottom: 12px;
}

.subject-header {
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
  margin-bottom: 8px;
}

.node-count {
  color: #999;
  font-weight: normal;
  font-size: 13px;
}

.node-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-left: 12px;
}

.node-item {
  padding: 6px 10px;
  background: #f9fafb;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  font-size: 13px;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.node-name {
  font-weight: 500;
}

.node-meta {
  font-size: 11px;
  color: #999;
}

.action-row {
  display: flex;
  justify-content: center;
}

.btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
  font-weight: 500;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: #4f46e5;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #4338ca;
}

.btn-secondary {
  background: #f3f4f6;
  color: #333;
  border: 1px solid #ddd;
}

.btn-ghost {
  background: transparent;
  color: #666;
}

.btn-large {
  padding: 14px 32px;
  font-size: 16px;
}

.stats-row {
  display: flex;
  gap: 24px;
  justify-content: center;
  margin-bottom: 16px;
}

.stat-item {
  text-align: center;
  padding: 12px 24px;
  border-radius: 10px;
  min-width: 100px;
}

.stat-item.success { background: #dcfce7; }
.stat-item.failed { background: #fee2e2; }
.stat-item.total { background: #eff6ff; }
.stat-item.selected { background: #fef3c7; }

.stat-num {
  display: block;
  font-size: 28px;
  font-weight: 700;
}

.stat-label {
  font-size: 13px;
  color: #666;
}

.failures-list h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
}

.failure-item {
  padding: 8px 12px;
  background: #fef2f2;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 13px;
}

.failure-index {
  font-weight: 600;
  color: #991b1b;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 10px;
}

.results-actions {
  display: flex;
  gap: 8px;
}

.question-card {
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 16px;
  transition: border-color 0.2s;
}

.question-card.selected {
  border-color: #4f46e5;
  background: #fafaff;
}

.question-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.question-num {
  font-weight: 600;
  font-size: 15px;
}

.question-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.tag {
  padding: 2px 8px;
  background: #f3f4f6;
  border-radius: 4px;
  font-size: 12px;
  color: #555;
}

.tag-difficulty {
  background: #fef3c7;
  color: #92400e;
}

.tag-node {
  background: #dbeafe;
  color: #1e40af;
}

.verify-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.verify-good { background: #dcfce7; color: #166534; }
.verify-warn { background: #fef3c7; color: #92400e; }
.verify-bad { background: #fee2e2; color: #991b1b; }
.verify-pending { background: #f3f4f6; color: #666; }

.question-text {
  font-size: 15px;
  line-height: 1.6;
  margin-bottom: 12px;
}

.math-text {
  font-family: 'Cambria Math', 'Times New Roman', serif;
}

.question-options {
  margin-bottom: 12px;
}

.option-item {
  padding: 4px 0;
  font-size: 14px;
}

.option-letter {
  font-weight: 600;
  margin-right: 6px;
}

.question-answer {
  padding: 8px 12px;
  background: #f0fdf4;
  border-radius: 6px;
  font-size: 14px;
  margin-bottom: 12px;
}

.answer-text {
  color: #166534;
  font-weight: 600;
}

.verify-issues {
  padding: 10px 12px;
  background: #fffbeb;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}

.verify-issues ul {
  margin: 6px 0;
  padding-left: 20px;
}

.question-analysis {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}

.question-analysis summary {
  padding: 8px 12px;
  background: #f9fafb;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.analysis-content {
  padding: 12px;
}

.thought-map, .error-tips {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 10px;
  font-size: 13px;
}

.thought-map {
  background: #eff6ff;
}

.error-tips {
  background: #fef2f2;
}

.analysis-step {
  padding: 6px 0;
  font-size: 14px;
  line-height: 1.6;
}

.step-num {
  font-weight: 600;
  color: #4f46e5;
}

.help-section {
  background: #f0f9ff;
  border: 1px solid #bae6fd;
}

.help-section h3 {
  color: #0c4a6e;
}

.help-section ul {
  margin: 0;
  padding-left: 20px;
}

.help-section li {
  margin-bottom: 8px;
  font-size: 14px;
  color: #0c4a6e;
  line-height: 1.6;
}
</style>
