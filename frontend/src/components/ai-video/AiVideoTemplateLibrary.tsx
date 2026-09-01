import { Alert, Button, Empty, Input, Modal, Popconfirm, Segmented, Select, Space, Tabs, Tag, Typography } from 'antd'
import { CheckCircleFilled, DeleteOutlined, SafetyOutlined, ThunderboltOutlined, UploadOutlined } from '@ant-design/icons'
import { CollabEntry } from '../collab/CollabEntry'
import TemplatePreview from './TemplatePreview'
import type { ReferenceImage, VideoGenerationTemplate } from '../../api/types'
import { TEMPLATE_PREVIEWS, templateAssetUrl, templateReferenceCount } from '../../pages/aiVideoUtils'

const { Title, Text } = Typography

export interface AiVideoTemplateLibraryProps {
  [key: string]: any
}

/** AI 视频模板库及模板套用表单；页面状态通过显式 props 注入。 */
export default function AiVideoTemplateLibrary(props: AiVideoTemplateLibraryProps) {
  const {
    projectId, navigate, openAdvancedWorkbench, setDrawerOpen, activeTab, setActiveTab,
    templateScopeFilter, setTemplateScopeFilter, displayTemplates, generationMode, selectedTemplateId,
    handleSelectTemplate, openTemplateApply, deletingTemplateId, handleDeleteTemplate,
    templateToApply, templateApplyOpen, setTemplateApplyOpen, confirmTemplateApply, templateApplyMode,
    usingOriginalTemplateFrames, originalTemplateReferenceIds, setApplyReferenceIds, refImages,
    applyReferenceIds, setApplyFirstFrameId, applyFirstFrameId, setApplyLastFrameId, applyLastFrameId,
    applySubject, setApplySubject, applyScene, setApplyScene,
  } = props
  const templateList = displayTemplates as VideoGenerationTemplate[]
  const referenceImages = refImages as ReferenceImage[]

  return (
<>
      {/* ============ 右侧：视频模板素材库 ============ */}
      <div className="ai-video-library">
        {/* 1. 标题区 */}
        <div className="av-lib-header">
          <div style={{ minWidth: 0 }}>
            <div className="av-lib-eyebrow">AI VIDEO STUDIO</div>
            <Title level={3} className="av-lib-title">专业视频渲染引擎</Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              选择模板一键套用，或自定义提示词生成投标演示视频
            </Text>
          </div>
          <div className="av-lib-actions">
            {projectId && <CollabEntry projectId={projectId} targetType="project" label="协作" />}
            <Button icon={<SafetyOutlined />} onClick={openAdvancedWorkbench}>高级提示词工程</Button>
            <Button onClick={() => setDrawerOpen(true)}>生成历史</Button>
            <Button type="primary" icon={<UploadOutlined />} onClick={() => navigate(`/project/${projectId}/ai-video/templates/new`)}>从视频创建模板</Button>
          </div>
        </div>

        {/* 2. 分类与范围 */}
        <div className="av-lib-toolbar">
          <Tabs
            className="av-lib-tabs"
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: 'exterior',
                label: <span style={{ fontWeight: 600 }}>建筑外景运镜</span>,
              },
              {
                key: 'creative',
                label: (
                  <span style={{ fontWeight: 600 }}>
                    首尾帧 / 多参考图·创意运镜
                    <Tag color="volcano" style={{ fontSize: 10, lineHeight: '16px', marginInlineStart: 6 }}>
                      NEW
                    </Tag>
                  </span>
                ),
              },
            ]}
          />
          <Segmented
            size="small"
            className="av-lib-scope"
            value={templateScopeFilter}
            onChange={(value) => setTemplateScopeFilter(value as 'all' | 'personal' | 'organization')}
            options={[
              { label: '全部可用', value: 'all' },
              { label: '我的模板', value: 'personal' },
              { label: '企业模板', value: 'organization' },
            ]}
          />
        </div>

        {/* 3. 模板网格 */}
        <div className="av-lib-scroll">
          {displayTemplates.length === 0 && <Empty description="当前分类暂无模板" style={{ marginTop: 60 }} />}
          <div className="av-tpl-grid">
            {templateList.map((t) => {
              const preview = TEMPLATE_PREVIEWS[t.name] || {}
              const isFL = (t.applicable_modes || []).includes('first_last_frame_video')
              const isMulti = (t.applicable_modes || []).includes('multi_reference_video') || (generationMode === 'multi_reference_video' && (t.applicable_modes || []).includes('image_to_video'))
              const selected = selectedTemplateId === t.id
              const backendPreview = {
                video: templateAssetUrl(t.preview_file_key) || preview.video,
                first: templateAssetUrl(t.first_frame_file_key || t.cover_file_key) || preview.first,
                last: templateAssetUrl(t.last_frame_file_key) || preview.last,
              }
              return (
                <div
                  key={t.id}
                  className={`av-tpl-card${selected ? ' is-selected' : ''}`}
                  onClick={() => handleSelectTemplate(t)}
                >
                  {selected && <span className="av-tpl-check"><CheckCircleFilled /></span>}
                  <TemplatePreview t={t} preview={backendPreview} isFL={isFL} />
                  <div className="av-tpl-body">
                    <div className="av-tpl-topline">
                      <span className="av-tpl-name" title={t.name}>{t.name}</span>
                      {isFL && <Tag color="purple" style={{ fontSize: 10, marginInlineEnd: 0, flexShrink: 0 }}>首尾帧</Tag>}
                      {isMulti && <Tag color="cyan" style={{ fontSize: 10, marginInlineEnd: 0, flexShrink: 0 }}>多参考图</Tag>}
                    </div>
                    <p className="av-tpl-desc" title={t.description || ''}>{t.description}</p>
                    <div className="av-tpl-meta">
                      {(t.category || t.prompt_recipe?.category) && <span className="av-tpl-chip">{t.category || t.prompt_recipe?.category}</span>}
                      {t.recommended_camera_motion && <span className="av-tpl-chip">{t.recommended_camera_motion}</span>}
                      <span className="av-tpl-chip">{t.recommended_duration}s</span>
                      <span className="av-tpl-chip is-scope">
                        {t.is_system ? '系统模板' : t.scope === 'personal' ? '个人模板' : '企业模板'}
                      </span>
                      {(t.tags || []).slice(0, 2).map((tag) => <span key={tag} className="av-tpl-chip">{tag}</span>)}
                    </div>
                    <div className="av-tpl-foot">
                      <Button
                        className="av-tpl-use"
                        type={selected ? 'primary' : 'default'}
                        size="small"
                        icon={<ThunderboltOutlined />}
                        onClick={(event) => {
                          event.stopPropagation()
                          openTemplateApply(t)
                        }}
                      >
                        使用此模板
                      </Button>
                      {!t.is_system && (
                        <Popconfirm
                          title="删除这个模板？"
                          description="删除后模板将从模板库移除，已生成的视频和历史任务不会受影响。"
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => void handleDeleteTemplate(t)}
                        >
                          <Button
                            className="av-tpl-delete"
                            danger
                            size="small"
                            icon={<DeleteOutlined />}
                            loading={deletingTemplateId === t.id}
                            onClick={(event) => event.stopPropagation()}
                          />
                        </Popconfirm>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <Modal
        title={templateToApply ? `套用模板：${templateToApply.name}` : '套用模板'}
        open={templateApplyOpen}
        onCancel={() => setTemplateApplyOpen(false)}
        onOk={confirmTemplateApply}
        okText="套用模板"
        width={680}
      >
        {templateToApply && (
          <div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 14 }}>
              多图施工模板的关键帧顺序就是动作本体。可直接使用样片关键帧复刻节奏，也可以替换为当前项目同阶段图片。
            </Text>
            {templateApplyMode === 'multi_reference_video' && (
              <Alert
                type={usingOriginalTemplateFrames ? 'success' : 'warning'}
                showIcon
                style={{ marginBottom: 14 }}
                message={usingOriginalTemplateFrames ? '已带入样片原始施工关键帧（推荐）' : '当前正在使用替换图片'}
                description={usingOriginalTemplateFrames
                  ? `Seedance 将按 ${originalTemplateReferenceIds.length} 张关键帧的顺序理解施工节奏。`
                  : '替换图片必须逐张对应模板中的施工阶段；只放首尾两张会退化为 AI 自由补间。'}
                action={originalTemplateReferenceIds.length === templateReferenceCount(templateToApply)
                  ? <Button size="small" onClick={() => setApplyReferenceIds(originalTemplateReferenceIds)}>恢复样片关键帧</Button>
                  : undefined}
              />
            )}
            <div style={{ display: 'grid', gridTemplateColumns: templateApplyMode === 'first_last_frame_video' ? '1fr 1fr' : '1fr', gap: 14 }}>
              {templateApplyMode === 'multi_reference_video' ? (
                <div>
                  <Text strong style={{ fontSize: 12 }}>施工关键帧（按实际发生顺序）</Text>
                  <Select
                    mode="multiple"
                    maxCount={templateReferenceCount(templateToApply)}
                    showSearch
                    optionFilterProp="label"
                    value={applyReferenceIds}
                    placeholder={`按施工顺序选择 ${templateReferenceCount(templateToApply)} 张关键帧`}
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={setApplyReferenceIds}
                    options={referenceImages.map((image) => ({ label: image.name, value: image.id, image }))}
                    optionRender={(option) => {
                      const image = (option.data as { image?: ReferenceImage }).image
                      return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                    }}
                  />
                </div>
              ) : (
                <div>
                  <Text strong style={{ fontSize: 12 }}>新的建筑首帧</Text>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    value={applyFirstFrameId || undefined}
                    placeholder="选择素材库中的首帧图片"
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={setApplyFirstFrameId}
                    options={referenceImages.map((image) => ({ label: image.name, value: image.id, image }))}
                    optionRender={(option) => {
                      const image = (option.data as { image?: ReferenceImage }).image
                      return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                    }}
                  />
                </div>
              )}
              {templateApplyMode === 'first_last_frame_video' && (
                <div>
                  <Text strong style={{ fontSize: 12 }}>新的建筑尾帧</Text>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    value={applyLastFrameId || undefined}
                    placeholder="选择素材库中的尾帧图片"
                    style={{ width: '100%', marginTop: 6 }}
                    onChange={setApplyLastFrameId}
                    options={referenceImages.map((image) => ({ label: image.name, value: image.id, image }))}
                    optionRender={(option) => {
                      const image = (option.data as { image?: ReferenceImage }).image
                      return <Space><img src={image?.url} alt="" style={{ width: 44, height: 32, objectFit: 'cover', borderRadius: 4 }} /><span>{option.label}</span></Space>
                    }}
                  />
                </div>
              )}
            </div>
            <div style={{ height: 1, background: '#eef1f6', margin: '18px 0 14px' }} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <div>
                <Text strong style={{ fontSize: 12 }}>建筑主体描述（可选）</Text>
                <Input.TextArea
                  rows={3}
                  value={applySubject}
                  onChange={(event) => setApplySubject(event.target.value)}
                  placeholder="例如：当前项目的白色幕墙办公楼"
                  style={{ marginTop: 6 }}
                />
              </div>
              <div>
                <Text strong style={{ fontSize: 12 }}>场景与环境描述（可选）</Text>
                <Input.TextArea
                  rows={3}
                  value={applyScene}
                  onChange={(event) => setApplyScene(event.target.value)}
                  placeholder="例如：阴天，前景保留施工道路和绿化"
                  style={{ marginTop: 6 }}
                />
              </div>
            </div>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 16 }}
              message={`将自动带入：${templateToApply.recommended_duration}s · ${templateToApply.recommended_aspect_ratio} · ${templateToApply.recommended_resolution}`}
              description="套用后仍可以在左侧编辑提示词和高级参数，再提交真实 Provider 生成。"
            />
          </div>
        )}
      </Modal>


</>
  )
}
