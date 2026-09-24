'use client';

import React from 'react';
import { Coins, Lock, RefreshCw, TrendingUp, TrendingDown, X } from 'lucide-react';
import type { CreditsAccount, CreditsLedgerItem } from '@/lib/workflowApi';

interface CreditsPanelProps {
  open: boolean;
  onClose: () => void;
  account: CreditsAccount | null;
  ledger: CreditsLedgerItem[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  /** 面板定位类，默认右上弹出；侧边栏内使用时覆盖为向上弹出 */
  panelClassName?: string;
}

function formatTime(value?: string | number): string {
  if (!value) return '—';
  const ts = typeof value === 'number' ? value : new Date(value).getTime() / 1000;
  if (!Number.isFinite(ts) || ts <= 0) return '—';
  try {
    return new Date(ts * 1000).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

export default function CreditsPanel({
  open,
  onClose,
  account,
  ledger,
  loading,
  error,
  onRefresh,
  panelClassName = 'absolute right-0 top-full mt-2',
}: CreditsPanelProps) {
  if (!open) return null;

  return (
    <div className={`${panelClassName} z-50 w-80 rounded-2xl bg-white shadow-xl ring-1 ring-gray-200 overflow-hidden`}>
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-100">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
          <Coins className="w-4 h-4 text-amber-500" />
          我的积分
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="刷新"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="关闭"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-red-600 bg-red-50 border-b border-red-100">
          {error}
        </div>
      )}

      {/* 余额 */}
      {account && (
        <div className="px-4 py-4">
          <div className="flex items-end gap-1">
            <span className="text-3xl font-bold text-gray-800 tabular-nums">{account.balance}</span>
            <span className="text-sm text-gray-500 mb-1">积分</span>
          </div>
          <div className="mt-1 text-xs text-gray-400">
            约 ¥{account.balance_value_yuan.toFixed(2)} · 1 积分 = ¥{account.yuan_per_credit}
          </div>

          <div className="grid grid-cols-2 gap-2 mt-3">
            <div className="rounded-xl bg-gray-50 px-3 py-2">
              <div className="flex items-center gap-1 text-[10px] text-gray-400">
                <Lock className="w-3 h-3" /> 冻结中
              </div>
              <div className="text-sm font-semibold text-gray-700 tabular-nums mt-0.5">
                {account.locked}
              </div>
            </div>
            <div className="rounded-xl bg-gray-50 px-3 py-2">
              <div className="flex items-center gap-1 text-[10px] text-gray-400">
                <TrendingUp className="w-3 h-3" /> 累计获得
              </div>
              <div className="text-sm font-semibold text-gray-700 tabular-nums mt-0.5">
                {account.total_granted}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 流水 */}
      <div className="border-t border-gray-100">
        <div className="px-4 py-2 text-[11px] font-medium text-gray-400">最近流水</div>
        {ledger.length === 0 ? (
          <div className="px-4 pb-4 text-xs text-gray-400">
            {loading ? '加载中…' : '暂无流水记录'}
          </div>
        ) : (
          <ul className="max-h-56 overflow-y-auto px-2 pb-2">
            {ledger.slice(0, 20).map((item, idx) => {
              const positive = item.amount > 0;
              return (
                <li
                  key={item.id || idx}
                  className="flex items-center gap-2 px-2 py-2 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <span
                    className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                      positive ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500'
                    }`}
                  >
                    {positive ? (
                      <TrendingUp className="w-3.5 h-3.5" />
                    ) : (
                      <TrendingDown className="w-3.5 h-3.5" />
                    )}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-gray-700 truncate">
                      {item.reason || (positive ? '获得积分' : '消耗积分')}
                    </div>
                    <div className="text-[10px] text-gray-400">{formatTime(item.created_at)}</div>
                  </div>
                  <div
                    className={`text-xs font-semibold tabular-nums flex-shrink-0 ${
                      positive ? 'text-emerald-600' : 'text-gray-700'
                    }`}
                  >
                    {positive ? '+' : ''}{item.amount}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
