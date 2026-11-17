import { KeyRound } from 'lucide-react'

import { useModelSettings } from '@/hooks/useModelSettings'
import { useModelSettingsUi } from '@/stores/modelSettings'

/**
 * 未配置模型 Key 时的提示。站点不提供公共额度，必须使用自己的模型账户。
 *
 * 内容竖排而不是横排：编辑器侧栏只有 288px 宽，横排会把文案和按钮挤到换行。
 */
export default function ModelKeyNotice({ className = '' }: { className?: string }) {
  const { configured, isLoading } = useModelSettings()
  const setOpen = useModelSettingsUi((state) => state.setOpen)

  if (isLoading || configured) return null

  return (
    <div
      role="status"
      className={`border-warning-border bg-warning-soft rounded-panel flex items-start gap-2.5 border px-3.5 py-3 ${className}`}
    >
      <KeyRound
        size={16}
        strokeWidth={1.8}
        className="text-warning mt-0.5 shrink-0"
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="text-warning-ink text-sm font-medium leading-snug">
          先配置你自己的模型 API Key
        </p>
        <p className="text-warning-ink/80 mt-1 text-[11px] leading-relaxed">
          AI 生成与编辑按你自己的阿里云百炼账户计费，站点不提供公共额度。
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="border-warning-border bg-paper text-warning-ink hover:bg-warning-soft rounded-chip mt-2 inline-flex h-7 items-center border px-2.5 text-[11px] font-medium transition-colors"
        >
          去配置
        </button>
      </div>
    </div>
  )
}
