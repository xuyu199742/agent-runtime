<script setup lang="ts">
defineProps<{ eyebrow: string; title: string; description?: string }>();
</script>
<template>
  <div class="page-head">
    <div>
      <div class="page-eyebrow">{{ eyebrow }}</div>
      <h1 class="page-title">{{ title }}</h1>
      <p class="page-description">{{ description }}</p>
    </div>
    <div class="page-actions"><slot /></div>
  </div>
</template>
