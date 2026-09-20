<template>
  <div class="stats-view">
    <div class="page-head">
      <div>
        <h2>📊 数据看板</h2>
        <p class="page-desc">学习数据总览、科目掌握度、活跃度热力图与 AI 周报</p>
      </div>
      <button class="btn" :disabled="generating" @click="generateWeekly">
        {{ generating ? '生成中...' : '✨ 生成本周周报' }}
      </button>
    </div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <StatCard icon="🔥" :value="overview.streak_days + '天'" label="连续学习" theme="orange" />
      <StatCard icon="⏱️" :value="overview.week_minutes + '分钟'" label="本周学习" theme="blue" />
      <StatCard icon="✅" :value="overview.total_tasks_done" label="累计完成任务" theme="green" />
      <StatCard icon="📚" :value="radar.length" label="在学科目" theme="purple" />
    </div>

    <div class="two-col">
      <!-- 科目掌握度 -->
      <div class="panel">
        <h3 class="panel-title">📚 科目掌握度</h3>
        <div v-if="radar.length" class="mastery-list">
          <div v-for="c in radar" :key="c.course_id" class="mastery-item">
            <div class="mastery-head">
              <span class="mastery-name">{{ c.name }}</span>
              <span class="mastery-val">{{ c.mastery }}%</span>
            </div>
            <div class="mastery-bar">
              <div class="mastery-fill" :style="{ width: c.mastery + '%', background: masteryColor(c.mastery) }"></div>
            </div>
          </div>
        </div>
        <div v-else class="empty-tip">暂无科目数据</div>
      </div>

      <!-- 学习热力图 -->
      <div class="panel">
        <h3 class="panel-title">🔥 近 12 周活跃度</h3>
        <div v-if="heatmapItems.length" class="heatmap">
          <div v-for="week in heatmapWeeks" :key="week[0]?.date || 'w'" class="heatmap-col">
            <div
              v-for="day in week"
              :key="day.date"
              class="heatmap-cell"
              :class="'level-' + day.score"
              :title="day.date + ' 活跃度 ' + day.score"
            ></div>
          </div>
        </div>
        <div v-else class="empty-tip">暂无活跃度数据</div>
        <div class="heatmap-legend">
          <span>少</span>
          <span class="heatmap-cell level-0"></span>
          <span class="heatmap-cell level-1"></span>
          <span class="heatmap-cell level-2"></span>
          <span class="heatmap-cell level-3"></span>
          <span class="heatmap-cell level-4"></span>
          <span>多</span>
        </div>
      </div>
    </div>

    <!-- 学习周报 -->
    <div class="panel weekly-panel">
      <div class="panel-head">
        <h3 class="panel-title">📝 AI 学习周报</h3>
        <span v-if="weekly.exists" class="weekly-date">{{ weekly.period }}</span>
      </div>
      <div v-if="weekly.exists && weekly.content" class="weekly-content">
        <pre>{{ weekly.content }}</pre>
      </div>
      <div v-else class="empty-tip">
        暂无周报，点击右上角「生成本周周报」按钮，AI 将基于你的学习数据生成周报。
        <br><small>生成需要约 10-30 秒，可在右下角任务悬浮窗查看进度</small>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import StatCard from '../components/StatCard.vue'
import { api } from '../api'

const overview = ref({ streak_days: 0, week_minutes: 0, total_tasks_done: 0 })
const radar = ref([])
const heatmapItems = ref([])
const weekly = ref({ exists: false, period: '', content: '' })
const generating = ref(false)

// 热力图按周分组（每周7天）
const heatmapWeeks = computed(() => {
  const weeks = []
  for (let i = 0; i < heatmapItems.value.length; i += 7) {
    weeks.push(heatmapItems.value.slice(i, i + 7))
  }
  return weeks
})

function masteryColor(v) {
  if (v >= 80) return '#22c55e'
  if (v >= 60) return '#eab308'
  if (v >= 40) return '#f97316'
  return '#ef4444'
}

