<template>
  <div class="math-view">
    <div class="page-head">
      <div>
        <h2>🔢 数学验证</h2>
        <p class="page-desc">sympy 符号计算 · 求导/积分/极限/方程/数值验证 · LaTeX 解析</p>
      </div>
    </div>

    <div class="math-main">
      <!-- 左侧：验证工具 -->
      <div class="math-panel">
        <div class="method-tabs">
          <button
            v-for="m in methods"
            :key="m.id"
            class="method-tab"
            :class="{ active: method === m.id }"
            @click="method = m.id; result = null"
          >{{ m.icon }} {{ m.name }}</button>
        </div>

        <!-- 求导验证 -->
        <div v-if="method === 'derivative'" class="form-group">
          <label>原函数（LaTeX）</label>
          <input v-model="form.function" class="form-input" placeholder="如：x^3 + 2x^2 - 5x + 1" />
          <label>待验证导数（LaTeX）</label>
          <input v-model="form.derivative" class="form-input" placeholder="如：3x^2 + 4x - 5" />
          <label>变量</label>
          <input v-model="form.var" class="form-input small" />
        </div>

        <!-- 积分验证 -->
        <div v-if="method === 'integral'" class="form-group">
          <label>被积函数（LaTeX）</label>
          <input v-model="form.function" class="form-input" placeholder="如：2x" />
          <label>待验证积分结果（LaTeX）</label>
          <input v-model="form.integral" class="form-input" placeholder="如：x^2" />
          <label>积分变量</label>
          <input v-model="form.var" class="form-input small" />
        </div>

        <!-- 极限验证 -->
        <div v-if="method === 'limit'" class="form-group">
          <label>函数（LaTeX）</label>
          <input v-model="form.function" class="form-input" placeholder="如：(1+1/x)^x" />
          <label>待验证极限值（LaTeX）</label>
          <input v-model="form.limit_value" class="form-input" placeholder="如：e" />
          <div class="form-row">
            <div>
              <label>变量</label>
              <input v-model="form.var" class="form-input small" />
            </div>
            <div>
              <label>极限点</label>
              <input v-model="form.point" class="form-input small" placeholder="oo / 0 / a" />
            </div>
          </div>
        </div>

        <!-- 数值验证 -->
        <div v-if="method === 'numeric'" class="form-group">
          <label>表达式（LaTeX）</label>
          <input v-model="form.expression" class="form-input" placeholder="如：\\sqrt{2} + \\pi" />
          <label>期望数值</label>
          <input v-model.number="form.expected_value" type="number" class="form-input" placeholder="如：4.5558" />
          <label>容差</label>
          <input v-model.number="form.tolerance" type="number" class="form-input small" />
        </div>

        <!-- 方程验证 -->
        <div v-if="method === 'equation'" class="form-group">
          <label>方程（LaTeX，含 = 号）</label>
          <input v-model="form.equation" class="form-input" placeholder="如：x^2 - 5x + 6 = 0" />
          <label>待验证的解</label>
          <input v-model="form.solution" class="form-input" placeholder="如：2,3 或 x=2" />
          <label>变量</label>
          <input v-model="form.var" class="form-input small" />
        </div>

        <!-- 自动验证 -->
        <div v-if="method === 'auto'" class="form-group">
          <label>题目文本</label>
          <textarea v-model="form.question" class="form-input" rows="3" placeholder="粘贴题目，自动识别验证方法"></textarea>
          <label>待验证答案</label>
          <input v-model="form.answer" class="form-input" placeholder="答案" />
        </div>

        <button class="btn verify-btn" :disabled="verifying" @click="onVerify">
          {{ verifying ? '验证中...' : '✅ 开始验证' }}
        </button>

        <!-- 验证结果 -->
        <div v-if="result" class="result-box" :class="result.valid ? 'pass' : 'fail'">
          <div class="result-header">
            <span class="result-icon">{{ result.valid ? '✅' : '❌' }}</span>
            <span class="result-title">{{ result.valid ? '验证通过' : '验证失败' }}</span>
            <span class="result-method">方法: {{ result.method }}</span>
            <span class="result-confidence" v-if="result.confidence">置信度: {{ (result.confidence * 100).toFixed(0) }}%</span>
          </div>
          <div class="result-detail" v-if="result.expected">
            <div><strong>期望值:</strong> <code>{{ result.expected }}</code></div>
            <div><strong>实际值:</strong> <code>{{ result.actual }}</code></div>
          </div>
          <div class="result-error" v-if="result.error">
            <strong>说明:</strong> {{ result.error }}
          </div>
        </div>
      </div>

      <!-- 右侧：解析测试 + 能力说明 -->
      <div class="math-side">
        <div class="side-panel">
          <h3>🔍 LaTeX 解析测试</h3>
          <input v-model="parseInput" class="form-input" placeholder="输入 LaTeX 表达式测试解析" @keyup.enter="onParse" />
          <button class="btn ghost mini" @click="onParse">解析</button>
          <div v-if="parseResult" class="parse-result">
            <div><strong>Python 表达式:</strong> <code>{{ parseResult.python_expr }}</code></div>
            <div><strong>sympy 结果:</strong> <code>{{ parseResult.sympy_expr || '解析失败' }}</code></div>
            <div class="parse-status" :class="parseResult.parse_success ? 'ok' : 'fail'">
              {{ parseResult.parse_success ? '✅ 解析成功' : '❌ 解析失败' }}
            </div>
          </div>
        </div>

        <div class="side-panel">
          <h3>📋 支持的验证能力</h3>
          <div class="cap-list">
            <div v-for="c in capabilities" :key="c.id" class="cap-item">
              <strong>{{ c.name }}</strong>
              <p>{{ c.description }}</p>
            </div>
          </div>
        </div>

        <div class="side-panel">
          <h3>⚠️ 使用限制</h3>
          <ul class="limit-list">
            <li>LaTeX 转换器为轻量实现，复杂嵌套（如多重积分）可能解析失败</li>
            <li>不支持级数展开、曲线积分、曲面积分等高级运算</li>
            <li>自动验证仅支持关键词匹配，复杂题目请手动选择验证方法</li>
            <li>验证是辅助功能，结果仅供参考，重要题目请人工复核</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api } from '../api'

