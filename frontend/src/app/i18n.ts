/*
 * One localization layer for frontend-owned interface copy.
 *
 * Only text the frontend itself authors lives here. Server-projected scientific
 * vocabulary — task parameter names, constraints, help, Runner-authored
 * descriptions, categories, and result-renderer wording — stays server-owned and
 * must never be duplicated into these catalogs. Runner/task semantics have one
 * source of truth: the owning `task.yaml` projected by the server.
 */

export type Locale = 'en' | 'zh-CN';

export const locales: ReadonlyArray<{ id: Locale; label: string }> = [
  { id: 'en', label: 'English' },
  { id: 'zh-CN', label: '简体中文' },
];

const storageKey = 'revocompute-locale';
const fallback: Locale = 'en';

type Dictionary = Record<string, string>;

const en: Dictionary = {
  // Shell chrome
  'shell.nav.primary': 'Primary',
  'shell.nav.runners': 'Runners',
  'shell.nav.dashboard': 'Dashboard',
  'shell.nav.newTask': 'New task',
  'shell.nav.expand': 'Expand navigation',
  'shell.nav.collapse': 'Collapse navigation',
  'shell.action.theme': 'Theme',
  'shell.action.profile': 'Profile',
  'shell.action.signIn': 'Sign in',
  'shell.action.logout': 'Log out',
  'shell.action.administration': 'Administration',
  'shell.action.language': 'Language',
  'shell.action.notices': 'System notices',
  'shell.admin.users': 'User control',
  'shell.admin.logs': 'Server logs',
  'shell.admin.configuration': 'Configuration',
  'theme.auto': 'Auto',
  'theme.light': 'Light',
  'theme.dark': 'Dark',

  // Public chrome
  'public.brand': 'REvoDesign',
  'public.home': 'REvoDesign home',
  'public.nav.home': 'Home',
  'public.nav.runners': 'Runners',
  'public.nav.api': 'API',
  'public.nav.agentApi': 'Agent API',
  'public.nav.documentation': 'Documentation',
  'public.nav.github': 'GitHub',
  'public.nav.open': 'Open navigation',
  'public.nav.label': 'Public navigation',

  // Shared page-level copy
  'page.notFound.title': 'Page not found',
  'page.notFound.body': 'The requested REvoCompute route does not exist.',
  'page.notFound.action': 'Browse runners',

  // Dashboard
  'dashboard.title': 'Dashboard',
  'dashboard.action.newTask': 'New task',
  'dashboard.action.refresh': 'Refresh',
  'dashboard.stats.label': 'Task totals',
  'dashboard.stats.total': 'Total',
  'dashboard.stats.pending': 'Pending',
  'dashboard.stats.running': 'Running',
  'dashboard.stats.finished': 'Finished',
  'dashboard.stats.attention': 'Needs attention',
  'dashboard.filters.label': 'Task filters',
  'dashboard.filter.search': 'Search',
  'dashboard.filter.searchPlaceholder': 'Task name',
  'dashboard.filter.regex': 'Regular expression',
  'dashboard.filter.status': 'Status',
  'dashboard.filter.allStatuses': 'All statuses',
  'dashboard.filter.status.pending': 'Pending',
  'dashboard.filter.status.running': 'Running',
  'dashboard.filter.status.finished': 'Finished',
  'dashboard.filter.status.failed': 'Failed',
  'dashboard.filter.status.cancelled': 'Cancelled',
  'dashboard.filter.type': 'Type',
  'dashboard.filter.typePlaceholder': 'All types',
  'dashboard.filter.owner': 'Owner',
  'dashboard.filter.ownerPlaceholder': 'All owners',
  'dashboard.filter.order': 'Order',
  'dashboard.filter.newestSubmitted': 'Newest submitted',
  'dashboard.filter.newestFinished': 'Newest finished',
  'dashboard.filter.advanced': 'Advanced search',
  'dashboard.filter.advancedActive': 'Advanced search, {count} active',
  'dashboard.filter.submittedFrom': 'Submitted from',
  'dashboard.filter.submittedTo': 'Submitted to',
  'dashboard.filter.finishedFrom': 'Finished from',
  'dashboard.filter.finishedTo': 'Finished to',
  'dashboard.view.label': 'View',
  'dashboard.view.detailed': 'Detailed',
  'dashboard.view.compact': 'Compact',
  'dashboard.view.table': 'Table',
  'dashboard.list.count': '{shown} of {total} tasks',
  'dashboard.list.empty': 'No tasks match the current filters.',
  'dashboard.list.fixExpression': 'Fix the search expression to continue.',
  'dashboard.list.loading': 'Loading tasks…',
  'dashboard.card.type': 'Type',
  'dashboard.card.taskId': 'Task ID',
  'dashboard.card.submitted': 'Submitted',
  'dashboard.card.finished': 'Finished',
  'dashboard.card.walltime': 'Wall time',
  'dashboard.card.owner': 'Owner',
  'dashboard.card.inputPreview': 'Input preview',
  'dashboard.card.previewHint': 'Open to load the structure preview.',
  'dashboard.card.previewLoading': 'Loading structure…',
  'dashboard.card.executionError': 'Execution error',
  'dashboard.card.select': 'Select',
  'dashboard.card.results': 'Results',
  'dashboard.card.download': 'Download',
  'dashboard.card.prepareZip': 'Prepare ZIP',
  'dashboard.card.cancel': 'Cancel',
  'dashboard.card.delete': 'Delete',
  'dashboard.card.deleteSelected': 'Delete selected',
  'dashboard.confirm.cancel': 'Cancel {name}?',
  'dashboard.confirm.delete': 'Delete {name} and its artifacts?',
  'dashboard.confirm.batchDelete': 'Delete {count} selected tasks?',
  'dashboard.notice.deleted': 'Task deleted.',
  'dashboard.notice.deletedSelected': 'Selected tasks deleted.',
  'dashboard.notice.cancelled': 'Task cancellation requested.',
  'dashboard.notice.archive': 'Result archive is being prepared.',
  'dashboard.table.name': 'Name',
  'dashboard.table.actions': 'Actions',
  'dashboard.error.load': 'Unable to load tasks.',

  // Guided tour
  'notice.hide': 'Hide notice',
  'notice.restore': 'Show',
  'tour.entry': 'Guided tour',
  'tour.resume': 'Resume tour',
  'tour.start': 'Start the tour',
  'tour.restart': 'Restart guided tour',
  'tour.stepOf': 'Step {current} of {total}',
  'tour.next': 'Next',
  'tour.back': 'Back',
  'tour.finish': 'Finish',
  'tour.skip': 'Skip',
  'tour.dismiss': 'Don’t show again',
  'tour.close': 'Close tour',
  'tour.step.dashboard.title': 'A task is a computational object',
  'tour.step.dashboard.body': 'Every submission becomes one Task with its own identity, lifecycle, metadata, and result. These totals are that collection at a glance — not five separate dashboards.',
  'tour.step.lifecycle.title': 'Watch the lifecycle here',
  'tour.step.lifecycle.body': 'A Task moves from pending to running to finished. The card is where you inspect its machine facts — type, ID, timestamps, wall time — and open its result once it exists.',
  'tour.step.runners.title': 'A Runner is a scientific method',
  'tour.step.runners.body': 'The catalog is a registry of methods and their runtime contracts: what each one does, which input roles it accepts, what it produces, and how it is accessed.',
  'tour.step.create.title': 'Prepare, then submit once',
  'tour.step.create.body': 'Create Task is where you supply inputs and parameters. The owning task.yaml defines their meaning, so the form always reflects the server contract. Submitting snapshots exactly what will run.',
  'tour.step.result.title': 'The result is the loudest thing',
  'tour.step.result.body': 'The result workspace shows the scientific artifact first, with its files, integrity, and provenance alongside. You can always trace what produced it and download the exact artifacts.',
};

