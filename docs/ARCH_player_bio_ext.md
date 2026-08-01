# ARCH — 球员主数据维度增量（bio_ext）

> 设计者：软件架构师 Bob（高见远）
> 上游：用户 BR 球员页字段标注（Julius Erving 页，含 7 个 dim_players 缺口，含离世日期 died）
> 性质：**增量设计 + 任务分解**（不写实现代码，仅定结构与爬取计划）
> 项目根：`/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13`
> DB：`5433/nba/postgres`（口令走 `backend.core.config.db_dsn()`，不硬编码）
> 配套图：`docs/player_bio_ext_class.mermaid`、`docs/player_bio_ext_sequence.mermaid`
>
> 修订（2026-07-17）：增补 **离世日期 died** 维度（`dim_players.died date`，nullable）。因架构师 agent 当时环境侧不可用（0s 报 `not available`），由主理人齐活林代为原地修订；类图/时序图无需改动（died 仅为 dim_players 加列，无新表/新关系）。

---

## 1. 实现方案 + 框架选型

### 1.1 这是增量，不是新建项目
完全复用既有范式，不引入任何新框架：

| 关注点 | 复用项 | 说明 |
|--------|--------|------|
| HTTP 直连（抗 CF） | `common/player_nickname.fetch_player_page`（curl_cffi impersonate=chrome124 → 失败返回 None） | 不碰 9222 Chrome |
| 抽取纯函数范式 | `common/player_nickname.extract_nickname` | 离线可测、零网络依赖 |
| 回填 crawler 范式 | `external_crawler/crawler/crawl_br_nicknames.py` | 独立脚本 + `--resume` + per-player commit + 限速 |
| 落库范式 | `crawl_br_nicknames.upsert_nickname` / `crawl_br_headshots.upsert_path` | `UPDATE dim_players` + 部分索引 + `scraped_at` 哨兵 |
| 迁移范式 | `sql/006_add_player_nickname.sql` + `sql/run_migrations.py` | `IF NOT EXISTS` 幂等 + 重建 `player_bio` 视图 |
| 依赖 | `psycopg2` / `curl_cffi` / `beautifulsoup4`（均已存在） | **零新增第三方包** |

### 1.2 「dim_players 加列」vs「新建表」的取舍原则

`player_bio` 是 `dim_players` 的**视图**（见 `nba_schema_only.sql:2140`）。因此任何**球员 1:1 主属性**只能落在 `dim_players`，视图重建即自动暴露；结构化、可查询的 **1:N 事实**才建子表。

| 判定 | 落点 | 理由 |
|------|------|------|
| 1:1、展示型、无需按子成分查询 | `dim_players` 加列 | 与 nickname / headshots 增量一致；视图自动暴露；API 零改动（SELECT * 已覆盖） |
| 1:N、需按子成分过滤（"所有 MVP"、"所有名人堂"） | 新建子表 | 归一化后可索引查询；awards 三表不覆盖这些荣誉 |

应用：aba_debut / **died** / hof_* / career_length / relatives / jersey_numbers / career_honors_text → **dim_players 加列**；honors → **新建 `player_career_honors` 表**（见 §3.6）。

---

## 2. 缺失维度建模决策（6 个缺口逐个定）

### 2.1 亲属 Relatives（`Relatives: Cousin Jeff Halliburton`）
**决策：单列 `relatives text`（逗号分隔），不结构化。**
- BR 页亲属是自由文本行（"Relatives: Cousin Jeff Halliburton"），多亲属罕见（逗号分隔）。
- 查询价值低（极少"按亲属检索球员"），结构化（关系类型/姓名）代价高、收益低。
- 与 nickname 范式一致：展示型文本直接存 `dim_players.relatives`。
- 若未来需"查某人亲属网"，再建 `player_relatives` 表；当前不建。

