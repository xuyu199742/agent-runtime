<script setup lang="ts">
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  zhCN,
  dateZhCN,
} from "naive-ui";
import type { GlobalThemeOverrides } from "naive-ui";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#527457",
    primaryColorHover: "#65876a",
    primaryColorPressed: "#405e45",
    primaryColorSuppl: "#527457",
    borderRadius: "10px",
  },
};
</script>
<template>
  <n-config-provider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme-overrides="themeOverrides"
  >
    <n-dialog-provider
      ><n-message-provider><router-view /></n-message-provider
    ></n-dialog-provider>
  </n-config-provider>
</template>
