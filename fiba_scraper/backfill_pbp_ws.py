"""Backfill play_by_play for FIBA games via the Azure Web PubSub replay.

DISCOVERY (2026-08-28, CORRECTED understanding):
  FIBA serves play-by-play through its Azure Web PubSub live-stats hub. The public
  REST route `/en/events/api/game-live-info/{id}/detail` returns
  {"game":{"content":null}} for games whose live window has closed, so it cannot
  backfill old games on its own. But when FIBA's competition backend is ACTIVE
  (i.e. during a live window for that competition -- games are being played), joining
  a game's group replays its periodActions. Group name = "game-<gameId>" (detail).
  Each replayed `groupMessage` carries {message:<gzip+base64>, fileType:"periodactions"}.
  Decode = atob(decodeURIComponent(b64)) -> gzip -> json  (== periodActions.content).

  The user PROVED old games DO have PBP (captured 127604 SWE-CZE, played 2026-07-04,
  full PBP at 21:49 during a live window). So historical PBP is recoverable -- but
  ONLY by running this during a live window.

  CONNECTION NOTES (empirically verified 2026-08-28):
   - Token from /en/events/api/websocket-token?isLive=true grants role
     "webpubsub.joinLeaveGroup" (join is allowed).
   - joinGroup MUST be sent immediately after the WS handshake, BEFORE reading the
     server's "connected" event. (Sending it after "connected" triggers a 1002 close.)
   - joinGroup is acked with {"type":"ack","success":true}.
   - Idle connections are dropped by Azure after ~2.6s (no CLOSE frame, just TCP FIN).
     During a live window the backend publishes continuously, so the connection stays
     alive and periodactions flow. => Reconnect fast when data flows; back off when idle.

Usage:
  backfill_pbp_ws.py [--competition-id 208943] [--capture-seconds 14400]
                     [--rejoin-interval 120] [--idle-backoff 15] [--force]
                     [--games 127604,127081] [--manifest /path/manifest.json]
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.request
from urllib.parse import unquote, urlparse

import fiba_api as fa
import fiba_db

APIM_KEY = "898cd5e7389140028ecb42943c47eb74"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


# ---------------------------------------------------------------------------
# Raw WebSocket client (Azure Web PubSub, json.webpubsub.azure.v1)
# ---------------------------------------------------------------------------
def get_ws_url():
    url = "https://www.fiba.basketball/en/events/api/websocket-token?isLive=true"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Ocp-Apim-Subscription-Key": APIM_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["url"]


def _recv_frames(ss, buf=b""):
    while True:
        if len(buf) < 2:
            c = ss.recv(65536)
            if not c:
                return
            buf += c
            continue
        b0, b1 = buf[0], buf[1]
        fin = (b0 & 0x80) >> 7
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) >> 7
        length = b1 & 0x7F
        idx = 2
        if length == 126:
            if len(buf) < idx + 2:
                buf += ss.recv(65536); continue
            length = struct.unpack(">H", buf[idx:idx+2])[0]; idx += 2
        elif length == 127:
            if len(buf) < idx + 8:
                buf += ss.recv(65536); continue
            length = struct.unpack(">Q", buf[idx:idx+8])[0]; idx += 8
        if masked:
            if len(buf) < idx + 4:
                buf += ss.recv(65536); continue
            mk = buf[idx:idx+4]; idx += 4
        else:
            mk = None
        if len(buf) < idx + length:
            buf += ss.recv(65536); continue
        payload = buf[idx:idx+length]
        if masked:
            payload = bytes(payload[i] ^ mk[i % 4] for i in range(len(payload)))
        buf = buf[idx+length:]
        yield (fin, opcode, payload)


def _decode_msg(b64str):
    """Mirror JS r(e): atob(decodeURIComponent(e)) -> gzip -> bytes."""
    raw = base64.b64decode(unquote(b64str))
    try:
        return gzip.decompress(raw)
    except Exception:
        try:
            return base64.b64decode(unquote(b64str))
        except Exception:
            return raw


def _send_json(ss, obj):
    body = json.dumps(obj).encode()
    mk = os.urandom(4)
    masked = bytes(body[i] ^ mk[i % 4] for i in range(len(body)))
    if len(body) < 126:
        ss.sendall(bytes([0x81, 0x80 | len(body)]) + mk + masked)
    else:
        ss.sendall(bytes([0x81, 0xFE]) + struct.pack(">H", len(body)) + mk + masked)


def _connect(host, port, path):
    s = socket.create_connection((host, port), timeout=15)
    ss = ssl.create_default_context().wrap_socket(s, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    ss.sendall(
        f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: json.webpubsub.azure.v1\r\n\r\n".encode())
    hbuf = b""
    while b"\r\n\r\n" not in hbuf:
        hbuf += ss.recv(1024)
    _, _, rest = hbuf.partition(b"\r\n\r\n")
    return ss, rest


def _try_parse(obj):
    if isinstance(obj, dict) and "items" in obj:
        return obj
    return None


def capture_groups(game_ids, capture_seconds=14400, rejoin_interval=120,
                   idle_backoff=15, manifest_path=None):
    """Join each game's 'game-<id>' group; capture periodactions replays.
    Adaptive: reconnect fast (2s) when data flowed this cycle (window open),
    back off (idle_backoff) when idle. Returns (results, manifest)."""
    ws_url = get_ws_url()
    p = urlparse(ws_url)
    host, port = p.hostname, p.port or 443
    path = p.path + (("?" + p.query) if p.query else "")

    results = {}
    manifest = {}  # gid -> {quarters:[...], events:N}
    ack_no = 1
    start = time.time()
    last_rejoin = start - rejoin_interval

    while time.time() - start < capture_seconds:
        if not [g for g in game_ids if g not in results]:
            break
        try:
            ss, rest = _connect(host, port, path)
        except Exception as e:
            print("[connect err]", e)
            time.sleep(5)
            continue
        # join IMMEDIATELY (before reading the 'connected' event) -- required by Azure
        pending = [g for g in game_ids if g not in results]
        for gid in pending:
            _send_json(ss, {"type": "joinGroup", "group": f"game-{gid}", "ackId": ack_no})
            ack_no += 1
        last_rejoin = time.time()
        print(f"[joined] {len(pending)} games (captured {len(results)}/{len(game_ids)})")

        ss.settimeout(2.0)
        gen = _recv_frames(ss, rest)
        captured_this_cycle = 0
        try:
            while time.time() - start < capture_seconds:
                if time.time() - last_rejoin >= rejoin_interval:
                    pending = [g for g in game_ids if g not in results]
                    if pending:
                        for gid in pending:
                            _send_json(ss, {"type": "joinGroup", "group": f"game-{gid}",
                                            "ackId": ack_no})
                            ack_no += 1
                        last_rejoin = time.time()
                        print(f"[rejoin] {len(pending)} uncaptured games")
                try:
                    fin, opcode, payload = next(gen)
                except StopIteration:
                    break
                except socket.timeout:
                    continue
                if opcode == 0x9:  # ping -> pong
                    ss.sendall(bytes([0x8A, len(payload)]) + payload)
                    continue
                if opcode == 0xA:  # pong
                    continue
                if opcode not in (0x1, 0x2):
                    continue
                try:
                    evt = json.loads(payload.decode("utf-8", "replace"))
                except Exception:
                    continue
                if evt.get("type") != "groupMessage":
                    continue
                data = evt.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                if not isinstance(data, dict) or "message" not in data:
                    continue
                if data.get("fileType") != "periodactions":
                    continue
                grp = evt.get("group", "")
                gid = grp.replace("game-", "").replace("gamelite-", "")
                if not gid.isdigit():
                    continue
                gid = int(gid)
                dec = _decode_msg(data["message"])
                try:
                    obj = json.loads(dec) if isinstance(dec, (bytes, bytearray)) else dec
                except Exception:
                    obj = None
                parsed = _try_parse(obj)
                if parsed is None:
                    print(f"[unparsed] group={grp} raw[:120]={str(dec)[:120]}")
                    continue
                results[gid] = parsed
                qs = list(parsed.get("items", {}).keys())
                nev = sum(len(v.get("items", [])) for v in parsed.get("items", {}).values()
                          if isinstance(v, dict))
                manifest[gid] = {"quarters": qs, "events": nev}
                captured_this_cycle += 1
                print(f"[captured] game-{gid} quarters={qs} events={nev} "
                      f"(total {len(results)}/{len(game_ids)})")
        except Exception as e:
            print("[conn err]", e)
        finally:
            try:
                ss.close()
            except Exception:
                pass
        # adaptive backoff
        if captured_this_cycle > 0:
            time.sleep(2)
        else:
            time.sleep(idle_backoff)

    if manifest_path:
        try:
            with open(manifest_path, "w") as f:
                json.dump({"captured": manifest,
                           "captured_count": len(results),
                           "total": len(game_ids),
                           "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=2)
            print(f"[manifest] wrote {manifest_path}")
        except Exception as e:
            print("[manifest err]", e)
    return results, manifest


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------
def _si(d, k):
    v = d.get(k)
    return None if v is None else int(v)


def _org_id(v):
    return None if v is None else int(v)


def _player_id(v):
    return None if v is None else int(v)


def load_game_pbp(conn, gid, content):
    """content == periodActions.content == {items:{Q1:{items:[...]}}}. Mirror
    batch_scrape_fiba.py load so row shape matches the 6 already-stored games."""
    pbp = fa.parse_play_by_play({"periodActions": {"content": content}})
    if not pbp:
        return 0
    rows = []
    for e in pbp:
        shot = e.get("act") == "shot"
        rows.append((
            gid, e.get("quarter"), _si(e, "order"), e.get("Time"),
            _si(e, "GT"), _si(e, "SA"), _si(e, "SB"), e.get("act"), e.get("ac"),
            e.get("txt"),
            e.get("made") if shot else None,
            _si(e, "pts") if shot else None,
            _si(e, "x") if shot else None,
            _si(e, "y") if shot else None,
            _org_id(e.get("oId")), _player_id(e.get("pId")),
            json.dumps(e, ensure_ascii=False),
        ))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM play_by_play WHERE game_id=%s", (gid,))
        sql = ("INSERT INTO play_by_play (game_id, quarter, seq_order, event_time, "
               "gt_epoch, score_a, score_b, act, action_code, description, made, pts, "
               "x, y, org_id, player_id, raw) VALUES %s")
        fiba_db.extras.execute_values(cur, sql, rows, page_size=200)
        cur.execute("UPDATE games SET pbp_loaded=TRUE WHERE game_id=%s", (gid,))
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--competition-id", type=int, default=208943)
    ap.add_argument("--capture-seconds", type=int, default=14400)
    ap.add_argument("--rejoin-interval", type=int, default=120)
    ap.add_argument("--idle-backoff", type=int, default=15)
    ap.add_argument("--force", action="store_true", help="re-capture already-loaded games")
    ap.add_argument("--games", type=str, default="", help="comma list of game_ids to limit to")
    ap.add_argument("--manifest", type=str, default="", help="path to write JSON manifest")
    args = ap.parse_args()

    conn = fiba_db.get_conn()
    if args.games:
        game_ids = [int(x) for x in args.games.split(",") if x.strip()]
    else:
        cur = conn.cursor()
        cur.execute("SELECT game_id FROM games WHERE competition_id=%s", (args.competition_id,))
        game_ids = [r[0] for r in cur.fetchall()]
    if not args.force:
        cur = conn.cursor()
        cur.execute("SELECT game_id FROM games WHERE competition_id=%s AND pbp_loaded",
                    (args.competition_id,))
        loaded = {r[0] for r in cur.fetchall()}
        game_ids = [g for g in game_ids if g not in loaded]
    print(f"[plan] capturing PBP for {len(game_ids)} games (comp {args.competition_id})")

    captured, manifest = capture_groups(
        game_ids, capture_seconds=args.capture_seconds,
        rejoin_interval=args.rejoin_interval, idle_backoff=args.idle_backoff,
        manifest_path=args.manifest or None)

    print(f"[capture done] {len(captured)}/{len(game_ids)} games returned periodactions")

    ok = 0
    for gid, content in captured.items():
        n = load_game_pbp(conn, gid, content)
        ok += 1
        print(f"[loaded] game-{gid}: {n} pbp rows")
    conn.close()
    print(f"=== backfill complete: {ok} games loaded, "
          f"{len(game_ids)-ok} not captured (run again during a live window) ===")


if __name__ == "__main__":
    main()