### 2.2 ABA Debut（`ABA Debut: October 15, 1971`）
**决策：`dim_players.aba_debut date`，与 `nba_debut` 并列。**
- 类型 `date`，NULL = 从未打 ABA。解析 `ABA Debut: <Month D, YYYY>`。
- 选择器待复核（见 §9），预计在 `#info` 的 meta 行，与 `NBA Debut` 同区。

### 2.3 Hall of Fame（`Hall of Fame: Inducted as Player in 1993`）
**决策：`dim_players.hof_inducted_year integer` + `hof_as text` + `is_hall_of_famer boolean`。**
- `hof_inducted_year`：入选年份（1993），NULL = 非名人堂。
- `hof_as`：入选身份（'Player' / 'Coach' / 'Contributor'），来自 "as {X}"。
- `is_hall_of_famer`：**普通布尔列**（非生成列），由 crawler upsert 时设为 `hof_inducted_year IS NOT NULL`——避免 STORED 生成列的表重写（保在线 DDL 安全）。建部分索引 `WHERE is_hall_of_famer = true` 支撑"列出所有名人堂"。
- 注意：awards 三表**不含**名人堂；这是唯一来源。

### 2.4 Career Length（`Career Length: 16 years`）
**决策：`dim_players.career_length_years integer`（冗余存储）。**
- 用户明确要此字段；BR 页直接给出 "Career Length: N years" → 抽整数。
- 虽可由 `year_to - year_from` 派生，但 BR 的生涯长度含 ABA / 间隔年，与差值**不一定一致**，故按用户要求**冗余存储**该抓取值（单一数据源 = BR 球员页）。

### 2.5 生涯荣誉汇总（Hall of Fame / 16x All Star / 1983 NBA Champ / 4x MVP …）
**决策：新建归一化表 `player_career_honors`（推荐），并可选 `dim_players.career_honors_text text[]` 去重列表作展示镜像。**

**为何不只用 awards 三表聚合视图：**
1. **覆盖缺口**：awards 表（player_award_shares / all_star_selections / end_of_season_teams）来自 `awards_{season}.html` / `allstar_{season}.html`，是**赛季级**分项；以下标注项**完全不在**其中：ABA Champ、NBA 75th Anniv. Team、Hall of Fame、ABA All-Time Team、MBWA ABA POY。
2. **聚合脆弱**："16x All Star" 需对 all_star_selections 按 player_id group，但 ABA 时代 / 历史球员缺失，计数不全。
3. **1:1 对齐标注**：球员页荣誉块就是用户标注的"生涯汇总清单"，直接解析最忠实。

**表结构（见 §3.6）**：`(player_id, honor_raw, honor_type, honor_count, honor_year, honor_detail)`，`honor_type` 归一化枚举便于查询。

**展示镜像（可选但推荐）**：`dim_players.career_honors_text text[]` = 去重后的 `honor_raw` 列表（如 `['Hall of Fame','16x All Star','1983 NBA Champ',…]`），crawler 在同一事务内维护，使 `player_bio` 视图 + `PlayerBio` schema 直接暴露"清单"，无需新端点即可展示。归一化表则服务"按类型/年份查询"。

### 2.6 球衣号码 Jersey（`32 / 32 / 6 / 6`）
**决策：`dim_players.jersey_numbers text[]`（去重数组），不建表。**
- 标注里的重复（32/32/6/6）疑似按球队/赛季重复出现；取**集合去重**得 `['32','6']`。
- 球员穿号通常 ≤3 个，展示型、低查询需求 → 数组列最简单，视图/API 直接暴露。
- 若未来需"按号码检索球员"或"号码+赛季范围"，再升级为 `player_jersey_numbers(player_id, number, seasons)` 表；当前不建。
- BR 页号码容器**位置待复核**（见 §9），疑为 `#info` 底部某 `<ul>` 或专门区块。

