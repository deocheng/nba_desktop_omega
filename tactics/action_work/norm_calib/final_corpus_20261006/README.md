# 定稿训练语料包 · final_corpus_20261006

- 状态：SIGNED(老程2026-10-06目视签核;merged=game20_KEEP8+gray_KEEP7)
- 来源轨迹：smooth_tracks_merged_v2
- 窗口裁剪：--skip-start=8（剔除开场包装帧）
- 排除清单（老程裁定，最高权威）：[2, 3, 5, 9, 12, 16, 19, 27, 31, 33]
- 命名：ASR gt_models（检测原语仅作结构佐证）
- 球质量：单列报告、不进顺畅分；ball_real_rate<0.30 标 ball_unreliable（见 labels/_quality_report.json）
- 按 ep 分组防泄漏：train 13 条 / val 2 条（cv_folds.json）

## 结构
frames/<pick_id>/f*.jpg   软链，仅签核通过窗口的帧
tracks/<pick_id>.json     球员逐帧坐标 + 球 xy/conf/pred
labels/asr_gt_models.json 战术名（ASR 真值）
labels/smooth_verdict.json 老程裁定
labels/_quality_report.json ID 碎片化 + 球质量
manifests/train.jsonl | val.jsonl | cv_folds.json

## 已知局限（交付训练前须知）
- ID 碎片化虚高：track_id 数 >> 每帧可见人数（见 _quality_report），所有按 ID 聚合指标带系统性虚高。
- 球检测不可靠：多数学球真检出率<30%，球轨迹仅参考。
- 顺畅分只量球员协同移动，内容级判断靠老程目视。
