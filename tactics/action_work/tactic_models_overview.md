# 战术抽象模型总表（55 模型 / 覆盖 61 库条目）

> 来源：《NBA战术笔记》人声 ASR（A4.56）。语义来自人声；sequence/signature 为形式化约定（engine/tactic_abstraction_spec.md）。
> signature 仅含**可观察量**；匹配只出候选，裁定归老程。
> `tier`: basic=简单配合 / system=战术（**草案**）。`key_primitive`=判别原语（缺失则该模型出局）。`seq_dependent`=判别量依赖次序/重复，signature 未评估时降级。`confirm`=不可检但可文档化的确认项。

## pnr_1_5
- 名称: 1-5 pick and roll / 一五挡拆 / 1-5 PnR
- 库条目: 1-5 pick and roll
- tier: system
- 目的: 5 号大个给 1 号后卫做高位有球掩护，制造突破/顺下吃饼。
- 触发: 防守对掩护处理不果断，追防者落后半个身位。
- 原语: SCREEN.DOWN -> DRIVE -> ROLL
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/DOWN → ball_handler:DRIVE → screener:ROLL
- 判别信号: on_ball_screen; handler_penetration; roller_short_lag
- 与最像战术的区别: 参与掩护的是 1 号位与 5 号位（最高大的内线给控卫做有球掩护）。
- 来源: 第70期：智帅基德亲手指挥杀死比赛 “一五挡拆”

## zone_23
- 名称: 23联防 / 2-3 zone / 二三联防
- 库条目: 23联防
- 类别: defense
- tier: basic
- 判别原语(key): ZONE_23
- 目的: 用 2-3 区域联防（两上三下）限制突破/中距离，保护禁区。
- 触发: 对手外线投射不稳，需收缩护框。
- 原语: ZONE_23
- 序列: defense:ZONE_23
- 判别信号: no_man_marking; two_plus_three_rows
- 与最像战术的区别: 区域防守（非盯人），2 上 3 下。
- 来源: 第11期：凯尔特人用一招“exitscreen”完美破解热火队的“23联防”

## pick_and_pop
- 名称: 4 pop / 4pop / 挡拆外弹
- 库条目: 4 pop
- tier: system
- 判别原语(key): POP
- 目的: 挡拆后掩护人（4 号）不外切而是外弹到弧顶/侧翼三分。
- 触发: 防守大个沉退/收缩，外线出现空位。
- 原语: SCREEN.DOWN -> POP
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/DOWN → screener:POP
- 判别信号: screener_moves_away_from_rim
- 与最像战术的区别: 掩护人**外弹**（vs 顺下 ROLL）。
- 来源: 第1期：听说4POP战术是为凯文·杜兰特量身打造的？

## cut_45
- 名称: 45 cut / 45度切入 / 45度切入
- 库条目: 45 cut
- tier: basic
- 判别原语(key): CUT.45
- 目的: 侧翼 45 度无球球员切向篮下接球终结，为持球人撕开传球角度。
- 触发: 防守协防持球人而放空侧翼。
- 原语: CUT.45
- 序列: ball_handler:DRIVE → cutter:CUT/45
- 判别信号: cut_starts_at_45; offball_speed_spike_toward_rim
- 与最像战术的区别: 起点在**侧翼 45 度**（vs 底角切入/反跑）。
- 来源: 《世界杯战术笔记》Ep06：布里奇斯盘活内外连线的“45度切入”

## transition_flare
- 名称: 7秒进攻+无球掩护 / 7秒进攻 / early offense flare
- 库条目: 7秒进攻+无球掩护
- tier: system
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 抢下篮板后 7 秒内速攻，用远切掩护（flare）让射手接球出手。
- 触发: 防守退防未成型，注意力集中在持球人身上。
- 原语: TRANSITION -> SCREEN.FLARE -> CUT.FLARE -> SPOT_UP
- 序列: ball_handler:TRANSITION → screener:SCREEN/FLARE → shooter:CUT/FLARE → shooter:SPOT_UP
- 判别信号: possession_time_lt_7s; screen_behind_defender; shooter_ends_perimeter
- 与最像战术的区别: 转换速攻 + 远切掩护的组合。
- 来源: 第32期：“7秒进攻+无球掩护”现在的哈利伯顿比肩巅峰纳什？

## backdoor
- 名称: backdoor / 反跑 / 后门 / backdoor cut
- 库条目: backdoor
- tier: basic
- 判别原语(key): CUT.BACKDOOR
- 目的: 无球人假装接球突然反跑，直切篮下接高吊球。
- 触发: 防守抢前/上线紧逼（deny the catch）。
- 原语: CUT.BACKDOOR
- 序列: cutter:CUT/BACKDOOR
- 判别信号: trajectory_reversal; defender_high_side
- 与最像战术的区别: 反跑——方向**反转**指向篮筐。
- 来源: 第2期：马刺经典战术配合ZipperBackdoor

