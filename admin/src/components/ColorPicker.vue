<template>
  <div class="color-picker">
    <div class="color-swatches">
      <button
        v-for="c in presetColors"
        :key="c.value"
        class="swatch"
        :class="{ active: modelValue === c.value }"
        :style="{ background: c.value }"
        :title="c.name"
        @click="select(c.value)"
      >
        <span v-if="modelValue === c.value" class="check">✓</span>
      </button>
    </div>
    <div class="custom-color" v-if="allowCustom">
      <label class="custom-label">
        <span>自定义</span>
        <input type="color" :value="modelValue || '#3E63DD'" @input="select($event.target.value)" />
      </label>
      <input type="text" class="hex-input" :value="modelValue" placeholder="#RRGGBB" @input="select($event.target.value)" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  allowCustom: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])

const presetColors = [
  { name: '靛蓝', value: '#3E63DD' },
  { name: '紫色', value: '#8A5CD6' },
  { name: '玫红', value: '#D63384' },
  { name: '红色', value: '#C24238' },
  { name: '橙色', value: '#C77E1E' },
  { name: '金色', value: '#D4A017' },
  { name: '绿色', value: '#3E8E58' },
  { name: '青色', value: '#17A2B8' },
  { name: '蓝色', value: '#0D6EFD' },
  { name: '深蓝', value: '#1B3A5C' },
  { name: '灰色', value: '#6C757D' },
  { name: '深灰', value: '#343A40' },
]

function select(val) {
  emit('update:modelValue', val)
}
</script>

<style scoped>
.color-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.color-swatches {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
}
.swatch {
  width: 100%;
  aspect-ratio: 1;
  border: 2px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  padding: 0;
  position: relative;
  transition: transform var(--transition-fast), border-color var(--transition-fast);
}
.swatch:hover { transform: scale(1.1); }
.swatch.active {
  border-color: var(--text);
  box-shadow: 0 0 0 2px var(--bg-card), 0 0 0 4px var(--text);
}
.check {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  text-shadow: 0 1px 2px rgba(0,0,0,.3);
}
.custom-color {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.custom-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.custom-label input[type="color"] {
  width: 32px;
  height: 28px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
}
.hex-input {
  flex: 1;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
  text-transform: uppercase;
  outline: none;
}
.hex-input:focus { border-color: var(--primary); }
</style>
