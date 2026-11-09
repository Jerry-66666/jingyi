# -*- coding: utf-8 -*-
"""
new Env('精易签到');
cron: 20 7 * * *
精易论坛每日签到 —— 青龙面板版 v2
站点已从 bbs.125.la 迁移到 bbs.ijingyi.com（老域名 301 跳转到新站）

环境变量
  JY_COOKIE   必填。格式  formhash@cookie
              多账号用换行（或多值分隔符 &）分开，每个账号一行；
              想给账号起名字写成  备注#formhash@cookie
              例：
                小小#40bd1d8c@xxx_2132_auth=xxxx; xxx_2132_saltkey=yyyy
  JY_QDXQ     选填。签到心情，默认 kx（开心）。可选：kx ng ymwl ch
  JY_SAY      选填。签到留言，默认空
  JY_RETRY    选填。单个账号最多尝试次数，默认 3
  JY_HOST     选填。站点域名，默认 bbs.ijingyi.com；站点再换域名时改这里
  JY_DEBUG    选填。填 1 时打印接口原始返回，排错用

抓包提醒
  1. 浏览器登录 bbs.ijingyi.com，F12 抓签到请求的 formhash 与 Cookie；
  2. Cookie 里不要带 __ancc_tokenV2（脚本会自己取，带着反而失效）；
  3. Cookie 只需保留 xxx_2132_ 开头的那几段即可。
"""

import datetime
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:  # 青龙镜像自带 requests，本机自测时给出明确提示
    print("缺少 requests 依赖，请先执行: pip install requests")
    raise SystemExit(1)

try:  # 青龙自带通知模块，没有时退化为纯打印
    from notify import send as _notify_send
except Exception:  # noqa: BLE001
    _notify_send = None

# 站点域名：2025 年起精易论坛迁到 bbs.ijingyi.com，老域名 bbs.125.la 已 301 跳转过去
HOST = os.getenv("JY_HOST", "bbs.ijingyi.com").strip() or "bbs.ijingyi.com"
SIGN_PAGE = "https://%s/plugin.php?id=dsu_paulsign:sign" % HOST
SIGN_API = "https://%s/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1" % HOST
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 20
DEBUG = os.getenv("JY_DEBUG", "").strip() == "1"

MSG_PREFIX = "本通知 By HY-jingyi（v2）"


def log(text):
    print(text, flush=True)


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def notify(title, content):
    """发送通知；没有 notify 模块或发送失败都不影响主流程。"""
    if not _notify_send:
        return
    try:
        _notify_send(title, "%s\n\n%s\n通知时间: %s" % (content, MSG_PREFIX, now_str()))
    except Exception as exc:  # noqa: BLE001
        log("通知发送失败: %s" % exc)


# ---------------------------------------------------------------- 账号解析


def parse_accounts(raw):
    """把 JY_COOKIE 拆成 [{'name','formhash','cookie'}]，兼容旧版单账号格式。"""
    text = (raw or "").replace("\u3000", " ").replace("\r", "")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # 青龙多值环境变量默认用 & 分隔；只在整体没有换行且出现多个 @ 时才按 & 拆
    if len(lines) == 1 and lines[0].count("@") > 1 and "&" in lines[0]:
        lines = [seg.strip() for seg in lines[0].split("&") if seg.strip()]

    accounts = []
    for index, line in enumerate(lines, start=1):
        name = "账号%d" % index
        chunk = line
        # 备注#formhash@cookie
        if "#" in line.split("@")[0]:
            name, chunk = line.split("#", 1)
            name = name.strip() or name
        if "@" not in chunk:
            accounts.append(
                {"name": name, "formhash": "", "cookie": "", "error": "格式不对，应为 formhash@cookie"}
            )
            continue
        formhash, cookie = chunk.split("@", 1)
        formhash = formhash.strip()
        cookie = cookie.strip().strip(";").strip()
        if not cookie:
            accounts.append({"name": name, "formhash": formhash, "cookie": "", "error": "Cookie 为空"})
            continue
        accounts.append({"name": name, "formhash": formhash, "cookie": cookie, "error": ""})
    return accounts


def cookie_to_dict(cookie_str):
    """'a=b; c=d' -> {'a': 'b', 'c': 'd'}，值里含 = 也能正确切分。"""
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


# ---------------------------------------------------------------- HTTP 工具


