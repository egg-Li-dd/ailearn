<template>
  <Teleport to="body">
    <Transition name="panel">
      <div v-if="modelValue" class="detail-overlay" @click.self="close">
        <div class="detail-panel" :class="[`width-${width}`]">
          <div class="panel-head">
            <div class="panel-title">
              <span v-if="icon" class="title-icon">{{ icon }}</span>
              <span>{{ title }}</span>
            </div>
            <button class="close-btn" @click="close">✕</button>
          </div>
          <div class="panel-body">
            <slot></slot>
          </div>
          <div class="panel-foot" v-if="$slots.footer">
            <slot name="footer"></slot>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '详情' },
  icon: { type: String, default: '' },
  width: { type: String, default: 'md' }, // sm/md/lg
})
const emit = defineEmits(['update:modelValue', 'close'])

function close() {
  emit('update:modelValue', false)
  emit('close')
}
</script>

<style scoped>
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.3);
  z-index: 900;
  display: flex;
  justify-content: flex-end;
}
.detail-panel {
  background: var(--bg-card);
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0,0,0,.12);
  animation: slideInRight .25s ease;
}
.width-sm { width: 360px; }
.width-md { width: 480px; }
.width-lg { width: 600px; }

.panel-head {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.title-icon { font-size: 20px; }
.close-btn {
  background: none;
  border: none;
  font-size: 16px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.close-btn:hover { background: var(--bg-sunken); color: var(--text); }

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.panel-foot {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.panel-enter-active, .panel-leave-active { transition: opacity .2s ease; }
.panel-enter-from, .panel-leave-to { opacity: 0; }
.panel-enter-active .detail-panel, .panel-leave-active .detail-panel {
  transition: transform .25s ease;
}
.panel-enter-from .detail-panel { transform: translateX(100%); }
.panel-leave-to .detail-panel { transform: translateX(100%); }

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
</style>