### 2.7 离世日期 Died（`Died: January 26, 2020 (aged 41) in Calabasas, CA`）
**决策：`dim_players.died date`（nullable），与 `birth_date` 并列。**
- **仅已故球员有此行**：BR 球员页 `#info` 元信息块里，对离世球员会多出一行 `Died: <Month D, YYYY> (aged X) in <place>`（与 Born / Relatives / ABA Debut 同一区域）。
- 抽取：文本前缀 `"Died:"` 定位 + 正则抽日期；**在世球员无此行 → 落 NULL**（切勿误填，NULL=在世或未知）。
- 选择器待复核（见 §9）：用真实已故球员页（样本 `bryanko01`）实测确认该行容器与格式。
- 不建表、不结构化；与 birth_date 同属 1:1 主属性，视图自动暴露。

---

## 3. 文件列表及相对路径

| 操作 | 路径 | 说明 |
|------|------|------|
| 新增 | `sql/007_add_player_bio_ext.sql` | 加列 + 建 `player_career_honors` + 重建 `player_bio` 视图（幂等） |
| 修改 | `sql/run_migrations.py` | `ordered` 列表追加 `007_add_player_bio_ext.sql`（置于 006 后） |
| 新增 | `common/player_bio_ext.py` | 抽取纯函数 + `fetch_player_page`（复用/包装 player_nickname）+ upsert 入库函数 |
| 新增 | `external_crawler/crawler/crawl_br_player_bio_ext.py` | 回填 crawler（`--resume/--limit/--dry-run/--rate`），DB 走 `config.db_dsn()` |
| 修改 | `backend/api/schemas.py` | `PlayerBio` 增字段 + `from_row` 读新列；新增 `PlayerHonor` / `PlayerHonorsResponse` |
| 修改 | `backend/api/routers/players.py` | 新增 `GET /players/{id}/honors` 端点（返回归一化荣誉） |
| 修改 | `backend/services/metric_engine/__init__.py` | 导出 `get_player_honors` 包装 |
| 修改 | `backend/data_layer/batch_loader.py` | 新增 `load_player_honors(player_id)`（SELECT FROM player_career_honors） |
| 新增 | `tests/test_player_bio_ext.py` | 各 `extract_*` 纯函数单测 + `upsert` mock 单测 |
| 新增 | `tests/fixtures/br_julius_erving.html` | 真实球员页快照（选择器复核回归基线） |
| 新增 | `docs/ARCH_player_bio_ext.md` | 本设计文档 |
| 新增 | `docs/player_bio_ext_class.mermaid` / `docs/player_bio_ext_sequence.mermaid` | 类图 / 时序图 |

---

## 4. 数据结构和接口（SQL DDL 草稿 + 表关系）

### 4.1 `sql/007_add_player_bio_ext.sql`（核心，幂等）

