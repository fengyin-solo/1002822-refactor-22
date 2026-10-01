<template>
  <section class="page" data-module="facility">
    <header class="page-head">
      <div>
        <h2>园建设施管理</h2>
        <p class="page-desc">维护园建设施，登记损坏、安排修复、验收修复按同一份口径判定损坏等级。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记园建设施</button>
        <button class="btn" type="button" @click="backfill">按新口径回填</button>
        <button class="btn" type="button" @click="exportRows">导出园建设施清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无园建设施数据，可先登记园建设施</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条园建设施记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/facility'
const columns = ["设施编号", "设施名称", "设施类型", "所在绿地", "安装日期", "上次检修", "损坏描述", "损坏等级", "设施状态"]
const actions = ["登记损坏", "安排修复", "验收修复"]
const statuses = ["完好", "轻微损坏", "严重损坏", "已修复"]
const stats = [{"label": "完好设施", "value": 0}, {"label": "损坏设施", "value": 0}, {"label": "已修复设施", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '园建设施登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  const values: Record<string, string> = { action }
  if (action === '登记损坏') {
    const description = window.prompt('请填写损坏描述（三个动作按同一份口径判定损坏等级）', String(row['损坏描述'] ?? ''))
    if (description === null) return
    values['损坏描述'] = description
  }
  if (action === '验收修复') {
    const conclusion = window.prompt('请填写验收结论（合格/不合格），等级冲突时以最后一次验收为准', '合格')
    if (conclusion === null) return
    values['验收结论'] = conclusion
  }
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error('园建设施动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message ?? '园建设施动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? `园建设施已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '园建设施操作失败'
  }
}

async function backfill() {
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/backfill`, {
      method: 'POST',
      body: JSON.stringify({ values: {} }),
    })
    if (!response.ok) {
      throw new Error('园建设施回填未生效，请稍后重试')
    }
    const payload = await response.json()
    noticeMessage.value = payload.message ?? '已按统一口径回填'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '园建设施回填失败'
  }
}

async function reload() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('园建设施列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 读取成功才清错误；接口超时等原因留在页面上，直到下一次成功
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '园建设施列表读取失败'
  }
}

onMounted(reload)
</script>