def build_session(cookie_str):
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    for key, value in cookie_to_dict(cookie_str).items():
        # 旧的 __ancc_tokenV2 一律丢掉，由脚本自己向站点取新的
        if key.lower().startswith("__ancc"):
            continue
        sess.cookies.set(key, value, domain=HOST)
    return sess


TOKEN_RE = re.compile(r"__ancc_tokenV2[^;]{0,160}?['\"]([A-Za-z0-9%_\-\.]{16,})['\"]")


def grab_token(sess, text):
    """从加速乐返回的 JS 或 Set-Cookie 里取出 __ancc_tokenV2，取到就写回会话。"""
    token = sess.cookies.get("__ancc_tokenV2", domain=HOST)
    if token:
        return token
    token = sess.cookies.get("__ancc_tokenV2")
    if token:
        return token
    if text:
        match = TOKEN_RE.search(text)
        if match:
            token = match.group(1)
            sess.cookies.set("__ancc_tokenV2", token, domain=HOST)
            return token
    return None


FORMHASH_RES = (
    re.compile(r'name="formhash"\s+value="([0-9A-Za-z]+)"'),
    re.compile(r'value="([0-9A-Za-z]+)"\s+name="formhash"'),
)


def find_formhash(text):
    for pattern in FORMHASH_RES:
        match = pattern.search(text or "")
        if match:
            return match.group(1)
    return None


def is_guest_page(text):
    """未登录判定：命中站点未登录提示，或同时具备登录入口且没有签到表单/退出入口。"""
    low = (text or "").lower()
    if "您需要先登录才能继续本操作" in low or "请先登录" in low:
        return True
    if "action=logout" in low:
        return False
    if 'name="qdxq"' in low or "qdxq=" in low:
        return False
    return ("logging&amp;action=login" in low) or ("logging&action=login" in low)


def already_signed_on_page(text):
    """签到页已签到时的特征：按钮变成“已签到 + 连续签到 N 天”，且没有心情表单。"""
    text = text or ""
    if 'name="qdxq"' in text:
        return False
    return ("已签到" in text) and ("连续签到" in text)


def parse_json_payload(text):
    """接口返回 JSON，但可能夹带 BOM/HTML 包装，逐个可行位置尝试。"""
    if not text:
        return None
    body = text.strip().lstrip("\ufeff")
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        pass
    for match in re.finditer(r"\{[^{}]*\"status\"[^{}]*\}", body, re.S):
        try:
            return json.loads(match.group(0))
        except Exception:  # noqa: BLE001
            continue
    for match in re.finditer(r"\{.*\}", body, re.S):
        try:
            return json.loads(match.group(0))
        except Exception:  # noqa: BLE001
            continue
    return None


ALREADY_WORDS = ("已经签到", "已签到", "今日已签", "今天已签到", "您今天已经签到过了")


def build_success_message(data):
    data = data or {}
    labels = {
        "days": "累计签到",
        "mdays": "本月签到",
        "reward": "总奖励",
        "qtime": "上次签到",
        "level": "当前等级",
        "todayreward": "本次奖励",
    }
    parts = ["签到成功"]
    for key, value in data.items():
        if value in (None, "", {}, []):
            continue
        label = labels.get(key, key)
        parts.append("%s: %s" % (label, value))
    return "\n".join(parts)


# ---------------------------------------------------------------- 单账号签到


