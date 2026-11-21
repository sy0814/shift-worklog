import { createI18n } from 'vue-i18n'
import elZh from 'element-plus/es/locale/lang/zh-cn'
import elEn from 'element-plus/es/locale/lang/en'
import elSrCyr from 'element-plus/es/locale/lang/sr'
import { deepLatin } from './translit'

// 塞尔维亚语一律用拉丁字母（sr-Latn）。塞语文案请塞方同事校对。
const messages = {
  zh: {
    app: { title: '工作记录系统' },
    common: {
      save: '保存', cancel: '取消', edit: '编辑', add: '新增', delete: '删除', confirm: '确定',
      saved: '已保存', requestFailed: '请求失败', yes: '是', no: '否', actions: '操作',
    },
    nav: { home: '首页', schedule: '排班', users: '账号管理', audit: '操作记录', logout: '退出', password: '修改密码' },
    login: { title: '登录', username: '用户名', password: '密码', submit: '登录', failed: '用户名或密码错误' },
    shift: { day: '白班', middle: '中班', night: '夜班', off: '休息', current: '当前在班', next: '下一个接班', now: '现在' },
    home: { welcome: '你好，{name}', myTeam: '我的班组', today: '今日排班', tasksSoon: '任务与交接功能将在下一步加入' },
    team: { rotating: '倒班', day: '常白班' },
    users: {
      username: '用户名', fullName: '姓名', role: '角色', team: '班组', lang: '语言', active: '启用',
      admin: '管理员', leader: '班长', password: '初始密码', resetPassword: '重置密码', newPassword: '新密码',
      oldPassword: '原密码', created: '创建时间',
    },
    schedule: {
      calendar: '排班日历', config: '排班基准', baseDate: '基准日期', offset: '基准日循环位置',
      dayStart: '白班开始', middleStart: '中班开始', nightStart: '夜班开始', holidays: '节假日（常白班休息）',
      holidayName: '名称', date: '日期', weekday: '星期', pos: ['白1', '白2', '中1', '中2', '夜1', '夜2', '休1', '休2'],
    },
    nav2: { tasks: '任务', workers: '员工名册', board: '交接班' },
    status: { not_started: '未开始', in_progress: '进行中', done: '已完成', handed_over: '已移交', discarded: '已废弃', open: '未完成', all: '全部' },
    task: {
      new: '新建任务', edit: '编辑任务', content: '工作内容', contentPh: '可以用中文、塞语或英语填写', workers: '参与人员', team: '班组',
      start: '开始时间', end: '完成时间', leftover: '遗留问题', status: '状态', publisher: '发布人', updater: '最后修改',
      recorded: '录入', shift: '班次', confirmedBy: '完成确认', start_action: '开始', done_action: '完成', reopen: '重新打开', undo_start: '改回未开始',
      history: '修改记录', original: '原文', pendingTr: '待翻译', search: '搜索内容', empty: '没有任务', allTeams: '全部班组',
      dateRange: '日期', noWorkers: '未选择', created: '已创建', confirmDone: '确认这项工作已完成？', loadMore: '加载更多',
    },
    photo: {
      title: '图片', camera: '拍照', gallery: '从相册选择', file: '选择图片', takenAt: '拍摄时间',
      src_exif: '照片自带时间', src_file: '文件时间', src_upload: '上传时间（照片无时间信息）',
      waiting: '待上传', remove: '删除图片', confirmRemove: '删除这张图片？（会留下记录）',
    },
    outbox: {
      title: '待同步', none: '没有待同步的内容', syncNow: '立即同步', savedOffline: '网络不通，已存为草稿，联网后自动同步',
      synced: '已同步 {n} 条', photos: '{n} 张图片', newTask: '新任务', addPhotos: '补充图片', failed: '同步失败', discard: '丢弃草稿',
      confirmDiscard: '丢弃后无法恢复，确定？', offline: '离线',
    },
    workers: { name: '姓名', no: '工号', team: '班组', bulk: '批量添加', bulkPh: '每行一个姓名', noTeam: '未分组', showInactive: '显示已停用' },
    history: { create: '创建', update: '修改', status: '状态', attach: '添加图片', detach: '删除图片', handover: '移交', receive: '接收移交', discard: '废弃' },
    ho: {
      handover: '移交', discard: '废弃', to: '移交给', suggested: '系统建议', note: '交接说明', notePh: '交给下一班需要注意的事项（会作为对方任务的遗留问题）',
      discardReason: '废弃原因', discardPh: '必须填写原因', from: '由 {team} 移交', toTeam: '已移交给 {team}', viewSource: '查看原任务', viewTarget: '查看接收任务',
      discarded: '已废弃', times: '已移交 {n} 次', done: '已移交 {n} 条', selected: '已选 {n} 条', batch: '移交所选', selectAll: '全选',
      confirmDiscard: '废弃后不能恢复，确定？',
    },
    board: {
      title: '交接班', onDuty: '当前在班 · {shift}', next: '下一班 · {date} {shift}', prev: '上一班', nextTeam: '默认移交给',
      received: '上一班移交过来', todo: '本班待办', doneRecent: '最近 12 小时完成', outRecent: '最近 12 小时移交出去', empty: '无',
    },
    overdue: {
      title: '未闭环警示', badge: '超时', hours: '{n} 小时', none: '没有超时未完成的任务', settings: '警示设置',
      hoursLabel: '超过多少小时未完成', handoversLabel: '移交多少次仍未完成', hint: '从第一次录入算起；满足任一条件就标红置顶',
    },
    audit: { at: '时间', user: '操作人', action: '操作', entity: '对象', field: '字段', old: '修改前', new: '修改后' },
  },
  sr: {
    app: { title: 'Radni dnevnik' },
    common: {
      save: 'Sačuvaj', cancel: 'Otkaži', edit: 'Izmeni', add: 'Dodaj', delete: 'Obriši', confirm: 'Potvrdi',
      saved: 'Sačuvano', requestFailed: 'Zahtev nije uspeo', yes: 'Da', no: 'Ne', actions: 'Radnje',
    },
    nav: { home: 'Početna', schedule: 'Raspored', users: 'Nalozi', audit: 'Evidencija izmena', logout: 'Odjava', password: 'Promena lozinke' },
    login: { title: 'Prijava', username: 'Korisničko ime', password: 'Lozinka', submit: 'Prijavi se', failed: 'Pogrešno korisničko ime ili lozinka' },
    shift: { day: 'Prva smena', middle: 'Druga smena', night: 'Treća smena', off: 'Slobodno', current: 'Trenutno na smeni', next: 'Sledeća smena', now: 'Sada' },
    home: { welcome: 'Zdravo, {name}', myTeam: 'Moja smena', today: 'Današnji raspored', tasksSoon: 'Zadaci i primopredaja dolaze u sledećem koraku' },
    team: { rotating: 'Smenski rad', day: 'Dnevna smena' },
    users: {
      username: 'Korisničko ime', fullName: 'Ime i prezime', role: 'Uloga', team: 'Smena', lang: 'Jezik', active: 'Aktivan',
      admin: 'Administrator', leader: 'Šef smene', password: 'Početna lozinka', resetPassword: 'Resetuj lozinku', newPassword: 'Nova lozinka',
      oldPassword: 'Stara lozinka', created: 'Kreirano',
    },
    schedule: {
      calendar: 'Kalendar smena', config: 'Osnova rasporeda', baseDate: 'Osnovni datum', offset: 'Pozicija u ciklusu',
      dayStart: 'Početak prve smene', middleStart: 'Početak druge smene', nightStart: 'Početak treće smene', holidays: 'Praznici (dnevna smena ne radi)',
      holidayName: 'Naziv', date: 'Datum', weekday: 'Dan', pos: ['P1', 'P2', 'D1', 'D2', 'T1', 'T2', 'S1', 'S2'],
    },
    nav2: { tasks: 'Zadaci', workers: 'Radnici', board: 'Primopredaja' },
    status: { not_started: 'Nije započeto', in_progress: 'U toku', done: 'Završeno', handed_over: 'Predato', discarded: 'Odbačeno', open: 'Nezavršeno', all: 'Sve' },
    task: {
      new: 'Novi zadatak', edit: 'Izmena zadatka', content: 'Opis posla', contentPh: 'Možete pisati na srpskom, kineskom ili engleskom', workers: 'Učesnici', team: 'Smena',
      start: 'Početak', end: 'Završetak', leftover: 'Preostali problemi', status: 'Status', publisher: 'Uneo', updater: 'Poslednja izmena',
      recorded: 'Uneto', shift: 'Smena', confirmedBy: 'Potvrdio završetak', start_action: 'Započni', done_action: 'Završi', reopen: 'Ponovo otvori', undo_start: 'Vrati na nije započeto',
      history: 'Istorija izmena', original: 'Original', pendingTr: 'Čeka prevod', search: 'Pretraga', empty: 'Nema zadataka', allTeams: 'Sve smene',
      dateRange: 'Datum', noWorkers: 'Nije izabrano', created: 'Kreirano', confirmDone: 'Potvrditi da je posao završen?', loadMore: 'Učitaj još',
    },
    photo: {
      title: 'Slike', camera: 'Fotografiši', gallery: 'Iz galerije', file: 'Izaberi sliku', takenAt: 'Snimljeno',
      src_exif: 'vreme iz fotografije', src_file: 'vreme fajla', src_upload: 'vreme otpremanja (fotografija nema vreme)',
      waiting: 'Čeka otpremanje', remove: 'Obriši sliku', confirmRemove: 'Obrisati ovu sliku? (ostaje zapis)',
    },
    outbox: {
      title: 'Čeka sinhronizaciju', none: 'Nema ničega za sinhronizaciju', syncNow: 'Sinhronizuj', savedOffline: 'Nema mreže – sačuvano kao nacrt, sinhronizuje se automatski',
      synced: 'Sinhronizovano: {n}', photos: '{n} slika', newTask: 'Novi zadatak', addPhotos: 'Dodatne slike', failed: 'Neuspešno', discard: 'Odbaci nacrt',
      confirmDiscard: 'Nacrt se ne može vratiti. Nastaviti?', offline: 'Van mreže',
    },
    workers: { name: 'Ime i prezime', no: 'Matični broj', team: 'Smena', bulk: 'Dodaj više', bulkPh: 'Jedno ime po redu', noTeam: 'Bez smene', showInactive: 'Prikaži neaktivne' },
    history: { create: 'Kreirano', update: 'Izmena', status: 'Status', attach: 'Dodata slika', detach: 'Obrisana slika', handover: 'Predato', receive: 'Primljeno', discard: 'Odbačeno' },
    ho: {
      handover: 'Predaj', discard: 'Odbaci', to: 'Predaj smeni', suggested: 'predlog sistema', note: 'Napomena za primopredaju', notePh: 'Šta sledeća smena treba da zna (postaje preostali problem kod njih)',
      discardReason: 'Razlog odbacivanja', discardPh: 'Razlog je obavezan', from: 'Predala {team}', toTeam: 'Predato smeni {team}', viewSource: 'Prikaži izvorni zadatak', viewTarget: 'Prikaži primljeni zadatak',
      discarded: 'Odbačeno', times: 'Predato {n} puta', done: 'Predato: {n}', selected: 'Izabrano: {n}', batch: 'Predaj izabrano', selectAll: 'Izaberi sve',
      confirmDiscard: 'Odbacivanje se ne može poništiti. Nastaviti?',
    },
    board: {
      title: 'Primopredaja', onDuty: 'Sada na smeni · {shift}', next: 'Sledeća smena · {date} {shift}', prev: 'Prethodna smena', nextTeam: 'Podrazumevano predati',
      received: 'Predato od prethodne smene', todo: 'Zadaci smene', doneRecent: 'Završeno u poslednjih 12 h', outRecent: 'Predato u poslednjih 12 h', empty: 'Nema',
    },
    overdue: {
      title: 'Nezatvoreni zadaci', badge: 'Kasni', hours: '{n} h', none: 'Nema zadataka koji kasne', settings: 'Podešavanje upozorenja',
      hoursLabel: 'Nezavršeno duže od (sati)', handoversLabel: 'Nezavršeno posle broja predaja', hint: 'Računa se od prvog unosa; dovoljan je jedan uslov',
    },
    audit: { at: 'Vreme', user: 'Korisnik', action: 'Radnja', entity: 'Objekat', field: 'Polje', old: 'Staro', new: 'Novo' },
  },
  en: {
    app: { title: 'Work Log' },
    common: {
      save: 'Save', cancel: 'Cancel', edit: 'Edit', add: 'Add', delete: 'Delete', confirm: 'OK',
      saved: 'Saved', requestFailed: 'Request failed', yes: 'Yes', no: 'No', actions: 'Actions',
    },
    nav: { home: 'Home', schedule: 'Schedule', users: 'Accounts', audit: 'Audit log', logout: 'Log out', password: 'Change password' },
    login: { title: 'Sign in', username: 'Username', password: 'Password', submit: 'Sign in', failed: 'Wrong username or password' },
    shift: { day: 'Day', middle: 'Middle', night: 'Night', off: 'Off', current: 'On shift now', next: 'Next shift', now: 'Now' },
    home: { welcome: 'Hello, {name}', myTeam: 'My team', today: "Today's schedule", tasksSoon: 'Tasks and handover come in the next step' },
    team: { rotating: 'Rotating', day: 'Day team' },
    users: {
      username: 'Username', fullName: 'Full name', role: 'Role', team: 'Team', lang: 'Language', active: 'Active',
      admin: 'Admin', leader: 'Team leader', password: 'Initial password', resetPassword: 'Reset password', newPassword: 'New password',
      oldPassword: 'Old password', created: 'Created',
    },
    schedule: {
      calendar: 'Shift calendar', config: 'Schedule baseline', baseDate: 'Base date', offset: 'Cycle position on base date',
      dayStart: 'Day shift starts', middleStart: 'Middle shift starts', nightStart: 'Night shift starts', holidays: 'Holidays (day team off)',
      holidayName: 'Name', date: 'Date', weekday: 'Weekday', pos: ['D1', 'D2', 'M1', 'M2', 'N1', 'N2', 'O1', 'O2'],
    },
    nav2: { tasks: 'Tasks', workers: 'Workers', board: 'Handover' },
    status: { not_started: 'Not started', in_progress: 'In progress', done: 'Done', handed_over: 'Handed over', discarded: 'Discarded', open: 'Open', all: 'All' },
    task: {
      new: 'New task', edit: 'Edit task', content: 'Work', contentPh: 'Chinese, Serbian or English', workers: 'Workers', team: 'Team',
      start: 'Start', end: 'Finish', leftover: 'Open issues', status: 'Status', publisher: 'Posted by', updater: 'Last edited',
      recorded: 'Recorded', shift: 'Shift', confirmedBy: 'Confirmed by', start_action: 'Start', done_action: 'Done', reopen: 'Reopen', undo_start: 'Back to not started',
      history: 'History', original: 'Original', pendingTr: 'Awaiting translation', search: 'Search', empty: 'No tasks', allTeams: 'All teams',
      dateRange: 'Date', noWorkers: 'None', created: 'Created', confirmDone: 'Confirm this work is done?', loadMore: 'Load more',
    },
    photo: {
      title: 'Photos', camera: 'Take photo', gallery: 'From gallery', file: 'Choose image', takenAt: 'Taken',
      src_exif: 'photo time', src_file: 'file time', src_upload: 'upload time (no time in photo)',
      waiting: 'Waiting to upload', remove: 'Delete photo', confirmRemove: 'Delete this photo? (it stays in the log)',
    },
    outbox: {
      title: 'Pending sync', none: 'Nothing to sync', syncNow: 'Sync now', savedOffline: 'No network – saved as draft, will sync automatically',
      synced: 'Synced {n}', photos: '{n} photos', newTask: 'New task', addPhotos: 'Extra photos', failed: 'Sync failed', discard: 'Discard draft',
      confirmDiscard: 'The draft cannot be recovered. Continue?', offline: 'Offline',
    },
    workers: { name: 'Name', no: 'Employee no.', team: 'Team', bulk: 'Bulk add', bulkPh: 'One name per line', noTeam: 'No team', showInactive: 'Show inactive' },
    history: { create: 'Created', update: 'Edited', status: 'Status', attach: 'Photo added', detach: 'Photo deleted', handover: 'Handed over', receive: 'Received', discard: 'Discarded' },
    ho: {
      handover: 'Hand over', discard: 'Discard', to: 'Hand over to', suggested: 'suggested', note: 'Handover note', notePh: 'What the next shift needs to know (becomes their open issue)',
      discardReason: 'Reason', discardPh: 'A reason is required', from: 'From {team}', toTeam: 'Handed over to {team}', viewSource: 'Open source task', viewTarget: 'Open received task',
      discarded: 'Discarded', times: 'Handed over {n}×', done: 'Handed over {n}', selected: '{n} selected', batch: 'Hand over selected', selectAll: 'Select all',
      confirmDiscard: 'This cannot be undone. Continue?',
    },
    board: {
      title: 'Handover', onDuty: 'On shift · {shift}', next: 'Next shift · {date} {shift}', prev: 'Previous shift', nextTeam: 'Hands over to',
      received: 'Received from previous shift', todo: 'Team to-do', doneRecent: 'Done in last 12 h', outRecent: 'Handed over in last 12 h', empty: 'None',
    },
    overdue: {
      title: 'Overdue', badge: 'Overdue', hours: '{n} h', none: 'Nothing overdue', settings: 'Alert settings',
      hoursLabel: 'Open longer than (hours)', handoversLabel: 'Still open after N handovers', hint: 'Counted from the first entry; either condition triggers',
    },
    audit: { at: 'Time', user: 'User', action: 'Action', entity: 'Object', field: 'Field', old: 'Before', new: 'After' },
  },
}

export const LANGS = [
  { code: 'zh', label: '中文' },
  { code: 'sr', label: 'Srpski' },
  { code: 'en', label: 'English' },
]

export const elementLocales = { zh: elZh, en: elEn, sr: deepLatin(elSrCyr) }

export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('lang') || 'zh',
  fallbackLocale: 'en',
  messages,
})

export function setLang(code) {
  i18n.global.locale.value = code
  localStorage.setItem('lang', code)
  document.documentElement.lang = code === 'sr' ? 'sr-Latn' : code
}

/** 按当前语言取对象的 name_zh / name_sr / name_en */
export function localName(obj) {
  if (!obj) return ''
  return obj[`name_${i18n.global.locale.value}`] || obj.name_zh
}

/**
 * 取三语字段在当前语言下的文字；当前语言还没有译文时退回原文。
 * 返回 { text, fallback }，fallback=true 表示显示的是原文。
 */
export function localText(tri, sourceLang) {
  if (!tri) return { text: '', fallback: false }
  const lang = i18n.global.locale.value
  if (tri[lang]) return { text: tri[lang], fallback: false }
  const src = tri[sourceLang] || tri.zh || tri.sr || tri.en || ''
  return { text: src, fallback: !!src }
}
