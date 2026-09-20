<script setup>
import { ref, onUnmounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  target: { type: HTMLTextAreaElement, required: true }, // 绑定的输入框
  appendText: { type: Function, default: null }, // 自定义插入文本的回调
})
const emit = defineEmits(['result'])

const recording = ref(false)
const uploading = ref(false)
const error = ref('')
let mediaRecorder = null
let chunks = []
let stream = null

async function toggle() {
  if (recording.value) {
    stop()
  } else {
    await start()
  }
}

async function start() {
  error.value = ''
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    mediaRecorder = new MediaRecorder(stream, { mimeType: mime })
    chunks = []
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
    mediaRecorder.onstop = onStop
    mediaRecorder.start()
    recording.value = true
  } catch (e) {
    error.value = '无法访问麦克风：' + e.message
  }
}

function stop() {
  if (mediaRecorder && recording.value) {
    mediaRecorder.stop()
    recording.value = false
  }
}

async function onStop() {
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
  if (chunks.length === 0) return
  const blob = new Blob(chunks, { type: 'audio/webm' })
  uploading.value = true
  try {
    const text = await api.asrTranscribe(blob)
    if (text) {
      if (props.appendText) {
        props.appendText(text)
      } else if (props.target) {
        const ta = props.target
        const start = ta.selectionStart ?? ta.value.length
        const end = ta.selectionEnd ?? ta.value.length
        ta.value = ta.value.slice(0, start) + text + ta.value.slice(end)
        ta.dispatchEvent(new Event('input', { bubbles: true }))
      }
      emit('result', text)
    }
  } catch (e) {
    error.value = e.message || '识别失败'
  } finally {
    uploading.value = false
    chunks = []
  }
}

onUnmounted(() => {
  if (recording.value) stop()
})
</script>

<template>
  <button
    type="button"
    class="voice-btn"
    :class="{ recording, uploading }"
    :disabled="uploading"
    @click="toggle"
    :title="recording ? '停止录音' : '语音输入'"
  >
    <span v-if="uploading" class="pulse">识别中…</span>
    <span v-else-if="recording" class="pulse">● 录音中</span>
    <span v-else>🎤</span>
  </button>
  <span v-if="error" class="voice-err">{{ error }}</span>
</template>

<style scoped>
.voice-btn {
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 14px;
  transition: all .15s;
}
.voice-btn:hover:not(:disabled) { border-color: var(--primary); }
.voice-btn.recording { border-color: #e74c3c; color: #e74c3c; background: #fff5f5; }
.voice-btn.uploading { opacity: .7; cursor: wait; }
.voice-btn:disabled { cursor: not-allowed; opacity: .5; }
.pulse { animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .5; } }
.voice-err { color: var(--danger); font-size: 11px; margin-left: 8px; }
</style>