const zhCN: Dictionary = {
  'shell.nav.primary': '主导航',
  'shell.nav.runners': '计算模块',
  'shell.nav.dashboard': '任务面板',
  'shell.nav.newTask': '新建任务',
  'shell.nav.expand': '展开导航',
  'shell.nav.collapse': '收起导航',
  'shell.action.theme': '主题',
  'shell.action.profile': '个人资料',
  'shell.action.signIn': '登录',
  'shell.action.logout': '退出登录',
  'shell.action.administration': '系统管理',
  'shell.action.language': '语言',
  'shell.action.notices': '系统通知',
  'shell.admin.users': '用户管理',
  'shell.admin.logs': '服务器日志',
  'shell.admin.configuration': '配置',
  'theme.auto': '自动',
  'theme.light': '浅色',
  'theme.dark': '深色',

  'public.brand': 'REvoDesign',
  'public.home': 'REvoDesign 首页',
  'public.nav.home': '首页',
  'public.nav.runners': '计算模块',
  'public.nav.api': 'API',
  'public.nav.agentApi': '智能体 API',
  'public.nav.documentation': '文档',
  'public.nav.github': 'GitHub',
  'public.nav.open': '打开导航',
  'public.nav.label': '公共导航',

  'page.notFound.title': '页面不存在',
  'page.notFound.body': '所请求的 REvoCompute 地址不存在。',
  'page.notFound.action': '浏览计算模块',

  'dashboard.title': '任务面板',
  'dashboard.action.newTask': '新建任务',
  'dashboard.action.refresh': '刷新',
  'dashboard.stats.label': '任务统计',
  'dashboard.stats.total': '总计',
  'dashboard.stats.pending': '等待中',
  'dashboard.stats.running': '运行中',
  'dashboard.stats.finished': '已完成',
  'dashboard.stats.attention': '需关注',
  'dashboard.filters.label': '任务筛选',
  'dashboard.filter.search': '搜索',
  'dashboard.filter.searchPlaceholder': '任务名称',
  'dashboard.filter.regex': '使用正则表达式',
  'dashboard.filter.status': '状态',
  'dashboard.filter.allStatuses': '全部状态',
  'dashboard.filter.status.pending': '等待中',
  'dashboard.filter.status.running': '运行中',
  'dashboard.filter.status.finished': '已完成',
  'dashboard.filter.status.failed': '失败',
  'dashboard.filter.status.cancelled': '已取消',
  'dashboard.filter.type': '类型',
  'dashboard.filter.typePlaceholder': '全部类型',
  'dashboard.filter.owner': '所有者',
  'dashboard.filter.ownerPlaceholder': '全部所有者',
  'dashboard.filter.order': '排序',
  'dashboard.filter.newestSubmitted': '最近提交',
  'dashboard.filter.newestFinished': '最近完成',
  'dashboard.filter.advanced': '高级搜索',
  'dashboard.filter.advancedActive': '高级搜索，{count} 项生效',
  'dashboard.filter.submittedFrom': '提交起始',
  'dashboard.filter.submittedTo': '提交截止',
  'dashboard.filter.finishedFrom': '完成起始',
  'dashboard.filter.finishedTo': '完成截止',
  'dashboard.view.label': '视图',
  'dashboard.view.detailed': '详细',
  'dashboard.view.compact': '紧凑',
  'dashboard.view.table': '表格',
  'dashboard.list.count': '共 {total} 个任务，显示 {shown} 个',
  'dashboard.list.empty': '没有符合当前筛选条件的任务。',
  'dashboard.list.fixExpression': '请修正搜索表达式后继续。',
  'dashboard.list.loading': '正在加载任务…',
  'dashboard.card.type': '类型',
  'dashboard.card.taskId': '任务 ID',
  'dashboard.card.submitted': '提交时间',
  'dashboard.card.finished': '完成时间',
  'dashboard.card.walltime': '运行时长',
  'dashboard.card.owner': '所有者',
  'dashboard.card.inputPreview': '输入预览',
  'dashboard.card.previewHint': '展开以加载结构预览。',
  'dashboard.card.previewLoading': '正在加载结构…',
  'dashboard.card.executionError': '执行错误',
  'dashboard.card.select': '选择',
  'dashboard.card.results': '结果',
  'dashboard.card.download': '下载',
  'dashboard.card.prepareZip': '打包 ZIP',
  'dashboard.card.cancel': '取消',
  'dashboard.card.delete': '删除',
  'dashboard.card.deleteSelected': '删除所选',
  'dashboard.confirm.cancel': '取消 {name}？',
  'dashboard.confirm.delete': '删除 {name} 及其产物？',
  'dashboard.confirm.batchDelete': '删除所选的 {count} 个任务？',
  'dashboard.notice.deleted': '任务已删除。',
  'dashboard.notice.deletedSelected': '所选任务已删除。',
  'dashboard.notice.cancelled': '已请求取消任务。',
  'dashboard.notice.archive': '正在准备结果归档。',
  'dashboard.table.name': '名称',
  'dashboard.table.actions': '操作',
  'dashboard.error.load': '无法加载任务。',

  'notice.hide': '隐藏通知',
  'notice.restore': '显示',
  'tour.entry': '引导教程',
  'tour.resume': '继续教程',
  'tour.start': '开始教程',
  'tour.restart': '重新开始引导教程',
  'tour.stepOf': '第 {current} 步，共 {total} 步',
  'tour.next': '下一步',
  'tour.back': '上一步',
  'tour.finish': '完成',
  'tour.skip': '跳过',
  'tour.dismiss': '不再显示',
  'tour.close': '关闭教程',
  'tour.step.dashboard.title': '任务是计算对象',
  'tour.step.dashboard.body': '每次提交都会成为一个任务，拥有自己的标识、生命周期、元数据与结果。这里的总数就是该集合的整体概览，而不是五个彼此独立的看板。',
  'tour.step.lifecycle.title': '在这里观察生命周期',
  'tour.step.lifecycle.body': '任务会从排队进入运行，再进入完成。卡片用于查看它的机器事实——类型、ID、时间戳、运行时长——并在结果产生后打开结果。',
  'tour.step.runners.title': '计算模块是科学方法',
  'tour.step.runners.body': '目录登记的是方法与它们的运行时契约：每个方法做什么、接受哪些输入角色、产出什么，以及如何获得访问权限。',
  'tour.step.create.title': '先准备，再一次性提交',
  'tour.step.create.body': '创建任务用于提供输入与参数。其含义由所属的 task.yaml 定义，因此表单始终反映服务端契约。提交时会精确快照将要运行的内容。',
  'tour.step.result.title': '结果是页面最醒目的部分',
  'tour.step.result.body': '结果工作区首先展示科学产物，并同时呈现其文件、完整性与来源。你始终可以追溯它的产生过程，并下载确切的产物。',
};