```sql
-- ============================================================================
-- 007_add_player_bio_ext.sql — 球员主数据维度增量
-- 幂等：IF NOT EXISTS / DROP+CREATE VIEW / CREATE TABLE IF NOT EXISTS
-- 安全：全部 nullable 在线 DDL；不改 awards / gamelog / pbp / headshots 任何逻辑
-- ============================================================================

-- (1) dim_players 加列（player_bio 是视图，新列只能落 dim_players）
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS aba_debut             date;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS died                date;   -- 离世日期（NULL=在世/未知），仅已故球员 BR 页有 Died: 行
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS hof_inducted_year     integer;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS hof_as                text;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS is_hall_of_famer     boolean;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS career_length_years  integer;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS relatives            text;
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS jersey_numbers        text[];
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS career_honors_text   text[];
ALTER TABLE public.dim_players ADD COLUMN IF NOT EXISTS bio_ext_scraped_at   timestamp without time zone;

-- (2) 新建归一化荣誉表（与 awards 三表解耦；awards 来自 seasonal 页面）
CREATE TABLE IF NOT EXISTS public.player_career_honors (
    id           bigserial PRIMARY KEY,
    player_id    text NOT NULL REFERENCES public.dim_players(player_id) ON DELETE CASCADE,
    honor_raw    text NOT NULL,          -- 原始文本: "16x All Star" / "1983 NBA Champ" / "Hall of Fame"
    honor_type   text NOT NULL,          -- 归一化枚举(见下)
    honor_count  integer,                -- "16x"→16；无次数→NULL
    honor_year   integer,                -- "1983 NBA Champ"→1983；"1993 HoF"→1993；无→NULL
    honor_detail text,                   -- 补充: HoF 的 "Player"；NBA 75th 的 "Team"
    source_url   text,
    scraped_at   timestamp without time zone DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pch_player ON public.player_career_honors(player_id);
CREATE INDEX IF NOT EXISTS idx_pch_type   ON public.player_career_honors(honor_type);

-- (3) 索引：resume 哨兵 + 名人堂过滤
CREATE INDEX IF NOT EXISTS idx_dp_bio_ext_ts ON public.dim_players(bio_ext_scraped_at);
CREATE INDEX IF NOT EXISTS idx_dp_hof        ON public.dim_players(is_hall_of_famer)
    WHERE is_hall_of_famer = true;

-- (4) 重建 player_bio 视图（含 nickname / headshot_* / 本次新列；SELECT * 同步机制）
DROP VIEW IF EXISTS public.player_bio;
CREATE VIEW public.player_bio AS
 SELECT player_id, player_name, full_name, pronunciation, "position", shoots,
        height_display, height_cm, weight_lbs, weight_kg, birth_date, birth_city,
        birth_state_country, nationality, college, high_school, recruiting_rank,
        draft_info, experience, nba_debut, source_url, scraped_at,
        nickname,                                  -- 来自 006
        headshot_path, headshot_url, headshot_status, headshot_scraped_at, -- 来自 headshots 增量
        aba_debut, died, hof_inducted_year, hof_as, is_hall_of_famer,
        career_length_years, relatives, jersey_numbers, career_honors_text,
        bio_ext_scraped_at
   FROM public.dim_players;

-- (5) 注释
COMMENT ON COLUMN public.dim_players.relatives           IS '亲属（BR 球员页 Relatives 行，多名逗号分隔）';
COMMENT ON COLUMN public.dim_players.aba_debut           IS 'ABA 首秀日期（NULL=从未打 ABA）';
COMMENT ON COLUMN public.dim_players.died              IS '离世日期（NULL=在世或未知）；仅已故球员 BR 页有 Died: 行';
COMMENT ON COLUMN public.dim_players.hof_inducted_year   IS '名人堂入选年份（NULL=非名人堂）';
COMMENT ON COLUMN public.dim_players.hof_as              IS '名人堂入选身份（Player/Coach/Contributor）';
COMMENT ON COLUMN public.dim_players.is_hall_of_famer    IS '是否名人堂（由 hof_inducted_year 派生，upsert 维护）';
COMMENT ON COLUMN public.dim_players.career_length_years IS '生涯长度（年），冗余存储 BR 页 Career Length';
COMMENT ON COLUMN public.dim_players.jersey_numbers      IS '生涯球衣号码（去重数组）';
COMMENT ON COLUMN public.dim_players.career_honors_text  IS '生涯荣誉清单（去重数组，player_career_honors 的展示镜像）';
```

`honor_type` 枚举取值（解析映射，存于 `common/player_bio_ext.parse_honor_line`）：
`hall_of_fame, all_star, nba_champ, aba_champ, all_nba, all_aba, all_defensive, all_rookie, mvp, as_mvp, aba_all_time_team, nba_75_team, mbwa_aba_poy, other`

### 4.2 表关系

```
dim_players (1) ──< (N) player_career_honors   [player_id FK, ON DELETE CASCADE]
dim_players (1) ──= (1) player_bio  [VIEW OVER dim_players]
awards 三表 (player_award_shares / all_star_selections / end_of_season_teams)
        ── 不改动，与 player_career_honors 平行（来源不同：seasonal 页 vs 球员页）
```

