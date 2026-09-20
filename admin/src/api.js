const BASE = '/api/v1'
const DEFAULT_TIMEOUT = 30000 // 30秒默认超时

// 管理台 Basic Auth（开发模式下 Vite 代理不会自动传递浏览器凭证，需显式设置）
const ADMIN_BASIC_AUTH = 'Basic ' + btoa('admin:ailearn2026')

// 当前查看的用户 key（管理台用户切换）
let currentUserKey = localStorage.getItem('admin_user_key') || 'eggli'

export function setCurrentUserKey(key) {
  currentUserKey = key
  localStorage.setItem('admin_user_key', key)
}
export function getCurrentUserKey() { return currentUserKey }

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body, options = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT)

  try {
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': ADMIN_BASIC_AUTH,
    }
    // 自动注入当前查看用户的 X-User-Key（物理分库路由）
    if (currentUserKey && !options.skipUserKey) {
      headers['X-User-Key'] = currentUserKey
    }
    const resp = await fetch(BASE + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: 'include',
    })
    if (resp.status === 204) return null
    const data = await resp.json().catch(() => null)
    if (!resp.ok) {
      const detail = data && data.detail
      const msg = detail
        ? typeof detail === 'string' ? detail : (detail.message || '请求失败')
        : `请求失败 (${resp.status})`
      throw new ApiError(msg, resp.status, detail)
    }
    return data
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new ApiError('请求超时，请检查网络或重试', 0, null)
    }
    if (e instanceof ApiError) throw e
    throw new ApiError(`网络错误：${e.message}`, 0, null)
  } finally {
    clearTimeout(timeout)
  }
}

