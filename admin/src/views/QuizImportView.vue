<script setup>
import { ref, computed } from 'vue'
import { api } from '../api.js'

// 模式：single 单题 / batch 批量
const mode = ref('single')
const inputText = ref('')
const nodeId = ref('')
const generateAnalysis = ref(true)
const loading = ref(false)
const errorMsg = ref('')

// 分割预览结果
const splitResult = ref(null)

// 解析预览结果
const parseResult = ref(null)

// 导入结果
const importResult = ref(null)

// 已导入题目列表（最近20条）
const recentQuestions = ref([])
const loadingRecent = ref(false)

const canSubmit = computed(() => inputText.value.trim().length > 0 && !loading.value)

// 分割预览
async function previewSplit() {
  if (!inputText.value.trim()) return
  errorMsg.value = ''
  try {
    splitResult.value = await api.quizImportSplitPreview(inputText.value)
    parseResult.value = null
    importResult.value = null
  } catch (e) {
    errorMsg.value = e.message
  }
}

// 解析预览（不保存）
async function previewParse() {
  if (!inputText.value.trim()) return
  loading.value = true
  errorMsg.value = ''
  parseResult.value = null
  try {
    parseResult.value = await api.quizImportParse({ text: inputText.value })
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

// 单题导入
async function importSingle() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  importResult.value = null
  try {
    const body = {
      text: inputText.value,
      generate_analysis: generateAnalysis.value,
    }
    if (nodeId.value) body.node_id = parseInt(nodeId.value)
    importResult.value = await api.quizImportText(body)
    // 刷新最近题目
    loadRecentQuestions()
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

// 批量导入
async function importBatch() {
  if (!canSubmit.value) return
  loading.value = true
  errorMsg.value = ''
  importResult.value = null
  try {
    const body = {
      text: inputText.value,
      generate_analysis: generateAnalysis.value,
    }
    if (nodeId.value) body.node_id = parseInt(nodeId.value)
    importResult.value = await api.quizImportBatch(body)
    loadRecentQuestions()
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

// 加载最近导入的题目
async function loadRecentQuestions() {
  loadingRecent.value = true
  try {
    // 用知识树节点的题目列表接口，如果没有则用通用接口
    // 暂时通过 /knowledge/nodes/{id}/quiz 不太方便，这里简化：不展示列表
    // 后续可添加专门的题目列表接口
    recentQuestions.value = []
  } catch (e) {
    // 静默失败
  } finally {
    loadingRecent.value = false
  }
}

// 清空
function clearAll() {
  inputText.value = ''
  splitResult.value = null
  parseResult.value = null
  importResult.value = null
  errorMsg.value = ''
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
</script>

<template>
  <div class="quiz-import-view">
    <div class="page-header">
      <h2>📥 题目导入</h2>
      <p class="subtitle">AI 自动解析题目、标注考点、生成步骤化解析</p>
    </div>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="alert alert-error">
      {{ errorMsg }}
    </div>

    <div class="import-panel">
      <!-- 模式切换 -->
      <div class="mode-tabs">
        <button
          class="mode-tab"
          :class="{ active: mode === 'single' }"
          @click="mode = 'single'; clearAll()"
        >
          单题导入
        </button>
        <button
          class="mode-tab"
          :class="{ active: mode === 'batch' }"
          @click="mode = 'batch'; clearAll()"
        >
          批量导入
        </button>
      </div>

      <!-- 输入区域 -->
      <div class="input-section">
        <label class="field-label">
          {{ mode === 'single' ? '题目文本（粘贴题干+选项+答案）' : '多道题目（按题号 1. 2. 3. 自动分割）' }}
        </label>
        <textarea
          v-model="inputText"
          class="text-input"
          :placeholder="mode === 'single'
            ? '示例：\n1. 求极限 lim(x→0) (sin x - x)/x³\n\nA. -1/6  B. 1/6  C. -1/3  D. 1/3\n\n答案：A'
            : '粘贴多道题目，每题以 1. 2. 3. 开头，系统自动分割...'"
          rows="10"
        ></textarea>

        <div class="options-row">
          <div class="option-item">
            <label>知识点节点 ID（可选，不填自动匹配）</label>
            <input
              v-model="nodeId"
              type="number"
              class="small-input"
              placeholder="留空自动匹配"
            />
          </div>
          <div class="option-item">
            <label class="checkbox-label">
              <input v-model="generateAnalysis" type="checkbox" />
              生成 AI 步骤化解析
            </label>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="action-row">
        <button
          v-if="mode === 'batch'"
          class="btn btn-secondary"
          :disabled="!canSubmit"
          @click="previewSplit"
        >
          🔍 分割预览
        </button>
        <button
          class="btn btn-secondary"
          :disabled="!canSubmit || loading"
          @click="previewParse"
        >
          👁️ 解析预览（不保存）
        </button>
        <button
          class="btn btn-primary"
          :disabled="!canSubmit || loading"
          @click="mode === 'single' ? importSingle() : importBatch()"
        >
          <span v-if="loading">⏳ AI 处理中...</span>
          <span v-else>📥 {{ mode === 'single' ? '导入题目' : '批量导入' }}</span>
        </button>
        <button class="btn btn-ghost" @click="clearAll">清空</button>
      </div>
    </div>

    <!-- 分割预览结果 -->
    <div v-if="splitResult" class="result-section">
      <h3>📋 分割预览（共 {{ splitResult.count }} 题）</h3>
      <div class="split-list">
        <div v-for="q in splitResult.questions" :key="q.index" class="split-item">
          <div class="split-index">第 {{ q.index }} 题</div>
          <div class="split-preview">{{ q.preview }}...</div>
          <div class="split-meta">长度：{{ q.length }} 字符</div>
        </div>
      </div>
    </div>

    <!-- 解析预览结果 -->
    <div v-if="parseResult" class="result-section">
      <h3>👁️ 解析预览（未保存）</h3>
      <div class="parse-detail">
        <div class="detail-row">
          <span class="detail-label">题型：</span>
          <span class="detail-value">{{ formatQtype(parseResult.parsed.qtype) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">难度：</span>
          <span class="detail-value">{{ parseResult.parsed.difficulty }} / 5</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">题干：</span>
          <span class="detail-value math-text">{{ parseResult.parsed.question }}</span>
        </div>
        <div v-if="parseResult.parsed.options && parseResult.parsed.options.length" class="detail-row">
          <span class="detail-label">选项：</span>
          <div class="detail-value">
            <div v-for="(opt, i) in parseResult.parsed.options" :key="i" class="option-item-inline">
              {{ String.fromCharCode(65 + i) }}. {{ opt }}
            </div>
          </div>
        </div>
        <div class="detail-row">
          <span class="detail-label">答案：</span>
          <span class="detail-value math-text">{{ parseResult.parsed.correct_answer || '（未识别）' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">考点：</span>
          <span class="detail-value">{{ parseResult.parsed.knowledge_hint }}</span>
        </div>
        <div v-if="parseResult.matched_node" class="detail-row">
          <span class="detail-label">匹配节点：</span>
          <span class="detail-value">{{ parseResult.matched_node.name }} (ID: {{ parseResult.matched_node.id }})</span>
        </div>
      </div>
    </div>

    <!-- 导入结果 -->
    <div v-if="importResult" class="result-section">
      <div v-if="mode === 'single'">
        <h3>✅ 导入成功</h3>
        <div class="detail-row">
          <span class="detail-label">题目 ID：</span>
          <span class="detail-value">{{ importResult.id }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">关联节点：</span>
          <span class="detail-value">{{ importResult.node_id || '未关联（可后续手动关联）' }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">题型：</span>
          <span class="detail-value">{{ formatQtype(importResult.parsed.qtype) }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">题干：</span>
          <span class="detail-value math-text">{{ importResult.parsed.question }}</span>
        </div>
      </div>

      <div v-else>
        <h3>✅ 批量导入完成</h3>
        <div class="batch-summary">
          <div class="summary-item success">
            <span class="summary-num">{{ importResult.success }}</span>
            <span class="summary-label">成功</span>
          </div>
          <div class="summary-item failed" v-if="importResult.failed > 0">
            <span class="summary-num">{{ importResult.failed }}</span>
            <span class="summary-label">失败</span>
          </div>
          <div class="summary-item total">
            <span class="summary-num">{{ importResult.total }}</span>
            <span class="summary-label">总计</span>
          </div>
        </div>

        <div v-if="importResult.failures && importResult.failures.length" class="failures-list">
          <h4>失败详情：</h4>
          <div v-for="f in importResult.failures" :key="f.index" class="failure-item">
            <span class="failure-index">第 {{ f.index }} 题：</span>
            <span class="failure-msg">{{ f.error }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 使用说明 -->
    <div class="help-section">
      <h3>💡 使用说明</h3>
      <ul>
        <li><strong>单题导入</strong>：粘贴一道题的完整内容（题干+选项+答案），AI 自动解析并生成步骤化解析</li>
        <li><strong>批量导入</strong>：粘贴多道题，每题以 <code>1.</code> <code>2.</code> <code>3.</code> 开头，系统自动分割后逐题导入</li>
        <li><strong>公式支持</strong>：自动识别数学公式并转换为 LaTeX 格式（$...$ / $$...$$）</li>
        <li><strong>考点匹配</strong>：AI 识别题目考察的知识点，自动匹配知识树节点；也可手动指定节点 ID</li>
        <li><strong>解析预览</strong>：先预览 AI 解析结果，确认无误后再导入</li>
        <li><strong>单题失败不影响批量</strong>：批量导入时某题失败会跳过，其他题目正常导入</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.quiz-import-view {
  padding: 20px;
  max-width: 900px;
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

.import-panel {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  margin-bottom: 20px;
}

.mode-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.mode-tab {
  padding: 8px 20px;
  border: 1px solid #ddd;
  background: #f9f9f9;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.mode-tab.active {
  background: #4f46e5;
  color: #fff;
  border-color: #4f46e5;
}

.field-label {
  display: block;
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 14px;
  color: #333;
}

.text-input {
  width: 100%;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  box-sizing: border-box;
}

.text-input:focus {
  outline: none;
  border-color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(79,70,229,0.1);
}

.options-row {
  display: flex;
  gap: 24px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.option-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.option-item label {
  font-size: 13px;
  color: #666;
}

.small-input {
  padding: 6px 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  width: 160px;
}

.checkbox-label {
  display: flex !important;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  margin-top: 20px;
}

.action-row {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  flex-wrap: wrap;
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

.btn-secondary:hover:not(:disabled) {
  background: #e5e7eb;
}

.btn-ghost {
  background: transparent;
  color: #666;
}

.btn-ghost:hover {
  background: #f3f4f6;
}

.result-section {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  margin-bottom: 20px;
}

.result-section h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
}

.split-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.split-item {
  padding: 12px;
  background: #f9fafb;
  border-radius: 8px;
  border-left: 3px solid #4f46e5;
}

.split-index {
  font-weight: 600;
  font-size: 14px;
  color: #4f46e5;
  margin-bottom: 4px;
}

.split-preview {
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
}

.split-meta {
  font-size: 12px;
  color: #999;
}

.detail-row {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
  align-items: flex-start;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-label {
  font-weight: 600;
  font-size: 14px;
  color: #666;
  min-width: 80px;
  flex-shrink: 0;
}

.detail-value {
  font-size: 14px;
  color: #333;
  flex: 1;
}

.math-text {
  font-family: 'Cambria Math', 'Times New Roman', serif;
}

.option-item-inline {
  padding: 2px 0;
  font-size: 14px;
}

.batch-summary {
  display: flex;
  gap: 24px;
  margin-bottom: 20px;
}

.summary-item {
  text-align: center;
  padding: 16px 24px;
  border-radius: 10px;
  min-width: 100px;
}

.summary-item.success {
  background: #dcfce7;
}

.summary-item.failed {
  background: #fee2e2;
}

.summary-item.total {
  background: #eff6ff;
}

.summary-num {
  display: block;
  font-size: 32px;
  font-weight: 700;
}

.summary-label {
  font-size: 13px;
  color: #666;
}

.failures-list h4 {
  margin: 0 0 10px 0;
  font-size: 15px;
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

.failure-msg {
  color: #666;
}

.help-section {
  background: #f0f9ff;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #bae6fd;
}

.help-section h3 {
  margin: 0 0 12px 0;
  font-size: 16px;
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

.help-section code {
  background: #e0f2fe;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
</style>
