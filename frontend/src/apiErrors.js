// 把服务器返回的英文错误说明翻译成界面语言（只翻用户操作会碰到的；其他的原样显示）
const T = {
  team_off: ['这个班组那天休息，请选一个班次', 'Ekipa tog dana ne radi; izaberite smenu', 'The team is off that day; choose a shift'],
  worker_off: ['{x} 那天不上班，请选一个班次', '{x} tog dana ne radi; izaberite smenu', '{x} is not on duty that day; choose a shift'],
  ot_long: ['加班时间太长（下班后最多 {x} 小时）', 'Prekovremeni rad je predug (najviše {x} h posle smene)', 'Overtime is too long (at most {x} h after the shift)'],
  ot_target: ['请选择班组或人员', 'Izaberite ekipu ili radnike', 'Choose a team or workers'],
  done_locked: ['已完成的任务只有管理员可以修改', 'Završen zadatak može da menja samo administrator', 'Only an administrator can change a completed task'],
  task_status: ['任务已经是「{x}」，不能再操作', 'Zadatak je već „{x}”', 'The task is already “{x}”'],
  not_team_task: ['不是本班组的任务', 'Nije zadatak vaše ekipe', 'Not your team’s task'],
  not_team_worker: ['不是本班组的员工', 'Nije radnik vaše ekipe', 'Not a worker of your team'],
  not_team: ['只能操作本班组', 'Samo za vašu ekipu', 'Your own team only'],
  worker_not_team: ['{x} 不是本班组的人', '{x} nije u vašoj ekipi', '{x} is not in your team'],
  same_team: ['不能移交给本班组', 'Ne može se predati istoj ekipi', 'Cannot hand over to the same team'],
  bad_transition: ['不能这样改状态', 'Ova promena statusa nije dozvoljena', 'This status change is not allowed'],
  file_big: ['文件太大', 'Datoteka je prevelika', 'File too large'],
  not_xlsx: ['不是 .xlsx 文件', 'Nije .xlsx datoteka', 'Not an .xlsx file'],
  not_image: ['不支持的图片格式', 'Format slike nije podržan', 'Unsupported image format'],
  too_many_photos: ['图片太多了', 'Previše slika', 'Too many photos'],
  empty_file: ['文件是空的', 'Datoteka je prazna', 'The file is empty'],
  no_name_col: ['缺少「姓名」列', 'Nedostaje kolona „Ime”', 'Missing column “Name”'],
  col_exists: ['已经有这一列了', 'Ta kolona već postoji', 'That column already exists'],
  no_exists: ['这个工号已经有人用了', 'Taj matični broj već postoji', 'That employee no. is already used'],
  user_exists: ['用户名已存在', 'Korisničko ime već postoji', 'Username already exists'],
  term_exists: ['术语已存在', 'Pojam već postoji', 'Term already exists'],
  wrong_pw: ['原密码不对', 'Pogrešna stara lozinka', 'Wrong old password'],
  bad_login: ['用户名或密码错误', 'Pogrešno korisničko ime ili lozinka', 'Invalid username or password'],
  reason: ['请填写原因', 'Unesite razlog', 'Please enter a reason'],
  end_before: ['完成时间早于开始时间', 'Završetak je pre početka', 'End is before start'],
  range: ['日期范围不对（最多 {x} 天）', 'Pogrešan period (najviše {x} dana)', 'Invalid date range (at most {x} days)'],
  insp_leader: ['班长只能管理固定派给本班组的巡查项', 'Šef smene upravlja samo obilascima svoje ekipe', 'Leaders can only manage inspections fixed to their own team'],
  insp_runs: ['已经派发过，不能删除，请改为停用', 'Već je dodeljivan; isključite ga umesto brisanja', 'Already dispatched; disable it instead'],
  same_shift: ['两人那天是同一个班', 'Oba radnika imaju istu smenu tog dana', 'Both have the same shift that day'],
  admin_only: ['只有管理员可以操作', 'Samo administrator', 'Administrator only'],
  analysis_running: ['已经有一个分析在进行，请稍后', 'Analiza je već u toku', 'Another analysis is running'],
  self: ['不能降级或停用自己', 'Ne možete sebi oduzeti prava', 'You cannot demote or disable yourself'],
}
const RULES = [
  [/^team is off that day/, 'team_off'],
  [/^(.+) is not on duty that day/, 'worker_off'],
  [/^overtime must end within (\d+)/, 'ot_long'],
  [/^give either team_id or worker_ids/, 'ot_target'],
  [/^task is done; only admin/, 'done_locked'],
  [/^task (?:\d+ )?is (\w+)$/, 'task_status', 'status'],
  [/^not your team's task/, 'not_team_task'],
  [/^not your team's worker/, 'not_team_worker'],
  [/^(?:not your team|own team only)$/, 'not_team'],
  [/^(.+) is not in your team/, 'worker_not_team'],
  [/^cannot hand over to the same team/, 'same_team'],
  [/^cannot go from/, 'bad_transition'],
  [/^file too large/, 'file_big'],
  [/^not an \.xlsx file/, 'not_xlsx'],
  [/^not a supported image/, 'not_image'],
  [/^too many photos/, 'too_many_photos'],
  [/^empty file/, 'empty_file'],
  [/^missing column: name/, 'no_name_col'],
  [/^column exists/, 'col_exists'],
  [/^employee_no exists/, 'no_exists'],
  [/^username exists/, 'user_exists'],
  [/^term exists/, 'term_exists'],
  [/^wrong old password/, 'wrong_pw'],
  [/^invalid username or password/, 'bad_login'],
  [/^reason required/, 'reason'],
  [/^end_at before start_at/, 'end_before'],
  [/^range must be \d+\.\.(\d+) days/, 'range'],
  [/^leaders can only manage inspections/, 'insp_leader'],
  [/^already has runs/, 'insp_runs'],
  [/^both have the same shift/, 'same_shift'],
  [/^admin only/, 'admin_only'],
  [/^another analysis is running/, 'analysis_running'],
  [/^cannot demote or disable yourself/, 'self'],
]
const IDX = { zh: 0, sr: 1, en: 2 }

/** detail：服务器的英文说明；t：vue-i18n 的 t（翻译任务状态用） */
export function translateError(detail, locale, t) {
  for (const [re, key, kind] of RULES) {
    const m = re.exec(detail)
    if (!m) continue
    let x = m[1] ?? ''
    if (kind === 'status' && t) x = t(`status.${x}`)
    return T[key][IDX[locale] ?? 0].replace('{x}', x)
  }
  return detail
}
