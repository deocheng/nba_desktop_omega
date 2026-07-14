#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Import NBA Draft Combine data (weight/height/wingspan) from CSV to PostgreSQL.
Then match to BR player_id via name matching.

Source: CSV/1947/csv/draft_combine_stats.csv (1202 records, 2001-2023)
"""
import csv
import re
import logging
import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CombineImport")

DB_CONFIG = {
    "host": "localhost", "port": 5433,
    "dbname": "nba", "user": "postgres", "password": "postgres",
}

CSV_PATH = "CSV/1947/csv/draft_combine_stats.csv"


def safe_float(val):
    if not val or val.strip() == '':
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def safe_int(val):
    f = safe_float(val)
    return int(f) if f is not None else None


def parse_height_to_cm(height_str):
    """Convert '6' 11.5''' to cm. Or return raw if unparseable."""
    if not height_str:
        return None
    # Format: "6' 11.5''"
    m = re.match(r"(\d+)'\s*([\d.]+)''", height_str)
    if m:
        feet = int(m.group(1))
        inches = float(m.group(2))
        return round(feet * 30.48 + inches * 2.54)
    return None


def main():
    # Read CSV
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    logger.info(f"Read {len(rows)} records from CSV")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Create draft_combine table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS draft_combine (
            id SERIAL PRIMARY KEY,
            season INTEGER NOT NULL,
            nba_player_id INTEGER,
            player_name TEXT NOT NULL,
            position VARCHAR(5),
            height_wo_shoes_cm INTEGER,
            height_wo_shoes_display TEXT,
            height_w_shoes_cm INTEGER,
            height_w_shoes_display TEXT,
            weight_lbs NUMERIC,
            wingspan_cm NUMERIC,
            standing_reach_cm NUMERIC,
            body_fat_pct NUMERIC,
            standing_vertical_leap NUMERIC,
            max_vertical_leap NUMERIC,
            lane_agility_time NUMERIC,
            three_quarter_sprint NUMERIC,
            bench_press INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(season, player_name)
        )
    """)
    conn.commit()

    # Clear existing
    cur.execute("TRUNCATE draft_combined CASCADE" if False else "DELETE FROM draft_combine")
    conn.commit()

    # Insert
    batch = []
    for r in rows:
        batch.append((
            int(r['season']),
            safe_int(r['player_id']),
            r['player_name'].strip(),
            r.get('position', '').strip() or None,
            parse_height_to_cm(r.get('height_wo_shoes_ft_in', '')),
            r.get('height_wo_shoes_ft_in', '').strip() or None,
            parse_height_to_cm(r.get('height_w_shoes_ft_in', '')),
            r.get('height_w_shoes_ft_in', '').strip() or None,
            safe_float(r.get('weight', '')),
            safe_float(r.get('wingspan', '')),
            safe_float(r.get('standing_reach', '')),
            safe_float(r.get('body_fat_pct', '')),
            safe_float(r.get('standing_vertical_leap', '')),
            safe_float(r.get('max_vertical_leap', '')),
            safe_float(r.get('lane_agility_time', '')),
            safe_float(r.get('three_quarter_sprint', '')),
            safe_int(r.get('bench_press', '')),
        ))

    execute_batch(cur, """
        INSERT INTO draft_combine
            (season, nba_player_id, player_name, position,
             height_wo_shoes_cm, height_wo_shoes_display,
             height_w_shoes_cm, height_w_shoes_display,
             weight_lbs, wingspan_cm, standing_reach_cm,
             body_fat_pct, standing_vertical_leap, max_vertical_leap,
             lane_agility_time, three_quarter_sprint, bench_press)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (season, player_name) DO NOTHING
    """, batch, page_size=200)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM draft_combine")
    combine_count = cur.fetchone()[0]
    logger.info(f"Combine table now has {combine_count} records")

    # Now match to BR player_id via name
    logger.info("Matching combine data to BR player_id...")
    cur.execute("""
        UPDATE player_weight_history pwh
        SET weight_lbs = dc.weight_lbs,
            height = dc.height_wo_shoes_display
        FROM draft_combine dc
        JOIN player_per_game ppg ON LOWER(dc.player_name) = LOWER(ppg.player)
        WHERE pwh.player_id = ppg.player_id
          AND pwh.weight_lbs IS NULL
          AND dc.weight_lbs IS NOT NULL
    """)
    updated = cur.rowcount
    logger.info(f"Updated {updated} existing weight records from combine data")

    # Insert new players from combine that aren't in weight_history yet
    cur.execute("""
        INSERT INTO player_weight_history (player_id, player_name, weight_lbs, height)
        SELECT DISTINCT ON (ppg.player_id)
               ppg.player_id, ppg.player,
               ROUND(dc.weight_lbs::numeric)::int,
               dc.height_wo_shoes_display
        FROM draft_combine dc
        JOIN player_per_game ppg ON LOWER(dc.player_name) = LOWER(ppg.player)
        WHERE dc.weight_lbs IS NOT NULL
          AND ppg.player_id NOT IN (SELECT player_id FROM player_weight_history)
        ORDER BY ppg.player_id, dc.season DESC
        ON CONFLICT (player_id) DO UPDATE SET
            weight_lbs = EXCLUDED.weight_lbs,
            height = EXCLUDED.height
    """)
    inserted = cur.rowcount
    conn.commit()
    logger.info(f"Inserted {inserted} new weight records from combine data")

    # Also need to handle the weight_lbs type: combine has NUMERIC, weight_history has INTEGER
    # Cast the weight_lbs to integer for any records that have decimal values
    cur.execute("""
        UPDATE player_weight_history
        SET weight_lbs = ROUND(weight_lbs::numeric)::int
        WHERE weight_lbs IS NOT NULL
    """)
    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) FROM draft_combine WHERE weight_lbs IS NOT NULL")
    combine_with_weight = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM player_weight_history WHERE weight_lbs IS NOT NULL")
    weight_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT player_id) FROM player_per_game")
    total_players = cur.fetchone()[0]

    logger.info("=" * 60)
    logger.info(f"Combine records with weight: {combine_with_weight}")
    logger.info(f"player_weight_history with weight: {weight_total}")
    logger.info(f"Total players in DB: {total_players}")
    logger.info(f"Coverage: {weight_total}/{total_players} = {weight_total/total_players*100:.1f}%")
    logger.info("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
