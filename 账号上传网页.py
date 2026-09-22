# -*- coding: utf-8 -*-
"""账号上传网页 — 双击同目录的「启动账号上传网页.bat」运行，手机/其他电脑（同一局域网）
打开网页即可批量上传账号，自动写入本工具的账号库（%APPDATA%\\DeltaAutoTool\\accounts.json），
主程序重启后即可看到。

特点：
  · 零第三方依赖（纯 Python 标准库），Python 3.8+ 可跑
  · 每次启动生成随机「访问码」，防局域网内其他人乱写
  · 单条表单 + 批量粘贴（每行：账号 密码 备注，分隔符支持 空格/逗号/Tab/----）
  · 与主程序完全同格式：账号名做 key、新账号自动置「暂停」（和主程序里新建账号一致，
    防止没检查就自动跑）；写盘原子化 + 自动备份，坏不了原数据
  · --data-dir 参数可指定数据目录（测试用）

用法：
  双击「启动账号上传网页.bat」          # 推荐。⚠️ Windows 上 .py 常被关联到编辑器，
                                        #   双击 .py 只会用编辑器打开、不会运行
  python 账号上传网页.py                # 默认端口 8790
  python 账号上传网页.py --port 9000    # 换端口

注意：
  1. 密码在局域网内是明文传输的，只在自己可信的网络里用，用完 Ctrl+C 关掉。
  2. 上传时主程序若开着：别在主程序里编辑账号（会互相覆盖），传完重启主程序即可看到新账号。
"""
import argparse
import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "账号上传网页"
DEFAULT_PORT = 8790
MAX_BACKUPS = 10
_NOTE_FIELDS = ("game_name", "name", "note", "level", "stamina", "observe")

_lock = threading.Lock()          # 提交串行化，防止并发写坏文件


