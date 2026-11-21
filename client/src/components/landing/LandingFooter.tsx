import BrandMark from '@/components/BrandMark'
import GithubIcon from '@/components/GithubIcon'
import { GITHUB_URL } from '@/lib/links'

export default function LandingFooter() {
  return (
    <footer className="border-line border-t">
      <div className="text-faint mx-auto flex max-w-5xl flex-col items-center justify-between gap-3 px-6 py-8 text-xs sm:flex-row">
        <BrandMark size="sm">
          <span className="text-muted font-medium">AI 营销素材工作台</span>
        </BrandMark>
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:gap-5">
          <p>为电商运营与内容创作者打造的商品物料工作台</p>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="hover:text-ink inline-flex items-center gap-1.5 transition-colors"
          >
            <GithubIcon size={15} />
            GitHub
          </a>
        </div>
      </div>
    </footer>
  )
}
