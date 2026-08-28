import { Card, Divider, Tag, Typography } from 'antd'
import { recipeCamera, recipeItems, recipeTimeline } from '../../features/video-template/recipe'

const { Text } = Typography

/** 展示 AI 提炼出的结构化配方；编辑动作仍由父级表单负责。 */
export default function TemplateRecipeOverview({ recipe }: { recipe: Record<string, any> }) {
  const camera = recipeCamera(recipe.camera)
  const timeline = recipeTimeline(recipe.timeline)
  const preserve = recipeItems(recipe.preserve, ['锁定建筑主体数量、体量、轮廓、层数', '保持道路、主入口和主要构件位置', '保持首尾帧构图和空间关系'])
  const allowChange = recipeItems(recipe.allow_change, ['轻微光影变化', '树木、云层、人物和车辆的自然微动'])
  const negative = recipeItems(recipe.negative || recipe.negative_prompt, ['变形', '模糊', '结构错位', '透视错误'])
  const recommended = recipe.recommended && typeof recipe.recommended === 'object' ? recipe.recommended : {}

  return (
    <Card size="small" title="AI 生成的结构化配方" className="video-template-recipe-card">
      <div className="video-template-recipe-content">
        <div className="video-template-recipe-summary">
          <Tag color="blue">{recipe.category || '建筑外景运镜'}</Tag>
          {recipeItems(recipe.generation_modes).map((mode) => <Tag key={mode}>{mode}</Tag>)}
          <Text type="secondary">模型已将镜头规则拆成可编辑字段</Text>
        </div>

        <section className="video-template-recipe-section">
          <div className="video-template-recipe-section-title"><Text strong>运镜类型</Text><Text type="secondary">镜头路径与节奏</Text></div>
          <div className="video-template-camera-grid">
            {[['类型', camera.type], ['速度', camera.speed], ['方向', camera.direction], ['路径', camera.path], ['强度', camera.intensity]].map(([label, value]) => <div className="video-template-camera-item" key={label}><Text type="secondary">{label}</Text><Text strong>{String(value || '-')}</Text></div>)}
          </div>
        </section>

        <section className="video-template-recipe-section">
          <div className="video-template-recipe-section-title"><Text strong>时间轴</Text><Text type="secondary">0%-100% 镜头阶段</Text></div>
          <div className="video-template-recipe-timeline">
            {timeline.map((item, index) => {
              const from = Math.max(0, Math.min(100, Number(item.from) || 0))
              const to = Math.max(from, Math.min(100, Number(item.to) || 0))
              return <div className="video-template-recipe-timeline-row" key={`${item.from}-${item.to}-${index}`}>
                <div className="video-template-recipe-timeline-label"><Text strong>{from}%-{to}%</Text><Text>{item.instruction}</Text></div>
                <div className="video-template-recipe-timeline-track"><span style={{ marginLeft: `${from}%`, width: `${Math.max(5, to - from)}%` }} /></div>
              </div>
            })}
          </div>
        </section>

        <div className="video-template-recipe-list-grid">
          <section className="video-template-recipe-section">
            <div className="video-template-recipe-section-title"><Text strong>建筑保持项</Text><Text type="secondary">生成时锁定</Text></div>
            <div className="video-template-recipe-tags">{preserve.map((item) => <Tag color="green" key={item}>{item}</Tag>)}</div>
          </section>
          <section className="video-template-recipe-section">
            <div className="video-template-recipe-section-title"><Text strong>允许变化</Text><Text type="secondary">仅限自然微动</Text></div>
            <div className="video-template-recipe-tags">{allowChange.map((item) => <Tag key={item}>{item}</Tag>)}</div>
          </section>
        </div>

        <section className="video-template-recipe-section">
          <div className="video-template-recipe-section-title"><Text strong>负向提示词</Text><Text type="secondary">自动加入生成约束</Text></div>
          <div className="video-template-recipe-tags video-template-recipe-negative">{negative.map((item) => <Tag key={item}>{item}</Tag>)}</div>
        </section>

        <section className="video-template-recipe-section video-template-recommended-section">
          <div className="video-template-recipe-section-title"><Text strong>推荐参数</Text><Text type="secondary">试生成会按此配置提交</Text></div>
          <div className="video-template-recommended-grid">
            <div><Text type="secondary">时长</Text><Text strong>{String(recommended.duration || '5 秒')}</Text></div>
            <div><Text type="secondary">比例</Text><Text strong>{String(recommended.aspect_ratio || 'adaptive')}</Text></div>
            <div><Text type="secondary">分辨率</Text><Text strong>{String(recommended.resolution || '720p')}</Text></div>
          </div>
        </section>
      </div>
    </Card>
  )
}
