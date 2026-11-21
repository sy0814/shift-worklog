// 手机端图片预处理：先读 EXIF 拍摄时间，再压缩到长边 2560 后上传（压缩会丢掉 EXIF，所以时间单独带给服务器）
import exifr from 'exifr/dist/lite.esm.mjs'
import { uuid } from './offline'

const MAX_EDGE = 2560
const QUALITY = 0.85
const SKIP_BELOW = 800 * 1024 // 小于 800KB 的 JPEG 不压缩，原样上传（保留完整 EXIF）

async function readExifTime(file) {
  try {
    // 注意：exifr lite 版的 pick 选项有 bug，按段指定要读的字段
    const tags = await exifr.parse(file, {
      ifd0: ['ModifyDate'],
      exif: ['DateTimeOriginal', 'OffsetTimeOriginal', 'CreateDate', 'OffsetTimeDigitized', 'OffsetTime'],
      gps: false, interop: false, ifd1: false,
      reviveValues: false,
    })
    if (!tags) return {}
    const dt = tags.DateTimeOriginal || tags.CreateDate || tags.ModifyDate
    const off = tags.DateTimeOriginal ? tags.OffsetTimeOriginal : tags.CreateDate ? tags.OffsetTimeDigitized : tags.OffsetTime
    return dt ? { exif_datetime: String(dt).trim(), exif_offset: off ? String(off).trim() : null } : {}
  } catch {
    return {}
  }
}

async function compress(file) {
  if (file.type === 'image/jpeg' && file.size < SKIP_BELOW) return null
  let bmp
  try {
    bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    return null // 浏览器解不了（如安卓 Chrome 上的 HEIC），原样上传由服务器处理
  }
  const scale = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height))
  const w = Math.round(bmp.width * scale)
  const h = Math.round(bmp.height * scale)
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(bmp, 0, 0, w, h)
  bmp.close?.()
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', QUALITY))
  if (!blob || blob.size >= file.size) return null
  return blob
}

/** 把选中的 File 变成发件箱里的照片记录（已压缩、带拍摄时间） */
export async function preparePhoto(file) {
  const exif = await readExifTime(file)
  const small = await compress(file)
  const name = small ? (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg' : file.name || 'photo.jpg'
  return {
    client_id: uuid(),
    blob: small || file,
    name,
    lastModified: file.lastModified || null,
    exif_datetime: exif.exif_datetime || null,
    exif_offset: exif.exif_offset || null,
    original_size: file.size,
    done: false,
  }
}

export const preparePhotos = (files) => Promise.all(files.map(preparePhoto))
