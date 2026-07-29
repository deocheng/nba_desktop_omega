"""CF 探针：用默认(headless Playwright)后端尝试抓一个 BR 球员页，
判断当前无头通道能否过 Cloudflare。若打印 CLEARED → 无头可用；
若 CF_CHALLENGE_RAISED → 无头被拦，需切 CDP(用户浏览器 9222)。"""
import sys, time, os
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))
from common.browser import get_driver, CFChallengeError  # noqa: E402

# 清掉上次爬行的旧 flag，保证本次判定干净
_FLAG = "/tmp/br_cf_challenge.flag"
if os.path.exists(_FLAG):
    try:
        os.remove(_FLAG)
    except Exception:  # noqa: BLE001
        pass
_RESULT = "/tmp/cf_probe_result.txt"
try:
    os.remove(_RESULT)
except Exception:  # noqa: BLE001
    pass

print("BUILDING DRIVER...", flush=True)
drv = get_driver()
url = "https://www.basketball-reference.com/players/a/abdelal01.html"
print("GET", url, flush=True)
t0 = time.time()
try:
    drv.get(url)
    src = drv.page_source
    print(
        f"CLEARED in {round(time.time() - t0, 1)}s; LEN={len(src)} "
        f"NICKFAQ={'Nickname' in src}",
        flush=True,
    )
    with open(_RESULT, "w") as _f:
        _f.write(f"CLEARED len={len(src)} nickfaq={'Nickname' in src}\n")
except CFChallengeError as e:
    print("CF_CHALLENGE_RAISED:", e, flush=True)
    with open(_RESULT, "w") as _f:
        _f.write("CHALLENGED\n")
except Exception as e:  # noqa: BLE001
    print("OTHER_ERR:", type(e).__name__, e, flush=True)
    with open(_RESULT, "w") as _f:
        _f.write(f"OTHER: {type(e).__name__} {e}\n")
