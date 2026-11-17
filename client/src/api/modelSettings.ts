import { api } from '@/api/client'

export type ModelSettings = {
  /** 当前账号是否已保存自己的 Key。 */
  configured: boolean
  /** 未配置时是否启用平台 Key 兜底，公网部署默认关闭。 */
  platform_fallback: boolean
  /** 当前是否可以调用模型。 */
  usable: boolean
  /** 已保存 Key 的尾号提示。 */
  key_hint: string | null
  /** 已保存的规划模型。 */
  planner_model: string | null
  /** 已保存的文生图模型。 */
  text_to_image_model: string | null
  /** 已保存的图片编辑模型。 */
  image_edit_model: string | null
  /** 表单预填用的默认模型名。 */
  defaults: {
    /** 对话规划模型。 */
    planner_model: string
    /** 文生图模型。 */
    text_to_image_model: string
    /** 图片编辑模型。 */
    image_edit_model: string
  }
}

export type ModelSettingsInput = {
  /** 新的 Key，留空表示沿用已保存的 Key。 */
  api_key?: string
  /** 对话规划模型。 */
  planner_model: string
  /** 文生图模型。 */
  text_to_image_model: string
  /** 图片编辑模型。 */
  image_edit_model: string
  /** 保存前是否验证 Key。 */
  verify: boolean
}

export const modelSettingsApi = {
  /**
   * 读取当前账号的脱敏模型设置。
   *
   * @returns
   */
  get: () => api.get<ModelSettings>('/model-settings'),
  /**
   * 保存模型设置，Key 只随本次请求提交。
   *
   * @param input 待保存的 Key 与模型名。
   * @returns
   */
  save: (input: ModelSettingsInput) => api.put<ModelSettings>('/model-settings', input),
  /**
   * 删除当前账号的模型配置。
   *
   * @returns
   */
  remove: () => api.delete<void>('/model-settings'),
}