### 4.3 类 / 模块关系（详见 `docs/player_bio_ext_class.mermaid`）

- `PlayerBioExtExtractor`：纯函数 `extract_aba_debut / extract_died / extract_hof / extract_career_length / extract_relatives / extract_jersey_numbers / extract_honors / parse_honor_line` + `fetch_player_page`（复用 player_nickname）。
- `PlayerBioExtCrawler`：`get_players(resume)` / `upsert_player_bio_ext(conn,pid,data)` / `run_pipeline(...)`。
- 数据层：`dim_players`（UPDATE）+ `player_career_honors`（DELETE+INSERT）+ `player_bio`（VIEW）。
- API：`PlayerBio`（extends 新字段）/ `PlayerHonor` / `PlayerHonorsResponse` + `GET /players/{id}/honors`。

---

## 5. 程序调用流程（时序图，详见 `docs/player_bio_ext_sequence.mermaid`）

要点：
1. CLI 调 `crawl_br_player_bio_ext.py --resume`。
2. Crawler `get_players` 取 `bio_ext_scraped_at IS NULL` 的 player_id 列表。
3. 逐人：`fetch_player_page`（curl_cffi 直连，CF→None 跳过）→ `extract_*` 纯函数解析 → `upsert_player_bio_ext`：`UPDATE dim_players`（含 `bio_ext_scraped_at=now()`）+ `DELETE/INSERT player_career_honors` → `COMMIT`（per-player）。
4. `player_bio` 视图随 `dim_players` 加列自动暴露；`load_players` 用 `SELECT *` → `PlayerBio.from_row` 读新列；`/players/{id}/honors` 读 `player_career_honors`。

---

## 6. 任务列表 T01..T06（有序 + 依赖 + 可并行）

> 说明：团队主理人示例即 T01..T06（迁移→抽取→crawler→schemas→单测→回填），
> 故本设计按 6 个有序任务交付（放宽通用"≤5 任务"默认，以本任务明确结构为准）。
> 各任务按"层"划分；单文件任务（T03 crawler）已标注其依赖与消费方。

| ID | 任务 | Source Files | 依赖 | 优先级 | 可并行 |
|----|------|--------------|------|--------|--------|
| **T01** | 增量迁移 + runner 接线 + 设计文档 | `sql/007_add_player_bio_ext.sql`, `sql/run_migrations.py`, `docs/ARCH_player_bio_ext.md` | — | P0 | 否（基础） |
| **T02** | 抽取模块 + 离线单测（含 `extract_died`） | `common/player_bio_ext.py`, `tests/test_player_bio_ext.py`, `tests/fixtures/br_julius_erving.html`, `tests/fixtures/br_kobebry01.html`(已故样本) | T01（列定义） | P0 | 与 T03 并行 |
| **T03** | 回填 crawler | `external_crawler/crawler/crawl_br_player_bio_ext.py` | T01, T02 | P0 | 与 T02 并行 |
| **T04** | API 暴露（schemas 接线 + 荣誉端点） | `backend/api/schemas.py`, `backend/api/routers/players.py`, `backend/services/metric_engine/__init__.py`, `backend/data_layer/batch_loader.py` | T01 | P1 | 与 T02/T03 并行 |
| **T05** | 回归单测 + 选择器复核 | `tests/test_player_bio_ext.py`（扩）, `tests/fixtures/br_erninca01.html`（ABA 样本） | T02, T03 | P1 | — |
| **T06** | 执行回填（dry-run→resume 全量） | （无新文件，执行既有脚本） | T01–T05 | P0 | — |

依赖图：`T01 → {T02, T03, T04} → T05 → T06`。T02/T03/T04 互不依赖，可并行实现。

---

## 7. 依赖包列表

