-- 全量(8,071)统一 NBA-API 解码复核: 首位数分布 + 解码赛季范围
SET max_parallel_workers_per_gather=0;

WITH orph AS (
  SELECT game_id_full,
         SUBSTRING(game_id_full FROM 1 FOR 1) AS type_digit,
         CAST(SUBSTRING(game_id_full FROM 2 FOR 2) AS int) AS yy
  FROM player_gamelog
  WHERE season IS NULL AND game_id_full IS NOT NULL AND game_id_full ~ '^[0-9]{8}'
    AND NOT EXISTS (SELECT 1 FROM dim_games dg WHERE dg.game_id = game_id_full AND dg.season IS NOT NULL)
),
dec AS (
  SELECT game_id_full, type_digit,
         CASE WHEN yy < 50 THEN 2000 + yy + 1 ELSE 1900 + yy + 1 END AS decoded_season
  FROM orph
)
SELECT 'type_digit_dist' AS chk, type_digit AS val, COUNT(*) AS n
FROM orph GROUP BY type_digit ORDER BY type_digit;

SELECT 'decoded_season_dist' AS chk, decoded_season::text AS val, COUNT(*) AS n
FROM dec GROUP BY decoded_season ORDER BY decoded_season;

SELECT 'out_of_range' AS chk,
       COUNT(*) FILTER (WHERE decoded_season NOT BETWEEN 1997 AND 2026) AS bad,
       COUNT(*) AS total
FROM dec;
