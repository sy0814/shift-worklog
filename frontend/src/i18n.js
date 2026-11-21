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