**零新增**。复用：`psycopg2`（DB）、`curl_cffi`（抗 CF 直连）、`beautifulsoup4`（荣誉块/亲属行解析）、`requests`（回退）。Python 标准库（`argparse`/`re`/`time`/`random`）足够。

---

## 8. 共享知识（跨文件约定）

- **DB 连接**：crawler 一律 `psycopg2.connect(backend.core.config.db_dsn())`，**不硬编码**弱口令；口令从 `.env` 的 `DB_PASSWORD` 经 `config` 注入（参照 `crawl_br_nicknames._connect`）。headshots crawler 的 `DB_CONFIG` 字典硬编码 host/port 是旧范式，本次统一改为 `db_dsn()`。
- **CF 直连范式**：`fetch_player_page` 优先 curl_cffi `impersonate="chrome124"`，遇 403 / "Just a moment" / "Checking your browser" → 返回 `None`，**绝不抛异常、绝不崩**；不触碰 9222 Chrome。
- **resume 模式**：以 `dim_players.bio_ext_scraped_at IS NULL` 为哨兵，跳过已抓行；抓取失败保留 NULL 以便重试。
- **限速**：基础 3.0s ±1s 随机抖动（`time.sleep(max(0.5, rate-1+random.uniform(0,2)))`），单人异常不中断整体。
- **per-entity commit**：每人独立 `conn.commit()`，`resume` 安全、可中断续跑。
- **在线 DDL 安全**：加列全 `IF NOT EXISTS` + nullable；**不重启 5433 PG、不杀 9222 Chrome**。
- **事务一致性**：荣誉写入为「同一 player_id 事务内 `DELETE player_career_honors` + `INSERT` + `UPDATE dim_players` + `UPDATE career_honors_text`」，避免表与镜像漂移。
- **视图重建**：每次加列后必须 `DROP VIEW + CREATE VIEW player_bio`，否则视图不暴露新列。

---

## 9. 待明确事项 / 选择器复核清单

以下抽取点的**精确选择器**需对 1~2 个真实 BR 球员页实测确定（用 `common/player_nickname.fetch_player_page` 直连保存 HTML 到 `tests/fixtures/` 后，用 BeautifulSoup 定位）：

| 字段 | 已知线索 | 待复核选择器 | 验证方法 |
|------|----------|--------------|----------|
| Relatives | "Relatives: Cousin Jeff Halliburton" 在 `#info` | 文本以 "Relatives:" 开头的 `<p>`/`<li>` | `soup.find(string=re.compile(r'^Relatives:'))` 的父节点 |
| ABA Debut | "ABA Debut: October 15, 1971" 与 NBA Debut 并列 | `#info` meta 行（`<p>` 含 "ABA Debut:"） | 同 Relatives 文本定位法 |
| Died（离世） | "Died: January 26, 2020 (aged 41) in Calabasas, CA"（**仅已故球员**） | `#info` meta 行（`<p>` 含 "Died:"）；在世球员无此行 → NULL | 文本定位 + 正则抽 `(\w+ \d+, \d{4})`；样本 `bryanko01` 实测 |
| Hall of Fame | "Hall of Fame: Inducted as Player in 1993" | `#info` meta 行（含 "Hall of Fame:"） | 文本定位 + 正则抽 `as (\w+) in (\d{4})` |
| Career Length | "Career Length: 16 years" | `#info` meta 行 | 文本定位 + 正则 `(\d+) years` |
| **Honors 块** | 清单：Hall of Fame / 16x All Star / 1983 NBA Champ / … | **容器未知**（疑 `#info` 底部 `<ul>` 或专门 "Honors" 区块） | 保存 HTML，搜 "All Star" / "NBA Champ" 上下文容器 |
| **Jersey 号码** | 32/32/6/6（重复） | **容器未知**（疑某 `<ul>` 或区块，每 stint 一项） | 保存 HTML，搜数字列表容器；确认是否含球队/赛季信息 |

