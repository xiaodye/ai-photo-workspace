import { useQuery } from '@tanstack/react-query'

import { modelSettingsApi } from '@/api/modelSettings'
import { useCurrentUser } from '@/hooks/useAuth'

export const MODEL_SETTINGS_KEY = ['model-settings']

/**
 * 按登录账号读取模型设置，登录态未就绪时不发请求。
 *
 * @returns
 */
export function useModelSettings() {
  const { user } = useCurrentUser()
  const query = useQuery({
    queryKey: MODEL_SETTINGS_KEY,
    queryFn: modelSettingsApi.get,
    enabled: Boolean(user),
    retry: false,
    staleTime: 30_000,
  })
  // 查询未完成时按可用处理，避免界面闪一下「未配置」
  return {
    ...query,
    configured: query.data?.configured ?? false,
    usable: query.data?.usable ?? true,
    // 站点不提供公共额度：只有配了自己的 Key 才允许发起模型调用
    ready: query.data?.configured ?? true,
  }
}