## cross_screen
- 名称: cross screen / crossscreen / 横掩护
- 库条目: cross screen
- tier: system
- 判别原语(key): SCREEN.CROSS
- 目的: 用横掩护（弱侧→强侧、横穿禁区）在低位制造接球/终结机会。
- 触发: 盯人/换防下，接球人借横掩护获得低位身位。
- 原语: SCREEN.CROSS
- 确认项(confirm): POST_UP
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/CROSS → receiver:POST_UP
- 判别信号: screener_traj_parallel_to_baseline; post_catch_low_block
- 与最像战术的区别: 掩护人**横向穿场**（轨迹平行底线）——区别于竖直方向的下/上掩护。
- 来源: 第24期：波波维奇一招“crossscreen”让文班亚马快速融入马刺体系

## pnr_curry_dray
- 名称: curry-dray pick and roll / 库追挡拆 / 库追 PnR
- 库条目: curry-dray pick and roll
- tier: system
- 目的: 库里-格林招牌挡拆：精英射手持球 + 策应型大个掩护，制造投篮/短顺下。
- 触发: 对手沉退或换防沟通失误。
- 原语: SCREEN.DOWN -> DRIVE -> SHORT_ROLL
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/DOWN → ball_handler:DRIVE
- 判别信号: on_ball_screen; shooter_handler
- 与最像战术的区别: 这是一条**实例化**（具名球员）战术，结构同 PnR，强调库里-格林组合。
- 来源: 第61期：麦克布朗打掉“库追挡拆”亲手为勇士王朝拉下帷幕

## cut_family
- 名称: cut / 切入 / 空切
- 库条目: cut
- tier: basic
- 判别原语(key): CUT
- 目的: 无球移动直接得分的终结方式总类（空切）。
- 触发: 防守注意力在球上，无球人获得向篮筐的空档。
- 原语: CUT
- 序列: cutter:CUT
- 判别信号: offball_speed_spike_toward_rim
- 与最像战术的区别: 无球终结的总类（含反跑/正面/底线/45度/借掩护切入等子类）。
- 来源: 第35期：看似越简单的“切入”配合竟可以演变出这么多的战术？

## delay
- 名称: delay / 延迟进攻 / delay pin
- 库条目: delay
- tier: system
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 延迟进攻：大个在弧顶持球，队友两侧下掩护后无球跑动，寻找错位或手递手机会。
- 触发: 需要半场组织，用无球跑动制造机会。
- 原语: SCREEN.DOWN -> PASS -> HANDOFF
- 序列: big:DRIBBLE_ENTRY → screener:SCREEN/DOWN → receiver:CUT → receiver:HANDOFF
- 判别信号: big_holds_at_top; two_side_down_screens; offball_curl_up
- 与最像战术的区别: 由**大个在弧顶发起**，一次性摆出两侧下掩护。
- 来源: 第41期：联盟中最会“Delay”的湖人勇士在宿敌周的收官大战相遇了

## delay_defense
- 名称: delay defense / 延误 / 延误防守
- 库条目: delay defense
- 类别: defense
- tier: basic
- 判别原语(key): DELAY
- 目的: 挡拆防守“延误”：大个防守人上抢至与掩护齐平，短暂施压持球人后回追对位。
- 触发: 对手挡拆，需短暂破坏其持球进攻。
- 原语: DELAY
- 序列: defense:DELAY
- 判别信号: big_defender_above_screen; brief_double_then_recover
- 与最像战术的区别: 与 DROP（沉退）差别：大个防守人站位更靠上。
- 来源: 第57期：掘金队的防守计划可能要被打乱了那么在季后赛他们还会继续“延误”吗？

## double_high_screen
- 名称: double high screen / doublehighscreen / 高位双掩护 / 4-5
- 库条目: double high screen
- tier: system
- 判别原语(key): SCREEN.HIGH
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 两名大个在三分线外（高位）同时给后卫做双掩护，两底角拉开。
- 触发: 对手对单掩护有准备，用双掩护增加选择。
- 原语: SCREEN.HIGH -> SCREEN.HIGH -> DRIVE
- 序列: screener1:SCREEN/HIGH → screener2:SCREEN/HIGH → ball_handler:DRIVE
- 判别信号: two_screeners_above_arc; corner_spacing
- 与最像战术的区别: **两名**掩护人在三分线外（vs 牛角的肘区站位）。
- 来源: 第23期：雄鹿队围绕利拉德设计“DoubleHighScreen”战术

## drop_defense
- 名称: drop / 沉退 / drop coverage
- 库条目: drop
- 类别: defense
- tier: basic
- 判别原语(key): DROP
- 目的: 挡拆防守“沉退”：大个守禁区，等持球人进来再干扰。
- 触发: 对手挡拆且持球人中距离/投射威胁有限。
- 原语: DROP
- 序列: defense:DROP
- 判别信号: big_between_ball_and_rim; handler_met_at_paint
- 与最像战术的区别: 与延误差别：大个站位在掩护**下方**（罚球线内）。
- 来源: 第27期：把戈贝尔的优势最大化发挥“drop”战术助森林狼队登顶西部

