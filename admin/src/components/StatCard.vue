<template>
  <div class="stat-card" :class="[`theme-${theme}`, { clickable: clickable }]" @click="$emit('click')">
    <div class="stat-icon">{{ icon }}</div>
    <div class="stat-body">
      <div class="stat-value">{{ value }}</div>
      <div class="stat-label">{{ label }}</div>
      <div class="stat-sub" v-if="sub">{{ sub }}</div>
    </div>
    <div class="stat-trend" v-if="trend !== null" :class="trend > 0 ? 'up' : 'down'">
      {{ trend > 0 ? '↑' : '↓' }} {{ Math.abs(trend) }}%
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '📊' },
  value: { type: [String, Number], default: 0 },
  label: { type: String, default: '' },
  sub: { type: String, default: '' },
  theme: { type: String, default: 'blue' }, // blue/green/orange/purple/red
  trend: { type: Number, default: null },
  clickable: { type: Boolean, default: false },
})
defineEmits(['click'])
</script>

<style scoped>
.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast), border-color var(--transition-fast);
  position: relative;
  overflow: hidden;
}
.stat-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--stat-accent, var(--primary));
}
.stat-card.clickable { cursor: pointer; }
.stat-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,.1);
  border-color: var(--stat-accent, var(--primary));
}
.theme-blue { --stat-accent: #3E63DD; }
.theme-green { --stat-accent: #3E8E58; }
.theme-orange { --stat-accent: #C77E1E; }
.theme-purple { --stat-accent: #8A5CD6; }
.theme-red { --stat-accent: #C24238; }

.stat-icon {
  font-size: 28px;
  line-height: 1;
  flex-shrink: 0;
  width: 44px; height: 44px;
  display: flex; align-items: center; justify-content: center;
  background: var(--stat-accent, var(--primary));
  border-radius: 10px;
  opacity: 0.9;
}
.stat-body { flex: 1; min-width: 0; }
.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.stat-sub {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.stat-trend {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}
.stat-trend.up { background: #e6f7ec; color: #3E8E58; }
.stat-trend.down { background: #fdecea; color: #C24238; }
</style>
