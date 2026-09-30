<script setup lang="ts">
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  zhCN,
  dateZhCN,
  darkTheme,
} from "naive-ui";
import type { GlobalThemeOverrides } from "naive-ui";
import { darkMode } from "./stores/theme";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#3f83ed",
    primaryColorHover: "#5a96ef",
    primaryColorPressed: "#286dd9",
    primaryColorSuppl: "#3f83ed",
    borderRadius: "4px",
  },
};
</script>

<template>
  <n-config-provider
    :locale="zhCN"
    :date-locale="dateZhCN"
    :theme="darkMode ? darkTheme : null"
    :theme-overrides="themeOverrides"
  >
    <n-dialog-provider
      ><n-message-provider><router-view /></n-message-provider
    ></n-dialog-provider>
  </n-config-provider>
</template>
