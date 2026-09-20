<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-overlay" @click.self="close">
      <div class="modal" :class="[`size-${size}`, { 'no-padding': noPadding }]" @click.stop>
        <div class="modal-head">
          <div class="modal-title">
            <span v-if="icon" class="title-icon">{{ icon }}</span>
            {{ title }}
          </div>
          <button class="close-btn" @click="close">✕</button>
        </div>

        <div class="modal-tabs" v-if="tabs.length">
          <button
            v-for="t in tabs"
            :key="t.key"
            class="tab"
            :class="{ active: activeTab === t.key }"
            @click="activeTab = t.key"
          >
            {{ t.label }}
          </button>
        </div>

        <div class="modal-body">
          <slot></slot>
        </div>

        <div class="modal-foot" v-if="!hideFooter">
          <slot name="footer">
            <button class="btn ghost" @click="close">{{ cancelText }}</button>
            <button class="btn" :class="{ loading: loading }" :disabled="loading" @click="confirm">
              {{ confirmText }}
            </button>
          </slot>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  icon: { type: String, default: '' },
  size: { type: String, default: 'md' }, // sm/md/lg/xl
  confirmText: { type: String, default: '确定' },
  cancelText: { type: String, default: '取消' },
  loading: { type: Boolean, default: false },
  hideFooter: { type: Boolean, default: false },
  noPadding: { type: Boolean, default: false },
  tabs: { type: Array, default: () => [] }, // [{key, label}]
  closeOnOverlay: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const activeTab = ref(props.tabs[0]?.key || '')

watch(() => props.modelValue, (val) => {
  if (val && props.tabs.length) activeTab.value = props.tabs[0].key
})

function close() {
  if (props.loading) return
  emit('update:modelValue', false)
  emit('cancel')
}
function confirm() {
  emit('confirm')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn .15s ease;
  padding: 20px;
}
.modal {
  background: var(--bg-card);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,.2);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  animation: slideUp .2s ease;
  overflow: hidden;
}
.size-sm { width: 400px; }
.size-md { width: 520px; }
.size-lg { width: 680px; }
.size-xl { width: 860px; }

.modal-head {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.modal-title {
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
  transition: background var(--transition-fast), color var(--transition-fast);
}
.close-btn:hover { background: var(--bg-sunken); color: var(--text); }

.modal-tabs {
  display: flex;
  gap: 4px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tab {
  padding: 10px 16px;
  background: none;
  border: none;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color var(--transition-fast), border-color var(--transition-fast);
}
.tab:hover { color: var(--text); }
.tab.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 500;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}
.no-padding .modal-body { padding: 0; }

.modal-foot {
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