## eog
- 名称: eog / end of game / 末段战术
- 库条目: eog
- 类别: ato
- tier: system
- 判别原语(key): SCREEN.STS
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 比赛末段（EOG）暂停后 ATO：STS + 下掩护 + 挡拆组合创造最后出手。
- 触发: 比赛临近结束、时间紧迫。
- 原语: SCREEN.CROSS -> SCREEN.STS -> SCREEN.DOWN -> SCREEN.DOWN -> SCREEN.DOWN
- 序列: screener:SCREEN/CROSS → screener:SCREEN/STS → ball_handler:SCREEN/DOWN
- 判别信号: sts_event; low_remaining_seconds
- 与最像战术的区别: **STS**（先掩护后受掩护）与横掩护的组合。
- 来源: 第75期：逐帧解析独行侠队“EOG”战术

## exchange_down
- 名称: exchange / exchangedown / 换位下掩护
- 库条目: exchange
- tier: system
- 判别原语(key): EXCHANGE
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: “换位 + 下掩护”：两人交叉换位，随后为另一人下掩护制造接球/突破。
- 触发: 盯人防守，需为接球人开路。
- 原语: EXCHANGE -> SCREEN.DOWN
- 序列: playerA:EXCHANGE → playerB:SCREEN/DOWN → receiver:DRIVE
- 判别信号: two_players_cross; then_down_screen
- 与最像战术的区别: 起始为**换位（交叉）**，再接下掩护。
- 来源: 第13期：预判你的预判！看掘金如何破解湖人队的exchangedown

## exit_screen
- 名称: exitscreen / 外切掩护 / exitscreen
- 库条目: exitscreen
- tier: system
- 判别原语(key): SCREEN.EXIT
- 目的: 底线外切掩护：为外切球员创造底角接球；或作为牵制带走弱侧防守。
- 触发: 盯人防守（对区域联防价值降低）。
- 原语: SCREEN.EXIT -> CUT -> SPOT_UP
- 序列: screener:SCREEN/EXIT → receiver:CUT → receiver:SPOT_UP
- 判别信号: screen_at_baseline; screened_moves_outward
- 与最像战术的区别: 掩护发生在**底线**、被掩护人向外（底角）移动。
- 来源: 第11期：凯尔特人用一招“exitscreen”完美破解了热火队的“23联防”

## iso_face_up
- 名称: face up / 面框单打 / isolation
- 库条目: face up
- tier: basic
- 判别原语(key): ISO
- 目的: 面框单打：拉开空间后持球人正面单打。
- 触发: 错位或对手单防弱。
- 原语: ISO
- 序列: spacer:SPOT_UP → ball_handler:ISO
- 判别信号: all_spaced; one_on_one_dribble
- 与最像战术的区别: 全员拉开 + 单点持球（vs 团队配合）。
- 来源: 第43期：井喷式的得分爆发的背后是“面框单打”在战术层面的占比提升

## gator_pass
- 名称: gator pass / gatorpass / 高低位传球 / high-low pass
- 库条目: gator pass
- tier: system
- 判别原语(key): PASS.HIGHLOW
- 目的: 破上线夹击的高低位传球：高位中转 → 顺下篮下。
- 触发: 对手对持球人进行上线夹击/延阻。
- 原语: SCREEN.DOWN -> PASS.HIGHLOW -> ROLL
- 序列: screener:SCREEN/DOWN → ball_handler:PASS → receiver:ROLL
- 判别信号: high_post_transit; double_team_event
- 与最像战术的区别: **高位中转传球**（high-low）。
- 来源: 第9期：挡拆如遇上线夹击或延阻就用GatorPass

## get_action
- 名称: get action / getaction / 急取
- 库条目: get action
- tier: system
- 判别原语(key): HANDOFF
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: “急取”：后卫停球传给大个后贴身取回，完成手递手。
- 触发: 追防者被掩护卡住或换防沟通失误。
- 原语: HANDOFF -> DRIVE
- 序列: ball_handler:PASS → ball_handler:HANDOFF → ball_handler:DRIVE
- 判别信号: handoff_event; handler_returns_to_big
- 与最像战术的区别: 手递手前的“取回”动作序列。
- 来源: 第22期：湖人队新赛季的变化五外站位下的“Getaction”

## ghost_screen
- 名称: ghost screen / ghostscreen / 幽灵掩护
- 库条目: ghost screen
- tier: system
- 判别原语(key): SCREEN.GHOST
- 目的: 利用对手换防预设：掩护人假装掩护但不接触，外弹制造突破/投篮机会。
- 触发: 防守方对持球挡拆采用换防(switch)预设。
- 原语: SCREEN.GHOST -> DRIVE
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/GHOST → screener:POP
- 判别信号: screen_no_contact; screener_out_after_close
- 与最像战术的区别: 掩护人**不与防守人接触**（幽灵）——关键负向信号。
- 来源: 第19期：看探花秀亨德森如何巧妙利用“Ghostscreen”