const methods = [
  { id: 'derivative', name: '求导验证', icon: '📈' },
  { id: 'integral', name: '积分验证', icon: '∫' },
  { id: 'limit', name: '极限验证', icon: '∞' },
  { id: 'numeric', name: '数值验证', icon: '🔢' },
  { id: 'equation', name: '方程验证', icon: '⚖️' },
  { id: 'auto', name: '自动识别', icon: '🤖' },
]

const method = ref('derivative')
const verifying = ref(false)
const result = ref(null)
const parseInput = ref('')
const parseResult = ref(null)
const capabilities = ref([])

const form = reactive({
  function: '',
  derivative: '',
  integral: '',
  limit_value: '',
  expression: '',
  expected_value: 0,
  tolerance: 0.0001,
  equation: '',
  solution: '',
  question: '',
  answer: '',
  var: 'x',
  point: 'oo',
})

onMounted(async () => {
  try {
    const caps = await api.mathCapabilities()
    capabilities.value = caps.methods || []
  } catch (e) {
    console.error('加载能力列表失败', e)
  }
})

async function onVerify() {
  verifying.value = true
  result.value = null
  try {
    let res
    switch (method.value) {
      case 'derivative':
        res = await api.mathVerifyDerivative({
          function: form.function,
          derivative: form.derivative,
          var: form.var,
        })
        break
      case 'integral':
        res = await api.mathVerifyIntegral({
          function: form.function,
          integral: form.integral,
          var: form.var,
        })
        break
      case 'limit':
        res = await api.mathVerifyLimit({
          function: form.function,
          limit_value: form.limit_value,
          var: form.var,
          point: form.point,
        })
        break
      case 'numeric':
        res = await api.mathVerifyNumeric({
          expression: form.expression,
          expected_value: form.expected_value,
          tolerance: form.tolerance,
        })
        break
      case 'equation':
        res = await api.mathVerifyEquation({
          equation: form.equation,
          solution: form.solution,
          var: form.var,
        })
        break
      case 'auto':
        res = await api.mathVerifyAuto({
          question: form.question,
          answer: form.answer,
          qtype: 'short',
        })
        break
    }
    result.value = res
  } catch (e) {
    result.value = { valid: false, method: method.value, error: '请求失败: ' + (e.message || e) }
  } finally {
    verifying.value = false
  }
}