const catalogs: Record<Locale, Dictionary> = { en, 'zh-CN': zhCN };

function isLocale(value: string | null | undefined): value is Locale {
  return value === 'en' || value === 'zh-CN';
}

/** The user's explicit choice, or null when they have never chosen. */
export function storedLocale(): Locale | null {
  const value = localStorage.getItem(storageKey);
  return isLocale(value) ? value : null;
}

/** Explicit choice → browser preference → deterministic English fallback. */
export function initialLocale(): Locale {
  const stored = storedLocale();
  if (stored) return stored;
  return navigator.language?.toLowerCase().startsWith('zh') ? 'zh-CN' : fallback;
}

export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
  const template = catalogs[locale]?.[key] ?? catalogs[fallback][key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

let active: Locale = typeof document === 'undefined' ? fallback : initialLocale();

export const locale = (): Locale => active;

/** Localize frontend-owned copy for the active locale. */
export const t = (key: string, params?: Record<string, string | number>): string => translate(active, key, params);

/** Apply a locale: persist the choice and keep `document.lang` truthful. */
export function applyLocale(next: Locale, persist = true): void {
  active = isLocale(next) ? next : fallback;
  if (persist) localStorage.setItem(storageKey, active);
  if (typeof document !== 'undefined') document.documentElement.lang = active;
}

export function setLocale(next: Locale): void {
  applyLocale(next);
  // Frontend-owned copy is baked into the DOM as it is built, so a locale change
  // is applied by reloading rather than by partially retranslating a live page.
  location.reload();
}
