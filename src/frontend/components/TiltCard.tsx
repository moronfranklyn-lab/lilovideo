"use client";

import { useCallback, useRef } from 'react';
import type { ReactNode } from 'react';

type TiltCardProps = {
  children: ReactNode;
  className?: string;
  /** 最大倾斜角度（deg） */
  maxTilt?: number;
};

/**
 * 指针 3D 倾斜包装（动效取自 ProfileCard 的 tilt 引擎）：
 * 鼠标进入 → 卡片随指针位置 3D 倾斜 + 高光跟随；离开 → 平滑回正。
 * 只负责动效，样式由外层 CSS（--rotate-x/--rotate-y/--pointer-x/--pointer-y）决定。
 */
export default function TiltCard({ children, className = '', maxTilt = 9 }: TiltCardProps) {
  const wrapRef = useRef<HTMLDivElement>(null);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const el = wrapRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
      const py = ((e.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
      el.style.setProperty('--pointer-x', `${px.toFixed(2)}%`);
      el.style.setProperty('--pointer-y', `${py.toFixed(2)}%`);
      el.style.setProperty('--rotate-x', `${((-((py - 50) / 50)) * maxTilt).toFixed(2)}deg`);
      el.style.setProperty('--rotate-y', `${(((px - 50) / 50) * maxTilt).toFixed(2)}deg`);
    },
    [maxTilt]
  );

  const onPointerEnter = useCallback(() => {
    wrapRef.current?.classList.add('tilt-active');
  }, []);

  const onPointerLeave = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    el.classList.remove('tilt-active');
    // 回正
    el.style.setProperty('--rotate-x', '0deg');
    el.style.setProperty('--rotate-y', '0deg');
  }, []);

  return (
    <div
      ref={wrapRef}
      onPointerMove={onPointerMove}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      className={`lilo-tilt-wrap ${className}`}
    >
      {children}
    </div>
  );
}
