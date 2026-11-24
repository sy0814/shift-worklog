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
      dayStart: '白班开始', middleStart: '中班开始', nightStart: '夜班开始', holidays: '节假日 / 调休上班（常白班）', kindHoliday: '节假日（休息）', kindWorkday: '调休上班',
      holidayName: '名称', date: '日期', weekday: '星期',
      teamShift: '班组整体调班', teamShiftHint: '整个班组在这几天改上别的班（或休息），首页在班、交接班、出勤、巡查派活都按调整后的算；个人调班请到「出勤」页', changedFrom: '原：{s}', restore: '恢复按排班', range: '日期', shiftTo: '改上', note: '备注', listTitle: '本月班组调班', clickHint: '点表格里的班次可直接调整', pos: ['白1', '白2', '中1', '中2', '夜1', '夜2', '休1', '休2'],
    },
    nav2: { tasks: '任务', workers: '员工名册', board: '交接班', glossary: '术语表' },
    status: { not_started: '未开始', in_progress: '进行中', done: '已完成', handed_over: '已移交', discarded: '已废弃', open: '未完成', all: '全部' },
    task: {
      new: '新建任务', edit: '编辑任务', content: '工作内容', contentPh: '可以用中文、塞语或英语填写', workers: '参与人员', team: '班组',
      start: '开始时间', end: '完成时间', leftover: '遗留问题', status: '状态', publisher: '发布人', updater: '最后修改',
      recorded: '录入', shift: '班次', confirmedBy: '完成确认', start_action: '开始', done_action: '完成', reopen: '重新打开', doneLocked: '已完成的任务只有管理员可以修改', undo_start: '改回未开始',
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
    workers: { name: '姓名', no: '工号', team: '班组', bulk: '批量添加', bulkPh: '每行一个姓名', noTeam: '未分组', showInactive: '显示已停用',
      active: '在职', addRow: '添加一行', addCol: '添加列', colName: '列名', renameCol: '改列名', delCol: '删除这一列', delColConfirm: '删除「{c}」这一列？所有人这一列的值都会删掉（删除前的值会记在操作记录里）',
      export: '导出 Excel', import: '导入 Excel', importHint: '第一行是表头：姓名（必填）、工号、班组、在职，其他列会作为自定义列（没有就自动添加）。按工号匹配，没有工号按姓名；已有的人更新，没有的新建；表里没有的人不会删除。',
      importPreview: '将新建 {c} 人、更新 {u} 人{cols}，确定导入？', importCols: '，并新增列：{cols}', importDone: '新建 {c} 人，更新 {u} 人，没变化 {n} 人', importErr: '有 {n} 行有问题，整个文件没有导入', editHint: '点格子直接修改，回车或点别处即保存；Esc 取消', saved: '已保存', newName: '输入姓名', avatarMenu: '头像' },
    history: { create: '创建', update: '修改',  status: '状态', attach: '添加图片', detach: '删除图片', handover: '移交', receive: '接收移交', discard: '废弃', auto_create: '巡查自动派发', translate: '机器翻译', translate_manual: '人工校对译文', retranslate: '重新翻译' },
    ho: {
      handover: '移交', discard: '废弃', to: '移交给', suggested: '系统建议', note: '交接说明', notePh: '交给下一班需要注意的事项（会作为对方任务的遗留问题）',
      discardReason: '废弃原因', discardPh: '必须填写原因', from: '由 {team} 移交', toTeam: '已移交给 {team}', viewSource: '查看原任务', viewTarget: '查看接收任务',
      discarded: '已废弃', times: '已移交 {n} 次', done: '已移交 {n} 条', selected: '已选 {n} 条', batch: '移交所选', selectAll: '全选',
      confirmDiscard: '废弃后不能恢复，确定？',
    },
    board: {
      title: '交接班', onDuty: '当前在班 · {shift}', next: '下一班 · {date} {shift}', prev: '上一班', nextTeam: '默认移交给',
      received: '上一班移交过来', todo: '本班待办', doneRecent: '本班完成', doneLast: '上个班完成（{date} {shift}）', outRecent: '最近 12 小时移交出去', empty: '无',
    },
    overdue: {
      title: '未闭环警示', badge: '超时', hours: '{n} 小时', none: '没有超时未完成的任务', settings: '警示设置',
      hoursLabel: '超过多少小时未完成', handoversLabel: '移交多少次仍未完成', hint: '从第一次录入算起；满足任一条件就标红置顶',
    },
    tr: {
      translating: '翻译中…', failed: '翻译失败', retry: '重新翻译', machine: '机器翻译', manual: '人工校对', showOriginal: '查看原文', hideOriginal: '收起原文',
      correct: '校对译文', source: '原文', notConfigured: '翻译服务未配置（缺少 DEEPSEEK_API_KEY）', keepOrRetranslateTitle: '原文已修改',
      keepOrRetranslate: '这条内容有人工校对过的译文。要重新翻译（覆盖人工校对）还是保留现有译文？', keep: '保留现有译文', pendingN: '待翻译 {n} 条', failedN: '失败 {n} 条', retryFailed: '重试失败的',
      model: '模型', fields: { content: '工作内容', leftover: '遗留问题', discard_reason: '废弃原因' },
    },
    glossary: { title: '术语表', zh: '中文', sr: '塞尔维亚语', en: '英语', category: '类别', note: '备注', import: '导入 CSV', export: '导出 CSV', imported: '新增 {added}，更新 {updated}，跳过 {skipped}', search: '搜索术语', hint: '翻译时会把术语表发给模型，保证专业词汇译法统一' },
    att: {
      title: '出勤', month: '月份', template: '下载导入模板', import: '导入出勤表', imported: '已导入 {n} 条', importFailed: '有 {n} 行有问题，整个文件没有导入，请改好后重新导入',
      row: '第 {n} 行', status: '出勤状态', shiftActual: '实际班次', shiftAuto: '不选 = 按所顶班组当天的班次', teamActual: '顶哪个班组', note: '备注', reset: '恢复按排班', defaultHint: '没改过的按排班默认出勤',
      st: { present: '出勤', leave: '请假', sick: '病假', absent: '缺勤', off: '休息' }, code: { day: '白', middle: '中', night: '夜', off: '休', leave: '假', sick: '病', absent: '缺' },
      dayTasks: '当天参与的任务', noTasks: '当天没有参与任务', edited: '手工修改', importedSrc: '导入', legend: '白/中/夜 = 出勤班次；加粗斜体 = 手工修改或导入',
      until: '连续设置到', swapWith: '与他人互换这天的班', swapPick: '选择互换的人', swap: '互换', swapped: '已互换', batch: '批量安排', workers: '人员', range: '日期', guest: '支援', batchDone: '已设置 {n} 个人次',
    },
    exp: { title: '导出 Excel', range: '时间段', team: '班组', worker: '人员', lang: '表格语言', download: '下载', all: '全部', note: '包含任务明细、人员工作量、出勤三张表' },
    sys: {
      appName: '系统名称', appNameHint: '显示在顶栏、登录页和浏览器标签上。可只填一种语言，没填的语言用默认名称：{def}', appNameDefault: '默认',
      title: '系统设置', ai: 'AI 接口', provider: '接口类型', deepseek: 'DeepSeek（默认）', other: '其他 OpenAI 兼容接口', baseUrl: '接口地址',
      apiKey: 'API Key', keySet: '已设置（{hint}），留空表示不修改', keyEnv: '使用服务器 .env 里的 Key（{hint}）', keyNone: '未设置',
      keyRequired: '换了接口地址，需要填写新的 API Key', translateModel: '翻译模型', analysisModel: 'AI 分析模型', fetchModels: '获取模型列表',
      test: '测试连接', testing: '正在用示例句子测试…', testOk: '连接正常，用时 {ms} 毫秒', testFail: '连接失败', save: '保存', reset: '恢复默认',
      confirmReset: '恢复为服务器默认的 DeepSeek 设置？后台保存的 API Key 会被删除。', source: '当前生效', srcEnv: '服务器默认（.env）', srcDb: '后台设置',
      fixedNote: '提示词、温度、超时和重试等基本设置固定不变；这里只改接口、Key 和模型。DeepSeek 会自动关闭思考模式。', saveHint: '建议先「测试连接」通过再保存',
      models: '{n} 个模型',
    },
    pwa: { newVersion: '有新版本', newVersionHint: '保存好正在填写的内容后刷新。', reload: '刷新', offline: '离线模式', offlineData: '离线模式：显示的是 {time} 的数据，新建的任务和照片会在联网后自动上传', offlineNoData: '离线模式：新建的任务和照片会在联网后自动上传', install: '添加到主屏幕' },
    menu: { more: '更多', admin: '管理' },
    ai: {
      title: 'AI 工作量分析', range: '时间段', team: '班组', allTeams: '全部班组', lang: '报告语言', start: '开始分析', history: '历史报告',
      running: '正在分析，一般需要 30～120 秒，可以先离开本页', failed: '分析失败', retry: '重新分析', download: '下载报告', print: '打印',
      stats: '统计数据（报告里的数字都来自这里）', teams: '班组', people: '人员', notConfigured: 'AI 接口未配置，请先到「系统设置」填写', empty: '还没有报告',
      st: { pending: '排队中', running: '分析中', done: '完成', failed: '失败' }, tokens: '用量 {i} / {o} token', by: '{name} 发起',
      col: { name: '姓名', team: '班组', sched: '排班班次', present: '实际出勤', leave: '请假', sick: '病假', absent: '缺勤', cover: '顶班', tasks: '任务', done: '完成', open: '未完成', ho: '已移交', hours: '工时', hps: '每班工时', overdue: '超时未完成', hoOut: '移出', hoIn: '移入', avgH: '平均工时', noWorkers: '无参与人', members: '人数', perMember: '人均任务（最少/中位/最多）', idle: '出勤但无任务' },
      note: '工时按「完成 − 开始」计算，多人参与的任务每人都计全部工时；出勤默认按排班。报告由 AI 根据统计数据撰写，仅供参考。',
    },
    insp: {
      title: '定期巡查', add: '新建巡查项', name: '名称', content: '巡查内容（生成任务的工作内容）', enabled: '启用', kind: '周期',
      kinds: { daily: '每天 / 每隔几天', weekly: '每周', monthly: '每月', yearly: '每年', shift: '按班次' },
      yearDates: '哪几天', yearPick: '选日期（可多选）', everyYears: '每隔几年', yearHint: '选 2 月 29 日时，平年按 2 月 28 日', leaderHint: '班长只能管理固定派给本班组的巡查项', readonly: '只读',
      everyDays: '每隔几天', atTime: '时间', startDate: '起算日期', weekdays: '周几', monthDays: '几号', monthHint: '选 29~31 号时，没有这一天的月份按最后一天',
      shiftKinds: '哪种班', everyShifts: '每隔几个班', assign: '派给谁', onDuty: '到时间正在上班的班组', fixed: '固定班组',
      fixedHint: '该班组到时间在休息的话，派到它的下一个班次；按班次时只算这个班组自己上的班', team: '班组', workers: '预设参与人员（可不选）',
      preview: '接下来 5 次', nextRun: '下次', lastRun: '上次', runs: '已派发', runNow: '立即派发', history: '派发记录', dispatched: '已派发',
      wd: ['一', '二', '三', '四', '五', '六', '日'], st: { created: '已派发', manual: '手动派发', skipped: '停机错过（未派）', failed: '失败' },
      sum: { daily: '每天 {t}', dailyN: '每 {n} 天 {t}', weekly: '每周{d} {t}', monthly: '每月 {d} 号 {t}', yearly: '每年 {d} {t}', yearlyN: '每 {n} 年 {d} {t}', shift: '每个{k}开始时', shiftN: '每隔 {n} 个{k}', own: '（{team}自己的班）' },
      noRule: '规则不完整，算不出时间', confirmDelete: '删除这个巡查项？', noDelete: '已经派发过的巡查项不能删除，请改为停用', tag: '巡查',
    },
    lead: { title: '带队人员', none: '未指定', members: '参与人员', pick: '选择带队人（可不选）' },
    duty: {
      onDuty: '在岗 {n} 人', busy: '忙碌 {n}', idle: '空闲 {n}', absent: '请假/缺勤 {n}', title: '{shift} 人员状态', support: '支援',
      st: { busy: '忙碌', idle: '空闲', leave: '请假', sick: '病假', absent: '缺勤', off: '调休' },
      none: '这个班次没有安排人员', select: '勾选人员后可快捷添加任务', addTask: '给选中的人添加任务（{n}）', noTask: '没有未完成的任务', clickHint: '点击查看人员',
    },
    ot: {
      title: '加班', add: '设置加班', target: '加班的人', people: '指定人员', team: '整个班组', day: '班次日期', shift: '哪个班次后加班', shiftAuto: '不选 = 按当天出勤 / 排班的班次',
      until: '加班到', note: '备注', list: '本月加班记录', hours: '{n} 小时', wholeTeam: '全班 {n} 人', del: '删除这条加班？', saved: '已设置加班', untilTag: '加班到 {t}', prevTag: '上个班加班到 {t}', sum: '加班', none: '本月没有加班记录', teamHint: '当天在这个班组上这个班的人都算加班（含来支援的）',
    },
    avatar: { upload: '上传头像', change: '更换头像', remove: '删除头像', removed: '已删除头像' },
    log: {
      allUsers: '全部账号', system: '系统自动', entity: '对象类型', all: '全部', dateRange: '日期', empty: '没有记录', more: '加载更多',
      verb: { create: '创建了', update: '修改了', delete: '删除了', status: '更改了状态：', handover: '移交了', receive: '接收了移交的', discard: '废弃了', attach: '给…添加了图片', detach: '删除了图片', translate: '自动翻译了', translate_manual: '人工校对了译文：', retranslate: '重新翻译了', login: '登录了系统', change_password: '修改了自己的密码', reset_password: '重置了密码：', import: '导入了', export: '导出了', batch: '批量设置了', swap: '互换了班次', auto_create: '按巡查计划自动派发了', retry: '重新执行了', reset: '恢复默认：', seed: '初始化了系统', retry_failed: '重试了失败的翻译', manual: '手动派发了' },
      ent: { task: '任务', user: '账号', worker: '员工', team: '班组', holiday: '节假日', glossary: '术语', inspection: '巡查项', attendance: '出勤', setting: '设置', shift_config: '排班基准', ai_report: 'AI 报告', export: 'Excel', system: '系统', overtime: '加班' },
      field: { full_name: '姓名', role: '角色', team_id: '班组', lang: '语言', is_active: '启用', name: '名称', employee_no: '工号', status: '状态', start_at: '开始时间', end_at: '完成时间', workers: '参与人员', lead_worker: '带队人员', avatar: '头像', note: '备注', shift_kind: '班次', enabled: '启用', content: '内容', kind: '周期', at_time: '时间', confirmed_by: '确认人', base_date: '基准日期', cycle_offset: '循环位置', overdue_hours: '超时小时数', overdue_handovers: '超时移交次数', zh: '中文', sr: '塞语', en: '英文', category: '类别', to_team: '移交给', team_shift: '整体调班', app_name: '系统名称', extra: '自定义列' },
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
      dayStart: 'Početak prve smene', middleStart: 'Početak druge smene', nightStart: 'Početak treće smene', holidays: 'Praznici / radne subote (dnevna smena)', kindHoliday: 'Praznik (ne radi se)', kindWorkday: 'Radni dan (nadoknada)',
      holidayName: 'Naziv', date: 'Datum', weekday: 'Dan',
      teamShift: 'Promena smene ekipe', teamShiftHint: 'Cela ekipa tih dana radi drugu smenu (ili je slobodna); početna strana, primopredaja, prisustvo i obilasci se ravnaju po tome. Pojedinačne zamene su na stranici „Prisustvo”', changedFrom: 'bilo: {s}', restore: 'Vrati po rasporedu', range: 'Datumi', shiftTo: 'Nova smena', note: 'Napomena', listTitle: 'Promene smena ekipa ovog meseca', clickHint: 'Kliknite na smenu u tabeli da je promenite', pos: ['P1', 'P2', 'D1', 'D2', 'T1', 'T2', 'S1', 'S2'],
    },
    nav2: { tasks: 'Zadaci', workers: 'Radnici', board: 'Primopredaja', glossary: 'Rečnik' },
    status: { not_started: 'Nije započeto', in_progress: 'U toku', done: 'Završeno', handed_over: 'Predato', discarded: 'Odbačeno', open: 'Nezavršeno', all: 'Sve' },
    task: {
      new: 'Novi zadatak', edit: 'Izmena zadatka', content: 'Opis posla', contentPh: 'Možete pisati na srpskom, kineskom ili engleskom', workers: 'Učesnici', team: 'Smena',
      start: 'Početak', end: 'Završetak', leftover: 'Preostali problemi', status: 'Status', publisher: 'Uneo', updater: 'Poslednja izmena',
      recorded: 'Uneto', shift: 'Smena', confirmedBy: 'Potvrdio završetak', start_action: 'Započni', done_action: 'Završi', reopen: 'Ponovo otvori', doneLocked: 'Završen zadatak može da menja samo administrator', undo_start: 'Vrati na nije započeto',
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
    workers: { name: 'Ime i prezime', no: 'Matični broj', team: 'Smena', bulk: 'Dodaj više', bulkPh: 'Jedno ime po redu', noTeam: 'Bez smene', showInactive: 'Prikaži neaktivne',
      active: 'Aktivan', addRow: 'Dodaj red', addCol: 'Dodaj kolonu', colName: 'Naziv kolone', renameCol: 'Preimenuj', delCol: 'Obriši kolonu', delColConfirm: 'Obrisati kolonu „{c}”? Sve vrednosti u njoj biće obrisane (stare vrednosti ostaju u evidenciji promena)',
      export: 'Izvezi Excel', import: 'Uvezi Excel', importHint: 'Prvi red je zaglavlje: Ime (obavezno), Matični br., Ekipa, Aktivan; ostale kolone postaju dodatne kolone (dodaju se same). Uparuje se po matičnom broju, inače po imenu; postojeći se ažuriraju, novi se dodaju; niko se ne briše.',
      importPreview: 'Biće dodato {c}, ažurirano {u}{cols}. Uvesti?', importCols: ', nove kolone: {cols}', importDone: 'Dodato {c}, ažurirano {u}, bez promene {n}', importErr: '{n} redova ima grešku, fajl nije uvezen', editHint: 'Kliknite na polje da ga izmenite; Enter ili klik van polja čuva, Esc otkazuje', saved: 'Sačuvano', newName: 'Unesite ime', avatarMenu: 'Slika' },
    history: { create: 'Kreirano', update: 'Izmena', status: 'Status', attach: 'Dodata slika', detach: 'Obrisana slika', handover: 'Predato', receive: 'Primljeno', discard: 'Odbačeno', auto_create: 'Automatski (obilazak)', translate: 'Mašinski prevod', translate_manual: 'Ručna ispravka prevoda', retranslate: 'Ponovni prevod' },
    ho: {
      handover: 'Predaj', discard: 'Odbaci', to: 'Predaj smeni', suggested: 'predlog sistema', note: 'Napomena za primopredaju', notePh: 'Šta sledeća smena treba da zna (postaje preostali problem kod njih)',
      discardReason: 'Razlog odbacivanja', discardPh: 'Razlog je obavezan', from: 'Predala {team}', toTeam: 'Predato smeni {team}', viewSource: 'Prikaži izvorni zadatak', viewTarget: 'Prikaži primljeni zadatak',
      discarded: 'Odbačeno', times: 'Predato {n} puta', done: 'Predato: {n}', selected: 'Izabrano: {n}', batch: 'Predaj izabrano', selectAll: 'Izaberi sve',
      confirmDiscard: 'Odbacivanje se ne može poništiti. Nastaviti?',
    },
    board: {
      title: 'Primopredaja', onDuty: 'Sada na smeni · {shift}', next: 'Sledeća smena · {date} {shift}', prev: 'Prethodna smena', nextTeam: 'Podrazumevano predati',
      received: 'Predato od prethodne smene', todo: 'Zadaci smene', doneRecent: 'Završeno u ovoj smeni', doneLast: 'Završeno u prethodnoj smeni ({date} {shift})', outRecent: 'Predato u poslednjih 12 h', empty: 'Nema',
    },
    overdue: {
      title: 'Nezatvoreni zadaci', badge: 'Kasni', hours: '{n} h', none: 'Nema zadataka koji kasne', settings: 'Podešavanje upozorenja',
      hoursLabel: 'Nezavršeno duže od (sati)', handoversLabel: 'Nezavršeno posle broja predaja', hint: 'Računa se od prvog unosa; dovoljan je jedan uslov',
    },
    tr: {
      translating: 'Prevodi se…', failed: 'Prevod nije uspeo', retry: 'Prevedi ponovo', machine: 'Mašinski prevod', manual: 'Ručno ispravljeno', showOriginal: 'Prikaži original', hideOriginal: 'Sakrij original',
      correct: 'Ispravi prevod', source: 'Original', notConfigured: 'Prevođenje nije podešeno (nedostaje DEEPSEEK_API_KEY)', keepOrRetranslateTitle: 'Original je izmenjen',
      keepOrRetranslate: 'Ovaj tekst ima ručno ispravljen prevod. Prevesti ponovo (zameniti ručne ispravke) ili zadržati postojeći prevod?', keep: 'Zadrži prevod', pendingN: 'Čeka prevod: {n}', failedN: 'Neuspešno: {n}', retryFailed: 'Ponovi neuspešne',
      model: 'Model', fields: { content: 'Opis posla', leftover: 'Preostali problemi', discard_reason: 'Razlog odbacivanja' },
    },
    glossary: { title: 'Rečnik pojmova', zh: 'Kineski', sr: 'Srpski', en: 'Engleski', category: 'Kategorija', note: 'Napomena', import: 'Uvezi CSV', export: 'Izvezi CSV', imported: 'Dodato {added}, izmenjeno {updated}, preskočeno {skipped}', search: 'Pretraga', hint: 'Rečnik se šalje modelu pri prevođenju da bi stručni izrazi bili ujednačeni' },
    att: {
      title: 'Prisustvo', month: 'Mesec', template: 'Preuzmi šablon', import: 'Uvezi prisustvo', imported: 'Uvezeno: {n}', importFailed: '{n} redova ima grešku; ništa nije uvezeno. Ispravite i uvezite ponovo',
      row: 'Red {n}', status: 'Status', shiftActual: 'Stvarna smena', shiftAuto: 'Prazno = smena te ekipe tog dana', teamActual: 'Za koju ekipu', note: 'Napomena', reset: 'Vrati na raspored', defaultHint: 'Bez izmena se računa po rasporedu',
      st: { present: 'Prisutan', leave: 'Odsustvo', sick: 'Bolovanje', absent: 'Izostanak', off: 'Slobodan' }, code: { day: 'P', middle: 'D', night: 'T', off: 'S', leave: 'O', sick: 'B', absent: 'I' },
      dayTasks: 'Zadaci tog dana', noTasks: 'Nema zadataka tog dana', edited: 'Ručno izmenjeno', importedSrc: 'Uvezeno', legend: 'P/D/T = smena; podebljano kurziv = ručno ili uvezeno',
      until: 'Isto do datuma', swapWith: 'Zameni smenu tog dana sa', swapPick: 'Izaberite radnika', swap: 'Zameni', swapped: 'Zamenjeno', batch: 'Grupno raspoređivanje', workers: 'Radnici', range: 'Datum', guest: 'Pomoć', batchDone: 'Podešeno: {n}',
    },
    exp: { title: 'Izvoz u Excel', range: 'Period', team: 'Ekipa', worker: 'Radnik', lang: 'Jezik tabele', download: 'Preuzmi', all: 'Svi', note: 'Sadrži zadatke, opterećenje po radniku i prisustvo' },
    sys: {
      appName: 'Naziv sistema', appNameHint: 'Prikazuje se u zaglavlju, na prijavi i na kartici pregledača. Prazno polje = podrazumevani naziv: {def}', appNameDefault: 'Podrazumevano',
      title: 'Podešavanja', ai: 'AI servis', provider: 'Vrsta servisa', deepseek: 'DeepSeek (podrazumevano)', other: 'Drugi OpenAI-kompatibilan servis', baseUrl: 'Adresa servisa',
      apiKey: 'API ključ', keySet: 'Podešen ({hint}); ostavite prazno da se ne menja', keyEnv: 'Koristi ključ iz .env na serveru ({hint})', keyNone: 'Nije podešen',
      keyRequired: 'Adresa je promenjena – unesite novi API ključ', translateModel: 'Model za prevod', analysisModel: 'Model za AI analizu', fetchModels: 'Učitaj modele',
      test: 'Testiraj vezu', testing: 'Testiranje primerom…', testOk: 'Veza radi, {ms} ms', testFail: 'Veza ne radi', save: 'Sačuvaj', reset: 'Vrati podrazumevano',
      confirmReset: 'Vratiti na podrazumevani DeepSeek sa servera? Sačuvani API ključ biće obrisan.', source: 'Trenutno važi', srcEnv: 'Podrazumevano (.env)', srcDb: 'Podešeno ovde',
      fixedNote: 'Prompt, temperatura, vremensko ograničenje i ponavljanja ostaju isti; ovde se menjaju samo servis, ključ i model. Za DeepSeek se razmišljanje automatski isključuje.', saveHint: 'Preporuka: prvo testirajte vezu',
      models: '{n} modela',
    },
    pwa: { newVersion: 'Nova verzija', newVersionHint: 'Sačuvajte unos pa osvežite.', reload: 'Osveži', offline: 'Van mreže', offlineData: 'Van mreže: prikazani su podaci od {time}; novi zadaci i slike se šalju kad mreža proradi', offlineNoData: 'Van mreže: novi zadaci i slike se šalju kad mreža proradi', install: 'Dodaj na početni ekran' },
    menu: { more: 'Još', admin: 'Upravljanje' },
    ai: {
      title: 'AI analiza opterećenja', range: 'Period', team: 'Ekipa', allTeams: 'Sve ekipe', lang: 'Jezik izveštaja', start: 'Pokreni analizu', history: 'Raniji izveštaji',
      running: 'Analiza je u toku, obično 30–120 s; možete napustiti stranicu', failed: 'Analiza nije uspela', retry: 'Ponovi', download: 'Preuzmi izveštaj', print: 'Štampaj',
      stats: 'Statistika (svi brojevi u izveštaju potiču odavde)', teams: 'Ekipe', people: 'Radnici', notConfigured: 'AI servis nije podešen – podesite ga u „Podešavanjima”', empty: 'Još nema izveštaja',
      st: { pending: 'Na čekanju', running: 'U toku', done: 'Gotovo', failed: 'Neuspešno' }, tokens: 'Potrošnja {i} / {o} tokena', by: 'pokrenuo {name}',
      col: { name: 'Ime', team: 'Ekipa', sched: 'Smene po rasporedu', present: 'Prisutan', leave: 'Odsustvo', sick: 'Bolovanje', absent: 'Izostanak', cover: 'Zamene', tasks: 'Zadaci', done: 'Završeno', open: 'Otvoreno', ho: 'Predato', hours: 'Sati', hps: 'Sati po smeni', overdue: 'Kasni', hoOut: 'Predato', hoIn: 'Primljeno', avgH: 'Prosečno sati', noWorkers: 'Bez učesnika', members: 'Radnika', perMember: 'Zadataka po radniku (min/med/max)', idle: 'Prisutni bez zadataka' },
      note: 'Sati = završetak − početak; kod zadataka sa više učesnika svakom se računaju svi sati; prisustvo po rasporedu. Izveštaj piše AI na osnovu statistike – samo kao pomoć.',
    },
    insp: {
      title: 'Periodični obilasci', add: 'Novi obilazak', name: 'Naziv', content: 'Sadržaj (opis posla za zadatak)', enabled: 'Aktivno', kind: 'Učestalost',
      kinds: { daily: 'Dnevno / na N dana', weekly: 'Nedeljno', monthly: 'Mesečno', yearly: 'Godišnje', shift: 'Po smenama' },
      yearDates: 'Datumi', yearPick: 'Izaberite datume (više)', everyYears: 'Na koliko godina', yearHint: '29. februar: u neprestupnim godinama 28. februar', leaderHint: 'Šef smene upravlja samo obilascima dodeljenim svojoj ekipi', readonly: 'Samo pregled',
      everyDays: 'Na koliko dana', atTime: 'Vreme', startDate: 'Od datuma', weekdays: 'Dani', monthDays: 'Datumi', monthHint: 'Za 29–31: u kraćim mesecima poslednji dan meseca',
      shiftKinds: 'Smene', everyShifts: 'Svaka N-ta smena', assign: 'Kome', onDuty: 'Ekipi koja je tada na smeni', fixed: 'Određenoj ekipi',
      fixedHint: 'Ako ekipa tada ne radi, zadatak ide u njenu sledeću smenu; kod smena se broje samo smene te ekipe', team: 'Ekipa', workers: 'Unapred izabrani radnici (opciono)',
      preview: 'Sledećih 5 puta', nextRun: 'Sledeće', lastRun: 'Poslednje', runs: 'Poslato', runNow: 'Pošalji sada', history: 'Istorija', dispatched: 'Poslato',
      wd: ['pon', 'uto', 'sre', 'čet', 'pet', 'sub', 'ned'], st: { created: 'Poslato', manual: 'Ručno', skipped: 'Propušteno (server isključen)', failed: 'Greška' },
      sum: { daily: 'Svaki dan u {t}', dailyN: 'Na {n} dana u {t}', weekly: 'Svake nedelje ({d}) u {t}', monthly: 'Mesečno ({d}.) u {t}', yearly: 'Godišnje ({d}) u {t}', yearlyN: 'Na {n} godine ({d}) u {t}', shift: 'Na početku svake smene: {k}', shiftN: 'Svaka {n}. smena: {k}', own: ' ({team})' },
      noRule: 'Pravilo nije potpuno', confirmDelete: 'Obrisati ovaj obilazak?', noDelete: 'Već je slat – isključite ga umesto brisanja', tag: 'Obilazak',
    },
    lead: { title: 'Vođa ekipe', none: 'Nije određen', members: 'Učesnici', pick: 'Izaberite vođu (opciono)' },
    duty: {
      onDuty: 'Na smeni {n}', busy: 'Zauzeto {n}', idle: 'Slobodno {n}', absent: 'Odsutno {n}', title: '{shift} – stanje radnika', support: 'Pomoć',
      st: { busy: 'Zauzet', idle: 'Slobodan', leave: 'Odsustvo', sick: 'Bolovanje', absent: 'Izostanak', off: 'Slobodan dan' },
      none: 'Za ovu smenu nema raspoređenih radnika', select: 'Označite radnike da biste brzo dodali zadatak', addTask: 'Dodaj zadatak izabranima ({n})', noTask: 'Nema otvorenih zadataka', clickHint: 'Kliknite za radnike',
    },
    ot: {
      title: 'Prekovremeni rad', add: 'Zakaži prekovremeni', target: 'Ko radi prekovremeno', people: 'Izabrani radnici', team: 'Cela ekipa', day: 'Datum smene', shift: 'Posle koje smene', shiftAuto: 'Prazno = smena po prisustvu / rasporedu',
      until: 'Do', note: 'Napomena', list: 'Prekovremeni rad ovog meseca', hours: '{n} h', wholeTeam: 'cela ekipa, {n} ljudi', del: 'Obrisati ovaj prekovremeni rad?', saved: 'Prekovremeni rad je zakazan', untilTag: 'prekovremeno do {t}', prevTag: 'iz prethodne smene, do {t}', sum: 'Prekov.', none: 'Nema prekovremenog rada ovog meseca', teamHint: 'Računa se svima koji tog dana rade tu smenu u ovoj ekipi (i onima koji pomažu)',
    },
    avatar: { upload: 'Dodaj sliku', change: 'Promeni sliku', remove: 'Obriši sliku', removed: 'Slika obrisana' },
    log: {
      allUsers: 'Svi nalozi', system: 'Sistem (automatski)', entity: 'Vrsta', all: 'Sve', dateRange: 'Datum', empty: 'Nema zapisa', more: 'Učitaj još',
      verb: { create: 'je kreirao', update: 'je izmenio', delete: 'je obrisao', status: 'je promenio status:', handover: 'je predao', receive: 'je primio', discard: 'je odbacio', attach: 'je dodao sliku na', detach: 'je obrisao sliku sa', translate: 'automatski preveo', translate_manual: 'je ispravio prevod:', retranslate: 'je ponovo preveo', login: 'se prijavio', change_password: 'je promenio svoju lozinku', reset_password: 'je resetovao lozinku:', import: 'je uvezao', export: 'je izvezao', batch: 'je grupno podesio', swap: 'je zamenio smene', auto_create: 'automatski poslao (obilazak)', retry: 'je ponovio', reset: 'je vratio podrazumevano:', seed: 'inicijalizovao sistem', retry_failed: 'je ponovio neuspele prevode', manual: 'je ručno poslao' },
      ent: { task: 'zadatak', user: 'nalog', worker: 'radnika', team: 'ekipu', holiday: 'praznik', glossary: 'pojam', inspection: 'obilazak', attendance: 'prisustvo', setting: 'podešavanje', shift_config: 'osnovu rasporeda', ai_report: 'AI izveštaj', export: 'Excel', system: 'sistem', overtime: 'prekovremeni rad' },
      field: { full_name: 'ime', role: 'uloga', team_id: 'ekipa', lang: 'jezik', is_active: 'aktivan', name: 'naziv', employee_no: 'matični br.', status: 'status', start_at: 'početak', end_at: 'završetak', workers: 'učesnici', lead_worker: 'vođa ekipe', avatar: 'slika', note: 'napomena', shift_kind: 'smena', enabled: 'aktivno', content: 'sadržaj', kind: 'učestalost', at_time: 'vreme', confirmed_by: 'potvrdio', base_date: 'osnovni datum', cycle_offset: 'pozicija u ciklusu', overdue_hours: 'sati kašnjenja', overdue_handovers: 'broj predaja', zh: 'kineski', sr: 'srpski', en: 'engleski', category: 'kategorija', to_team: 'predato', team_shift: 'promena smene ekipe', app_name: 'naziv sistema', extra: 'dodatne kolone' },
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
      dayStart: 'Day shift starts', middleStart: 'Middle shift starts', nightStart: 'Night shift starts', holidays: 'Holidays / make-up workdays (day team)', kindHoliday: 'Holiday (off)', kindWorkday: 'Make-up workday',
      holidayName: 'Name', date: 'Date', weekday: 'Weekday',
      teamShift: 'Team shift change', teamShiftHint: 'The whole team works another shift (or is off) on these days; home page, handover, attendance and inspections follow it. For individual swaps use the Attendance page', changedFrom: 'was: {s}', restore: 'Back to schedule', range: 'Dates', shiftTo: 'New shift', note: 'Note', listTitle: 'Team shift changes this month', clickHint: 'Click a shift in the table to change it', pos: ['D1', 'D2', 'M1', 'M2', 'N1', 'N2', 'O1', 'O2'],
    },
    nav2: { tasks: 'Tasks', workers: 'Workers', board: 'Handover', glossary: 'Glossary' },
    status: { not_started: 'Not started', in_progress: 'In progress', done: 'Done', handed_over: 'Handed over', discarded: 'Discarded', open: 'Open', all: 'All' },
    task: {
      new: 'New task', edit: 'Edit task', content: 'Work', contentPh: 'Chinese, Serbian or English', workers: 'Workers', team: 'Team',
      start: 'Start', end: 'Finish', leftover: 'Open issues', status: 'Status', publisher: 'Posted by', updater: 'Last edited',
      recorded: 'Recorded', shift: 'Shift', confirmedBy: 'Confirmed by', start_action: 'Start', done_action: 'Done', reopen: 'Reopen', doneLocked: 'Only an administrator can change a completed task', undo_start: 'Back to not started',
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
    workers: { name: 'Name', no: 'Employee no.', team: 'Team', bulk: 'Bulk add', bulkPh: 'One name per line', noTeam: 'No team', showInactive: 'Show inactive',
      active: 'Active', addRow: 'Add row', addCol: 'Add column', colName: 'Column name', renameCol: 'Rename', delCol: 'Delete column', delColConfirm: 'Delete column “{c}”? Its values are removed for everyone (old values stay in the operation log)',
      export: 'Export Excel', import: 'Import Excel', importHint: 'First row is the header: Name (required), Employee no., Team, Active; any other column becomes a custom column (added automatically). Matched by employee no., otherwise by name; existing people are updated, new ones added; nobody is deleted.',
      importPreview: 'Will add {c} and update {u}{cols}. Import?', importCols: ', new columns: {cols}', importDone: 'Added {c}, updated {u}, unchanged {n}', importErr: '{n} rows have problems; nothing was imported', editHint: 'Click a cell to edit; Enter or click elsewhere saves, Esc cancels', saved: 'Saved', newName: 'Type a name', avatarMenu: 'Photo' },
    history: { create: 'Created', update: 'Edited', status: 'Status', attach: 'Photo added', detach: 'Photo deleted', handover: 'Handed over', receive: 'Received', discard: 'Discarded', auto_create: 'Auto (inspection)', translate: 'Machine translation', translate_manual: 'Translation corrected', retranslate: 'Retranslated' },
    ho: {
      handover: 'Hand over', discard: 'Discard', to: 'Hand over to', suggested: 'suggested', note: 'Handover note', notePh: 'What the next shift needs to know (becomes their open issue)',
      discardReason: 'Reason', discardPh: 'A reason is required', from: 'From {team}', toTeam: 'Handed over to {team}', viewSource: 'Open source task', viewTarget: 'Open received task',
      discarded: 'Discarded', times: 'Handed over {n}×', done: 'Handed over {n}', selected: '{n} selected', batch: 'Hand over selected', selectAll: 'Select all',
      confirmDiscard: 'This cannot be undone. Continue?',
    },
    board: {
      title: 'Handover', onDuty: 'On shift · {shift}', next: 'Next shift · {date} {shift}', prev: 'Previous shift', nextTeam: 'Hands over to',
      received: 'Received from previous shift', todo: 'Team to-do', doneRecent: 'Done this shift', doneLast: 'Done in last shift ({date} {shift})', outRecent: 'Handed over in last 12 h', empty: 'None',
    },
    overdue: {
      title: 'Overdue', badge: 'Overdue', hours: '{n} h', none: 'Nothing overdue', settings: 'Alert settings',
      hoursLabel: 'Open longer than (hours)', handoversLabel: 'Still open after N handovers', hint: 'Counted from the first entry; either condition triggers',
    },
    tr: {
      translating: 'Translating…', failed: 'Translation failed', retry: 'Translate again', machine: 'Machine translation', manual: 'Corrected', showOriginal: 'Show original', hideOriginal: 'Hide original',
      correct: 'Correct translation', source: 'Original', notConfigured: 'Translation not configured (DEEPSEEK_API_KEY missing)', keepOrRetranslateTitle: 'Original changed',
      keepOrRetranslate: 'This text has manually corrected translations. Translate again (overwriting corrections) or keep the current translations?', keep: 'Keep translations', pendingN: '{n} pending', failedN: '{n} failed', retryFailed: 'Retry failed',
      model: 'Model', fields: { content: 'Work', leftover: 'Open issues', discard_reason: 'Discard reason' },
    },
    glossary: { title: 'Glossary', zh: 'Chinese', sr: 'Serbian', en: 'English', category: 'Category', note: 'Note', import: 'Import CSV', export: 'Export CSV', imported: '{added} added, {updated} updated, {skipped} skipped', search: 'Search', hint: 'The glossary is sent to the model so technical terms are translated consistently' },
    att: {
      title: 'Attendance', month: 'Month', template: 'Download template', import: 'Import attendance', imported: '{n} rows imported', importFailed: '{n} rows have problems; nothing was imported. Fix the file and import again',
      row: 'Row {n}', status: 'Status', shiftActual: 'Actual shift', shiftAuto: 'Empty = that team\'s shift on the day', teamActual: 'Covering team', note: 'Note', reset: 'Reset to schedule', defaultHint: 'Unchanged days follow the schedule',
      st: { present: 'Present', leave: 'Leave', sick: 'Sick', absent: 'Absent', off: 'Off' }, code: { day: 'D', middle: 'M', night: 'N', off: 'O', leave: 'L', sick: 'S', absent: 'A' },
      dayTasks: 'Tasks that day', noTasks: 'No tasks that day', edited: 'Edited', importedSrc: 'Imported', legend: 'D/M/N = shift worked; bold italic = edited or imported',
      until: 'Apply through', swapWith: 'Swap this day\'s shift with', swapPick: 'Choose a worker', swap: 'Swap', swapped: 'Swapped', batch: 'Batch assign', workers: 'Workers', range: 'Dates', guest: 'Support', batchDone: '{n} entries set',
    },
    exp: { title: 'Export to Excel', range: 'Period', team: 'Team', worker: 'Worker', lang: 'Sheet language', download: 'Download', all: 'All', note: 'Contains tasks, workload per person and attendance' },
    sys: {
      appName: 'System name', appNameHint: 'Shown in the top bar, on the login page and in the browser tab. Empty = default name: {def}', appNameDefault: 'Default',
      title: 'Settings', ai: 'AI API', provider: 'Provider', deepseek: 'DeepSeek (default)', other: 'Other OpenAI-compatible API', baseUrl: 'Base URL',
      apiKey: 'API key', keySet: 'Set ({hint}); leave empty to keep', keyEnv: 'Using the key from the server .env ({hint})', keyNone: 'Not set',
      keyRequired: 'The address changed – enter a new API key', translateModel: 'Translation model', analysisModel: 'AI analysis model', fetchModels: 'Load models',
      test: 'Test connection', testing: 'Testing with a sample sentence…', testOk: 'Works, {ms} ms', testFail: 'Connection failed', save: 'Save', reset: 'Restore default',
      confirmReset: 'Restore the server default DeepSeek settings? The saved API key will be deleted.', source: 'In effect', srcEnv: 'Server default (.env)', srcDb: 'Set here',
      fixedNote: 'Prompt, temperature, timeout and retries stay fixed; only the API, key and model change here. Thinking mode is turned off automatically for DeepSeek.', saveHint: 'Test the connection before saving',
      models: '{n} models',
    },
    pwa: { newVersion: 'New version available', newVersionHint: 'Save what you are typing, then reload.', reload: 'Reload', offline: 'Offline', offlineData: 'Offline: showing data from {time}; new tasks and photos upload when back online', offlineNoData: 'Offline: new tasks and photos upload when back online', install: 'Add to home screen' },
    menu: { more: 'More', admin: 'Admin' },
    ai: {
      title: 'AI workload analysis', range: 'Period', team: 'Team', allTeams: 'All teams', lang: 'Report language', start: 'Run analysis', history: 'Past reports',
      running: 'Analysing, usually 30–120 s; you can leave this page', failed: 'Analysis failed', retry: 'Retry', download: 'Download report', print: 'Print',
      stats: 'Statistics (every number in the report comes from here)', teams: 'Teams', people: 'People', notConfigured: 'AI API not configured – set it up in Settings', empty: 'No reports yet',
      st: { pending: 'Queued', running: 'Running', done: 'Done', failed: 'Failed' }, tokens: 'Usage {i} / {o} tokens', by: 'by {name}',
      col: { name: 'Name', team: 'Team', sched: 'Scheduled shifts', present: 'Present', leave: 'Leave', sick: 'Sick', absent: 'Absent', cover: 'Covers', tasks: 'Tasks', done: 'Done', open: 'Open', ho: 'Handed over', hours: 'Hours', hps: 'Hours/shift', overdue: 'Overdue', hoOut: 'Out', hoIn: 'In', avgH: 'Avg hours', noWorkers: 'No workers', members: 'Members', perMember: 'Tasks per member (min/med/max)', idle: 'Present, no tasks' },
      note: 'Hours = finish − start; tasks with several workers count full hours for each; attendance follows the schedule. The report is written by AI from these statistics and is for guidance only.',
    },
    insp: {
      title: 'Scheduled inspections', add: 'New inspection', name: 'Name', content: 'Content (work text of the generated task)', enabled: 'Enabled', kind: 'Schedule',
      kinds: { daily: 'Daily / every N days', weekly: 'Weekly', monthly: 'Monthly', yearly: 'Yearly', shift: 'By shift' },
      yearDates: 'Dates', yearPick: 'Pick dates (multiple)', everyYears: 'Every N years', yearHint: 'Feb 29: Feb 28 in non-leap years', leaderHint: 'Leaders can only manage inspections fixed to their own team', readonly: 'Read only',
      everyDays: 'Every N days', atTime: 'Time', startDate: 'Starting', weekdays: 'Weekdays', monthDays: 'Days of month', monthHint: '29–31: shorter months use their last day',
      shiftKinds: 'Shifts', everyShifts: 'Every N-th shift', assign: 'Assign to', onDuty: 'The team on shift at that time', fixed: 'A fixed team',
      fixedHint: 'If the team is off at that time, the task goes to its next shift; by shift counts only that team\'s own shifts', team: 'Team', workers: 'Preset workers (optional)',
      preview: 'Next 5 times', nextRun: 'Next', lastRun: 'Last', runs: 'Dispatched', runNow: 'Dispatch now', history: 'History', dispatched: 'Dispatched',
      wd: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], st: { created: 'Dispatched', manual: 'Manual', skipped: 'Missed (server down)', failed: 'Failed' },
      sum: { daily: 'Daily at {t}', dailyN: 'Every {n} days at {t}', weekly: 'Weekly ({d}) at {t}', monthly: 'Monthly ({d}) at {t}', yearly: 'Yearly ({d}) at {t}', yearlyN: 'Every {n} years ({d}) at {t}', shift: 'At the start of every {k} shift', shiftN: 'Every {n}th {k} shift', own: ' ({team})' },
      noRule: 'Rule incomplete', confirmDelete: 'Delete this inspection?', noDelete: 'Already dispatched – disable it instead', tag: 'Inspection',
    },
    lead: { title: 'Lead', none: 'Not set', members: 'Workers', pick: 'Choose a lead (optional)' },
    duty: {
      onDuty: '{n} on shift', busy: '{n} busy', idle: '{n} free', absent: '{n} absent', title: '{shift} – people', support: 'Support',
      st: { busy: 'Busy', idle: 'Free', leave: 'Leave', sick: 'Sick', absent: 'Absent', off: 'Day off' },
      none: 'Nobody is scheduled for this shift', select: 'Tick people to add a task quickly', addTask: 'Add a task for selected ({n})', noTask: 'No open tasks', clickHint: 'Click to see people',
    },
    ot: {
      title: 'Overtime', add: 'Add overtime', target: 'Who', people: 'Selected people', team: 'Whole team', day: 'Shift date', shift: 'After which shift', shiftAuto: 'Empty = the shift from attendance / schedule',
      until: 'Until', note: 'Note', list: 'Overtime this month', hours: '{n} h', wholeTeam: 'whole team, {n} people', del: 'Delete this overtime?', saved: 'Overtime saved', untilTag: 'overtime until {t}', prevTag: 'from last shift, until {t}', sum: 'OT', none: 'No overtime this month', teamHint: 'Counts for everyone on this team\'s shift that day (including helpers)',
    },
    avatar: { upload: 'Upload photo', change: 'Change photo', remove: 'Remove photo', removed: 'Photo removed' },
    log: {
      allUsers: 'All accounts', system: 'System (automatic)', entity: 'Type', all: 'All', dateRange: 'Date', empty: 'No records', more: 'Load more',
      verb: { create: 'created', update: 'edited', delete: 'deleted', status: 'changed the status of', handover: 'handed over', receive: 'received', discard: 'discarded', attach: 'added a photo to', detach: 'deleted a photo from', translate: 'auto-translated', translate_manual: 'corrected the translation of', retranslate: 'retranslated', login: 'logged in', change_password: 'changed own password', reset_password: 'reset the password of', import: 'imported', export: 'exported', batch: 'batch-set', swap: 'swapped shifts', auto_create: 'auto-dispatched (inspection)', retry: 'retried', reset: 'restored the default of', seed: 'initialised the system', retry_failed: 'retried failed translations', manual: 'dispatched manually' },
      ent: { task: 'task', user: 'account', worker: 'worker', team: 'team', holiday: 'holiday', glossary: 'term', inspection: 'inspection', attendance: 'attendance', setting: 'setting', shift_config: 'schedule baseline', ai_report: 'AI report', export: 'Excel', system: 'system', overtime: 'overtime' },
      field: { full_name: 'name', role: 'role', team_id: 'team', lang: 'language', is_active: 'active', name: 'name', employee_no: 'employee no.', status: 'status', start_at: 'start', end_at: 'finish', workers: 'workers', lead_worker: 'lead', avatar: 'photo', note: 'note', shift_kind: 'shift', enabled: 'enabled', content: 'content', kind: 'schedule', at_time: 'time', confirmed_by: 'confirmed by', base_date: 'base date', cycle_offset: 'cycle position', overdue_hours: 'overdue hours', overdue_handovers: 'overdue handovers', zh: 'Chinese', sr: 'Serbian', en: 'English', category: 'category', to_team: 'handed to', team_shift: 'team shift change', app_name: 'system name', extra: 'custom columns' },
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