def checkin_once(sess, account, attempts):
    """返回 (状态, 说明)。状态取 success / already / failed。"""
    formhash = account.get("formhash") or ""
    last_error = ""

    # 第一步：打开签到页，确认登录态并顺手刷新 formhash / 加速乐 token
    try:
        page = sess.get(SIGN_PAGE, timeout=TIMEOUT, allow_redirects=True)
        page_text = page.text
        if DEBUG:
            log("[%s] 签到页 HTTP %s，长度 %d" % (account["name"], page.status_code, len(page_text)))
        if is_guest_page(page_text):
            return "failed", "Cookie 已失效（签到页显示未登录），请重新抓包"
        grab_token(sess, page_text)
        if already_signed_on_page(page_text):
            return "already", "今天已经签到过了（页面显示已签到）"
        fresh = find_formhash(page_text)
        if fresh:
            formhash = fresh
    except Exception as exc:  # noqa: BLE001
        last_error = "打开签到页失败: %s" % exc

    # 第二步：提交签到
    payload = {
        "formhash": formhash,
        "submit": "1",
        "targerurl": "",
        "todaysay": os.getenv("JY_SAY", ""),
        "qdxq": os.getenv("JY_QDXQ", "kx") or "kx",
    }
    headers = {
        "Referer": SIGN_PAGE,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
    }

    for attempt in range(1, attempts + 1):
        try:
            resp = sess.post(SIGN_API, data=payload, headers=headers, timeout=TIMEOUT)
            text = resp.text or ""
            if DEBUG:
                log("[%s] 第%d次 签到接口 HTTP %s: %s"
                    % (account["name"], attempt, resp.status_code, text[:600]))
            if resp.status_code != 200:
                last_error = "接口 HTTP %s" % resp.status_code
                time.sleep(2 * attempt)
                continue

            base = parse_json_payload(text)
            if base is None:
                # 没拿到 JSON：可能是加速乐挑战或是登录页
                if grab_token(sess, text):
                    last_error = "遇到加速乐校验，已取 token 重试"
                    log("[%s] 第%d次 %s" % (account["name"], attempt, last_error))
                    time.sleep(1)
                    continue
                if is_guest_page(text):
                    return "failed", "Cookie 已失效（接口返回登录页）"
                if "签到成功" in text:
                    # 少数模板直接返回 HTML 弹窗，不返回 JSON
                    days = re.search(r"累计签到[^\d]{0,8}(\d+)", text)
                    return "success", "签到成功" + ("\n累计签到: %s" % days.group(1) if days else "")
                last_error = "返回内容不是签到结果: %s" % re.sub(r"\s+", " ", text[:200])
                time.sleep(2 * attempt)
                continue

            status = str(base.get("status", "")).strip()
            msg = str(base.get("msg", "") or base.get("message", "") or "").strip()

            if status == "1":
                return "success", build_success_message(base.get("data"))
            if any(word in msg for word in ALREADY_WORDS):
                return "already", "今天已经签到过了：%s" % (msg or "无需重复签到")
            if status in ("-1", "-2", "-3", "-4") and msg:
                last_error = "签到失败(status=%s): %s" % (status, msg)
                break
            if not status and msg:
                last_error = "签到失败: %s" % msg
                break
            last_error = "签到返回无法识别: %s" % json.dumps(base, ensure_ascii=False)[:200]
            break
        except requests.exceptions.Timeout:
            last_error = "请求超时"
            time.sleep(2 * attempt)
        except requests.exceptions.ConnectionError as exc:
            last_error = "网络连接失败: %s" % exc
            time.sleep(3 * attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = "未知异常: %s" % exc
            time.sleep(2 * attempt)

    return "failed", last_error or "签到未成功"


def run_account(account, attempts):
    if account.get("error"):
        return "failed", account["error"]

    log("\n===== %s 开始签到 =====" % account["name"])
    try:
        sess = build_session(account["cookie"])
    except Exception as exc:  # noqa: BLE001
        return "failed", "初始化会话失败: %s" % exc
    try:
        return checkin_once(sess, account, attempts)
    except Exception as exc:  # noqa: BLE001
        return "failed", "签到过程异常: %s" % exc
    finally:
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    raw = os.getenv("JY_COOKIE", "")
    if not raw.strip():
        log("未找到环境变量 JY_COOKIE，格式应为 formhash@cookie")
        notify("精易签到", "未配置 JY_COOKIE，签到未执行")
        return 1

    try:
        attempts = max(1, int(os.getenv("JY_RETRY", "3")))
    except ValueError:
        attempts = 3

    accounts = parse_accounts(raw)
    if not accounts:
        log("JY_COOKIE 解析后没有有效账号")
        notify("精易签到", "JY_COOKIE 解析失败，请检查格式 formhash@cookie")
        return 1

    ok_count, fail_count = 0, 0
    details = []
    for account in accounts:
        status, message = run_account(account, attempts)
        if status in ("success", "already"):
            ok_count += 1
            log("✅ %s %s" % (account["name"], message.replace("\n", " / ")))
        else:
            fail_count += 1
            log("❌ %s %s" % (account["name"], message))
        details.append(
            "%s %s\n%s"
            % ("✅" if status in ("success", "already") else "❌", account["name"], message)
        )

    summary = "精易签到完成：成功 %d 个，失败 %d 个\n\n%s" % (ok_count, fail_count, "\n\n".join(details))
    log("\n" + summary)
    notify("精易签到", summary)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
