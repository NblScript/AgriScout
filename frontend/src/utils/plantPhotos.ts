/**
 * 单株照片的常用判断（单株时间线、待确认、巡检回放大棚模式共用）。
 * 合格口径与后端 greenhouse_plans._accepted 一致：车端 accepted 优先，没有再看平台按同一公式测的质量。
 */
import type { CapturePointFull, ImageQuality, TimelinePhoto, ViewMeta } from '../types'

export type PhotoSide = 'upper' | 'under'

export function photoSide(view: ViewMeta | null | undefined): PhotoSide {
  return view?.side === 'under' ? 'under' : 'upper'
}

/** 车端判断优先（拍摄当场的结论），没有再用平台测的结果 */
export function timelineQuality(photo: TimelinePhoto): ImageQuality | null {
  return photo.view?.quality ?? photo.analysis?.image_quality ?? null
}

export function pointQuality(point: CapturePointFull): ImageQuality | null {
  return point.view?.quality ?? (point.analysis?.detail?.image_quality as ImageQuality | undefined) ?? null
}

export function isAccepted(view: ViewMeta | null | undefined, quality: ImageQuality | null): boolean | null {
  if (typeof view?.accepted === 'boolean') return view.accepted
  return typeof quality?.ok === 'boolean' ? quality.ok : null
}

export function timelineAccepted(photo: TimelinePhoto): boolean | null {
  return isAccepted(photo.view, timelineQuality(photo))
}

function latest<T extends { captured_at: string }>(items: T[]): T | null {
  return items.reduce<T | null>((best, p) => (best == null || Date.parse(p.captured_at) > Date.parse(best.captured_at) ? p : best), null)
}

/** 人工确认挂在哪张图上：回看期内最近一张合格叶背图（0015 时间线「确认状态」的口径） */
export function confirmTarget(photos: TimelinePhoto[]): TimelinePhoto | null {
  return latest(photos.filter((p) => photoSide(p.view) === 'under' && timelineAccepted(p) === true))
}

/** 列表缩略图：优先最近一张合格叶背，没有就最近一张叶背，再没有就最近一张 */
export function previewPhoto(photos: TimelinePhoto[]): TimelinePhoto | null {
  const under = photos.filter((p) => photoSide(p.view) === 'under')
  return confirmTarget(photos) ?? latest(under) ?? latest(photos)
}

/** 巡检回放的采样点按时间线照片的样子给出（缩略图组件共用） */
export function pointAsPhoto(point: CapturePointFull): TimelinePhoto {
  const analysis = point.analysis
  return {
    capture_point_id: point.id,
    patrol_id: point.patrol_id,
    captured_at: point.captured_at,
    photo_url: point.photo_url,
    view: point.view,
    analysis: analysis
      ? {
          risk_score: analysis.risk_score,
          disease_detections: analysis.disease_detections,
          analyzer_version: analysis.analyzer_version,
          image_quality: (analysis.detail?.image_quality as ImageQuality | undefined) ?? null,
        }
      : null,
  }
}