async function onParse() {
  if (!parseInput.value) return
  try {
    parseResult.value = await api.mathParse(parseInput.value)
  } catch (e) {
    parseResult.value = { parse_success: false, python_expr: '', sympy_expr: null }
  }
}
</script>

<style scoped>
.math-view { padding: 20px; }
.page-head { margin-bottom: 16px; }
.page-head h2 { margin: 0 0 4px; font-size: 22px; }
.page-desc { margin: 0; color: #64748b; font-size: 13px; }

.math-main { display: grid; grid-template-columns: 1fr 340px; gap: 16px; }

.math-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; }

.method-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px; }
.method-tab { padding: 8px 14px; border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; cursor: pointer; font-size: 13px; transition: all 0.15s; }
.method-tab:hover { background: #f1f5f9; }
.method-tab.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }

.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; font-weight: 500; color: #334155; margin-bottom: 4px; margin-top: 10px; }
.form-input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; box-sizing: border-box; font-family: monospace; }
.form-input:focus { outline: none; border-color: #3b82f6; }
.form-input.small { width: 120px; }
.form-row { display: flex; gap: 16px; }
.form-row > div { flex: 1; }

.verify-btn { width: 100%; padding: 12px; background: #3b82f6; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 500; cursor: pointer; margin-top: 8px; }
.verify-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.verify-btn:hover:not(:disabled) { background: #2563eb; }

.result-box { margin-top: 16px; padding: 16px; border-radius: 8px; border: 1px solid; }
.result-box.pass { background: #f0fdf4; border-color: #86efac; }
.result-box.fail { background: #fef2f2; border-color: #fca5a5; }
.result-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.result-icon { font-size: 18px; }
.result-title { font-weight: 600; font-size: 15px; }
.result-method { font-size: 12px; color: #64748b; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; }
.result-confidence { font-size: 12px; color: #64748b; }
.result-detail { font-size: 13px; line-height: 1.8; }
.result-detail code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
.result-error { font-size: 13px; color: #b91c1c; margin-top: 8px; }

.math-side { display: flex; flex-direction: column; gap: 16px; }
.side-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; }
.side-panel h3 { margin: 0 0 12px; font-size: 15px; color: #1e293b; }

.parse-result { margin-top: 12px; font-size: 12px; line-height: 1.8; }
.parse-result code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; word-break: break-all; }
.parse-status { margin-top: 8px; font-weight: 500; }
.parse-status.ok { color: #16a34a; }
.parse-status.fail { color: #dc2626; }

.cap-list { display: flex; flex-direction: column; gap: 10px; }
.cap-item { padding: 8px 10px; background: #f8fafc; border-radius: 6px; }
.cap-item strong { font-size: 13px; color: #1e293b; }
.cap-item p { margin: 4px 0 0; font-size: 12px; color: #64748b; }

.limit-list { margin: 0; padding-left: 18px; font-size: 12px; color: #64748b; line-height: 1.8; }

.btn { padding: 8px 14px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; background: #3b82f6; color: #fff; margin-top: 8px; }
.btn.ghost { background: #f1f5f9; color: #475569; }
.btn.mini { padding: 6px 12px; font-size: 12px; }
</style>
