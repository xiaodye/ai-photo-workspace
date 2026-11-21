import { Link } from 'react-router-dom'

import BrandMark from '@/components/BrandMark'
import GithubIcon from '@/components/GithubIcon'
import ThemeSwitcher from '@/components/ThemeSwitcher'
import { GITHUB_URL } from '@/lib/links'

export default function LandingHeader({ account }: { account: string | null }) {
  return (
    <header className="border-line/70 bg-canvas/80 sticky top-0 z-10 border-b backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
        <Link to="/" aria-label="AI 营销素材工作台首页">
          <BrandMark size="sm">
            <span className="text-ink text-sm font-semibold">AI 营销素材工作台</span>
          </BrandMark>
        </Link>

        <div className="flex items-center gap-3">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            title="GitHub 仓库"
            aria-label="在 GitHub 上查看源码"
            className="border-line bg-soft text-muted hover:text-ink rounded-control grid size-10 shrink-0 place-items-center border transition-colors"
          >
            <GithubIcon size={18} />
          </a>
          <ThemeSwitcher />
          {account ? (
            <Link
              to="/create"
              className="border-line-strong text-ink hover:bg-soft rounded-control border px-3.5 py-1.5 text-sm font-medium transition-colors"
            >
              {account} · 进入工作台
            </Link>
          ) : (
            <Link to="/auth" className="text-muted hover:text-ink text-sm transition-colors">
              登录
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}