## handoff
- 名称: handoff / 手递手 / 手递手战术 / DHO
- 库条目: handoff / 手递手战术
- tier: basic
- 判别原语(key): HANDOFF
- 目的: 以身体作墙、手递手交球给绕行的队友，制造接球后的出手/突破。
- 触发: 追防者被掩护卡在身后或换防沟通失误。
- 原语: HANDOFF
- 序列: ball_handler:DRIBBLE_ENTRY → receiver:CUT/GIVE_GO → receiver:SPOT_UP
- 判别信号: handoff_event
- 与最像战术的区别: 球在两**相邻**球员间直接交接（vs 拉开距离的传球）。
- 来源: 第53期：看似简单的“手递手战术”湖人队怎么就防不住呢？

## horns
- 名称: horns / 牛角 / horns out / horns out backdoor
- 库条目: horns
- tier: system
- 判别原语(key): SCREEN.CROSS
- 目的: 以牛角站位起手，用横切掩护制造 backdoor 或低位机会。
- 触发: 持球人被上线紧逼、外线接球被切断。
- 原语: SCREEN.CROSS -> CUT.BACKDOOR
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/CROSS → cutter:CUT/BACKDOOR
- 判别信号: formation_snapshot; cross_screen_event
- 与最像战术的区别: 起手落位=牛角（两肘区），后续以横切掩护衔接。
- 来源: 第14期：约老师用“牛角”破联防

## keep_action
- 名称: keep / fake DHO / 假手递手
- 库条目: keep
- tier: system
- 判别原语(key): HANDOFF
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 假手递手（Keep/Fake DHO）：假装交球实则自己保留，欺骗追防后自行攻击。
- 触发: 防守注意力全在射手身上（预设换防/追防）。
- 原语: HANDOFF -> DRIVE
- 序列: ball_handler:HANDOFF → ball_handler:DRIVE
- 判别信号: handoff_approach_no_transfer
- 与最像战术的区别: 与真手递手相反——**球未易手**。
- 来源: 第4期：学会“Keep”打破球场惯性思维让对手措手不及

## lift_spread_pnr
- 名称: lift / 上提 / 上提+分散挡拆 / shake / spread PnR + lift
- 库条目: lift / 上提+分散挡拆
- tier: system
- 判别原语(key): CUT.LIFT
- 目的: 上提 + 分散挡拆：底角球员上提到 45 度接球投，破解上线夹击。
- 触发: 对手对挡拆夹击，强侧防守人短暂离开对位人去护框。
- 原语: SCREEN.DOWN -> CUT.LIFT -> SPOT_UP
- 序列: screener:SCREEN/DOWN → shooter:CUT/LIFT → shooter:SPOT_UP
- 判别信号: corner_lifts_to_45; screen_then_skip_pass
- 与最像战术的区别: 无球人**从底角上提**接球（vs 原地定点）。
- 来源: 第30期：“上提+分散挡拆”鹈鹕队轻松破解国王夹击防守挺进半决赛

## motion_offense
- 名称: motion offense / 动态进攻 / flip guide
- 库条目: motion offense
- tier: system
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 动态进攻体系：连续手递手/传切/掩护的自由流动进攻。
- 触发: 强调早期进攻、给多名持球手创造突破机会。
- 原语: HANDOFF -> HANDOFF -> CUT -> SCREEN.DOWN -> PASS
- 序列: ball_handler:HANDOFF → receiver:HANDOFF → cutter:CUT
- 判别信号: repeated_handoff_chain; no_fixed_pattern
- 与最像战术的区别: **体系**（非单一配合）——多点连续动作。
- 来源: 第28期：在“动态进攻”体系下恩比德逐渐“约基奇化”

## off_ball_scoring
- 名称: off-ball / 无球 / 无球终结
- 库条目: off-ball
- tier: system
- 目的: 无球终结：手递手/定点/无球掩护后的接球终结（核心转为无球点）。
- 触发: 持球核心被限制或战术设计让其打无球。
- 原语: HANDOFF -> SPOT_UP -> SCREEN.FLARE
- 序列: star:CUT → star:SPOT_UP
- 判别信号: star_off_ball
- 与最像战术的区别: 无球角色（vs 持球发起）。
- 来源: 第32期：“7秒进攻+无球掩护”现在的哈利伯顿比肩巅峰纳什？

## off_ball_screen
- 名称: off-ball screen / 无球掩护 / flare
- 库条目: off-ball screen
- tier: basic
- 判别原语(key): SCREEN.FLARE
- 目的: 无球掩护（含远切封盖 flare），为射手制造接球出手空间。
- 触发: 防守人面向持球人、注意力在球上。
- 原语: SCREEN.FLARE
- 序列: screener:SCREEN/FLARE → shooter:SPOT_UP
- 判别信号: offball_screen_event; screen_behind_defender
- 与最像战术的区别: 无球掩护（非有球）。
- 来源: 第32期：“7秒进攻+无球掩护”现在的哈利伯顿比肩巅峰纳什？

