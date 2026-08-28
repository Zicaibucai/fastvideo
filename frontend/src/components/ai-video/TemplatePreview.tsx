import { useState } from 'react'
import { Tag, Typography } from 'antd'
import { ArrowRightOutlined, PlayCircleOutlined } from '@ant-design/icons'
import type { VideoGenerationTemplate } from '../../api/types'

const { Text } = Typography

interface TemplatePreviewProps {
  t: VideoGenerationTemplate
  preview: { video?: string; first?: string; last?: string }
  isFL: boolean
}

/** 模板卡片预览：视频占位、首尾帧缩略图和时长标识。 */
export default function TemplatePreview({ t, preview, isFL }: TemplatePreviewProps) {
  return (
    <div style={{ position: 'relative', height: 160, background: '#F0F4FA', overflow: 'hidden' }}>
      {preview.video ? (
        <video src={preview.video} poster={preview.first} style={{ width: '100%', height: '100%', objectFit: 'cover' }} muted loop playsInline preload="metadata"
          onMouseEnter={(e) => e.currentTarget.play().catch(() => {})}
          onMouseLeave={(e) => { const v = e.currentTarget; v.pause(); v.currentTime = 0 }} />
      ) : (
        <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6, color: '#8b93a7' }}>
          <PlayCircleOutlined style={{ fontSize: 36, color: '#a5b0c7' }} />
          <Text style={{ fontSize: 12, color: '#8b93a7' }}>预览视频待补充</Text>
          <Text style={{ fontSize: 11, color: '#a5adbd' }}>{t.recommended_camera_motion || ''}</Text>
        </div>
      )}
      <div style={{ position: 'absolute', left: 8, bottom: 8, display: 'flex', alignItems: 'flex-end', gap: 5 }}>
        <Thumb url={preview.first} label="首" origin="left bottom" />
        {isFL && <ArrowRightOutlined style={{ color: '#fff', fontSize: 12, marginBottom: 9 }} />}
        {isFL && <Thumb url={preview.last} label="尾" origin="right bottom" />}
      </div>
      <Tag style={{ position: 'absolute', right: 8, top: 8, fontSize: 11 }}>{t.recommended_duration}s</Tag>
    </div>
  )
}

function Thumb({ url, label, origin = 'left bottom' }: { url?: string; label: string; origin?: string }) {
  const [hover, setHover] = useState(false)
  if (!url) return <div style={{ width: 36, height: 36, borderRadius: 6, border: '2px solid #fff', background: 'rgba(30, 41, 59, 0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 11, fontWeight: 600, flexShrink: 0 }}>{label}</div>
  return <div onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} style={{ width: 36, height: 36, borderRadius: 6, border: '2px solid #fff', boxShadow: hover ? '0 6px 20px rgba(0,0,0,0.45)' : '0 1px 4px rgba(0,0,0,0.2)', overflow: 'hidden', position: 'relative', zIndex: hover ? 10 : 1, transform: hover ? 'scale(2.4)' : 'scale(1)', transformOrigin: origin, transition: 'transform .18s ease, boxShadow .18s ease', cursor: 'zoom-in', flexShrink: 0 }}>
    <img src={url} alt={label} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
  </div>
}
