"use client";

/**
 * GradientBlob —— 动态渐变光晕组件（自研 WebGL 实现）。
 *
 * 参照 ReactBits pro「Gradient Blob」的视觉气质：流动的多色渐变光晕，
 * 支持鼠标跟随变形、视差、呼吸节奏，暗底上呈现液态发光感。
 *
 * 实现：全屏 quad + fragment shader（3D simplex noise fbm 驱动颜色场），
 * 无第三方依赖，性能可控（渲染分辨率分级 / FPS 上限 / 离屏暂停）。
 */

import { useEffect, useRef } from "react";

export interface GradientBlobColors {
  primary: string;
  secondary: string;
  accent: string;
  base: string;
}

export interface GradientBlobProps {
  colors?: GradientBlobColors;
  /** 动画速度倍率 */
  speed?: number;
  /** 光晕尺寸倍率 */
  size?: number;
  /** 形变强度 0–2 */
  morphIntensity?: number;
  /** 鼠标靠近时光晕随光标变形 */
  enableCursorMorph?: boolean;
  /** 视差：整体随光标轻微位移 */
  parallax?: boolean;
  parallaxStrength?: number;
  opacity?: number;
  /** 渲染分辨率分级（与 devicePixelRatio 相乘） */
  quality?: "low" | "medium" | "high";
  maxFPS?: number;
  /** 离开视口时暂停渲染 */
  pauseWhenOffscreen?: boolean;
  className?: string;
  /** 叠加在光晕之上的内容 */
  children?: React.ReactNode;
}

const QUALITY_SCALE: Record<string, number> = {
  low: 0.5,
  medium: 0.75,
  high: 1.0,
};

function hexToRgba(hex: string): [number, number, number, number] {
  let h = hex.replace("#", "").trim();
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  const n = parseInt(h, 16);
  if (Number.isNaN(n) || h.length !== 6) return [1, 1, 1, 1];
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, 1];
}

const VERT_SRC = `
attribute vec2 aPos;
void main() {
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

const FRAG_SRC = `
precision highp float;

uniform vec2  uResolution;
uniform float uTime;
uniform vec2  uMouse;      // 0..1
uniform float uSpeed;
uniform float uSize;
uniform float uMorph;
uniform float uCursorOn;
uniform float uParallaxOn;
uniform float uParallaxStrength;
uniform float uOpacity;
uniform vec4  uColorA;     // primary
uniform vec4  uColorB;     // secondary
uniform vec4  uColorC;     // accent
uniform vec4  uColorD;     // base

// ---- 3D simplex noise (Ashima Arts, MIT) ----
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
            i.z + vec4(0.0, i1.z, i2.z, 1.0))
          + i.y + vec4(0.0, i1.y, i2.y, 1.0))
          + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

