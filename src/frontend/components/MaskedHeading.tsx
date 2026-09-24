"use client";

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import './MaskedHeading.css';

type MaskedHeadingProps = {
  text: string;
  src: string;
  /** 背景图放大倍数（>1 放大，露出更丰富的纹理） */
  fillScale?: number;
  /** 滚动视差位移（px），0 关闭 */
  parallax?: number;
  /** 入场方式：rise 从下升起 / fade 淡入 / none 直接显示 */
  reveal?: 'rise' | 'fade' | 'none';
  /** 触发时机：view 进入视口 / load 挂载即播 */
  trigger?: 'view' | 'load';
  brightness?: number;
  saturation?: number;
  grayscale?: boolean;
  /** 动画时长（秒） */
  duration?: number;
  /** 每词延迟（秒）——整句模式下作为整体延迟保留 */
  stagger?: number;
  align?: 'left' | 'center' | 'right';
  weight?: number;
  tracking?: number;
  lineHeight?: number;
  className?: string;
  style?: CSSProperties;
};

/**
 * 文字蒙版标题：文字笔画内填充背景图，支持升起/淡入入场与滚动视差。
 * 实现：background-clip: text —— 整张纹理图只显示在文字笔画内，
 * 单元素动画，无逐词测量开销，性能可控。
 */
export default function MaskedHeading({
  text,
  src,
  fillScale = 1,
  parallax = 0,
  reveal = 'rise',
  trigger = 'view',
  brightness = 1,
  saturation = 1,
  grayscale = false,
  duration = 1.1,
  stagger = 0.09,
  align = 'left',
  weight = 700,
  tracking = -0.03,
  lineHeight = 1.06,
  className = '',
  style,
}: MaskedHeadingProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);

  // 入场触发
  useEffect(() => {
    if (trigger === 'load') {
      const t = setTimeout(() => setActive(true), 150);
      return () => clearTimeout(t);
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setActive(true);
          io.disconnect();
        }
      },
      { threshold: 0.15 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [trigger]);

  // 滚动视差：背景图随页面滚动轻微位移（相对视口中心的进度）
  useEffect(() => {
    if (!parallax) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const r = el.getBoundingClientRect();
      const progress =
        (r.top + r.height / 2 - window.innerHeight / 2) / Math.max(window.innerHeight, 1);
      el.style.setProperty('--masked-parallax', `${(-progress * parallax).toFixed(2)}px`);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [parallax]);

  const revealCls =
    reveal === 'fade' ? 'masked-heading--fade' : reveal === 'none' ? '' : 'masked-heading--rise';
  const fillPct = Math.round(fillScale * 100);

  return (
    <div
      ref={ref}
      className={`masked-heading ${revealCls} ${active ? 'masked-heading--active' : ''} ${className}`}
      style={
        {
          textAlign: align,
          fontWeight: weight,
          letterSpacing: tracking,
          lineHeight,
          '--masked-duration': `${duration}s`,
          '--masked-stagger': `${stagger}s`,
          ...style,
        } as CSSProperties
      }
    >
      <span
        className="masked-heading__text"
        style={{
          backgroundImage: `url(${src})`,
          backgroundSize: `${fillPct}% auto`,
          filter: `brightness(${brightness}) saturate(${saturation})${grayscale ? ' grayscale(1)' : ''}`,
        }}
      >
        {text}
      </span>
    </div>
  );
}
