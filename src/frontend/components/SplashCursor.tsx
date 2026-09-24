"use client";

/**
 * SplashCursor —— 流体溅射光标（自研 WebGL 流体模拟）。
 *
 * 参照 React Bits「SplashCursor」的视觉：鼠标移动搅动一片流体色墨，
 * 带速度、卷曲（curl）、耗散、辉光着色。基于经典的 WebGL 简化流体模拟
 * （平流 + splat 注入 + curl 力 + 耗散），无第三方依赖。
 */

import { useEffect, useRef } from "react";

export interface SplashCursorProps {
  /** 密度耗散速度（越大消失越快） */
  DENSITY_DISSIPATION?: number;
  /** 速度耗散 */
  VELOCITY_DISSIPATION?: number;
  /** 压力（简化实现中作为 curl 力的加权） */
  PRESSURE?: number;
  /** 卷曲强度（漩涡感） */
  CURL?: number;
  /** 注入半径 */
  SPLAT_RADIUS?: number;
  /** 注入力度 */
  SPLAT_FORCE?: number;
  /** 颜色更新速度（彩虹模式用） */
  COLOR_UPDATE_SPEED?: number;
  /** 简单光照着色 */
  SHADING?: boolean;
  /** 彩虹变色 */
  RAINBOW_MODE?: boolean;
  /** 主色 */
  COLOR?: string;
  /** 注入的色墨量 */
  DYE_AMOUNT?: number;
  className?: string;
}