## pick_and_roll
- 名称: pick and roll / 挡拆 / 约基奇挡拆 / PnR
- 库条目: pick and roll / 约基奇挡拆
- tier: system
- 目的: 挡拆总类：有球掩护 + 持球人攻击 + 掩护人顺下/外弹。
- 触发: 对手挡拆防守的破绽（沉退/换防/夹击）。
- 原语: SCREEN.DOWN -> DRIVE -> ROLL
- 序列: screener:SCREEN/DOWN → ball_handler:DRIVE → screener:ROLL
- 判别信号: on_ball_screen
- 与最像战术的区别: 挡拆总类（含 1-5 / 分散 / 反向 / 库追 / 约基奇挡拆等实例）。
- 来源: 第9期：挡拆如遇上线夹击或延阻就用GatorPass

## pistol_5
- 名称: pistol 5 / 手枪5 / pistol
- 库条目: pistol 5
- tier: system
- 目的: 强侧清空的手枪系列挡拆：大个弧顶拿球，一侧清空给持球人。
- 触发: 需为持球人创造清晰的一侧突破/挡拆空间。
- 原语: SCREEN.DOWN -> DRIVE -> PASS
- 序列: big:DRIBBLE_ENTRY → screener:SCREEN/DOWN → ball_handler:DRIVE
- 判别信号: strong_side_cleared; big_holds_then_screen
- 与最像战术的区别: 强侧清空（弱侧堆人）。
- 来源: 第10期：斯波教练的“手枪5”战术让射手邓肯·罗宾逊华丽变身

## post_up
- 名称: post up / 背身单打 / 低位进攻
- 库条目: post up
- tier: basic
- 判别原语(key): POST_UP
- 目的: 背身单打：低位接球后背框进攻。
- 触发: 低位错位或对手单防弱。
- 原语: POST_UP
- 序列: scorer:POST_UP → scorer:ISO
- 判别信号: low_post_catch; back_to_basket
- 与最像战术的区别: 背框（vs 面框）。
- 来源: 第44期：MVP约老师告诉你传统武器“背身单打”永不过时

## princeton_offense
- 名称: princeton offense / princeton / 普林斯顿进攻 / point series
- 库条目: princeton offense
- 类别: system
- tier: system
- 判别原语(key): PASS.HIGHLOW
- 目的: 普林斯顿进攻：高位中锋策应 + 反跑/背切 + handoff。
- 触发: 需要无固定控卫的流动进攻。
- 原语: PASS.HIGHLOW -> CUT.BACKDOOR -> HANDOFF -> SCREEN.DOWN
- 序列: big:PASS → cutter:CUT/BACKDOOR → cutter:HANDOFF
- 判别信号: high_post_initiator; split_action
- 与最像战术的区别: **高位中锋策应**开局 + 反跑。
- 来源: NBA篮球术语/The Basics of the Point Series _ Princeton Offense

## putback
- 名称: putback / 补篮 / 二次进攻
- 库条目: putback
- tier: system
- 判别原语(key): OFF_REBOUND
- 目的: 补篮：抢前场篮板后立即补进。
- 触发: 投篮不中且防守大个被拉出护框。
- 原语: OFF_REBOUND -> PUTBACK
- 序列: crasher:OFF_REBOUND → crasher:PUTBACK
- 判别信号: off_rebound_then_shot
- 与最像战术的区别: 起始于**前场篮板**。
- 来源: 第33期：看完本期内容就会发现“补篮”其实也是一种战术

## ram_screen
- 名称: ram screen / ram掩护 / ram
- 库条目: ram screen
- tier: system
- 判别原语(key): SCREEN.RAM
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: RAM 掩护：先给掩护人做掩护(ram)，该人再给持球人做有球掩护。
- 触发: 对手对挡拆强延误，需为掩护人创造更大操作空间。
- 原语: SCREEN.RAM -> SCREEN.DOWN -> ROLL
- 序列: screenerA:SCREEN/RAM → screenerB:SCREEN/DOWN → ball_handler:DRIVE
- 判别信号: ram_event
- 与最像战术的区别: **给掩护人做掩护**（ram）——两段掩护串联。
- 来源: 第31期：看独行侠如何围绕东契奇玩转“Ram掩护”

## reject
- 名称: reject / 拒绝掩护
- 库条目: reject
- tier: system
- 判别原语(key): REJECT
- 目的: 拒绝掩护：持球人/无球人反向绕过掩护（走另一侧）。
- 触发: 防守人提前挤掩护或采取过于激进的防守方式。
- 原语: REJECT -> DRIVE
- 序列: ball_handler:REJECT → ball_handler:DRIVE
- 判别信号: direction_reversal_at_screen
- 与最像战术的区别: 反方向绕过（vs 顺掩护）。
- 来源: 第21期：卡姆·惠特摩尔用一招“reject”最大化自己的身体天赋

