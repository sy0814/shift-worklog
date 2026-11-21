import dayjs from 'dayjs'

export const fmtTime = (iso) => (iso ? dayjs(iso).format('MM-DD HH:mm') : '')
export const fmtFull = (iso) => (iso ? dayjs(iso).format('YYYY-MM-DD HH:mm') : '')
export const STATUS_TYPE = { not_started: 'info', in_progress: 'warning', done: 'success', handed_over: 'primary', discarded: 'danger' }
export const isTouch = () => window.matchMedia?.('(pointer: coarse)').matches
export const isNarrow = () => window.innerWidth < 640
