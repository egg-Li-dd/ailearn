<script setup>
import { ref, nextTick } from 'vue'
import { api } from '../api.js'
import VoiceInput from './VoiceInput.vue'

const props = defineProps({
  contextType: { type: String, required: true },
  title: { type: String, default: 'AI 生成' },
  placeholder: { type: String, default: '描述要生成的数据，例如：每周二上午9点英语一…' },
  createFn: { type: Function, required: true },
})
const emit = defineEmits(['done', 'close'])

const open = ref(false)
const instruction = ref('')
const busy = ref(false)
const items = ref([])
const ignored = ref([])
const error = ref('')
const textareaRef = ref(null)

function show() {
  open.value = true
  instruction.value = ''
  items.value = []
  ignored.value = []
  error.value = ''
  nextTick(() => textareaRef.value?.focus())
}

async function generate() {
  if (!instruction.value.trim()) { error.value = '请输入描述'; return }
  busy.value = true
  error.value = ''
  items.value = []
  ignored.value = []
  try {
    const r = await api.aiGenerate({
      context_type: props.contextType,
      items: [],
      instruction: instruction.value.trim(),
    })
    items.value = r.items || []
    ignored.value = r.ignored || []
    if (!items.value.length) error.value = '未能解析出数据，请换一种描述'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}

function fmt(item) {
  const out = {}
  for (const [k, v] of Object.entries(item)) {
    let val = v
    if (k === 'weekday' && typeof v === 'number') val = ['周一','周二','周三','周四','周五','周六','周日'][v] || v
    if (k === 'course_id') val = `科目#${v}`
    if (k === 'action') val = v === 'add' ? '加课' : v === 'remove' ? '停课' : v
    out[k] = val
  }
  return out
}

async function create() {
  busy.value = true
  try {
    await props.createFn(items.value)
    emit('done')
    open.value = false
  } catch (e) { error.value = e.message } finally { busy.value = false }
}

defineExpose({ show })
</script>

<template>
  <div v-if="open" class="overlay" @click.self="open = false">
    <div class="modal">
      <h3>{{ title }}</h3>
      <div class="input-row">
        <textarea ref="textareaRef" v-model="instruction" rows="3" :placeholder="placeholder" @keydown.ctrl.enter="generate"></textarea>
        <VoiceInput :target="textareaRef" />
      </div>
      <div class="actions">
        <button class="btn ai" :disabled="busy" @click="generate">{{ busy ? 'AI 生成中…' : 'AI 生成' }}</button>
      </div>
      <div v-if="error" class="err">{{ error }}</div>
      <div v-if="ignored.length" class="warn">
        已忽略 {{ ignored.length }} 条无效数据：
        <ul>
          <li v-for="(ig, i) in ignored" :key="i">{{ ig.reason }}</li>
        </ul>
      </div>
      <div v-if="items.length" class="preview">
        <div class="pv-head">将新增 {{ items.length }} 条 <span class="hint">（确认后逐条落库）</span></div>
        <div v-for="(it, i) in items" :key="i" class="pv-item">
          <template v-for="(v, k) in fmt(it)" :key="k">
            <span class="pv-k">{{ k }}</span><span class="pv-v">{{ v }}</span>
          </template>
        </div>
        <div class="actions">
          <button class="btn ghost mini" @click="open = false">取消</button>
          <button class="btn mini" :disabled="busy" @click="create">确认创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(28,27,26,.35);
  display: flex; align-items: center; justify-content: center; z-index: 210;
}
.modal {
  background: var(--bg-card); border-radius: 14px; padding: 20px 22px;
  width: 480px; box-shadow: 0 8px 32px rgba(0,0,0,.2); max-height: 78vh; overflow-y: auto;
}
.modal h3 { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.input-row { display: flex; gap: 8px; align-items: flex-start; }
.input-row textarea { flex: 1; }
textarea { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; font-family: inherit; outline: none; resize: vertical; }
textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(62,99,221,.12); }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.err { color: var(--danger); font-size: 12px; margin-top: 10px; }
.warn { color: #b8860b; font-size: 12px; margin-top: 10px; background: #fff8e6; border: 1px solid #f0d98c; border-radius: 6px; padding: 8px 10px; }
.warn ul { margin: 4px 0 0; padding-left: 18px; }
.preview { margin-top: 14px; }
.pv-head { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.hint { font-size: 11px; color: var(--text-muted); font-weight: 400; }
.pv-item {
  display: flex; flex-wrap: wrap; gap: 4px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 12px; margin-bottom: 6px; font-size: 12.5px;
}
.pv-k { color: var(--text-muted); }
.pv-v { color: var(--text); font-weight: 500; }
</style>