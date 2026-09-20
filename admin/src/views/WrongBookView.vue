<template>
  <div class="wb-view">
    <div class="page-head">
      <div>
        <h2>📕 错题本</h2>
        <p class="page-desc">自动收录错题 · 薄弱点诊断 · 针对性复习 · 错题重练 · 导出打印</p>
      </div>
      <div class="head-actions">
        <select v-model="selectedSubject" class="toolbar-select" @change="loadAll">
          <option value="">全部科目</option>
          <option v-for="c in courses" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <button class="btn ghost" @click="exportCSV">📥 导出CSV</button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row" v-if="stats">
      <StatCard icon="📕" :value="stats.total_wrong" label="错题总数" theme="red" />
      <StatCard icon="❌" :value="stats.total_wrong_attempts" label="错误总次数" theme="orange" />
      <StatCard icon="🔥" :value="stats.high_frequency.length" label="高频错题" theme="purple" />
      <StatCard icon="⚠️" :value="stats.weak_nodes.length" label="薄弱知识点" theme="yellow" />
    </div>

    <div class="wb-main">
      <!-- 左侧：统计 + 推荐 -->
      <div class="wb-side">
        <!-- 7天错误趋势 -->
        <div class="panel" v-if="stats">
          <h3>📈 近7天错误趋势</h3>
          <div class="trend-chart">
            <div v-for="t in stats.trend" :key="t.date" class="trend-bar-wrap">
              <div class="trend-bar" :style="{ height: (t.wrong_count * 20 + 4) + 'px' }">
                <span class="trend-value">{{ t.wrong_count }}</span>
              </div>
              <span class="trend-label">{{ t.date }}</span>
            </div>
          </div>
        </div>

        <!-- 薄弱知识点 -->
        <div class="panel" v-if="stats && stats.weak_nodes.length">
          <h3>⚠️ 薄弱知识点 TOP5</h3>
          <div class="weak-list">
            <div v-for="(w, i) in stats.weak_nodes.slice(0, 5)" :key="w.node_id" class="weak-item">
              <span class="weak-rank">{{ i + 1 }}</span>
              <div class="weak-info">
                <span class="weak-name">{{ w.node_name }}</span>
                <span class="weak-meta">错题 {{ w.wrong_count }} 次 · 掌握度 {{ w.mastery ?? '-' }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 针对性复习推荐 -->
        <div class="panel" v-if="recommend">
          <h3>🎯 复习计划建议</h3>
          <div class="plan-list">
            <div v-for="p in recommend.review_plan" :key="p.priority" class="plan-item">
              <span class="plan-priority" :class="'p' + p.priority">{{ p.priority }}</span>
              <div class="plan-content">
                <strong>{{ p.type }}</strong>
                <p>{{ p.content }}</p>
                <span class="plan-action">{{ p.action }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 错题重练 -->
        <div class="panel">
          <h3>✏️ 错题重练</h3>
          <div class="practice-form">
            <label>出题模式</label>
            <select v-model="practiceMode" class="form-input">
              <option value="random">随机抽取</option>
              <option value="frequent">优先高频错题</option>
              <option value="recent">优先最近答错</option>
            </select>
            <label>题目数量</label>
            <input v-model.number="practiceCount" type="number" min="1" max="50" class="form-input" value="5" />
            <button class="btn full" @click="onPractice" :disabled="practicing">
              {{ practicing ? '生成中...' : '开始练习' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧：错题列表 -->
      <div class="wb-list-panel">
        <div class="list-toolbar">
          <h3>📋 错题列表（{{ wrongList.length }} 道）</h3>
          <div class="filter-group">
            <select v-model="filterDays" class="toolbar-select mini" @change="loadWrongList">
              <option :value="null">全部时间</option>
              <option :value="7">最近7天</option>
              <option :value="30">最近30天</option>
            </select>
            <select v-model="filterMinCount" class="toolbar-select mini" @change="loadWrongList">
              <option :value="1">全部错题</option>
              <option :value="2">错2次以上</option>
              <option :value="3">错3次以上</option>
            </select>
          </div>
        </div>

        <div class="wrong-list" v-if="wrongList.length">
          <div v-for="w in wrongList" :key="w.question_id" class="wrong-card" @click="toggleDetail(w.question_id)">
            <div class="wrong-card-head">
              <span class="wrong-badge" :class="'d' + w.difficulty">难度{{ w.difficulty }}</span>
              <span class="wrong-qtype">{{ qtypeName(w.qtype) }}</span>
              <span class="wrong-node" v-if="w.node_name">📌 {{ w.node_name }}</span>
              <span class="wrong-count">❌ 错{{ w.wrong_count }}次</span>
            </div>
            <div class="wrong-question">{{ w.question }}</div>
            <div class="wrong-options" v-if="w.options && w.options.length">
              <div v-for="(opt, i) in w.options" :key="i" class="opt-item">
                <span class="opt-label">{{ String.fromCharCode(65 + i) }}.</span> {{ opt }}
              </div>
            </div>

            <!-- 展开详情 -->
            <div v-if="expandedId === w.question_id" class="wrong-detail">
              <div class="detail-section">
                <strong>✅ 正确答案：</strong>{{ w.correct_answer }}
              </div>
              <div class="detail-section" v-if="w.analysis && w.analysis.length">
                <strong>📝 解析：</strong>
                <div v-for="(a, i) in w.analysis" :key="i" class="analysis-step">
                  步骤{{ a.step || i + 1 }}: {{ a.text }}
                </div>
              </div>
              <div class="detail-section" v-if="w.thought_map">
                <strong>💡 思路要点：</strong>{{ w.thought_map }}
              </div>
              <div class="detail-section" v-if="w.error_tips">
                <strong>⚠️ 易错点：</strong>{{ w.error_tips }}
              </div>
              <div class="detail-section" v-if="w.wrong_answers && w.wrong_answers.length">
                <strong>📊 最近错误答案：</strong>
                <div v-for="(wa, i) in w.wrong_answers" :key="i" class="wrong-answer-item">
                  得分{{ wa.score }}分: {{ wa.user_answer }}
                </div>
              </div>
            </div>
            <div class="wrong-card-foot">
              <span class="expand-hint">{{ expandedId === w.question_id ? '收起 ▲' : '展开详情 ▼' }}</span>
              <span class="wrong-time" v-if="w.last_wrong_at">最近错误: {{ formatTime(w.last_wrong_at) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="empty-state">
          <p>🎉 暂无错题记录</p>
          <p class="empty-desc">开始答题后，答错的题目会自动收录到这里</p>
        </div>
      </div>
    </div>

    <!-- 练习弹窗 -->
    <div v-if="practiceQuestions.length" class="practice-modal" @click.self="practiceQuestions = []">
      <div class="practice-content">
        <div class="practice-head">
          <h3>✏️ 错题重练（{{ practiceQuestions.length }} 题）</h3>
          <button class="btn mini ghost" @click="practiceQuestions = []">✕ 关闭</button>
        </div>
        <div class="practice-list">
          <div v-for="(q, i) in practiceQuestions" :key="q.question_id" class="practice-item">
            <div class="practice-q-head">
              <span class="q-num">第{{ i + 1 }}题</span>
              <span class="q-badge">{{ qtypeName(q.qtype) }}</span>
              <span class="q-wrong-count">曾错{{ q.wrong_count }}次</span>
            </div>
            <div class="practice-question">{{ q.question }}</div>
            <div class="practice-options" v-if="q.options && q.options.length">
              <div v-for="(opt, j) in q.options" :key="j" class="opt-item">
                <span class="opt-label">{{ String.fromCharCode(65 + j) }}.</span> {{ opt }}
              </div>
            </div>
            <button class="btn ghost mini show-answer-btn" @click="togglePracticeAnswer(i)">
              {{ practiceAnswerShown[i] ? '隐藏答案' : '查看答案' }}
            </button>
            <div v-if="practiceAnswerShown[i]" class="practice-answer">
              <p><strong>✅ 答案：</strong>{{ q._correct_answer }}</p>
              <div v-if="q._analysis && q._analysis.length" class="analysis-step">
                <div v-for="(a, j) in q._analysis" :key="j">步骤{{ a.step || j + 1 }}: {{ a.text }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { api } from '../api'
import StatCard from '../components/StatCard.vue'

const courses = ref([])
const selectedSubject = ref('')
const stats = ref(null)
const recommend = ref(null)
const wrongList = ref([])
const expandedId = ref(null)
const filterDays = ref(null)
const filterMinCount = ref(1)
const practicing = ref(false)
const practiceMode = ref('random')
const practiceCount = ref(5)
const practiceQuestions = ref([])
const practiceAnswerShown = reactive({})

onMounted(async () => {
  try {
    courses.value = await api.courses()
  } catch (e) {
    console.error('加载科目失败', e)
  }
  loadAll()
})

function loadAll() {
  loadStats()
  loadRecommend()
  loadWrongList()
}

async function loadStats() {
  try {
    const params = {}
    if (selectedSubject.value) params.subject_id = selectedSubject.value
    stats.value = await api.wrongBookStats(params)
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

async function loadRecommend() {
  try {
    const params = {}
    if (selectedSubject.value) params.subject_id = selectedSubject.value
    recommend.value = await api.wrongBookRecommend(params)
  } catch (e) {
    console.error('加载推荐失败', e)
  }
}

async function loadWrongList() {
  try {
    const params = { min_wrong_count: filterMinCount.value }
    if (selectedSubject.value) params.subject_id = selectedSubject.value
    if (filterDays.value) params.days = filterDays.value
    const data = await api.wrongBookList(params)
    wrongList.value = data.wrong_questions || []
  } catch (e) {
    console.error('加载错题列表失败', e)
  }
}

function toggleDetail(id) {
  expandedId.value = expandedId.value === id ? null : id
}

function togglePracticeAnswer(i) {
  practiceAnswerShown[i] = !practiceAnswerShown[i]
}

async function onPractice() {
  practicing.value = true
  try {
    const params = {
      count: practiceCount.value,
      mode: practiceMode.value,
    }
    if (selectedSubject.value) params.subject_id = selectedSubject.value
    const data = await api.wrongBookPractice(params)
    practiceQuestions.value = data.questions || []
    Object.keys(practiceAnswerShown).forEach(k => delete practiceAnswerShown[k])
    if (!practiceQuestions.value.length) {
      alert('暂无错题可供练习')
    }
  } catch (e) {
    alert('生成练习失败: ' + (e.message || e))
  } finally {
    practicing.value = false
  }
}

function exportCSV() {
  const params = {}
  if (selectedSubject.value) params.subject_id = selectedSubject.value
  const url = api.wrongBookExportUrl(params)
  // 带 Basic Auth 的下载
  window.open(url, '_blank')
}

function qtypeName(qtype) {
  const map = {
    single_choice: '单选', multiple_choice: '多选',
    judge: '判断', fill_single: '填空', fill_cloze: '填空',
    short: '简答', code: '代码', recite: '背诵',
  }
  return map[qtype] || qtype
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}
</script>

<style scoped>
.wb-view { padding: 20px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-head h2 { margin: 0 0 4px; font-size: 22px; }
.page-desc { margin: 0; color: #64748b; font-size: 13px; }
.head-actions { display: flex; gap: 8px; align-items: center; }
.toolbar-select { padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; background: #fff; }
.toolbar-select.mini { padding: 4px 8px; font-size: 12px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }

.wb-main { display: grid; grid-template-columns: 340px 1fr; gap: 16px; }

.wb-side { display: flex; flex-direction: column; gap: 16px; }
.panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; }
.panel h3 { margin: 0 0 12px; font-size: 15px; color: #1e293b; }

.trend-chart { display: flex; justify-content: space-between; align-items: flex-end; height: 100px; padding: 0 4px; }
.trend-bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.trend-bar { background: linear-gradient(to top, #ef4444, #f87171); border-radius: 4px 4px 0 0; min-height: 4px; display: flex; align-items: flex-start; justify-content: center; width: 24px; }
.trend-value { font-size: 10px; color: #fff; padding-top: 2px; }
.trend-label { font-size: 10px; color: #94a3b8; }

.weak-list { display: flex; flex-direction: column; gap: 8px; }
.weak-item { display: flex; align-items: center; gap: 10px; padding: 8px; background: #fef2f2; border-radius: 8px; }
.weak-rank { width: 20px; height: 20px; background: #ef4444; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; }
.weak-info { display: flex; flex-direction: column; gap: 2px; }
.weak-name { font-size: 13px; font-weight: 500; color: #1e293b; }
.weak-meta { font-size: 11px; color: #94a3b8; }

.plan-list { display: flex; flex-direction: column; gap: 10px; }
.plan-item { display: flex; gap: 10px; padding: 10px; background: #f8fafc; border-radius: 8px; }
.plan-priority { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: #fff; flex-shrink: 0; }
.plan-priority.p1 { background: #ef4444; }
.plan-priority.p2 { background: #f59e0b; }
.plan-priority.p3 { background: #3b82f6; }
.plan-priority.p4 { background: #10b981; }
.plan-content { flex: 1; }
.plan-content strong { font-size: 13px; color: #1e293b; }
.plan-content p { margin: 4px 0; font-size: 12px; color: #475569; line-height: 1.5; }
.plan-action { font-size: 11px; color: #64748b; font-style: italic; }

.practice-form { display: flex; flex-direction: column; gap: 8px; }
.practice-form label { font-size: 12px; color: #64748b; font-weight: 500; }
.form-input { padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; }
.btn { padding: 10px; background: #3b82f6; color: #fff; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; font-weight: 500; }
.btn:hover { background: #2563eb; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.ghost { background: #f1f5f9; color: #475569; }
.btn.mini { padding: 6px 12px; font-size: 12px; }
.btn.full { width: 100%; margin-top: 4px; }

.wb-list-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; max-height: calc(100vh - 320px); overflow-y: auto; }
.list-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.list-toolbar h3 { margin: 0; font-size: 16px; }
.filter-group { display: flex; gap: 8px; }

.wrong-list { display: flex; flex-direction: column; gap: 12px; }
.wrong-card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; cursor: pointer; transition: border-color 0.15s; }
.wrong-card:hover { border-color: #3b82f6; }
.wrong-card-head { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.wrong-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.wrong-badge.d1 { background: #dcfce7; color: #166534; }
.wrong-badge.d2 { background: #bbf7d0; color: #15803d; }
.wrong-badge.d3 { background: #fef3c7; color: #92400e; }
.wrong-badge.d4 { background: #fed7aa; color: #9a3412; }
.wrong-badge.d5 { background: #fecaca; color: #991b1b; }
.wrong-qtype { padding: 2px 8px; background: #f1f5f9; color: #475569; border-radius: 4px; font-size: 11px; }
.wrong-node { font-size: 12px; color: #64748b; }
.wrong-count { margin-left: auto; font-size: 12px; color: #ef4444; font-weight: 500; }
.wrong-question { font-size: 14px; color: #1e293b; line-height: 1.6; margin-bottom: 8px; }
.wrong-options { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.opt-item { font-size: 13px; color: #475569; }
.opt-label { font-weight: 600; color: #1e293b; margin-right: 4px; }
.wrong-detail { background: #f8fafc; border-radius: 8px; padding: 12px; margin: 8px 0; }
.detail-section { margin-bottom: 8px; font-size: 13px; line-height: 1.6; color: #334155; }
.detail-section strong { color: #1e293b; }
.analysis-step { margin-left: 8px; font-size: 12px; color: #475569; line-height: 1.8; }
.wrong-answer-item { font-size: 12px; color: #ef4444; margin-left: 8px; }
.wrong-card-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 8px; border-top: 1px solid #f1f5f9; }
.expand-hint { font-size: 12px; color: #3b82f6; }
.wrong-time { font-size: 11px; color: #94a3b8; }

.empty-state { text-align: center; padding: 60px 20px; }
.empty-state p { margin: 0; font-size: 18px; color: #64748b; }
.empty-desc { font-size: 14px !important; color: #94a3b8 !important; margin-top: 8px !important; }

.practice-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.practice-content { background: #fff; border-radius: 12px; width: 90%; max-width: 700px; max-height: 85vh; overflow-y: auto; padding: 20px; }
.practice-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.practice-head h3 { margin: 0; }
.practice-list { display: flex; flex-direction: column; gap: 16px; }
.practice-item { border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; }
.practice-q-head { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.q-num { font-weight: 600; color: #3b82f6; }
.q-badge { padding: 2px 8px; background: #f1f5f9; border-radius: 4px; font-size: 11px; }
.q-wrong-count { font-size: 12px; color: #ef4444; margin-left: auto; }
.practice-question { font-size: 14px; line-height: 1.6; margin-bottom: 8px; }
.practice-options { margin-bottom: 8px; }
.show-answer-btn { margin-top: 4px; }
.practice-answer { background: #f0fdf4; border-radius: 6px; padding: 10px; margin-top: 8px; font-size: 13px; }
.practice-answer p { margin: 0 0 6px; }
</style>
