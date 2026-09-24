/**
 * Lilovideo 品牌唯一源（Single Source of Truth）
 *
 * 所有界面文案、页面标题、图标、成片署名都从这里取。
 * 改名或换图标时只需修改本文件，避免品牌信息散落各处。
 */
export const BRAND = {
  /** 产品英文名 */
  name: 'Lilovideo',
  /** 产品中文名 */
  nameZh: 'Lilovideo',
  /** 一句话定位 */
  tagline: '从一句创意到一部成片',
  /** 页面描述（SEO / 分享卡片） */
  description: 'AI 视频生产系统 · 剧本 → 角色 → 分镜 → 参考图 → 视频 → 成片',
  /** 产品署名（用于成片水印、导出文件名等） */
  signature: 'Lilovideo',
  /** 版权方 */
  author: 'Lilovideo',
  /** 仓库地址 */
  repository: '',
} as const;

/**
 * 图标资源。
 *
 * 存在两个版本，用途不同，不要混用：
 *
 * - `mark`：**无背景底板的纯符号**。用于界面内（侧栏、页头）。
 *   它没有内嵌底色，因此能自然叠加在任意背景上，也能被单色渲染。
 *
 * - `badge`：**带深色圆角底板的版本**。用于需要独立成块的位置
 *   （浏览器标签页、iOS 主屏、分享卡片）。这些位置背景不可控，
 *   必须自带底色才保证对比度。
 *
 * 设计规范明确禁止把底板烘进"图标本体"，但允许为展示提供独立底板版本。
 * 这里就是按这个区分落地的。
 */
export const BRAND_ICON = {
  /** 纯符号（SVG，可缩放，无底板） */
  mark: '/brand/logo.svg',
  /** 带底板的方形标（PNG，用于不可控背景处） */
  badge: '/brand/logo-512.png',
  /** 小尺寸位图，用于需要固定像素密度的地方 */
  badgeSmall: '/brand/logo-32.png',
  /** iOS 主屏图标 */
  appleTouch: '/brand/apple-touch-icon.png',
} as const;

export type Brand = typeof BRAND;
