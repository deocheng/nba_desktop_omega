# 星环图新版实现概览

## 完成内容
按 2026-08-03 提供的设计文档、演示代码与 30 队配色表，完成了新版「星环图」生成器，并生成了 6 支球队 2026 赛季的 chart。

## 关键改动
- `team_shot_radial.py` 完全重写：
  - **全局比例动态分配**：300° 弧按球员总出手比例切分，不再固定 45° 槽。
  - **跨球员横向全比例**：同一距离环内， wedge 角度按该球员真实出手占环内最大者比例绘制。
  - **球队主题配色**：30 队 primary/secondary 色板仅用于 UI 框架；数据四色（蓝/青/橙/黄）保持统一。
  - **四种背景模式**：`portrait`（本地黑白头像，默认）、`logo`（本地队徽）、`heatmap`（FG% 热力）、`grid`（极简网格）。
  - **本地资源接入**：头像经 `player_id_bridge` 映射到 BBRef ID 后从 `/Volumes/12T/NBA/headshots/` base64 嵌入；队徽从 `NBAlogo/*.svg` 预转为透明 PNG 后嵌入。
  - 保留白字、无加粗、阴影增强可读性；浅色主色球队自动 fallback 到深色文字。
- 预生成：`NBAlogo/*.png`（30 队透明底队徽）。

## 交付文件
- `star_ring_{OKC,SAS,LAL,HOU,CLE,DET}_2026.png`：默认 portrait（黑白头像背景）。
- `star_ring_{OKC,SAS,LAL,HOU,CLE,DET}_2026_logo.png`：队徽背景模式。

## 后续
- 未写入 skill（尊重此前「视觉/实验性改动不进 skill」的要求）。
- 如需要，可继续生成 heatmap/grid 模式的 6 队版本，或调整头像/队徽透明度。
