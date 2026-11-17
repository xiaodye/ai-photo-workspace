import { create } from 'zustand'

type ModelSettingsUi = {
  /** 模型设置弹窗是否打开。 */
  open: boolean
  /** 打开或关闭模型设置弹窗。 */
  setOpen: (open: boolean) => void
}

/** 模型设置弹窗由工作台外壳统一渲染，任意入口只切换开关。 */
export const useModelSettingsUi = create<ModelSettingsUi>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))
