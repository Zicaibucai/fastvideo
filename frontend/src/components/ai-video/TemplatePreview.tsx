import { ArrowRightOutlined, PlayCircleOutlined } from '@ant-design/icons'
import type { VideoGenerationTemplate } from '../../api/types'

interface TemplatePreviewProps {
  t: VideoGenerationTemplate
  preview: { video?: string; first?: string; last?: string }
  isFL: boolean
}

/** 模板卡片封面：视频预览、首尾帧缩略图和时长标识。 */
export default function TemplatePreview({ t, preview, isFL }: TemplatePreviewProps) {
  return (
    <div className="av-tpl-cover">
      {preview.video ? (
        <video
          className="av-tpl-cover-media"
          src={preview.video}
          poster={preview.first}
          muted
          loop
          playsInline
          preload="metadata"
          onMouseEnter={(e) => e.currentTarget.play().catch(() => {})}
          onMouseLeave={(e) => { const v = e.currentTarget; v.pause(); v.currentTime = 0 }}
        />
      ) : preview.first ? (
        <img className="av-tpl-cover-media" src={preview.first} alt={t.name} />
      ) : (
        <div className="av-tpl-cover-empty">
          <PlayCircleOutlined style={{ fontSize: 34, color: '#a5b0c7' }} />
          <span style={{ fontSize: 12 }}>预览视频待补充</span>
          {t.recommended_camera_motion && <span style={{ fontSize: 11, color: '#a5adbd' }}>{t.recommended_camera_motion}</span>}
        </div>
      )}
      <div className="av-tpl-thumbs">
        <Thumb url={preview.first} label="首" />
        {isFL && <ArrowRightOutlined style={{ color: '#fff', fontSize: 12, marginBottom: 9, textShadow: '0 1px 3px rgba(0,0,0,0.5)' }} />}
        {isFL && <Thumb url={preview.last} label="尾" />}
      </div>
      <span className="av-tpl-duration">{t.recommended_duration}s</span>
    </div>
  )
}

function Thumb({ url, label }: { url?: string; label: string }) {
  return (
    <div className="av-tpl-thumb">
      {url ? <img src={url} alt={label} /> : <span className="av-tpl-thumb-placeholder">{label}</span>}
    </div>
  )
}
