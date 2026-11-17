import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Checkbox,
  Description,
  Input,
  Label,
  Link,
  Modal,
  TextField,
} from '@heroui/react'
import { KeyRound } from 'lucide-react'
import { useState } from 'react'

import { modelSettingsApi, type ModelSettings } from '@/api/modelSettings'
import { MODEL_SETTINGS_KEY, useModelSettings } from '@/hooks/useModelSettings'
import { errorMessage } from '@/hooks/useAuth'

const CONSOLE_URL = 'https://bailian.console.aliyun.com/'

const MODEL_FIELDS = [
  { name: 'planner_model', label: '规划模型', hint: '把一句话拆成修图步骤' },
  { name: 'text_to_image_model', label: '文生图模型', hint: '从零生成候选图' },
  { name: 'image_edit_model', label: '图片编辑模型', hint: '换背景、扩图、局部改图' },
] as const

type ModelNames = Record<(typeof MODEL_FIELDS)[number]['name'], string>

/**
 * 模型设置弹窗：Key 与模型名按账号保存，调用费用由用户自己的百炼账户承担。
 */
export default function ModelSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data, isPending, isError, error, refetch } = useModelSettings()

  return (
    <Modal.Backdrop isOpen={open} onOpenChange={onOpenChange}>
      <Modal.Container size="md" scroll="inside">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Icon className="bg-accent-soft text-accent-soft-foreground">
              <KeyRound className="size-5" aria-hidden />
            </Modal.Icon>
            <Modal.Heading>模型设置</Modal.Heading>
          </Modal.Header>

          {isPending && (
            <Modal.Body>
              <p className="text-muted text-sm">正在读取设置…</p>
            </Modal.Body>
          )}

          {!isPending && (isError || !data) && (
            <Modal.Body>
              <p role="alert" className="text-danger text-sm">
                {errorMessage(error)}
              </p>
              <Button variant="secondary" className="mt-4" onPress={() => void refetch()}>
                重试
              </Button>
            </Modal.Body>
          )}

          {!isPending && data && (
            <SettingsForm
              key={`${data.configured}-${data.key_hint ?? ''}-${data.planner_model ?? ''}`}
              settings={data}
              onClose={() => onOpenChange(false)}
            />
          )}
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  )
}

function SettingsForm({ settings, onClose }: { settings: ModelSettings; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [apiKey, setApiKey] = useState('')
  const [verify, setVerify] = useState(true)
  const [error, setError] = useState('')
  const [models, setModels] = useState<ModelNames>({
    planner_model: settings.planner_model ?? settings.defaults.planner_model,
    text_to_image_model: settings.text_to_image_model ?? settings.defaults.text_to_image_model,
    image_edit_model: settings.image_edit_model ?? settings.defaults.image_edit_model,
  })

  const save = useMutation({
    mutationFn: () =>
      modelSettingsApi.save({
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        planner_model: models.planner_model.trim(),
        text_to_image_model: models.text_to_image_model.trim(),
        image_edit_model: models.image_edit_model.trim(),
        verify,
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(MODEL_SETTINGS_KEY, next)
      onClose()
    },
    onError: (cause) => setError(errorMessage(cause)),
  })

  const remove = useMutation({
    mutationFn: () => modelSettingsApi.remove(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MODEL_SETTINGS_KEY })
      onClose()
    },
    onError: (cause) => setError(errorMessage(cause)),
  })

  const pending = save.isPending || remove.isPending
  const missingKey = !settings.configured && !apiKey.trim()
  const invalidModels = Object.values(models).some((value) => !value.trim())

  return (
    <>
      <Modal.Body className="flex flex-col gap-4">
        <p className="text-muted text-sm leading-relaxed">
          生成与编辑使用你自己的阿里云百炼（DashScope）API Key，费用由你的百炼账户承担；处理时会把图片和修图指令发送到阿里云。
        </p>

        <TextField isDisabled={pending}>
          <Label>DashScope API Key</Label>
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              settings.configured
                ? `已保存 ${settings.key_hint ?? ''}，留空保持不变`
                : '粘贴你的 API Key'
            }
          />
          <Description>
            <Link href={CONSOLE_URL} target="_blank" rel="noreferrer noopener">
              去百炼控制台创建 API Key
            </Link>
          </Description>
        </TextField>

        {MODEL_FIELDS.map((field) => (
          <TextField key={field.name} isDisabled={pending}>
            <Label>{field.label}</Label>
            <Input
              value={models[field.name]}
              maxLength={128}
              spellCheck={false}
              onChange={(event) =>
                setModels((current) => ({ ...current, [field.name]: event.target.value }))
              }
            />
            <Description>{field.hint}</Description>
          </TextField>
        ))}

        <Checkbox isSelected={verify} onChange={setVerify} isDisabled={pending}>
          <Checkbox.Content>
            <Checkbox.Control>
              <Checkbox.Indicator />
            </Checkbox.Control>
            保存前验证 Key
          </Checkbox.Content>
          <Description>
            会用所填规划模型发送一次极短请求，可能产生极少费用；验证失败不会覆盖原配置。
          </Description>
        </Checkbox>

        {error && (
          <p role="alert" className="text-danger text-sm">
            {error}
          </p>
        )}
      </Modal.Body>

      <Modal.Footer>
        {settings.configured && (
          <Button
            variant="danger-soft"
            className="mr-auto"
            isDisabled={pending}
            onPress={() => {
              if (!window.confirm('删除模型配置？已有图片和编辑历史不会删除。')) return
              setError('')
              remove.mutate()
            }}
          >
            删除配置
          </Button>
        )}
        <Button variant="tertiary" isDisabled={pending} onPress={onClose}>
          取消
        </Button>
        <Button
          variant="primary"
          isDisabled={pending || missingKey || invalidModels}
          onPress={() => {
            setError('')
            save.mutate()
          }}
        >
          {pending ? '保存中…' : apiKey.trim() && verify ? '验证并保存' : '保存'}
        </Button>
      </Modal.Footer>
    </>
  )
}