# --------------------------------------------------------------------------- #
# 数据目录与账号库读写（与 account_manager.py 的格式逐字段对齐）
# --------------------------------------------------------------------------- #
class AccountStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.accounts_path = os.path.join(data_dir, "accounts.json")
        self.cooldown_path = os.path.join(data_dir, "cooldown.json")

    def _backup(self, path):
        """写前备份（带时间戳，轮转保留 MAX_BACKUPS 份）"""
        if not os.path.exists(path):
            return
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            dest = "%s.webupload.bak.%s" % (path, ts)
            shutil.copy2(path, dest)
            base = path + ".webupload.bak."
            olds = sorted(p for p in os.listdir(os.path.dirname(path))
                          if p.startswith(os.path.basename(base)))
            for old in olds[:-MAX_BACKUPS]:
                try:
                    os.remove(os.path.join(os.path.dirname(path), old))
                except OSError:
                    pass
        except Exception:
            pass

    @staticmethod
    def _atomic_write(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def load_accounts(self):
        """读账号库；不存在/损坏时给空骨架（不在这里动备份恢复——那是主程序的事）"""
        try:
            with open(self.accounts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("accounts.json 顶层应为对象")
            data.setdefault("wegame", [])
            data.setdefault("qq", [])
            data.setdefault("assets", {})
            data.setdefault("asset_history", {})
            data.setdefault("notes", {})
            return data
        except FileNotFoundError:
            return {"wegame": [], "qq": [], "assets": {},
                    "asset_history": {}, "notes": {}}
        except Exception as e:
            raise RuntimeError("accounts.json 读不了（%s）——为防覆盖已中止，请先修好它" % e)

    def load_cooldown(self):
        try:
            with open(self.cooldown_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def upsert(self, account, password, remark="", update_existing=False,
               extra=None):
        """新增/更新一个账号。返回 (状态, 消息)，状态 ∈ added/updated/skipped/error"""
        account = str(account).strip()
        password = str(password)
        if not account:
            return "error", "账号为空"
        if not password.strip():
            return "error", "「%s」密码为空" % account
        if any(c in account for c in ":/\r\n"):
            return "error", "「%s」账号里含非法字符（: / 换行）" % account

        with _lock:
            data = self.load_accounts()
            cd = self.load_cooldown()
            exists = account in data["notes"]
            if exists and not update_existing:
                return "skipped", "「%s」已存在（未勾选更新）" % account

            note = dict(data["notes"].get(account, {}))     # 保留旧字段（level 等）
            note["account"] = account
            note["password"] = password
            note["note"] = str(remark or "").strip() or note.get("note", "")
            for k in _NOTE_FIELDS:
                note.setdefault(k, "" if k != "observe" else False)
            for k, v in (extra or {}).items():
                if k in _NOTE_FIELDS and str(v).strip():
                    note[k] = v

            if not exists:
                data["qq"].append("account:" + account)
                data["assets"].setdefault(account, "0")
                data["asset_history"].setdefault(account, [])
                # 与主程序「新建账号」一致：先置暂停，防止没检查就自动跑
                cd.setdefault(account, {})
                cd[account]["account_paused"] = True
            data["notes"][account] = note

            self._backup(self.accounts_path)
            self._atomic_write(self.accounts_path, data)
            self._backup(self.cooldown_path)
            self._atomic_write(self.cooldown_path, cd)
            return ("added", "「%s」已新增（暂停状态，主程序重启后可见）" % account) if not exists else \
                   ("updated", "「%s」已更新密码/备注" % account)

    def summary(self):
        data = self.load_accounts()
        names = list(data["notes"].keys())
        return len(names), names


# --------------------------------------------------------------------------- #
# 批量行解析：每行「账号 密码 备注」，分隔符：空白 / , / ， / tab / ----
# --------------------------------------------------------------------------- #
_LINE_SPLIT = re.compile(r"\s*\.{3,}|-{3,}|—{3,}|\t+|,+|，+|\s+")


def parse_batch(text):
    rows, errors = [], []
    for ln, line in enumerate(str(text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in _LINE_SPLIT.split(line) if p]
        if len(parts) < 2:
            errors.append("第 %d 行「%s」至少要有 账号 和 密码 两列" % (ln, line[:24]))
            continue
        account, password = parts[0], parts[1]
        remark = parts[2] if len(parts) >= 3 else ""
        if len(parts) > 3:
            remark = " ".join(parts[2:])
        rows.append((account, password, remark))
    return rows, errors


# --------------------------------------------------------------------------- #
# 网页
# --------------------------------------------------------------------------- #
PAGE_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{font-family:-apple-system,"Microsoft YaHei",sans-serif;margin:0;background:#f2f4f8;color:#222}
.card{max-width:640px;margin:16px auto;background:#fff;border-radius:14px;padding:20px;
      box-shadow:0 2px 10px rgba(0,0,0,.06)}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#888;font-size:13px;margin-bottom:16px}
label{display:block;font-size:13px;color:#555;margin:10px 0 4px}
input[type=text],input[type=password],textarea{width:100%;padding:10px;border:1px solid #d8dce3;
      border-radius:8px;font-size:15px;-webkit-text-size-adjust:100%}
textarea{height:120px;font-family:inherit}
.row{display:flex;gap:10px}.row>div{flex:1}
button{margin-top:16px;width:100%;padding:12px;font-size:16px;color:#fff;background:#2f6fed;
       border:0;border-radius:10px}
button:active{background:#2456c4}
.opt{display:flex;align-items:center;gap:6px;margin-top:12px;font-size:14px;color:#555}
details{margin-top:12px}summary{font-size:13px;color:#888;cursor:pointer}
.ok{color:#1a7f4b}.warn{color:#b26a00}.bad{color:#c0392b}
.res{margin-top:14px;font-size:14px;line-height:1.7;white-space:pre-wrap}
.hint{font-size:12px;color:#999;margin-top:6px}
"""

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head><body><div class="card">
<h1>{title}</h1><div class="sub">填好提交即自动写入工具的账号库；主程序重启后生效</div>
{body}
</div></body></html>"""


def _page(body, title=APP_NAME):
    return PAGE.format(title=html.escape(title), css=PAGE_CSS, body=body)


def render_gate(msg=""):
    body = """
<form method="post" action="/gate">
<label>访问码（见运行本程序的黑色窗口）</label>
<input type="password" name="code" autofocus autocomplete="off">
<button>进入</button>
{msg}
</form>""".format(msg='<div class="res bad">%s</div>' % html.escape(msg) if msg else "")
    return _page(body, "访问码 · " + APP_NAME)


def render_main(count, msg="", msg_kind="ok"):
    body = """
{status}
<form method="post" action="/submit">
<label>游戏账号 *（即账号名，不能含 : /）</label>
<input type="text" name="account" required>
<label>密码 *</label>
<input type="password" name="password" required>
<label>备注（可空）</label>
<input type="text" name="remark">
<details><summary>更多字段（可空）</summary>
<div class="row"><div><label>名称</label><input type="text" name="name"></div>
<div><label>游戏名</label><input type="text" name="game_name"></div></div>
<div class="row"><div><label>等级</label><input type="text" name="level"></div>
<div><label>体力</label><input type="text" name="stamina"></div></div>
</details>
<div class="opt"><input type="checkbox" name="update" id="u"><label for="u" style="margin:0">
账号已存在时：更新密码/备注（不勾=跳过）</label></div>
<button>上传这一个账号</button>
</form>
<hr style="border:0;border-top:1px solid #eee;margin:20px 0">
<form method="post" action="/batch">
<label>批量粘贴（每行一个：账号 密码 备注）</label>
<textarea name="lines" placeholder="user001 p@ss 备注一
user002 p@ss,备注二
user003----p@ss"></textarea>
<div class="hint">分隔符随便用：空格 / 逗号 / Tab / ---- 都行；备注可省略</div>
<div class="opt"><input type="checkbox" name="update" id="u2"><label for="u2" style="margin:0">
已存在的账号：更新密码/备注（不勾=跳过）</label></div>
<button>批量上传</button>
</form>""".format(
        status=('<div class="res %s">%s</div>' % (msg_kind, msg)) if msg else "")
    return _page(body)


def render_result(count, lines, kind="ok"):
    body = '<div class="res %s">%s</div><p class="hint">当前账号总数：%d</p>' % (
        kind, html.escape("\n".join(lines)), count)
    body += '<form method="get" action="/"><button>继续上传</button></form>'
    return _page(body)


# --------------------------------------------------------------------------- #
# HTTP 服务
# --------------------------------------------------------------------------- #
def lan_ips():
    """列出本机局域网 IPv4（排除回环/虚拟网卡常见的 169.254）"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            try:
                if (ipaddress.ip_address(ip).is_global
                        and not ip.startswith("169.254.")) and ip not in out:
                    out.append(ip)
            except ValueError:
                continue
    except Exception:
        pass
    return out or ["127.0.0.1"]


class Handler(BaseHTTPRequestHandler):
    server_version = "AccUpload/1.0"
    store = None            # AccountStore
    access_code = None       # 本次启动的访问码

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---- 工具 ----
    def _send(self, body, code=200, headers=None):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self):
        return self.path.startswith("/css") or "sid=%s" % SID in self.headers.get("Cookie", "")

    def _form(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}

    # ---- 路由 ----
    def do_GET(self):
        if not self._authorized():
            return self._send(render_gate())
        count, _ = self.store.summary()
        self._send(render_main(count))

    def do_POST(self):
        global SID
        if self.path == "/gate":
            f = self._form()
            if (f.get("code") or "").strip() == self.access_code:
                SID = secrets.token_urlsafe(24)
                self._send(render_main(self.store.summary()[0]),
                           headers={"Set-Cookie":
                                    "sid=%s; Path=/; HttpOnly; SameSite=Strict" % SID})
                print("✅ 访问码验证通过")
                return
            print("⚠️ 访问码错误")
            return self._send(render_gate("访问码不对，请看运行本程序的窗口"), code=401)

        if not self._authorized():
            return self._send(render_gate(), code=401)

        count = self.store.summary()[0]
        if self.path == "/submit":
            f = self._form()
            extra = {k: f.get(k, "") for k in ("name", "game_name", "level", "stamina")}
            status, msg = self.store.upsert(
                f.get("account", ""), f.get("password", ""), f.get("remark", ""),
                update_existing=bool(f.get("update")), extra=extra)
            kind = {"added": "ok", "updated": "ok",
                    "skipped": "warn", "error": "bad"}[status]
            print("提交：%s" % msg)
            new_count = self.store.summary()[0]
            self._send(render_result(new_count, [msg], kind))
            return

        if self.path == "/batch":
            f = self._form()
            rows, errors = parse_batch(f.get("lines", ""))
            results, n_add, n_upd, n_skip, n_err = [], 0, 0, 0, 0
            for account, password, remark in rows:
                status, msg = self.store.upsert(account, password, remark,
                                                update_existing=bool(f.get("update")))
                results.append(msg)
                if status == "added":
                    n_add += 1
                elif status == "updated":
                    n_upd += 1
                elif status == "skipped":
                    n_skip += 1
                else:
                    n_err += 1
            results += ["⚠️ " + e for e in errors]
            n_err += len(errors)
            head = "批量完成：新增 %d、更新 %d、跳过 %d、失败 %d" % (
                n_add, n_upd, n_skip, n_err)
            print(head)
            self._send(render_result(
                self.store.summary()[0], [head] + results,
                kind="ok" if n_err == 0 else "warn"))
            return
        self._send(_page("<p class='res bad'>未知路径</p>"), code=404)


SID = ""


def main():
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--data-dir", default=os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "DeltaAutoTool"),
        help="数据目录（默认 %%APPDATA%%\\DeltaAutoTool）")
    args = ap.parse_args()

    store = AccountStore(args.data_dir)
    Handler.store = store
    Handler.access_code = "%04d" % secrets.randbelow(10000)

    count, names = store.summary()
    print("=" * 56)
    print("  %s" % APP_NAME)
    print("=" * 56)
    print("  数据目录：%s" % store.data_dir)
    print("  当前账号：%d 个%s" % (count, ("（" + "、".join(names[:8]) + "…）") if names else ""))
    ips = lan_ips()
    print()
    print("  手机/其他电脑（同一 Wi-Fi）用浏览器打开：")
    for ip in ips:
        print("      http://%s:%d" % (ip, args.port))
    print()
    print("  访问码：%s   （只在本机窗口显示，网页端输入一次即可）" % Handler.access_code)
    print("  用完按 Ctrl+C 关闭（或网页底部不再提供关闭，防误触）")
    print("  ⚠️ 密码经局域网明文传输，只在可信网络使用")
    print("=" * 56)

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print("已退出。")


if __name__ == "__main__":
    main()
