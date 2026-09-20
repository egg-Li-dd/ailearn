<template>
  <div class="empty-state">
    <div class="empty-icon">{{ icon }}</div>
    <div class="empty-title">{{ title }}</div>
    <div class="empty-desc" v-if="desc">{{ desc }}</div>
    <div class="empty-actions" v-if="$slots.default || actionLabel">
      <slot></slot>
      <button v-if="actionLabel" class="btn" @click="$emit('action')">{{ actionLabel }}</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '📭' },
  title: { type: String, default: '暂无数据' },
  desc: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
})
defineEmits(['action'])
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.6;
  line-height: 1;
}
.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}
.empty-desc {
  font-size: 13px;
  color: var(--text-muted);
  max-width: 360px;
  margin-bottom: 20px;
  line-height: 1.6;
}
.empty-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: center;
}
</style>