function hexToRgb(hex: string): [number, number, number] {
  let h = hex.replace("#", "").trim();
  if (h.length === 3) {
    h = h
      .split("")
      .map((c) => c + c)
      .join("");
  }
  const n = parseInt(h, 16);
  if (Number.isNaN(n) || h.length !== 6) return [1, 1, 1];
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

const VERT = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG_ADVECT = `
precision highp float;
uniform sampler2D uVelocity;
uniform sampler2D uSource;
uniform vec2 uTexel;
uniform vec2 uRes;
uniform float uDt;
uniform float uDissipation;

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  vec2 vel = texture2D(uVelocity, uv).xy;
  vec2 coord = uv - uDt * vel * 6.0;
  coord = clamp(coord, vec2(0.0), vec2(1.0));
  vec4 src = texture2D(uSource, coord);
  src *= exp(-uDissipation * uDt);
  gl_FragColor = src;
}
`;

const FRAG_SPLAT = `
precision highp float;
uniform sampler2D uTarget;
uniform vec2 uTexel;
uniform vec2 uRes;
uniform vec2 uPoint;
uniform float uRadius;
uniform vec3 uColor;
uniform float uAspect;
uniform float uIsVelocity;
uniform vec2 uDir;        // 鼠标运动方向（归一化）
uniform float uDirEnable; // 1=沿运动方向推动（抚摸），0=径向涟漪

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  vec2 d = uv - uPoint;
  d.x *= uAspect;
  float r2 = dot(d, d);
  float rad2 = uRadius * uRadius;
  float e = exp(-r2 / rad2);

  vec4 cur = texture2D(uTarget, uv);
  if (uIsVelocity > 0.5) {
    // 速度注入：优先沿鼠标运动方向轻柔推动（抚摸感），静止时退化为径向
    vec2 radial = d / max(length(d), 0.001);
    vec2 dir = mix(radial, normalize(uDir), uDirEnable);
    vec2 vel = dir * e * 1.0;
    gl_FragColor = vec4(cur.xy + vel, 0.0, 1.0);
  } else {
    // 色墨注入
    vec3 col = uColor * e;
    gl_FragColor = vec4(cur.rgb + col * 1.2, 1.0);
  }
}
`;

const FRAG_CURL = `
precision highp float;
uniform sampler2D uVelocity;
uniform vec2 uTexel;
uniform vec2 uRes;
uniform float uCurl;

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  vec2 t = texture2D(uVelocity, uv + vec2(0.0, uTexel.y)).xy;
  vec2 b = texture2D(uVelocity, uv - vec2(0.0, uTexel.y)).xy;
  vec2 l = texture2D(uVelocity, uv - vec2(uTexel.x, 0.0)).xy;
  vec2 r = texture2D(uVelocity, uv + vec2(uTexel.x, 0.0)).xy;

  float dvdy = (t.x - b.x) * 0.5;
  float dudx = (r.y - l.y) * 0.5;
  float curl = (dudx - dvdy) * uCurl;

  // 旋度作为速度的切向力注入（简化稳定流体）
  vec2 force = vec2(t.y - b.y, r.x - l.x) * 0.5 * uCurl;
  vec2 vel = texture2D(uVelocity, uv).xy + force;
  gl_FragColor = vec4(vel, 0.0, 1.0);
}
`;

const FRAG_RENDER = `
precision highp float;
uniform sampler2D uDye;
uniform sampler2D uVelocity;
uniform vec2 uTexel;
uniform vec2 uRes;
uniform float uShading;
uniform float uBrightness;

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  vec4 dye = texture2D(uDye, uv);
  if (uShading > 0.5) {
    // 简化光照：密度梯度 × 速度方向
    vec2 g = vec2(
      texture2D(uDye, uv + vec2(uTexel.x, 0.0)).r - texture2D(uDye, uv - vec2(uTexel.x, 0.0)).r,
      texture2D(uDye, uv + vec2(0.0, uTexel.y)).r - texture2D(uDye, uv - vec2(0.0, uTexel.y)).r
    );
    vec2 vel = texture2D(uVelocity, uv).xy;
    float light = dot(g, normalize(vel + vec2(0.0001))) * 0.6;
    dye.rgb *= 1.0 + light;
  }
  gl_FragColor = dye * uBrightness;
}
`;

interface FBO {
  tex: WebGLTexture;
  fb: WebGLFramebuffer;
  w: number;
  h: number;
}

function createFBO(gl: WebGLRenderingContext, w: number, h: number): FBO {
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  const fb = gl.createFramebuffer()!;
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  return { tex, fb, w, h };
}

export default function SplashCursor({
  DENSITY_DISSIPATION = 2.2,
  VELOCITY_DISSIPATION = 1.5,
  PRESSURE = 0.1,
  CURL = 0.2,
  SPLAT_RADIUS = 0.4,
  SPLAT_FORCE = 2500,
  COLOR_UPDATE_SPEED = 10,
  SHADING = true,
  RAINBOW_MODE = false,
  COLOR = "#B497CF",
  DYE_AMOUNT = 0.5,
  className = "",
}: SplashCursorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const gl = canvas.getContext("webgl", {
      alpha: true,
      premultipliedAlpha: false,
      antialias: false,
    });
    if (!gl) return;

    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.error("[SplashCursor] shader:", gl.getShaderInfoLog(sh));
        gl.deleteShader(sh);
        return null;
      }
      return sh;
    };
    const makeProgram = (fragSrc: string) => {
      const vs = compile(gl.VERTEX_SHADER, VERT);
      const fs = compile(gl.FRAGMENT_SHADER, fragSrc);
      if (!vs || !fs) return null;
      const prog = gl.createProgram()!;
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        console.error("[SplashCursor] link:", gl.getProgramInfoLog(prog));
        return null;
      }
      return prog;
    };

    const progAdvect = makeProgram(FRAG_ADVECT);
    const progSplat = makeProgram(FRAG_SPLAT);
    const progCurl = makeProgram(FRAG_CURL);
    const progRender = makeProgram(FRAG_RENDER);
    if (!progAdvect || !progSplat || !progCurl || !progRender) return;

    // 全屏 quad
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);

    // 模拟分辨率（约 1/3，上采样渲染，性能与细腻度平衡）
    let simW = 0;
    let simH = 0;
    let vel: [FBO, FBO] | null = null;
    let dye: [FBO, FBO] | null = null;
    let simScale = 1;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const w = Math.max(1, rect.width);
      const h = Math.max(1, rect.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      simScale = Math.max(0.22, Math.min(0.45, 900 / Math.max(w, h)));
      simW = Math.max(2, Math.round(canvas.width * simScale));
      simH = Math.max(2, Math.round(canvas.height * simScale));
      vel = [createFBO(gl, simW, simH), createFBO(gl, simW, simH)];
      dye = [createFBO(gl, simW, simH), createFBO(gl, simW, simH)];
    };
    const rafId = requestAnimationFrame(resize);
    resize();

    const ro = new ResizeObserver(resize);
    ro.observe(container);

    // 鼠标状态
    const last = { x: -1, y: -1, active: false };
    let hue = 0;

    const pointerPos = (e: MouseEvent | TouchEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return null;
      const cx = "touches" in e ? e.touches[0]?.clientX : e.clientX;
      const cy = "touches" in e ? e.touches[0]?.clientY : e.clientY;
      if (cx == null || cy == null) return null;
      return {
        x: (cx - rect.left) / rect.width,
        y: 1 - (cy - rect.top) / rect.height,
      };
    };

    const onMove = (e: MouseEvent | TouchEvent) => {
      const p = pointerPos(e);
      if (!p) return;
      last.x = p.x;
      last.y = p.y;
      last.active = true;
      lastActiveAt = performance.now();
      if (running && !raf) raf = requestAnimationFrame(loop);
    };
    const onDown = (e: MouseEvent | TouchEvent) => {
      const p = pointerPos(e);
      if (!p) return;
      last.x = p.x;
      last.y = p.y;
      last.active = true;
      lastActiveAt = performance.now();
      if (running && !raf) raf = requestAnimationFrame(loop);
    };
    const onUp = () => {
      last.active = false;
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchstart", onDown, { passive: true });
    window.addEventListener("touchend", onUp, { passive: true });

    // uniform 辅助
    const unis = (prog: WebGLProgram, names: string[]) => {
      const map: Record<string, WebGLUniformLocation | null> = {};
      for (const n of names) map[n] = gl.getUniformLocation(prog, n);
      return map;
    };
    const aPos = (prog: WebGLProgram) => {
      const loc = gl.getAttribLocation(prog, "aPos");
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    };

    const uAdvect = unis(progAdvect, ["uVelocity", "uSource", "uTexel", "uRes", "uDt", "uDissipation"]);
    const uSplat = unis(progSplat, ["uTarget", "uTexel", "uRes", "uPoint", "uRadius", "uColor", "uAspect", "uIsVelocity", "uDir", "uDirEnable"]);
    const uCurl = unis(progCurl, ["uVelocity", "uTexel", "uRes", "uCurl"]);
    const uRender = unis(progRender, ["uDye", "uVelocity", "uTexel", "uRes", "uShading", "uBrightness"]);

    const bindFBO = (fbo: FBO | null) => {
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo ? fbo.fb : null);
      gl.viewport(0, 0, fbo ? fbo.w : canvas.width, fbo ? fbo.h : canvas.height);
    };
    const bindTex = (unit: number, tex: WebGLTexture, loc: WebGLUniformLocation | null) => {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(loc, unit);
    };

    const step = (dt: number, target: FBO, source: FBO, dissipation: number) => {
      // 平流
      gl.useProgram(progAdvect);
      aPos(progAdvect);
      bindFBO(target);
      bindTex(0, source.tex, uAdvect.uSource);
      bindTex(1, source.tex, uAdvect.uVelocity);
      gl.uniform2f(uAdvect.uTexel, 1 / simW, 1 / simH);
      gl.uniform2f(uAdvect.uRes, simW, simH);
      gl.uniform1f(uAdvect.uDt, dt);
      gl.uniform1f(uAdvect.uDissipation, dissipation);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    const applyCurl = (target: FBO, source: FBO) => {
      gl.useProgram(progCurl);
      aPos(progCurl);
      bindFBO(target);
      bindTex(0, source.tex, uCurl.uVelocity);
      gl.uniform2f(uCurl.uTexel, 1 / simW, 1 / simH);
      gl.uniform2f(uCurl.uRes, simW, simH);
      gl.uniform1f(uCurl.uCurl, CURL);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    const splat = (
      x: number,
      y: number,
      color: [number, number, number],
      force: number,
      dir: [number, number] | null,
    ) => {
      if (!vel || !dye) return;
      // 速度注入
      gl.useProgram(progSplat);
      aPos(progSplat);
      bindFBO(vel[0]);
      bindTex(0, vel[1].tex, uSplat.uTarget);
      gl.uniform2f(uSplat.uTexel, 1 / simW, 1 / simH);
      gl.uniform2f(uSplat.uRes, simW, simH);
      gl.uniform2f(uSplat.uPoint, x, y);
      gl.uniform1f(uSplat.uRadius, SPLAT_RADIUS);
      gl.uniform3f(uSplat.uColor, 0, 0, 0);
      gl.uniform1f(uSplat.uAspect, simW / simH);
      gl.uniform1f(uSplat.uIsVelocity, 1);
      gl.uniform2f(uSplat.uDir, dir ? dir[0] : 0, dir ? dir[1] : 0);
      gl.uniform1f(uSplat.uDirEnable, dir ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      // 色墨注入
      bindFBO(dye[0]);
      bindTex(0, dye[1].tex, uSplat.uTarget);
      gl.uniform2f(uSplat.uPoint, x, y);
      gl.uniform1f(uSplat.uRadius, SPLAT_RADIUS);
      gl.uniform3f(uSplat.uColor, color[0], color[1], color[2]);
      gl.uniform1f(uSplat.uAspect, simW / simH);
      gl.uniform1f(uSplat.uIsVelocity, 0);
      gl.uniform2f(uSplat.uDir, dir ? dir[0] : 0, dir ? dir[1] : 0);
      gl.uniform1f(uSplat.uDirEnable, dir ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    let running = true;
    let raf = 0;
    const start = performance.now();
    let prev = performance.now();
    let forceNow = 0;
    // 上一帧指针位置（用于计算抚摸方向）
    let prevPtr: { x: number; y: number } | null = null;
    // 空闲暂停：鼠标静止超时后停止渲染循环，移动时立即唤醒（显著降低后台 GPU 占用）
    let lastActiveAt = performance.now();
    const IDLE_MS = 2000;

    const loop = (now: number) => {
      if (!running) return;
      // 空闲暂停：无指针活动超时后停止循环，鼠标移动时由 onMove/onDown 唤醒
      if (!last.active && now - lastActiveAt > IDLE_MS) {
        raf = 0;
        return;
      }
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.033, (now - prev) / 1000);
      prev = now;
      if (!vel || !dye) return;

      // 颜色更新（彩虹）
      if (RAINBOW_MODE) {
        hue += dt * COLOR_UPDATE_SPEED * 0.1;
      }

      // 鼠标注入：持续移动时以力注入（位移越大力越大）
      if (last.active) {
        forceNow = Math.min(SPLAT_FORCE, forceNow + dt * 6000);
      } else {
        forceNow = Math.max(0, forceNow - dt * 3000);
      }
      if (last.x >= 0 && forceNow > 0.001) {
        let col: [number, number, number];
        if (RAINBOW_MODE) {
          const hsv = hue % 360;
          col = hsvToRgb(hsv);
        } else {
          col = hexToRgb(COLOR);
        }
        // 抚摸方向：当前帧与上一帧指针的位移（uv 空间，考虑宽高比）
        let dir: [number, number] | null = null;
        if (prevPtr) {
          const dx = (last.x - prevPtr.x) * (simW / simH);
          const dy = last.y - prevPtr.y;
          const len = Math.hypot(dx, dy);
          if (len > 0.0015) {
            dir = [dx / len, dy / len];
          }
        }
        splat(last.x, last.y, col, forceNow / 1000, dir);
        prevPtr = { x: last.x, y: last.y };
      } else {
        prevPtr = null;
      }

      // 速度场：平流 → curl → 平流（耗散各自独立）
      step(dt, vel[0], vel[1], VELOCITY_DISSIPATION);
      applyCurl(vel[1], vel[0]);
      // 密度场：平流（耗散）
      step(dt, dye[0], dye[1], DENSITY_DISSIPATION);

      // 渲染
      gl.useProgram(progRender);
      aPos(progRender);
      bindFBO(null);
      gl.disable(gl.BLEND);
      bindTex(0, dye[0].tex, uRender.uDye);
      bindTex(1, vel[0].tex, uRender.uVelocity);
      gl.uniform2f(uRender.uTexel, 1 / simW, 1 / simH);
      gl.uniform2f(uRender.uRes, simW, simH);
      gl.uniform1f(uRender.uShading, SHADING ? 1 : 0);
      gl.uniform1f(uRender.uBrightness, 1.0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      // ping-pong 交换
      const v = vel;
      const d = dye;
      vel = [v[1], v[0]];
      dye = [d[1], d[0]];
    };
    raf = requestAnimationFrame(loop);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      cancelAnimationFrame(rafId);
      ro.disconnect();
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchstart", onDown);
      window.removeEventListener("touchend", onUp);
      gl.deleteBuffer(buf);
      for (const p of [progAdvect, progSplat, progCurl, progRender]) gl.deleteProgram(p);
    };
  }, [
    DENSITY_DISSIPATION,
    VELOCITY_DISSIPATION,
    CURL,
    SPLAT_RADIUS,
    SPLAT_FORCE,
    COLOR_UPDATE_SPEED,
    SHADING,
    RAINBOW_MODE,
    COLOR,
  ]);

  return (
    <div ref={containerRef} className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />
    </div>
  );
}

function hsvToRgb(h: number): [number, number, number] {
  const s = 0.9;
  const v = 1.0;
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [r + m, g + m, b + m];
}
