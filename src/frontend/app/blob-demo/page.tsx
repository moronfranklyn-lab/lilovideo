"use client";

/**
 * Gradient Blob 演示页（独立演示页）。
 *
 * 目的：在项目内先跑一个可交互演示，确认效果与配色方向后再决定落地位置。
 * 实现：自研 WebGL（无第三方依赖），气质参照 React Bits Pro「Gradient Blob」。
 * 官方 Pro 组件需付费 license 才能安装（见本页底部说明）。
 */

import { useState } from "react";
import GradientBlob, { type GradientBlobColors } from "@/components/GradientBlob";
import SplashCursor from "@/components/SplashCursor";

const PRESETS: { id: string; name: string; colors: GradientBlobColors }[] = [
  {
    id: "aurora",
    name: "Aurora（官方默认）",
    colors: { primary: "#5227ff", secondary: "#ff9ffc", accent: "#b19eef", base: "#27c5ff" },
  },
  {
    id: "ember",
    name: "Ember（项目暖橙）",
    colors: { primary: "#ff7a45", secondary: "#ffb38a", accent: "#ffd9c2", base: "#7a2b0d" },
  },
  {
    id: "lagoon",
    name: "Lagoon（深海）",
    colors: { primary: "#0f766e", secondary: "#22d3ee", accent: "#a5f3fc", base: "#04303a" },
  },
  {
    id: "violet",
    name: "Violet（紫罗兰）",
    colors: { primary: "#7c3aed", secondary: "#c4b5fd", accent: "#f0abfc", base: "#2e1065" },
  },
];

export default function BlobDemoPage() {
  const [preset, setPreset] = useState(PRESETS[0]);
  const [speed, setSpeed] = useState(1.0);
  const [morph, setMorph] = useState(1.0);
  const [size, setSize] = useState(1.2);
  const [cursor, setCursor] = useState(true);
  const [parallax, setParallax] = useState(false);

  return (
    <div className="relative h-screen min-h-[600px] w-full overflow-hidden bg-[#0d0d12]">
      {/* 动态光晕背景 */}
      <GradientBlob
        colors={preset.colors}
        speed={speed}
        morphIntensity={morph}
        size={size}
        enableCursorMorph={cursor}
        parallax={parallax}
        parallaxStrength={0.5}
        quality="high"
        maxFPS={60}
        pauseWhenOffscreen
        className="absolute inset-0 h-full w-full"
      />

      {/* 流体光标（SplashCursor，覆盖在背景之上） */}
      <SplashCursor
        DENSITY_DISSIPATION={2.2}
        VELOCITY_DISSIPATION={1.5}
        PRESSURE={0.1}
        CURL={0.2}
        SPLAT_RADIUS={0.4}
        SPLAT_FORCE={2500}
        COLOR_UPDATE_SPEED={10}
        SHADING
        RAINBOW_MODE={false}
        COLOR="#B497CF"
        className="z-[5]"
      />

      {/* 中央标题（光晕之上） */}
      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center text-center">
        <div className="rounded-full border border-white/10 bg-white/5 px-4 py-1 text-xs tracking-wide text-white/60 backdrop-blur-sm">
          Gradient Blob 演示
        </div>
        <h1 className="mt-5 text-4xl font-semibold tracking-tight text-white drop-shadow-[0_2px_16px_rgba(0,0,0,0.6)]">
          流动的渐变光晕
        </h1>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-white/70 drop-shadow-[0_1px_8px_rgba(0,0,0,0.8)]">
          自研 WebGL 实现 · 移动鼠标观察光晕跟随变形，试试下面的配色与参数。
        </p>
      </div>

      {/* 控制面板 */}
      <div className="absolute bottom-5 right-5 z-20 w-64 rounded-2xl border border-white/10 bg-[#15151d]/80 p-4 shadow-2xl backdrop-blur-md">
        <div className="text-xs font-medium text-white/80">配色预设</div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPreset(p)}
              className={`flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-[11px] transition-colors ${
                preset.id === p.id
                  ? "border-[#ff7a45] bg-[#ff7a45]/15 text-white"
                  : "border-white/10 bg-white/5 text-white/60 hover:bg-white/10"
              }`}
            >
              <span
                className="h-3 w-3 shrink-0 rounded-full ring-1 ring-white/20"
                style={{
                  background: `linear-gradient(135deg, ${p.colors.primary}, ${p.colors.secondary})`,
                }}
              />
              <span className="truncate">{p.name}</span>
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-3">
          {(
            [
              ["速度", speed, setSpeed, 0.2, 2.0, 0.1],
              ["形变", morph, setMorph, 0.2, 2.0, 0.1],
              ["尺寸", size, setSize, 0.5, 2.0, 0.1],
            ] as const
          ).map(([label, val, set, min, max, step]) => (
            <label key={label} className="block">
              <div className="flex justify-between text-[11px] text-white/60">
                <span>{label}</span>
                <span className="tabular-nums text-white/80">{Number(val).toFixed(1)}</span>
              </div>
              <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={val}
                onChange={(e) => set(Number(e.target.value))}
                className="mt-1 h-1 w-full cursor-pointer appearance-none rounded-full bg-white/15 accent-[#ff7a45]"
              />
            </label>
          ))}

          <div className="flex gap-3 pt-1">
            <button
              onClick={() => setCursor((v) => !v)}
              className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] transition-colors ${
                cursor
                  ? "border-[#ff7a45] bg-[#ff7a45]/15 text-white"
                  : "border-white/10 bg-white/5 text-white/50 hover:bg-white/10"
              }`}
            >
              光标变形 {cursor ? "开" : "关"}
            </button>
            <button
              onClick={() => setParallax((v) => !v)}
              className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] transition-colors ${
                parallax
                  ? "border-[#ff7a45] bg-[#ff7a45]/15 text-white"
                  : "border-white/10 bg-white/5 text-white/50 hover:bg-white/10"
              }`}
            >
              视差 {parallax ? "开" : "关"}
            </button>
          </div>
        </div>
      </div>

      {/* 底部说明 */}
      <div className="pointer-events-none absolute bottom-5 left-5 z-10 max-w-xs text-[11px] leading-relaxed text-white/35">
        背景：自研 WebGL（simplex noise fbm）光晕，无第三方依赖，离屏自动暂停渲染。
        <br />
        光标：自研 WebGL 流体模拟（SplashCursor 风格），鼠标移动搅动色墨。
        <br />
        官方 React Bits Pro「Gradient Blob」需付费 license（
        <span className="text-white/60">@reactbits-starter</span> registry），本项目未购买。
      </div>
    </div>
  );
}
