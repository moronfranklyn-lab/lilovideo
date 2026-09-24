# 图标交付说明

定稿：**斜缝（缝里有光）** · 谱系：日本纹章（Kamon）

---

## 1. 文件清单

### 纯符号（无背景底板）

| 文件 | 用途 |
| --- | --- |
| `logo.svg` | **首选**。矢量、可缩放、可换色。界面内一律用它 |

### 带底板的方形标（背景不可控时使用）

| 文件 | 尺寸 | 用途 |
| --- | --- | --- |
| `logo-16.png` | 16 | 浏览器标签页最小尺寸 |
| `logo-32.png` | 32 | 书签栏、紧凑导航 |
| `logo-48.png` | 48 | Windows 站点图标 |
| `logo-180.png` | 180 | iOS 主屏（apple-touch-icon） |
| `logo-192.png` | 192 | PWA manifest |
| `logo-512.png` | 512 | PWA 遮罩图标、应用图标 |
| `logo-1024.png` | 1024 | 高清源图、应用商店 |
| `favicon.ico` | 16+32+48 内嵌 | 老浏览器兼容 |
| `apple-touch-icon.png` | 180 | 与 logo-180 内容相同，独立文件便于直接引用 |

### 为什么分两套

设计规范**禁止把背景底板烘焙进图标本体**——带底板的标志在单色渲染（macOS 菜单栏模板、反色 favicon、单色印刷）时会塌成一个实心方块。

但浏览器标签页、iOS 主屏这类位置的**背景不可控**，没有底板就没有对比度保证。

所以拆成两套：`logo.svg` 是**纯符号**，任何时候都不会塌；`logo-N.png` 是**带底板的成品**，专供背景不可控处。

---

## 2. 在项目中的使用

图标路径集中在 `src/frontend/config/brand.ts`，不要硬编码路径：

```ts
import { BRAND_ICON } from '@/config/brand';

// 界面内（可缩放、无底板）
<img src={BRAND_ICON.mark} alt="Lilovideo" />

// 需要独立成块处（带底板）
<img src={BRAND_ICON.badge} alt="Lilovideo" />
```

| 常量 | 值 | 用在哪 |
| --- | --- | --- |
| `BRAND_ICON.mark` | `/brand/logo.svg` | 侧栏、页头等界面内位置 |
| `BRAND_ICON.badge` | `/brand/logo-512.png` | 需要固定位图的展示位 |
| `BRAND_ICON.badgeSmall` | `/brand/logo-32.png` | 小尺寸位图 |
| `BRAND_ICON.appleTouch` | `/brand/apple-touch-icon.png` | iOS 主屏 |

### React 组件

```tsx
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <img src="/brand/logo.svg" alt="Lilovideo"
         width={size} height={size} />
  );
}
```

### 内联 SVG

需要跟随文字颜色时可内联，把两个 `fill` 换成 `currentColor` 与一个强调色：

```tsx
<svg viewBox="0 0 100 100" width="32" height="32" aria-label="Lilovideo">
  <path fill="currentColor" fillRule="evenodd"
        d="M20 16H76a8 8 0 0 1 8 8V76a8 8 0 0 1-8 8H20a8 8 0 0 1-8-8V24a8 8 0 0 1 8-8Z
           M44 16L57 16L44 84L31 84Z"/>
  <path fill="#FFD9C2" d="M44 16L50 16L37 84L31 84Z"/>
</svg>
```

### CSS 背景（data-URI）

小尺寸场景（如伪元素图标）可用 32px 位图：

```css
.brand-mark {
  width: 32px;
  height: 32px;
  background: url('/brand/logo-32.png') center / contain no-repeat;
}
```

### 单色遮罩（菜单栏、反色场景）

纯符号版可以直接当遮罩用，形状不会塌：

```css
.monochrome-mark {
  width: 24px;
  height: 24px;
  background-color: currentColor;
  -webkit-mask: url('/brand/logo.svg') center / contain no-repeat;
  mask: url('/brand/logo.svg') center / contain no-repeat;
}
```

### favicon `<head>`

Next.js 项目已在 `app/layout.tsx` 的 `metadata.icons` 中声明。若迁到非 Next 环境：

```html
<link rel="icon" href="/brand/logo.svg" type="image/svg+xml">
<link rel="icon" href="/brand/logo-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/brand/logo-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/brand/apple-touch-icon.png" sizes="180x180">
<link rel="shortcut icon" href="/favicon.ico">
```

> 顺序要紧：**支持 SVG 图标的浏览器优先取 `logo.svg`**，矢量在任何缩放下都最清晰；位图只作为后备。

### Web manifest

```json
{
  "name": "Lilovideo",
  "short_name": "Lilovideo",
  "theme_color": "#0d0d12",
  "background_color": "#0d0d12",
  "icons": [
    { "src": "/brand/logo-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/brand/logo-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/brand/logo-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

---

## 3. 重新导出

改了 SVG 源文件后：

```bash
cd docs/design/icons
python3 export_icons.py threshold/concept-1b-slit-light.svg export/
cp export/* ../../src/frontend/public/brand/
cp export/favicon.ico ../../src/frontend/app/favicon.ico
```

导出脚本会**检测空白输出**。这是有意加的：原 skill 的文档记录过一个真实故障——渲染器静默丢掉渐变或遮罩后产出空白 PNG，**退出码却是 0**。只看命令是否成功会漏掉这类问题。

---

## 4. 改图标前先跑审计

```bash
python3 audit_icons.py <你的.svg>
```

六项实测：墨迹覆盖、单色塌陷、16px 镂空存活、最细笔画、节点数、边界留白。

**其中最容易犯的是"把背景底板烘焙进图标本体"**——墨迹覆盖率会立刻暴露它（>0.85 即判失败）。这个问题在 SVG 源码里看不出来，只有渲染成像素才看得见。

---

## 5. 其它方向（未采用，留档）

`threshold/` 下保留本轮全部候选与审计结果：

| 文件 | 名称 | 审计 |
| --- | --- | --- |
| `concept-1-slit.svg` | 斜缝（单色版） | 通过 |
| `concept-1b-slit-light.svg` | **斜缝 · 缝里有光（定稿）** | 通过 |
| `concept-2-gap.svg` | 缺口 | FAIL 笔画过细 |
| `concept-3-ring.svg` | 环缝 | 通过 |
| `concept-4-shear.svg` | 断轴 | 通过 |
| `concept-5-steps.svg` | 步进 | 通过，但语义偏均衡器 |

第一版（播放键 + 创意点）的四个方向保留在 `concept-*.svg`（上级目录），
它们**不符合规范**（烘焙底板 + 使用 AI 领域禁用的 sparkle 符号），仅作对比留档。