**验证命令（设计，不执行）**：
```bash
.venv/bin/python - <<'PY'
from common.player_nickname import fetch_player_page
html = fetch_player_page("ervinju01")   # Julius Erving
open("tests/fixtures/br_julius_erving.html","w").write(html or "")
html2 = fetch_player_page("grunfer01")  # Ernie Grunfeld（含 ABA，验证 ABA Debut/ABA Champ）
open("tests/fixtures/br_erninca01.html","w").write(html2 or "")
PY
```
随后在 `tests/test_player_bio_ext.py` 中对 fixture 断言各 `extract_*`，固化选择器。

---

## 10. 爬取计划

### 10.1 复用「独立回填 crawler + --resume」范式
完全照搬 `crawl_br_nicknames.py`：独立进程、独立单实例文件锁（`.crawl_br_player_bio_ext.lock`）、`--resume` 跳过 `bio_ext_scraped_at IS NOT NULL`、per-player commit、限速、CF 优雅 None。

### 10.2 是否并入 nba_daily_crawler 的 player_bio 占位？
**本次不并入。** 理由：
- `nba_daily_crawler.py:710` 的 `'player_bio'` 规则是**未实现占位**（无 `crawl_player_bio` 方法），且它跑在 9222 Chrome / UC 会话里；bio_ext 走 curl_cffi 直连，范式不同。
- 独立脚本与在跑的 daily crawler / gamelog / pbp / awards 爬虫**零写冲突**（见 10.4）。
- **未来可选增强**：在 `nba_daily_crawler` 注册 `crawl_player_bio_ext` 方法并让 `player_bio` 规则调用，做每日增量刷新——但非本次范围。

### 10.3 回填命令示例
```bash
# 1) 应用迁移（含 007，置于 006 后）
.venv/bin/python sql/run_migrations.py

# 2) 先 dry-run 验证流程（不抓不写）
.venv/bin/python external_crawler/crawler/crawl_br_player_bio_ext.py --limit 5 --dry-run

# 3) 小批量实测
.venv/bin/python external_crawler/crawler/crawl_br_player_bio_ext.py --limit 50 --resume

# 4) 全量回填（跳过已抓）
.venv/bin/python external_crawler/crawler/crawl_br_player_bio_ext.py --resume
```

### 10.4 与在跑爬虫的零冲突保证
1. **独立进程 + 文件锁**：单实例运行，避免自身重复。
2. **写表隔离**：仅 `UPDATE dim_players`（新列）/ `DELETE+INSERT player_career_honors`。这些表/列**不被** daily crawler 的 player_bio 占位（未实现）、gamelog、pbp、awards 爬虫写入 → 无写竞争。
3. **在线 DDL 安全**：`ADD COLUMN IF NOT EXISTS` 全 nullable，对 5433 在线实例毫秒级、不加锁重写（除 `is_hall_of_famer` 为普通布尔列，无表重写）。
4. **不碰 9222 Chrome / 不重启 5433 PG**：纯 curl_cffi 直连。
5. **resume + per-player commit**：可随时中断，重启续跑，不丢不重。
6. **限流友好**：3s±1s，对 BR 压力与既有爬虫叠加可控。

---

## 附：决策速查表

| 缺口 | 落点 | 类型 | 备注 |
|------|------|------|------|
| Relatives | dim_players.relatives | text | 逗号分隔，不结构化 |
| ABA Debut | dim_players.aba_debut | date | NULL=无 ABA |
| Died（离世） | dim_players.died | date | NULL=在世/未知；仅已故球员有 Died: 行 |
| Hall of Fame | dim_players.hof_inducted_year + hof_as + is_hall_of_famer | int+text+bool | 部分索引过滤 |
| Career Length | dim_players.career_length_years | int | 冗余存储 BR 值 |
| Honors | player_career_honors（表）+ dim_players.career_honors_text[]（镜像） | 表+数组 | 归一化查询 + 展示 |
| Jersey | dim_players.jersey_numbers | text[] | 去重数组，不建表 |
