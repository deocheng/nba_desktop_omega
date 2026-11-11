#!/usr/bin/env python3
"""把姿态缓存（yolo11n-pose）转成关系层需要的 `players.json` 契约。

第 5 层 `segment_relations.py` 只吃 `players.json`，而本轮全帧姿态已经缓存在
`action_work/seg_hi/pose_hi_cache.json`（435 帧，key = 帧序号的字符串形式）。
本脚本做两件事：补几何量、补帧时间戳，不重跑模型。

契约（与 segment_relations.py 的读取代码逐一对应）：
    {"frames": [{"idx": int, "t": float,
                 "players": [{"box":[x1,y1,x2,y2], "conf": float,
                              "foot":[fx,fy], "h": float, "sel_id": "p1"}]}]}

🔴 两个必须如实标注的点：
  1. **不写 `pid` 字段**。pid→球员名映射在本轮被判定为未解决（87 帧出现 80 个 pid，
     相邻帧 Jaccard 中位 0.538），所以标签退化为帧内序号 `sel_id`——
     这意味着**关系三元组的 s/o 只是帧内位置标签，不是球员身份**，
     下游不得把 `p3` 当同一个人跨帧追踪。
  2. `foot` 用框底边中点，`h` 用框高，二者都是纯几何量，无模型假设。

用法：
  build_players_from_pose.py <pose_cache.json> <frames.json> <out.json>
"""
from __future__ import annotations

import argparse
import json


def _frame_rec(cache: dict, idx: int):
    """取某一帧的姿态记录，兼容两种缓存布局。

    🔴 曾经的 bug：脚本按**扁平 key**（`cache[str(idx)]`）读，而 `pose_keypoints.py` 实际
    落盘的是 `{"frames": {idx_str: {...}}, "meta": ...}` 嵌套结构 ⇒ `cache.get(str(idx))`
    恒为 None ⇒ 静默产出**全空**的 players.json（每帧 players=[]），下游关系层会直接输出
    空三元组却看不出错。这里显式兼容两种布局。
    """
    for box in (cache.get("frames"), cache):
        if isinstance(box, dict):
            rec = box.get(str(idx))
            if rec is None:
                rec = box.get(idx)
            if rec is not None:
                return rec
    return None


def _persons(rec: dict) -> list[dict]:
    """兼容 `boxes`（旧，元素含 box/conf）与 `persons`（新，元素含 box/conf/kpt）。"""
    for k in ("persons", "boxes"):
        v = rec.get(k)
        if isinstance(v, list):
            return [e for e in v if isinstance(e, dict) and "box" in e and "conf" in e]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pose_cache")
    ap.add_argument("frames_json")
    ap.add_argument("out")
    a = ap.parse_args()

    cache = json.load(open(a.pose_cache))
    frames = json.load(open(a.frames_json))

    out_frames = []
    for f in frames:
        idx = f["idx"]
        rec = _frame_rec(cache, idx)
        if rec is None:
            out_frames.append({"idx": idx, "t": f["t"], "players": []})
            continue
        pls = []
        # 按框面积降序，让 sel_id 在帧内稳定一点（近景球员优先拿到小序号）
        boxes = sorted(_persons(rec),
                       key=lambda b: -((b["box"][2] - b["box"][0]) *
                                       (b["box"][3] - b["box"][1])))
        for i, b in enumerate(boxes):
            x1, y1, x2, y2 = [float(v) for v in b["box"]]
            pls.append({
                "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                "conf": round(float(b["conf"]), 4),
                "foot": [round((x1 + x2) / 2.0, 1), round(y2, 1)],
                "h": round(y2 - y1, 1),
                "sel_id": f"p{i + 1}",
            })
        out_frames.append({"idx": idx, "t": f["t"], "players": pls})

    n_pl = sum(len(x["players"]) for x in out_frames)
    with open(a.out, "w") as fp:
        json.dump({"frames": out_frames, "note": "labels are per-frame sel_id, NOT player identity"},
                  fp, ensure_ascii=False, indent=1)
    n_empty = sum(1 for x in out_frames if not x["players"])
    print(f"[out] {a.out}")
    print(f"[stat] 帧 {len(out_frames)}  球员框合计 {n_pl}  "
          f"均 {n_pl / max(len(out_frames), 1):.2f} 人/帧  空帧 {n_empty}")
    # 自检：空帧率过高说明缓存布局又对不上了（历史上曾静默产出全空文件）
    if n_pl == 0 or n_empty > len(out_frames) * 0.2:
        raise SystemExit(f"❌ 自检失败：{n_empty}/{len(out_frames)} 帧为空（合计 {n_pl} 框）"
                         " —— 姿态缓存布局与读取代码不匹配，请检查 _frame_rec/_persons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
