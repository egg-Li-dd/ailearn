<template>
  <div class="search-bar">
    <div class="search-input-wrap">
      <span class="search-icon">🔍</span>
      <input
        type="text"
        class="search-input"
        :placeholder="placeholder"
        :value="modelValue"
        @input="onInput"
        @keydown.enter="$emit('search', modelValue)"
      />
      <button v-if="modelValue" class="clear-btn" @click="clear">✕</button>
    </div>

    <div class="filter-group" v-if="filters.length">
      <div class="filter-dropdown" v-for="f in filters" :key="f.key">
        <select :value="filterValues[f.key]" @change="onFilterChange(f.key, $event.target.value)">
          <option value="">{{ f.label }}</option>
          <option v-for="opt in f.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </div>
    </div>

    <div class="action-group">
      <slot name="actions"></slot>
      <button v-if="showExport" class="btn ghost mini" @click="$emit('export')">📤 导出</button>
      <button v-if="primaryLabel" class="btn mini" @click="$emit('primary')">{{ primaryLabel }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索...' },
  filters: { type: Array, default: () => [] }, // [{key, label, options:[{value,label}]}]
  showExport: { type: Boolean, default: false },
  primaryLabel: { type: String, default: '' },
  debounce: { type: Number, default: 300 },
})
const emit = defineEmits(['update:modelValue', 'search', 'filter-change', 'export', 'primary'])

const filterValues = ref({})
let debounceTimer = null

function onInput(e) {
  const val = e.target.value
  emit('update:modelValue', val)
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => emit('search', val), props.debounce)
}
function clear() {
  emit('update:modelValue', '')
  emit('search', '')
}
function onFilterChange(key, value) {
  filterValues.value[key] = value
  emit('filter-change', { key, value })
}
watch(() => props.filters, (newFilters) => {
  newFilters.forEach(f => { if (!(f.key in filterValues.value)) filterValues.value[f.key] = '' })
}, { immediate: true })
</script>

<style scoped>
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.search-input-wrap {
  position: relative;
  flex: 1;
  min-width: 200px;
  max-width: 360px;
}
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 13px;
  opacity: 0.5;
  pointer-events: none;
}
.search-input {
  width: 100%;
  height: 34px;
  padding: 0 32px 0 32px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: 13px;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.search-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(62,99,221,.12);
}
.clear-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 50%;
}
.clear-btn:hover { background: var(--bg-sunken); color: var(--text); }

.filter-group { display: flex; gap: 8px; }
.filter-dropdown select {
  height: 34px;
  padding: 0 28px 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  font-size: 13px;
  cursor: pointer;
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23908D85' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
}
.filter-dropdown select:focus { border-color: var(--primary); }

.action-group { display: flex; gap: 8px; margin-left: auto; }
</style>