## rip_screen
- 名称: rip screen / ripscreen / 背掩护 / back screen
- 库条目: rip screen
- tier: system
- 判别原语(key): SCREEN.BACK
- 目的: 背掩护（rip/back screen）：为切入者在其防守人身后设掩护。
- 触发: 防守人站在进攻球员与篮筐之间、未准备好后方掩护。
- 原语: SCREEN.BACK -> CUT
- 序列: screener:SCREEN/BACK → cutter:CUT
- 判别信号: screen_set_behind_defender; cutter_goes_to_rim
- 与最像战术的区别: 掩护在防守人**身后**（背掩护）。
- 来源: 第6期：湖人队的ripscreen

## roll
- 名称: roll / 顺下
- 库条目: roll
- tier: system
- 判别原语(key): ROLL
- 目的: 顺下（含强顺下/短顺下）：掩护后掩护人向篮筐移动接球。
- 触发: 对手夹击持球人，掩护人获得顺下空间。
- 原语: SCREEN.DOWN -> ROLL
- 序列: screener:SCREEN/DOWN → screener:ROLL
- 判别信号: screener_moves_to_rim
- 与最像战术的区别: 顺下方向/距离（vs 外弹 POP）。
- 来源: 第17期：双核驱动“短顺下”战术就是总决赛G4掘金队的致胜策略

## second_screen
- 名称: second screen / 二次掩护 / re-screen
- 库条目: second screen
- tier: basic
- 判别原语(key): SCREEN.DOWN
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 二次掩护：第一次掩护失败后再做一次（调整角度）。
- 触发: 对手挤过掩护或走下线使首次掩护失败。
- 原语: SCREEN.DOWN -> SCREEN.DOWN
- 序列: screener:SCREEN/DOWN → screener:SCREEN/DOWN
- 判别信号: consecutive_screens_same_pair
- 与最像战术的区别: **重复**掩护（vs 单次）。
- 来源: 《世界杯战术笔记》Ep05：胡金秋的“二次掩护”助力中国男篮首胜

## short_roll
- 名称: short roll / 短顺下 / 提前顺下
- 库条目: short roll
- tier: system
- 判别原语(key): SHORT_ROLL
- 目的: 短顺下：掩护人到罚球线接球再处理（形成 4 打 3）。
- 触发: 对手夹击/强延误挡拆，掩护人获得短顺下接球空间。
- 原语: SCREEN.DOWN -> SHORT_ROLL
- 序列: screener:SCREEN/DOWN → screener:SHORT_ROLL
- 判别信号: roller_stops_at_elbow
- 与最像战术的区别: 顺下距离短（肘区停，vs 直下篮下）。
- 来源: 第17期：双核驱动“短顺下”战术就是总决赛G4掘金队的致胜策略

## slob
- 名称: sideline play / 边线球战术 / SLOB / twirl exitscreen
- 库条目: sideline play / 边线球战术
- 类别: ato
- tier: system
- 判别原语(key): INBOUND
- 目的: 边线球战术（SLOB）：界外发球后利用组合掩护接球投/终结。
- 触发: 死球/暂停后边线发球，时间紧。
- 原语: INBOUND -> SCREEN.STAGGER -> SCREEN.FLARE -> CUT
- 序列: inbounder:INBOUND → screener:SCREEN/STAGGER → shooter:CUT
- 判别信号: inbound_start; stacked_screen_series
- 与最像战术的区别: 起手为**边线发球**（SLOB）。
- 来源: 第12期：边线球战术真的很难吗？东决G6凯尔特人 / 第54期：边线球战术成就欧文天外飞仙

## slice
- 名称: slice / slice action
- 库条目: slice
- tier: system
- 判别原语(key): SCREEN.RAM
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: Slice：ram 掩护转双人远切/下掩护（步行者常用）。
- 触发: 对手对单人掩护有准备，用 ram→双人拖拽增加层次。
- 原语: SCREEN.RAM -> SCREEN.DOWN -> SCREEN.DOWN -> DRIVE
- 序列: screenerA:SCREEN/RAM → screener:SCREEN/DOWN → ball_handler:DRIVE
- 判别信号: ram_then_double_drag
- 与最像战术的区别: ram → 双人拖拽的组合。
- 来源: 第48期：每一个选择都是细节满满哈利伯顿全方位解读“slice”战术

## split_cut
- 名称: split cut / splitcut / 反切 / 劈分
- 库条目: split cut
- tier: system
- 判别原语(key): SCREEN.CROSS
- 目的: 分切：肘区/高位持球，两侧无球手做掩护分向篮下/三分。
- 触发: 高位持球人被阻断直接传球。
- 原语: SCREEN.CROSS -> CUT.BACKDOOR
- 序列: big:PASS → cutter:SCREEN/DOWN → cutter:CUT
- 判别信号: elbow_catch; two_offball_screens_opposite
- 与最像战术的区别: **肘区**持球 + 双向分掩护。
- 来源: 第7期：约老师专属代号“C”Splitcut战术

