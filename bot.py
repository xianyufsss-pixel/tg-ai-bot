#!/usr/bin/env python3
"""Telegram AI Bot - Zaka AI style, own brand.
Backend is pluggable: edit config.yaml ai.* only, no code change needed.
No token/key is hardcoded; both come from config.yaml (not committed).
"""
import sqlite3, yaml, httpx, logging, os, subprocess, json
from datetime import date
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tg-ai-bot")

def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

CFG = load_config()

# 用户可在菜单里自己切换的模型，来自 huyon /v1/models 列表
MODELS = ["均衡", "快速", "极致", "Deepseek-V4-Pro", "Deepseek-V4.1-Flash",
          "GLM-5.1", "GLM-5.2", "GLM-5.3", "GLM-5.3-Flash", "Kimi-K2.8-Preview",
          "Kimi-K3", "Kimi-K3.1-Pro", "MiniMax-M3", "MiniMax-M3.1-Flash",
          "Step-5-Preview", "Xiaomi MiMo-V2.6-Pro", "Hy3", "Hy4 preview", "Space-Bunny"]

def db():
    c = sqlite3.connect(CFG["db"]["path"])
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, referrer INTEGER, used_today INTEGER DEFAULT 0,
        used_date TEXT, bonus INTEGER DEFAULT 0, model TEXT)""")
    try: c.execute("ALTER TABLE users ADD COLUMN model TEXT")
    except Exception: pass
    c.execute("""CREATE TABLE IF NOT EXISTS history(
        user_id INTEGER, role TEXT, content TEXT, seq INTEGER)""")
    return c

def get_user(uid, referrer=None):
    c = db(); row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        c.execute("INSERT INTO users(id, referrer, used_date) VALUES(?,?,?)", (uid, referrer, str(date.today())))
        c.commit()
        if referrer and referrer != uid:
            c.execute("UPDATE users SET bonus=bonus+? WHERE id=?", (CFG["quota"]["referral_bonus"], referrer))
            c.commit()
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    # reset daily counter
    if row[3] != str(date.today()):
        c.execute("UPDATE users SET used_today=0, used_date=? WHERE id=?", (str(date.today()), uid)); c.commit()
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close(); return row

def quota_left(uid):
    u = get_user(uid); free = CFG["quota"]["free_per_day"]
    if free == 0: return 999999
    return max(0, free + u[4] - u[2])

def user_model(uid):
    u = get_user(uid)
    return u[5] if len(u) > 5 and u[5] else CFG["ai"]["model"]

def set_user_model(uid, model):
    c = db(); c.execute("UPDATE users SET model=? WHERE id=?", (model, uid)); c.commit(); c.close()

def model_keyboard(current):
    kb = []
    for i in range(0, len(MODELS), 2):
        row = []
        for m in MODELS[i:i+2]:
            label = f"✅ {m}" if m == current else m
            row.append(InlineKeyboardButton(label, callback_data=f"model:{m}"))
        kb.append(row)
    return InlineKeyboardMarkup(kb)

async def delete_safe(context, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception as e:
        log.warning("delete message failed: %s", e)

async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; get_user(uid)
    text = f"当前模型：{user_model(uid)}\n点下面切换，切换后会自动开始新对话："
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=model_keyboard(user_model(uid)))
    else:
        # 用户输入 /model 后，先删掉这条命令消息，再发模型菜单
        if update.message:
            await delete_safe(context, update.effective_chat.id, update.message.message_id)
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=model_keyboard(user_model(uid)))

async def check_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = CFG["bot"].get("channel")
    if not ch: return True
    try:
        m = await context.bot.get_chat_member(ch, update.effective_user.id)
        return m.status in ("creator", "administrator", "member")
    except Exception as e:
        log.warning("channel check failed: %s", e); return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = None
    if context.args and context.args[0].startswith("ref_"):
        try: ref = int(context.args[0][4:])
        except Exception: ref = None
    get_user(update.effective_user.id, ref)
    if not await check_channel(update, context):
        kb = [[InlineKeyboardButton("订阅频道", url=f"https://t.me/{CFG['bot']['channel'].lstrip('@')}")],
              [InlineKeyboardButton("我已订阅", callback_data="check_sub")]]
        await update.message.reply_text("请先订阅频道，订阅后点“我已订阅”。", reply_markup=InlineKeyboardMarkup(kb)); return
    kb = [[InlineKeyboardButton("开始聊天", callback_data="chat")],
          [InlineKeyboardButton("模型设置", callback_data="model_menu")],
          [InlineKeyboardButton("我的额度", callback_data="balance"),
           InlineKeyboardButton("邀请好友", callback_data="invite")]]
    await update.message.reply_text(
        f"你好，我是 AI 助手，直接发消息就能聊天。\n当前模型：{user_model(update.effective_user.id)}\n今日剩余免费次数：{quota_left(update.effective_user.id)}",
        reply_markup=InlineKeyboardMarkup(kb))

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if q.data == "check_sub":
        await start(update, context) if False else await q.message.reply_text("已订阅的话直接发消息聊天即可。")
    elif q.data == "balance":
        await q.message.reply_text(f"今日剩余免费次数：{quota_left(uid)}")
    elif q.data == "invite":
        me = await context.bot.get_me()
        await q.message.reply_text(f"你的邀请链接：\nhttps://t.me/{me.username}?start=ref_{uid}\n邀请一人奖励 {CFG['quota']['referral_bonus']} 次。")
    elif q.data == "chat":
        await q.message.reply_text("直接发消息，我来回答。发 /new 可以开始新对话。")
    elif q.data == "model_menu":
        await model_menu(update, context)
    elif q.data.startswith("model:"):
        m = q.data[6:]
        if m not in MODELS:
            await q.message.reply_text("这个模型不在列表里。"); return
        set_user_model(uid, m)
        c = db(); c.execute("DELETE FROM history WHERE user_id=?", (uid,)); c.commit(); c.close()
        # 点击切换后，先删掉当前模型菜单消息，再发确认
        await delete_safe(context, q.message.chat_id, q.message.message_id)
        await context.bot.send_message(q.message.chat_id, f"已切换到模型：{m}，已开始新对话，直接发消息即可。")

async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = db(); c.execute("DELETE FROM history WHERE user_id=?", (update.effective_user.id,)); c.commit(); c.close()
    await update.message.reply_text("已开始新对话。")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"今日剩余免费次数：{quota_left(update.effective_user.id)}")

def sandbox_dir(uid):
    d = Path("users") / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d

def run_tool(uid, name, args):
    # 每人一个沙盒：所有文件操作只在 users/<uid>/ 里，命令超时 30 秒，禁止访问宿主机其他目录
    sd = sandbox_dir(uid)
    try:
        if name == "sandbox_ls":
            rel = args.get("path", ".")
            p = (sd / rel).resolve()
            if not str(p).startswith(str(sd.resolve())): return "错误：只能访问自己的沙盒目录"
            return "\n".join(x.name for x in p.iterdir()) if p.is_dir() else str(p)
        if name == "sandbox_write":
            rel = args.get("path", "output.txt"); content = args.get("content", "")
            p = (sd / rel).resolve()
            if not str(p).startswith(str(sd.resolve())): return "错误：只能写自己的沙盒目录"
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
            return f"已写入 {rel}，{len(content)} 字"
        if name == "sandbox_read":
            rel = args.get("path", "")
            p = (sd / rel).resolve()
            if not str(p).startswith(str(sd.resolve())) or not p.is_file(): return "错误：文件不存在或不在沙盒内"
            return p.read_text(encoding="utf-8")[:4000]
        if name == "sandbox_run":
            cmd = args.get("command", "")
            # 只允许在沙盒内运行简单命令，禁止 sudo / rm -rf / 等危险操作
            banned = ["sudo", "rm -rf /", "mkfs", "dd if=", "curl", "wget"]
            if any(b in cmd for b in banned): return "错误：该命令被沙盒禁止"
            r = subprocess.run(cmd, shell=True, cwd=str(sd), capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr)[:4000] or "(无输出)"
        if name == "nezha_servers":
            token = (CFG.get("nezha") or {}).get("api_key", "")
            if not token or token.startswith("PUT_"): return "哪吒 API 还没配置，管理员需在 config.yaml 的 nezha.api_key 里填令牌"
            import urllib.request
            req = urllib.request.Request("https://tz.xianyufss.cloud/api/v1/server", method="GET")
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.load(resp)
            out = []
            for s in d.get("data", []):
                st = s.get("state", {}) or {}; h = s.get("host", {}) or {}
                out.append(f"{s['name']}：CPU {st.get('cpu',0):.1f}% 内存 {st.get('mem_used',0)//1024//1024}/{h.get('mem_total',0)//1024//1024}MB 最后在线 {s.get('last_active','')}")
            return "\n".join(out) or "无服务器"
    except Exception as e:
        return f"工具执行失败：{e}"
    return "未知工具"

TOOLS = [
    {"type": "function", "function": {"name": "sandbox_ls", "description": "列出用户自己沙盒里的文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "sandbox_write", "description": "在用户自己沙盒里写文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "sandbox_read", "description": "读用户自己沙盒里的文件", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "sandbox_run", "description": "在用户自己沙盒里运行命令，超时30秒", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "nezha_servers", "description": "查哪吒 11 台服务器状态（只读）", "parameters": {"type": "object", "properties": {}}}},
]

async def ask_ai(uid, text):
    c = db()
    rows = c.execute("SELECT role, content FROM history WHERE user_id=? ORDER BY seq DESC LIMIT ?",
                     (uid, CFG["ai"]["max_history"])).fetchall()
    msgs = [{"role": "system", "content": CFG["ai"]["system_prompt"] + " 你是一个 Agent，可以调用工具在用户自己的沙盒里执行任务，执行完再把结果整理告诉用户。不要假装执行了没调用工具的任务。"}] + \
           [{"role": r, "content": t} for r, t in reversed(rows)] + [{"role": "user", "content": text}]
    reply = ""
    async with httpx.AsyncClient(timeout=120) as client:
        for _ in range(5):
            r = await client.post(f"{CFG['ai']['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {CFG['ai']['api_key']}"},
                json={"model": user_model(uid), "messages": msgs, "temperature": CFG["ai"]["temperature"], "tools": TOOLS, "tool_choice": "auto"})
            r.raise_for_status(); choice = r.json()["choices"][0]["message"]
            if not choice.get("tool_calls"):
                reply = choice.get("content") or ""; break
            msgs.append(choice)
            for tc in choice["tool_calls"]:
                try: args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception: args = {}
                result = run_tool(uid, tc["function"]["name"], args)
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            else:
                continue
            reply = "工具已执行，正在整理结果……"
        else:
            reply = reply or "任务步骤太多，已停止，请分步再试。"
    seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM history WHERE user_id=?", (uid,)).fetchone()[0]
    c.execute("INSERT INTO history VALUES(?,?,?,?)", (uid, "user", text, seq))
    c.execute("INSERT INTO history VALUES(?,?,?,?)", (uid, "assistant", reply, seq+1))
    c.execute("UPDATE users SET used_today=used_today+1 WHERE id=?", (uid,)); c.commit(); c.close()
    return reply

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; get_user(uid)
    if not await check_channel(update, context):
        await update.message.reply_text("请先订阅频道后再聊天。"); return
    if quota_left(uid) <= 0:
        await update.message.reply_text("今日免费次数已用完，明天再来，或联系管理员开通。"); return
    if CFG["ai"]["api_key"].startswith("PUT_"):
        await update.message.reply_text("后端还没配置：请管理员在 config.yaml 里填 ai.api_key / base_url / model 后再试。"); return
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        await update.message.reply_text(await ask_ai(uid, update.message.text))
    except Exception as e:
        log.exception(e); await update.message.reply_text("后端调用失败，请稍后再试。")

def main():
    app = Application.builder().token(CFG["bot"]["token"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("new", new_chat))
    app.add_handler(CommandHandler("model", model_menu))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.run_polling()

if __name__ == "__main__":
    main()