async function loadAll() {
  try {
    const [ov, rd, hm, wr] = await Promise.all([
      api.statsOverview().catch(() => ({})),
      api.statsRadar().catch(() => ({ courses: [] })),
      api.statsHeatmap(84).catch(() => ({ items: [] })),
      api.weeklyReport().catch(() => ({ exists: false })),
    ])
    overview.value = ov || overview.value
    radar.value = rd.courses || []
    heatmapItems.value = hm.items || []
    weekly.value = wr || weekly.value
  } catch (e) {
    console.error('加载看板数据失败', e)
  }
}

async function generateWeekly() {
  if (generating.value) return
  generating.value = true
  try {
    const result = await api.generateWeeklyReport()
    const taskId = result.task_id
    if (!taskId) {
      alert('周报生成失败：未返回任务 ID')
      return
    }
    // 轮询任务状态
    const poll = setInterval(async () => {
      try {
        const task = await api.taskDetail(taskId)
        if (task.status === 'completed') {
          clearInterval(poll)
          generating.value = false
          await loadAll()
        } else if (task.status === 'failed' || task.status === 'cancelled') {
          clearInterval(poll)
          generating.value = false
          alert('周报生成失败：' + (task.error || '未知错误'))
        }
      } catch (e) {
        // 轮询出错不中断
      }
    }, 2000)
    // 超时保护：2分钟后停止轮询
    setTimeout(() => {
      clearInterval(poll)
      if (generating.value) {
        generating.value = false
        alert('周报生成超时，请在任务悬浮窗查看状态，完成后刷新页面')
      }
    }, 120000)
  } catch (e) {
    generating.value = false
    alert('创建周报任务失败：' + (e.message || e))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.stats-view { padding: 0; }

.page-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px; gap: 16px; flex-wrap: wrap;
}
.page-head h2 { margin: 0 0 4px; font-size: 22px; }
.page-desc { margin: 0; color: var(--text-muted); font-size: 13px; }

.stat-row {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 14px; margin-bottom: 20px;
}

.two-col {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 16px; margin-bottom: 20px;
}

.panel {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px;
}
.panel-title { margin: 0 0 14px; font-size: 15px; font-weight: 600; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.panel-head .panel-title { margin: 0; }

.weekly-date { font-size: 12px; color: var(--text-muted); background: var(--bg-sunken); padding: 3px 10px; border-radius: 6px; }

/* 科目掌握度 */
.mastery-list { display: flex; flex-direction: column; gap: 12px; }
.mastery-item { }
.mastery-head { display: flex; justify-content: space-between; margin-bottom: 5px; }
.mastery-name { font-size: 13px; font-weight: 500; }
.mastery-val { font-size: 13px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.mastery-bar { height: 8px; background: var(--bg-sunken); border-radius: 4px; overflow: hidden; }
.mastery-fill { height: 100%; border-radius: 4px; transition: width .3s ease; }

/* 热力图 */
.heatmap { display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 12px; }
.heatmap-col { display: flex; flex-direction: column; gap: 3px; }
.heatmap-cell { width: 12px; height: 12px; border-radius: 2px; }
.heatmap-cell.level-0 { background: var(--bg-sunken); }
.heatmap-cell.level-1 { background: #bbf7d0; }
.heatmap-cell.level-2 { background: #4ade80; }
.heatmap-cell.level-3 { background: #16a34a; }
.heatmap-cell.level-4 { background: #14532d; }
.heatmap-legend { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-muted); }
.heatmap-legend .heatmap-cell { width: 10px; height: 10px; }

/* 周报 */
.weekly-panel { }
.weekly-content {
  background: var(--bg-sunken); border-radius: 8px; padding: 16px;
  max-height: 500px; overflow-y: auto;
}
.weekly-content pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: inherit; font-size: 14px; line-height: 1.8; color: var(--text);
}

.empty-tip {
  text-align: center; padding: 32px 16px; color: var(--text-muted);
  font-size: 13px; line-height: 1.8;
}
.empty-tip small { font-size: 12px; opacity: .7; }

.btn {
  padding: 8px 18px; border-radius: 8px; border: none;
  background: var(--primary); color: #fff; font-size: 13px;
  cursor: pointer; transition: opacity .15s;
}
.btn:hover:not(:disabled) { opacity: .9; }
.btn:disabled { opacity: .5; cursor: not-allowed; }

@media (max-width: 900px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .two-col { grid-template-columns: 1fr; }
}
</style>