## spot_action
- 名称: spot action / 定点战术 / spot up
- 库条目: spot action
- tier: basic
- 判别原语(key): SPOT_UP
- 目的: 定点：外线接球后直接进攻（投/突/传）。
- 触发: 突分或转移球后出现外线空位。
- 原语: SPOT_UP
- 序列: receiver:SPOT_UP → receiver:DRIVE
- 判别信号: catch_on_perimeter; immediate_action
- 与最像战术的区别: 定点接球（vs 无球掩护/切入）。
- 来源: 第36期：“定点战术”是指球员在外线接球后直接进攻

## spread_pnr
- 名称: spread pnr / 分散挡拆 / spread pick and roll
- 库条目: spread pnr
- tier: system
- 目的: 分散挡拆：有球掩护在上线，两翼底角/45 度 + 强侧底角拉开，空间最大化。
- 触发: 对手收缩护框，需最大化空间。
- 原语: SCREEN.DOWN -> DRIVE -> PASS
- 序列: screener:SCREEN/DOWN → ball_handler:DRIVE → receiver:SPOT_UP
- 判别信号: four_out_spacing; on_ball_screen_above_arc
- 与最像战术的区别: 空间最大化的挡拆站位（4-out）。
- 来源: 第30期：“上提+分散挡拆”鹈鹕队轻松破解国王夹击防守挺进半决赛

## stagger_screen
- 名称: stagger screen / staggerscreen / 梯次掩护 / tiered screen / stack screen
- 库条目: stagger screen / tiered screen
- tier: system
- 判别原语(key): SCREEN.DOWN
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 为射手连续设置两个下掩护，制造三分出手空间。
- 触发: 追防者需连续穿过两名掩护人，易被卡住。
- 原语: SCREEN.DOWN -> SCREEN.DOWN -> CUT
- 序列: screener1:SCREEN/DOWN → screener2:SCREEN/DOWN → shooter:SPOT_UP
- 判别信号: consecutive_screens; shooter_ends_perimeter
- 与最像战术的区别: **连续两个**下掩护（vs 单个下掩护）。
- 来源: 第15期：总决赛G2热火队的“Staggerscreen” / 世界杯 Ep07 梯次掩护

## sts
- 名称: sts / screen the screener / 给掩护人做掩护
- 库条目: sts
- tier: system
- 判别原语(key): SCREEN.STS
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 给掩护人做掩护（STS）：先做掩护者再借掩护接球。
- 触发: 防守盯防接球人、需用双重掩护制造接球空间。
- 原语: SCREEN.STS -> CUT -> SCREEN.DOWN
- 序列: player:SCREEN/DOWN → player:CUT
- 判别信号: sts_event
- 与最像战术的区别: **先掩护后受掩护**。
- 来源: 第19期：看探花秀亨德森如何巧妙利用“Ghostscreen” / STS 战术

## through_veer
- 名称: through veer / through+veer / 穿插+变向掩护
- 库条目: through veer
- tier: system
- 判别原语(key): SCREEN.VEER
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 穿插（through）+ 变向掩护（veer）组合，为持球人重设掩护。
- 触发: 初次掩护被挤过，需用变向掩护重新创造角度。
- 原语: CUT.THROUGH -> SCREEN.VEER -> DRIVE
- 序列: player:CUT/THROUGH → screener:SCREEN/VEER → ball_handler:DRIVE
- 判别信号: through_run; veer_screen_redirection
- 与最像战术的区别: through + veer 的组合。
- 来源: 第83期：《NBA战术笔记》核心遭遇限制怎么办？不妨试试步行者的“Through+Veer”

## touch_screen
- 名称: touch screen / touchscreen / 触碰掩护
- 库条目: touch screen
- tier: system
- 判别原语(key): SCREEN.TOUCH
- 目的: 触碰掩护：掩护人与防守人轻微接触后立刻顺下，接口袋传球。
- 触发: 防守人换防/追防犹豫的瞬间。
- 原语: SCREEN.TOUCH -> ROLL -> PASS.POCKET
- 序列: screener:SCREEN/TOUCH → screener:ROLL → ball_handler:PASS
- 判别信号: brief_contact_then_slip; pocket_pass
- 与最像战术的区别: **轻触即走**（vs 完整掩护停留）。
- 来源: 第20期：湖人队二年级球员马克斯·克里斯蒂“Touchscreen”触碰掩护战术

## transition
- 名称: transition / 转换 / 快攻
- 库条目: transition
- tier: system
- 判别原语(key): TRANSITION
- 目的: 转换进攻：防守未就位时的快速进攻。
- 触发: 防守方退防未成型（未处于正常防守站位）。
- 原语: TRANSITION -> DRIVE -> PASS
- 序列: ball_handler:TRANSITION → ball_handler:DRIVE
- 判别信号: defense_not_set
- 与最像战术的区别: 基于**防守站位**判定（非得分类型）。
- 来源: 第37期：理解好这些场上的细节你就会顺利发起“转换”战术

