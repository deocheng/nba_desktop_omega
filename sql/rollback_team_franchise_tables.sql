-- 回滚脚本：删除本次新建的 6 张 franchise 页表（如需撤销）
-- 仅在用户明确确认放弃该数据集时执行。
DROP TABLE IF EXISTS team_franchise_stats    CASCADE;
DROP TABLE IF EXISTS team_franchise_players  CASCADE;
DROP TABLE IF EXISTS team_franchise_numbers  CASCADE;
DROP TABLE IF EXISTS team_franchise_head2head CASCADE;
DROP TABLE IF EXISTS team_franchise_hof      CASCADE;
DROP TABLE IF EXISTS team_franchise_all_star CASCADE;
-- franchise 主页 franchise 页（第 18 类，/teams/{slug}/）
DROP TABLE IF EXISTS team_franchise_index     CASCADE;
DROP TABLE IF EXISTS team_franchise_coaches   CASCADE;
DROP TABLE IF EXISTS team_franchise_playoffs  CASCADE;
-- 若仅需撤销 coaches 列（保留表）：ALTER TABLE team_franchise_index DROP COLUMN coaches;
