-- 看 play_by_play 是否含这些孤儿 ID 且带 season/日期可佐证
SET max_parallel_workers_per_gather=0;

-- play_by_play 关键列(确认有 gameid / season / 日期)
SELECT column_name || ' ' || data_type
FROM information_schema.columns
WHERE table_schema='public' AND table_name='play_by_play'
  AND (column_name ILIKE '%game%' OR column_name ILIKE '%season%' OR column_name ILIKE '%date%')
ORDER BY ordinal_position;

-- 这些孤儿 ID 是否出现在 play_by_play.gameid
SELECT 'orphan_in_pbp' AS chk, COUNT(DISTINCT gl.game_id_full) AS distinct_ids
FROM player_gamelog gl
WHERE gl.season IS NULL AND gl.game_id_full ~ '^[0-9]{8}'
  AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
  AND EXISTS (SELECT 1 FROM play_by_play pbp WHERE pbp.gameid::text = gl.game_id_full);

-- play_by_play 中这些 ID 的 season 分布(若有, 即权威佐证)
SELECT pbp.season, COUNT(*) AS n
FROM play_by_play pbp
WHERE EXISTS (
  SELECT 1 FROM player_gamelog gl
  WHERE gl.season IS NULL AND gl.game_id_full = pbp.gameid::text
    AND gl.game_id_full ~ '^[0-9]{8}'
    AND SUBSTRING(gl.game_id_full FROM 1 FOR 8) !~ '^[0-9]{4}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$'
)
GROUP BY pbp.season ORDER BY pbp.season;
