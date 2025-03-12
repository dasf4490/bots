import discord
from discord.ext import tasks, commands
from discord import app_commands
import asyncio
import os
from aiohttp import web
import logging
from aiohttp import ClientSession
from datetime import datetime
import sys
import time

# 環境変数からトークンを取得
token = os.getenv("DISCORD_TOKEN")

# トークンのチェック
if not token:
    print("Error: DISCORD_TOKEN is not set.")
    exit(1)
else:
    print(f"Token successfully loaded: {token[:5]}****")  # トークンの一部のみ表示で安全性を確保

# intentsを設定し、Botオブジェクトを作成
intents = discord.Intents.default()
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # スラッシュコマンドの同期
        await self.tree.sync()
        logger.info("Slash commands synced!")

bot = MyBot()

# ウェルカムメッセージとロール設定
welcome_channel_id = 1165799413558542446  # ウェルカムメッセージを送信するチャンネルID
role_id = 1165785520593436764  # メンションしたいロールのID

# 管理者のDiscordユーザーIDリスト
admin_user_ids = [1073863060843937812, 1175571621025689661]

# DM送信対象のユーザーIDリスト
target_user_ids = [1175571621025689661, 1073863060843937812]

# 状態管理
welcome_sent = False
wait_time = 50  # 秒単位の待機時間

# ロガーを設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiohttp.server")

# ロックの導入
lock = asyncio.Lock()

# 管理者に通知を送信する関数
async def notify_admins(message):
    """管理者にメッセージをDMで送信する"""
    for admin_user_id in admin_user_ids:
        try:
            admin_user = await bot.fetch_user(admin_user_id)
            if admin_user:
                async with lock:
                    await admin_user.send(message)
                logger.info(f"管理者 {admin_user_id} にメッセージを送信しました。")
            else:
                logger.warning(f"管理者ユーザーID {admin_user_id} が見つかりませんでした。")
        except Exception as e:
            logger.error(f"管理者 {admin_user_id} への通知に失敗しました: {e}")

# テキストコマンド: /restart
@bot.command()
@commands.has_permissions(administrator=True)
async def restart(ctx):
    """Botを再起動するテキストコマンド"""
    logger.info("Text-based restart command invoked.")
    await ctx.send("再起動しています... 🔄")
    await bot.close()
    os.execl(sys.executable, sys.executable, *sys.argv)

# スラッシュコマンド: /restart
@bot.tree.command(name="restart", description="Botを再起動するスラッシュコマンド")
@app_commands.checks.has_permissions(administrator=True)
async def restart_slash(interaction: discord.Interaction):
    """Botを再起動するスラッシュコマンド"""
    logger.info("Slash-based restart command invoked.")
    await interaction.response.send_message("再起動しています... 🔄")
    await bot.close()
    os.execl(sys.executable, sys.executable, *sys.argv)

# 権限エラーのハンドリング
@restart_slash.error
async def restart_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 管理者権限が必要です。", ephemeral=True)

# 新しいメンバーが参加したときの処理
@bot.event
async def on_member_join(member):
    global welcome_sent
    logger.info(f"New member joined: {member.name} ({member.id})")
    try:
        channel = bot.get_channel(welcome_channel_id)
        role = member.guild.get_role(role_id)

        if not welcome_sent and channel and role:
            welcome_sent = True
            await channel.send(
                f"こんにちは！{role.mention}の皆さん。「おしゃべりを始める前に、もういくつかステップが残っています。」"
                f"と出ていると思うので、「了解」を押してルールに同意しましょう。その後に"
                f"https://discord.com/channels/1165775639798878288/1165775640918773843で"
                f"認証をして、みんなとお喋りをしましょう！"
            )
            await asyncio.sleep(wait_time)
            welcome_sent = False
        elif not channel:
            logger.warning("チャンネルが見つかりません。`welcome_channel_id`を正しい値に設定してください。")
        elif not role:
            logger.warning("ロールが見つかりません。`role_id`を正しい値に設定してください。")
    except Exception as e:
        error_message = f"新規メンバー参加時のエラー: {e}"
        logger.error(error_message)
        await notify_admins(f"⚠️新規メンバー参加時のエラー:\n{error_message}")

# リクエストログを記録するミドルウェア（`/health`リクエストを除外）
@web.middleware
async def log_requests(request, handler):
    response = await handler(request)
    if request.path != "/health":
        peername = request.transport.get_extra_info("peername")
        client_ip = peername[0] if peername else "Unknown IP"
        client_port = peername[1] if peername else "Unknown Port"
        logger.info(f"{client_ip}:{client_port} - {request.method} {request.path}")
    return response

# ヘルスチェック用のエンドポイント
async def health_check(request):
    logger.info("Health check endpoint accessed.")
    current_time = time.time()
    return web.json_response({"status": "ok"})

# aiohttpサーバーを起動
async def start_web_server():
    logger.info("Starting web server...")
    app = web.Application(middlewares=[log_requests])
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

# 定期PingをRenderに送信してアイドル状態を防ぐ
async def keep_alive():
    logger.info("Starting keep_alive task...")
    async with ClientSession() as session:
        while True:
            try:
                async with lock:
                    async with session.get("https://bot-2ptf.onrender.com/health") as resp:
                        logger.info(f"Pinged Render: {resp.status}")
            except Exception as e:
                logger.error(f"Failed to ping Render: {e}")
            await asyncio.sleep(300)

# 複数ユーザーに1時間ごとにDMを送信するタスク
@tasks.loop(hours=1)
async def send_dm():
    """1時間ごとにユーザーにDMを送信し、結果を管理者に報告する"""
    logger.info("Running send_dm task...")
    no_errors = True
    for user_id in target_user_ids:
        try:
            user = await bot.fetch_user(user_id)
            if user:
                async with lock:
                    await user.send("これは1時間ごとのDMテストメッセージです。")
                logger.info(f"DMを送信しました: {user.name}")
            else:
                logger.warning(f"指定されたユーザーが見つかりませんでした（ID: {user_id}）。")
        except Exception as e:
            no_errors = False
            error_message = f"ユーザーID {user_id} へのDM送信中にエラーが発生しました: {e}"
            logger.error(error_message)
            await notify_admins(f"⚠️エラーが発生しました:\n{error_message}")

    if no_errors:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await notify_admins(f"✅ 過去1時間でエラーは発生しませんでした。\n実行時間: {current_time}")

# Bot起動時にタスクを確認し、開始
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    if not send_dm.is_running():
        logger.info("Starting send_dm task...")
        send_dm.start()
    else:
        logger.info("send_dm task is already running.")

# メイン関数でBotとWebサーバーを並行実行
async def main():
    logger.info("Starting main function...")
    await asyncio.gather(
        bot.start(token),   # Discord Botを起動
        start_web_server(),  # Webサーバーを起動
        keep_alive()         # RenderへのPing処理を実行
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutting down...")