float fbm(vec3 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {
    v += a * snoise(p);
    p *= 2.02;
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 p = (uv - 0.5) * 2.0;
  float aspect = uResolution.x / uResolution.y;
  p.x *= aspect;

  float t = uTime * uSpeed;

  // 光标位置（归一化到 -1..1）
  vec2 mp = (uMouse - 0.5) * 2.0;
  mp.x *= aspect;

  // 光标附近的形变扰动
  float cm = 0.0;
  if (uCursorOn > 0.5) {
    cm = exp(-length(p - mp * 0.7) * 2.2) * uMorph * 1.6;
  }

  // 视差整体位移
  vec2 plx = (mp * 0.05) * uParallaxOn * uParallaxStrength;

  // 多层噪声场
  vec3 q1 = vec3(p * uSize + plx, t * 0.12);
  float n1 = fbm(q1 + vec3(cm));
  float n2 = fbm(q1 * 1.7 + vec3(t * 0.05, -t * 0.04, n1 * 0.6));
  float n3 = fbm(q1 * 3.1 - vec3(n1 * 1.2, n2 * 1.2, t * 0.03));

  float v = n1 * 0.5 + n2 * 0.33 + n3 * 0.17;
  float x = v * 0.5 + 0.5;

  // 有机轮廓
  float r = length(p);
  float breath = 0.86 + 0.14 * sin(t * 0.35);
  float maskBase = smoothstep(1.0, 0.1, r * breath);
  float shape = clamp(maskBase + (x - 0.5) * 1.6, 0.0, 1.0);
  shape = smoothstep(0.0, 1.0, shape);

  // 四色渐变
  vec3 col = mix(uColorA.rgb, uColorB.rgb, smoothstep(0.0, 1.0, x));
  col = mix(col, uColorC.rgb, smoothstep(0.4, 0.95, x) * 0.55);
  col = mix(col, uColorD.rgb, smoothstep(0.0, 0.75, r * 1.05) * 0.3);

  // 伪光照：中心高光 + 边缘菲涅尔
  float hl = smoothstep(0.9, 0.0, r) * 0.22;
  float fres = pow(1.0 - clamp(r / 1.15, 0.0, 1.0), 2.5) * 0.4;
  col += vec3(1.0) * (hl + fres * 0.32);

  float alpha = shape * uOpacity;
  gl_FragColor = vec4(col, alpha);
}
`;

export default function GradientBlob({
  colors,
  speed = 1.0,
  size = 1.0,
  morphIntensity = 1.0,
  enableCursorMorph = true,
  parallax = false,
  parallaxStrength = 0.5,
  opacity = 1.0,
  quality = "medium",
  maxFPS = 60,
  pauseWhenOffscreen = true,
  className = "",
  children,
}: GradientBlobProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // 参数镜像：uniform 每帧读取，避免 props 变化触发重初始化
  const params = useRef({
    colors: colors ?? {
      primary: "#5227ff",
      secondary: "#ff9ffc",
      accent: "#b19eef",
      base: "#27c5ff",
    },
    speed,
    size,
    morphIntensity,
    enableCursorMorph,
    parallax,
    parallaxStrength,
    opacity,
    qualityScale: QUALITY_SCALE[quality] ?? 0.75,
    maxFPS,
    pauseWhenOffscreen,
  });

  useEffect(() => {
    params.current = {
      ...params.current,
      colors: colors ?? params.current.colors,
      speed,
      size,
      morphIntensity,
      enableCursorMorph,
      parallax,
      parallaxStrength,
      opacity,
      qualityScale: QUALITY_SCALE[quality] ?? 0.75,
      maxFPS,
      pauseWhenOffscreen,
    };
  }, [colors, speed, size, morphIntensity, enableCursorMorph, parallax, parallaxStrength, opacity, quality, maxFPS, pauseWhenOffscreen]);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const gl = canvas.getContext("webgl", {
      alpha: true,
      premultipliedAlpha: false,
      antialias: false,
      powerPreference: "high-performance",
    });
    if (!gl) return;

    // ---- shader 编译 ----
    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.error("[GradientBlob] shader error:", gl.getShaderInfoLog(sh));
        gl.deleteShader(sh);
        return null;
      }
      return sh;
    };
    const vs = compile(gl.VERTEX_SHADER, VERT_SRC);
    const fs = compile(gl.FRAGMENT_SHADER, FRAG_SRC);
    if (!vs || !fs) return;

    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.error("[GradientBlob] link error:", gl.getProgramInfoLog(prog));
      return;
    }
    gl.useProgram(prog);

    const loc = {
      aPos: gl.getAttribLocation(prog, "aPos"),
      uResolution: gl.getUniformLocation(prog, "uResolution"),
      uTime: gl.getUniformLocation(prog, "uTime"),
      uMouse: gl.getUniformLocation(prog, "uMouse"),
      uSpeed: gl.getUniformLocation(prog, "uSpeed"),
      uSize: gl.getUniformLocation(prog, "uSize"),
      uMorph: gl.getUniformLocation(prog, "uMorph"),
      uCursorOn: gl.getUniformLocation(prog, "uCursorOn"),
      uParallaxOn: gl.getUniformLocation(prog, "uParallaxOn"),
      uParallaxStrength: gl.getUniformLocation(prog, "uParallaxStrength"),
      uOpacity: gl.getUniformLocation(prog, "uOpacity"),
      uColorA: gl.getUniformLocation(prog, "uColorA"),
      uColorB: gl.getUniformLocation(prog, "uColorB"),
      uColorC: gl.getUniformLocation(prog, "uColorC"),
      uColorD: gl.getUniformLocation(prog, "uColorD"),
    };

    // ---- 全屏 quad ----
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(loc.aPos);
    gl.vertexAttribPointer(loc.aPos, 2, gl.FLOAT, false, 0, 0);

    // ---- 尺寸（rect 测量 + rAF 兜底，避免初始布局未就绪时读到 0） ----
    const resize = () => {
      const rect = container.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      if (w < 2 || h < 2) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5); // 全屏光晕降低分辨率，减少 GPU 占用
      const scale = params.current.qualityScale;
      canvas.width = Math.max(2, Math.round(w * dpr * scale));
      canvas.height = Math.max(2, Math.round(h * dpr * scale));
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    const rafId = requestAnimationFrame(resize);
    resize();

    const ro = new ResizeObserver(resize);
    ro.observe(container);

    // ---- 鼠标 ----
    const mouse = { x: 0.5, y: 0.5 };
    const onMouse = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      mouse.x = (e.clientX - rect.left) / rect.width;
      mouse.y = 1 - (e.clientY - rect.top) / rect.height;
    };
    const onTouch = (e: TouchEvent) => {
      const t = e.touches[0];
      if (!t) return;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      mouse.x = (t.clientX - rect.left) / rect.width;
      mouse.y = 1 - (t.clientY - rect.top) / rect.height;
    };
    container.addEventListener("mousemove", onMouse);
    container.addEventListener("touchmove", onTouch, { passive: true });

    // ---- 离屏暂停 ----
    let visible = true;
    let io: IntersectionObserver | null = null;
    if (params.current.pauseWhenOffscreen && "IntersectionObserver" in window) {
      io = new IntersectionObserver(([entry]) => {
        visible = entry.isIntersecting;
      });
      io.observe(container);
    }

    // ---- 渲染循环（带 FPS 上限） ----
    let raf = 0;
    let running = true;
    const start = performance.now();
    let last = 0;
    const frameMs = 1000 / Math.max(1, params.current.maxFPS);

    const render = (now: number) => {
      if (!running) return;
      raf = requestAnimationFrame(render);
      if (now - last < frameMs) return;
      last = now;
      if (!visible) return;

      const p = params.current;
      const t = (now - start) / 1000;

      gl.useProgram(prog);
      gl.uniform2f(loc.uResolution, canvas.width, canvas.height);
      gl.uniform1f(loc.uTime, t);
      gl.uniform2f(loc.uMouse, mouse.x, mouse.y);
      gl.uniform1f(loc.uSpeed, p.speed);
      gl.uniform1f(loc.uSize, p.size);
      gl.uniform1f(loc.uMorph, p.morphIntensity);
      gl.uniform1f(loc.uCursorOn, p.enableCursorMorph ? 1 : 0);
      gl.uniform1f(loc.uParallaxOn, p.parallax ? 1 : 0);
      gl.uniform1f(loc.uParallaxStrength, p.parallaxStrength);
      gl.uniform1f(loc.uOpacity, p.opacity);

      const [ra, ga, ba] = hexToRgba(p.colors.primary);
      const [rb, gb, bb] = hexToRgba(p.colors.secondary);
      const [rc, gc, bc] = hexToRgba(p.colors.accent);
      const [rd, gd, bd] = hexToRgba(p.colors.base);
      gl.uniform4f(loc.uColorA, ra, ga, ba, 1);
      gl.uniform4f(loc.uColorB, rb, gb, bb, 1);
      gl.uniform4f(loc.uColorC, rc, gc, bc, 1);
      gl.uniform4f(loc.uColorD, rd, gd, bd, 1);

      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    raf = requestAnimationFrame(render);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      cancelAnimationFrame(rafId);
      ro.disconnect();
      io?.disconnect();
      container.removeEventListener("mousemove", onMouse);
      container.removeEventListener("touchmove", onTouch);
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, []);

  return (
    <div ref={containerRef} className={`overflow-hidden ${className}`}>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      />
      {children != null && <div className="relative z-10 h-full w-full">{children}</div>}
    </div>
  );
}