## triangle_offense
- 名称: triangle offense / 三角进攻 / blind pig
- 库条目: triangle offense
- 类别: system
- tier: system
- 判别原语(key): CUT.BLIND_PIG
- 目的: 三角进攻：侧翼三角落位 + 高位策应 + 反跑（blind pig）。
- 触发: 对手阻断侧翼接球时，用反跑破解。
- 原语: PASS -> CUT.BLIND_PIG -> SCREEN
- 序列: big:PASS → cutter:CUT/BLIND_PIG
- 判别信号: sideline_triangle_formation; blind_pig_cut
- 与最像战术的区别: 三角落位 + blind pig 反跑。
- 来源: 第45期：新春特辑龙之队看杜兰特如何巧用“三角进攻”

## twirl_action
- 名称: twirl action / 旋转门 / twirl
- 库条目: twirl action
- tier: system
- 判别原语(key): SCREEN.STAGGER
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 旋转门：跑掩护者只用第一掩护后卷切篮下，第一掩护人借第二掩护绕出。
- 触发: 防守沟通需在两次掩护间快速切换。
- 原语: SCREEN.STAGGER -> CUT.CURL -> SCREEN
- 序列: cutter:CUT/CURL → screener:SCREEN
- 判别信号: twirl_event
- 与最像战术的区别: stagger 变种——两人**互换**跑位。
- 来源: 第26期：通过“Twirlaction”战术看新帅乌度卡如何让火箭队完成蜕变

## wall_defense
- 名称: wall defense / 筑墙式防守
- 库条目: wall defense
- 类别: defense
- tier: basic
- 判别原语(key): WALL
- 目的: 筑墙式防守：转换防守时用人墙保护篮下。
- 触发: 对手转换进攻，需先保护篮下。
- 原语: WALL
- 序列: defense:WALL
- 判别信号: defensive_wall
- 与最像战术的区别: 防守；转换退防场景。
- 来源: 第49期：看太阳队如何巧用“筑墙式防守”应对转换进攻

## wedge_screen
- 名称: wedge screen / wedge / 蝎掩护
- 库条目: wedge screen
- tier: system
- 判别原语(key): SCREEN.WEDGE
- 目的: 蝎掩护（wedge）：小个给大个做无球掩护，让大个低位进攻或回高位做掩护。
- 触发: 需为大个创造低位/高位操作空间。
- 原语: SCREEN.WEDGE -> SCREEN.DOWN
- 序列: guard:SCREEN/WEDGE → big:SCREEN/DOWN
- 判别信号: small_screens_big
- 与最像战术的区别: **小个给大个**做掩护（vs 常规大个给后卫掩护）。
- 来源: 第16期：布劳恩如何发起小个给大个掩护的“wedgescreen”战术

## zipper
- 名称: zipper / 拉链掩护 / 拉链挡拆 / zipper cut
- 库条目: zipper / 拉链挡拆
- tier: system
- 判别原语(key): SCREEN.ZIPPER
- 目的: 拉链掩护/切入：强侧为侧翼球员做掩护，使其到外线接球组织后续进攻。
- 触发: 需让侧翼球员更容易到外线接球。
- 原语: SCREEN.ZIPPER -> CUT.ZIPPER
- 序列: screener:SCREEN/DOWN → cutter:CUT/ZIPPER
- 判别信号: cut_along_lane_to_perimeter
- 与最像战术的区别: zipper cut——到**外线**接球（vs backdoor 到篮下）。
- 来源: 第2期：马刺经典战术配合ZipperBackdoor / 世界杯 EP01 拉链挡拆

## zipper_backdoor
- 名称: zipper backdoor / 拉链挡拆 / zipper / backdoor
- 库条目: zipper backdoor
- tier: system
- 判别原语(key): CUT.ZIPPER
- 时序依赖(seq_dependent): 是（判别量=次序/重复，signature 未评估时降级）
- 目的: 用「借下掩护外切接球(zipper cut)」作诱饵，趁防守抢前反跑后门，直切篮下得分。
- 触发: 防守人为断外线接球而抢前/贴身(over-play the catch)。
- 原语: SCREEN.DOWN -> CUT.ZIPPER -> CUT.BACKDOOR
- 序列: ball_handler:DRIBBLE_ENTRY → cutter:CUT/ZIPPER → cutter:CUT/BACKDOOR
- 判别信号: trajectory_reversal; defender_high_side
- 与最像战术的区别: 前置存在 Zipper Cut（借掩护外切接球）——与「裸 backdoor」的区别。
- 来源: 第2期：马刺经典战术配合ZipperBackdoor

## inverted_pnr
- 名称: 反向挡拆 / inverted pick and roll / inverted PnR
- 库条目: 反向挡拆
- tier: system
- 目的: 反向挡拆：小个给大个做有球掩护，把大个防守人带离舒适区。
- 触发: 对手大个防守人习惯沉退、对防持球无准备。
- 原语: SCREEN.DOWN -> DRIVE
- 序列: ball_handler:DRIBBLE_ENTRY → screener:SCREEN/DOWN → ball_handler:DRIVE
- 判别信号: screener_smaller_than_handler
- 与最像战术的区别: 掩护人**体型小于**持球人。
- 来源: 第25期：通过“反向挡拆”战术重新定义切特·霍姆格伦
