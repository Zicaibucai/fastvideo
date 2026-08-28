import { useEffect, useState } from 'react'
import { Select, Tag } from 'antd'
import { collabApi } from '../../api'
import type { ProjectMember } from '../../api/types'
import { ROLE_LABELS } from '../../hooks/useProjectPermissions'

/** 项目成员选择器（只列出 active 成员） */
export default function MemberSelect({
  projectId,
  value,
  onChange,
  placeholder = '选择项目成员',
  allowClear = true,
  roleFilter,
  style,
}: {
  projectId: string
  value?: string
  onChange?: (value: string | undefined) => void
  placeholder?: string
  allowClear?: boolean
  roleFilter?: (member: ProjectMember) => boolean
  style?: React.CSSProperties
}) {
  const [members, setMembers] = useState<ProjectMember[]>([])

  useEffect(() => {
    collabApi
      .members(projectId)
      .then((resp) => setMembers(resp.data.filter((m) => m.status === 'active')))
      .catch(() => setMembers([]))
  }, [projectId])

  const options = members
    .filter((m) => (roleFilter ? roleFilter(m) : true))
    .map((m) => ({
      value: m.user_id,
      label: (
        <span>
          {m.full_name || m.username || m.email}{' '}
          <Tag style={{ marginLeft: 4 }}>{ROLE_LABELS[m.role] ?? m.role}</Tag>
        </span>
      ),
    }))

  return (
    <Select
      showSearch
      optionFilterProp="label"
      value={value}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      allowClear={allowClear}
      style={{ minWidth: 220, ...style }}
    />
  )
}
