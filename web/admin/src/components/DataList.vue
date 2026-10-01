<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  NButton,
  NDataTable,
  NInput,
  NPagination,
  NIcon,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import { RefreshOutline, SearchOutline } from "@vicons/ionicons5";
import { api, query, type Page, type RecordData } from "../api/client";

const props = withDefaults(
  defineProps<{
    eyebrow: string;
    title: string;
    description?: string;
    endpoint: string;
    columns: DataTableColumns<RecordData>;
    params?: Record<string, string | number | boolean | undefined | null>;
    searchable?: boolean;
    pageSize?: number;
    emptyText?: string;
  }>(),
  { searchable: false, pageSize: 20, emptyText: "暂无数据" },
);
const rows = ref<RecordData[]>([]),
  page = ref(1),
  total = ref(0),
  keyword = ref(""),
  loading = ref(false);
const message = useMessage();
const pageCount = computed(() =>
  Math.max(1, Math.ceil(total.value / props.pageSize)),
);
async function reload() {
  loading.value = true;
  try {
    const result = await api.get<Page<RecordData> | RecordData[]>(
      query(props.endpoint, {
        page: page.value,
        page_size: props.pageSize,
        ...(props.searchable ? { keyword: keyword.value.trim() } : {}),
        ...props.params,
      }),
    );
    if (Array.isArray(result)) {
      rows.value = result;
      total.value = result.length;
    } else {
      rows.value = result.items;
      total.value = result.total;
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : "加载失败");
  } finally {
    loading.value = false;
  }
}
function search() {
  page.value = 1;
  reload();
}
watch(
  () => props.params,
  () => {
    page.value = 1;
    reload();
  },
  { deep: true },
);
watch(
  () => props.endpoint,
  () => {
    page.value = 1;
    reload();
  },
);
onMounted(reload);
defineExpose({ reload });
</script>

<template>
  <div class="page-head">
    <div>
      <div class="page-eyebrow">{{ eyebrow }}</div>
      <h1 class="page-title">{{ title }}</h1>
      <p class="page-description">{{ description }}</p>
    </div>
    <div class="page-actions">
      <slot name="top-actions" /><n-button
        secondary
        :loading="loading"
        @click="reload"
        ><template #icon><n-icon :component="RefreshOutline" /></template
        >刷新</n-button
      >
    </div>
  </div>
  <div class="panel">
    <div class="toolbar">
      <n-input
        v-if="searchable"
        v-model:value="keyword"
        clearable
        placeholder="搜索名称或关键词"
        style="width: 250px"
        @keyup.enter="search"
        @clear="search"
        ><template #prefix
          ><n-icon :component="SearchOutline" /></template></n-input
      ><n-button v-if="searchable" secondary @click="search">搜索</n-button
      ><slot name="filters" /><span class="grow" /><span
        class="muted mono"
        style="font-size: 10px"
        >{{ total }} RECORDS</span
      >
    </div>
    <div class="table-wrap">
      <n-data-table
        :columns="columns"
        :data="rows"
        :loading="loading"
        :pagination="false"
        :bordered="false"
        :single-line="false"
        :row-key="(row: RecordData) => String(row.id || row.code)"
        :scroll-x="900"
      />
    </div>
    <div class="pagination-bar">
      <span>第 {{ page }} / {{ pageCount }} 页 · 共 {{ total }} 条</span
      ><n-pagination
        v-model:page="page"
        :page-count="pageCount"
        size="small"
        @update:page="reload"
      />
    </div>
  </div>
</template>