export const api = {
  // 科目
  courses: (params) => request('GET', `/courses?${new URLSearchParams(params || {}).toString()}`),
  createCourse: (b) => request('POST', '/courses', b),
  updateCourse: (id, b) => request('PUT', `/courses/${id}`, b),
  deleteCourse: (id) => request('DELETE', `/courses/${id}`),
  archiveCourse: (id, isArchived) => request('PUT', `/courses/${id}/archive`, { is_archived: isArchived }),
  sortCourses: (items) => request('PUT', '/courses/sort', items),
  courseSummary: (id) => request('GET', `/courses/${id}/summary`),
  batchDeleteCourses: (ids) => request('DELETE', '/courses/batch', { ids }),

  // 周课表
  schedule: (params) => request('GET', `/schedule?${new URLSearchParams(params || {}).toString()}`),
  createScheduleItem: (b) => request('POST', '/schedule', b),
  updateScheduleItem: (id, b) => request('PUT', `/schedule/${id}`, b),
  deleteScheduleItem: (id) => request('DELETE', `/schedule/${id}`),
  scheduleGrid: (weekType) => request('GET', `/schedule/grid?week_type=${weekType || 'all'}`),
  moveScheduleItem: (id, b) => request('PUT', `/schedule/${id}/move`, b),
  scheduleConflicts: (weekday) => request('GET', `/schedule/conflicts${weekday !== undefined ? '?weekday=' + weekday : ''}`),
  batchDeleteSchedule: (ids) => request('DELETE', '/schedule/batch', { ids }),
  // 课表模板
  scheduleTemplates: () => request('GET', '/schedule/templates'),
  saveScheduleTemplate: (b) => request('POST', '/schedule/templates', b),
  applyScheduleTemplate: (id) => request('POST', `/schedule/templates/${id}/apply`),
  deleteScheduleTemplate: (id) => request('DELETE', `/schedule/templates/${id}`),

  // 日期例外
  exceptions: (params) => request('GET', `/schedule/exceptions?${new URLSearchParams(params || {}).toString()}`),
  createException: (b) => request('POST', '/schedule/exceptions', b),
  updateException: (id, b) => request('PUT', `/schedule/exceptions/${id}`, b),
  deleteException: (id) => request('DELETE', `/schedule/exceptions/${id}`),
  exceptionsCalendar: (year, month) => request('GET', `/schedule/exceptions/calendar?year=${year}&month=${month}`),
  batchImportExceptions: (items) => request('POST', '/schedule/exceptions/batch', { items }),
  expandExceptions: (start, end) => request('GET', `/schedule/exceptions/expand?start=${start}&end=${end}`),
  batchDeleteExceptions: (ids) => request('DELETE', '/schedule/exceptions/batch', { ids }),

  // AI 配置（旧接口，向后兼容）
  aiConfig: () => request('GET', '/ai/config'),
  saveAiConfig: (b) => request('PUT', '/ai/config', b),
  testAi: () => request('POST', '/ai/test', null, { timeout: 60000 }),
  aiAction: (b) => request('POST', '/ai/action', b, { timeout: 60000 }),
  aiGenerate: (b) => request('POST', '/ai/generate', b, { timeout: 60000 }),
  opencodeImport: () => request('GET', '/ai/opencode-import', null, { timeout: 15000 }),
  aiModels: () => request('GET', '/ai/models', null, { timeout: 15000 }),

  // AI 渠道管理（新接口）
  aiChannels: (params) => request('GET', `/ai/channels?${new URLSearchParams(params || {}).toString()}`),
  aiChannelStats: () => request('GET', '/ai/channels/stats'),
  createAiChannel: (b) => request('POST', '/ai/channels', b),
  updateAiChannel: (id, b) => request('PUT', `/ai/channels/${id}`, b),
  deleteAiChannel: (id) => request('DELETE', `/ai/channels/${id}`),
  toggleAiChannel: (id) => request('POST', `/ai/channels/${id}/toggle`),
  testAiChannel: (id) => request('POST', `/ai/channels/${id}/test`, null, { timeout: 60000 }),
  fetchAiChannelModels: (id) => request('GET', `/ai/channels/${id}/models`, null, { timeout: 15000 }),

  // AI 调用记录
  aiCalls: (params) => request('GET', `/ai/calls?${new URLSearchParams(params).toString()}`),
  aiCallStats: () => request('GET', '/ai/calls/stats'),
  aiCallDetail: (id) => request('GET', `/ai/calls/${id}`),
  deleteAiCall: (id) => request('DELETE', `/ai/calls/${id}`),
  clearAiCalls: () => request('DELETE', '/ai/calls'),

  // AI 功能配置
  aiFunctionConfig: () => request('GET', '/ai/function-config'),
  updateAiFunctionConfig: (funcType, b) => request('PUT', `/ai/function-config/${funcType}`, b),
  detectAiFunctionConfig: () => request('POST', '/ai/function-config/detect'),
  autoAiFunctionConfig: (apply) => request('POST', '/ai/function-config/auto-config', { apply }),
  getAutoConfigTask: (taskId) => request('GET', `/ai/function-config/auto-config/${taskId}`),
  getAutoConfigSettings: () => request('GET', '/ai/auto-config-settings'),
  updateAutoConfigSettings: (b) => request('PUT', '/ai/auto-config-settings', b),

  // 知识树
  knowledgeTree: (params) => request('GET', `/knowledge/tree?${new URLSearchParams(params || {}).toString()}`),
  importOutline: (b) => request('POST', '/knowledge/import-outline', b, { timeout: 60000 }),
  importOutlinePreview: (b) => request('POST', '/knowledge/import-preview', b, { timeout: 60000 }),
  confirmImportOutline: (b) => request('POST', '/knowledge/import-confirm', b),
  createNode: (b) => request('POST', '/knowledge/nodes', b),
  updateNode: (id, b) => request('PUT', `/knowledge/nodes/${id}`, b),
  deleteNode: (id, cascade) => request('DELETE', `/knowledge/nodes/${id}${cascade ? '?cascade=true' : ''}`),
  moveNode: (id, b) => request('PUT', `/knowledge/nodes/${id}/move`, b),
  sortNodes: (items) => request('PUT', '/knowledge/nodes/sort', items),
  nodeDetail: (id) => request('GET', `/knowledge/nodes/${id}/detail`),
  nodeMasteryHistory: (id, limit) => request('GET', `/knowledge/nodes/${id}/mastery-history?limit=${limit || 20}`),
  updateNodePrerequisites: (id, ids) => request('PUT', `/knowledge/nodes/${id}/prerequisites`, { ids }),
  exportKnowledgeTree: (subjectId, format) => request('GET', `/knowledge/export?subject_id=${subjectId || ''}&format=${format || 'json'}`),
  copySubtree: (id, targetSubjectId) => request('POST', `/knowledge/nodes/${id}/copy-subtree`, { target_subject_id: targetSubjectId }),
  batchDeleteNodes: (ids, cascade) => request('DELETE', `/knowledge/nodes/batch${cascade ? '?cascade=true' : ''}`, { ids }),
  searchKnowledge: (keyword, subjectId) => request('GET', `/knowledge/search?keyword=${encodeURIComponent(keyword)}${subjectId ? '&subject_id=' + subjectId : ''}`),
  updateMastery: (id, b) => request('POST', `/knowledge/nodes/${id}/mastery`, b),
  // 知识点细化（参数表）
  refineNodeParams: (id, force) => request('POST', `/knowledge/nodes/${id}/refine?force=${force ? 'true' : 'false'}`, null, { timeout: 120000 }),
  getNodeParams: (id) => request('GET', `/knowledge/nodes/${id}/params`),
  updateNodeParams: (id, params) => request('PUT', `/knowledge/nodes/${id}/params`, params),
  // 知识点参数表 CSV 批量导入导出
  exportParamsCsvUrl: (subjectId, onlyRefined) => `${BASE}/knowledge/params/export?subject_id=${subjectId || ''}&only_refined=${onlyRefined ? 'true' : 'false'}`,
  importParamsCsv: async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    const resp = await fetch(BASE + '/knowledge/params/import', { method: 'POST', body: fd })
    const data = await resp.json().catch(() => null)
    if (!resp.ok) throw new ApiError(data?.detail || '导入失败', resp.status, data?.detail)
    return data
  },

  // 审计日志
  auditLogs: (params) => request('GET', `/audit-logs?${new URLSearchParams(params || {}).toString()}`),
  cleanupAuditLogs: (days) => request('DELETE', `/audit-logs/cleanup?days=${days || 90}`),

  // 会话与任务
  sessionsToday: () => request('GET', '/sessions/today'),
  sessionDetail: (id) => request('GET', `/sessions/${id}`),
  planSession: (id) => request('POST', `/sessions/${id}/plan`, null, { timeout: 60000 }),
  createTask: (sessionId, b) => request('POST', `/sessions/${sessionId}/tasks`, b),
  completeTask: (taskId) => request('POST', `/tasks/${taskId}/complete`),
  skipTask: (taskId) => request('POST', `/tasks/${taskId}/skip`),

  // 统计
  statsOverview: () => request('GET', '/stats/overview'),
  statsRadar: () => request('GET', '/stats/radar'),
  statsHeatmap: (days) => request('GET', `/stats/heatmap?days=${days || 84}`),
  weeklyReport: () => request('GET', '/stats/weekly-report'),
  generateWeeklyReport: () => request('POST', '/stats/weekly-report', null, { timeout: 60000 }),

  // 复习
  reviewToday: () => request('GET', '/review/today'),
  reviewRate: (queueId, rating) => request('POST', `/review/${queueId}/rate`, { rating }),
  completeReview: (queueId, correct) => request('POST', `/review/${queueId}/complete`, { correct }),

  // 出题判卷
  createQuiz: (nodeId) => request('POST', `/knowledge/nodes/${nodeId}/quiz`, null, { timeout: 60000 }),
  answerQuiz: (b) => request('POST', '/quiz/answer', b, { timeout: 60000 }),

  // 课堂
  classroomState: () => request('GET', '/classroom/state'),
  classroomActivate: (sessionId) => request('POST', '/classroom/activate', { session_id: sessionId }),
  classroomRetention: () => request('GET', '/classroom/retention'),
  setClassroomRetention: (days) => request('PUT', '/classroom/retention', { days }),
  cleanupClassroom: () => request('POST', '/classroom/cleanup'),
  // 课堂消息管理（历史信息映射）
  classroomConversations: () => request('GET', '/classroom/admin/conversations'),
  classroomMessages: (convId) => request('GET', '/classroom/admin/conversations/' + convId + '/messages'),
  deleteClassroomMessage: (msgId) => request('DELETE', '/classroom/admin/messages/' + msgId),
  clearClassroomConversation: (convId) => request('DELETE', '/classroom/admin/conversations/' + convId + '/messages'),

  // 答疑
  conversations: () => request('GET', '/conversations'),
  createConversation: (b) => request('POST', '/conversations', b),
  conversationMessages: (id) => request('GET', `/conversations/${id}/messages`),
  generateSediments: (id) => request('POST', `/conversations/${id}/sediments`, null, { timeout: 60000 }),
  acceptSediment: (id) => request('POST', `/sediments/${id}/accept`),
  rejectSediment: (id) => request('POST', `/sediments/${id}/reject`),

  // ASR
  asrTranscribe: async (blob) => {
    const fd = new FormData()
    fd.append('file', blob, 'recording.webm')
    const resp = await fetch(BASE + '/asr/transcribe', { method: 'POST', body: fd })
    const data = await resp.json().catch(() => null)
    if (!resp.ok) throw new ApiError(data?.detail || `识别失败 (${resp.status})`, resp.status, data?.detail)
    return data.text
  },
  asrStatus: () => request('GET', '/asr/status'),

  // 设置
  getSprint: () => request('GET', '/settings/sprint'),
  setSprint: (enabled) => request('PUT', '/settings/sprint', { enabled }),

  // 日志中心
  logs: (params) => request('GET', `/logs?${new URLSearchParams(params || {}).toString()}`),
  logStats: () => request('GET', '/logs/stats'),
  cleanupLogs: (source, days) => request('DELETE', `/logs?source=${source || 'all'}&days=${days || 30}`),

  // 后台任务
  tasks: (params) => request('GET', `/tasks?${new URLSearchParams(params || {}).toString()}`),
  activeTasks: () => request('GET', '/tasks/active'),
  taskDetail: (id) => request('GET', `/tasks/${id}`),
  taskEvents: (id) => request('GET', `/tasks/${id}/events`),
  cancelTask: (id) => request('POST', `/tasks/${id}/cancel`),
  retryTask: (id) => request('POST', `/tasks/${id}/retry`),
  deleteTask: (id) => request('DELETE', `/tasks/${id}`),

  // 题目导入
  quizImportText: (b) => request('POST', '/quiz/import/text', b, { timeout: 180000 }),
  quizImportBatch: (b) => request('POST', '/quiz/import/batch', b, { timeout: 300000 }),
  quizImportParse: (b) => request('POST', '/quiz/import/parse', b, { timeout: 120000 }),
  quizImportAnalysis: (b) => request('POST', '/quiz/import/analysis', b, { timeout: 180000 }),
  quizImportSplitPreview: (text) => request('GET', `/quiz/import/split-preview?text=${encodeURIComponent(text)}`, null, { timeout: 30000 }),

  // 智能出题
  quizGenerateBatch: (b) => request('POST', '/quiz/generate/batch', b, { timeout: 300000 }),
  quizGenerateSave: (b) => request('POST', '/quiz/generate/save', b, { timeout: 60000 }),
  quizGenerateVerify: (b) => request('POST', '/quiz/generate/verify', b, { timeout: 120000 }),
  quizGenerateNodes: (subjectId) => request('GET', `/quiz/generate/nodes${subjectId ? `?subject_id=${subjectId}` : ''}`, null, { timeout: 30000 }),

  // 知识增强（Phase 3）
  analyzePrerequisites: (chapterId, autoApply = true) =>
    request('POST', `/knowledge/enhance/prerequisites/${chapterId}?auto_apply=${autoApply}`, null, { timeout: 180000 }),
  generateNotes: (nodeId, autoApply = true) =>
    request('POST', `/knowledge/enhance/notes/${nodeId}?auto_apply=${autoApply}`, null, { timeout: 120000 }),
  generateNotesBatch: (nodeIds, autoApply = true) =>
    request('POST', '/knowledge/enhance/notes/batch', { node_ids: nodeIds, auto_apply: autoApply }, { timeout: 600000 }),
  getWeakPoints: (subjectId) => request('GET', `/knowledge/enhance/weak-points/${subjectId}`),
  getKnowledgeGraph: (subjectId) => request('GET', `/knowledge/enhance/graph/${subjectId}`),

  // 数学验证（Phase 4）
  mathVerifyDerivative: (b) => request('POST', '/math/verify/derivative', b, { timeout: 30000 }),
  mathVerifyIntegral: (b) => request('POST', '/math/verify/integral', b, { timeout: 30000 }),
  mathVerifyLimit: (b) => request('POST', '/math/verify/limit', b, { timeout: 30000 }),
  mathVerifyNumeric: (b) => request('POST', '/math/verify/numeric', b, { timeout: 30000 }),
  mathVerifyEquation: (b) => request('POST', '/math/verify/equation', b, { timeout: 30000 }),
  mathVerifyAuto: (b) => request('POST', '/math/verify/auto', b, { timeout: 30000 }),
  mathCapabilities: () => request('GET', '/math/capabilities'),
  mathParse: (latex) => request('POST', '/math/parse', { latex }),

  // 错题本（Phase 5）
  wrongBookList: (params) => request('GET', `/wrong-book/list?${new URLSearchParams(params || {}).toString()}`),
  wrongBookStats: (params) => request('GET', `/wrong-book/stats?${new URLSearchParams(params || {}).toString()}`),
  wrongBookRecommend: (params) => request('GET', `/wrong-book/recommend?${new URLSearchParams(params || {}).toString()}`),
  wrongBookPractice: (b) => request('POST', '/wrong-book/practice', b),
  wrongBookExportUrl: (params) => `/api/v1/wrong-book/export?${new URLSearchParams(params || {}).toString()}`,

  // 系统设置
  getSettings: () => request('GET', '/settings'),

  // ========== 用户管理（多用户物理分库） ==========
  adminUsers: () => request('GET', '/auth/admin/users'),
  adminCreateUser: (b) => request('POST', '/auth/admin/users', b),
  adminUpdateUser: (id, b) => request('PUT', `/auth/admin/users/${id}`, b),
  adminResetPin: (id, pin) => request('POST', `/auth/admin/users/${id}/reset-pin`, { pin }),
  adminDeleteUser: (id) => request('DELETE', `/auth/admin/users/${id}`),
  adminUserStats: (id) => request('GET', `/auth/admin/users/${id}/stats`),
}

export { ApiError }
