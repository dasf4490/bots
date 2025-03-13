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
from dotenv import load_dotenv

# ローカル開発の場合、.env ファイルから環境変数をロード（プロダクションではホスティングサービスの環境変数を利用）
load_dotenv()

# 環境変数からトークンを取得
token = os.getenv("DISCORD_TOKEN")
if not token:
    print("エラー: DISCORD_TOKEN が設定されていません。")
    exit(1)
else:
    print(f"トークンが正常に読み込まれました: {token[:5]}****")

# 起動時刻を記録（ヘルスチェック用）
start_time = time.time()

# Discord intents の設定
intents = discord.Intents.default()
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # スラッシュコマンドの同期
        await self.tree.sync()
        logger.info("スラッシュコマンドの同期が完了しました！")

bot = MyBot()

# 各種設定（ID 等は適切なものに置き換えてください）
welcome_channel_id = 1165799413558542446  # ウェルカムメッセージ送信用チャンネルID
role_id = 1165785520593436764             # メンション用ロールID
admin_user_ids = [1073863060843937812, 1175571621025689661]  # 管理者ユーザーIDのリスト
target_user_ids = [1175571621025689661, 1073863060843937812]   # 定期DM送信対象のユーザーIDリスト
welcome_sent = False
wait_time = 50  # 待機時間（秒）

# ロガーの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiohttp.server")

# 排他用ロックの設定
lock = asyncio.Lock()

# 管理者へ通知する関数（エラーや状況を日本語メッセージで送信）
async def notify_admins(message):
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

# テキストコマンドによる再起動コマンド
@bot.command()
@commands.has_permissions(administrator=True)
async def restart(ctx):
    logger.info("テキストコマンドによる再起動が呼び出されました")
    await ctx.send("再起動しています… 🔄")
    await bot.close()
    os.execl(sys.executable, sys.executable, *sys.argv)

# スラッシュコマンドによる再起動コマンド
@bot.tree.command(name="restart", description="Botを再起動するスラッシュコマンド")
@app_commands.checks.has_permissions(administrator=True)
async def restart_slash(interaction: discord.Interaction):
    logger.info("スラッシュコマンドによる再起動が呼び出されました")
    await interaction.response.send_message("再起動しています… 🔄")
    await bot.close()
    os.execl(sys.executable, sys.executable, *sys.argv)

@restart_slash.error
async def restart_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 管理者権限が必要です。", ephemeral=True)

# 新しいメンバー参加時の処理（ウェルカムメッセージを送信）
@bot.event
async def on_member_join(member):
    global welcome_sent
    logger.info(f"新しいメンバーが参加しました: {member.name} ({member.id})")
    try:
        channel = bot.get_channel(welcome_channel_id)
        role = member.guild.get_role(role_id)
        if not welcome_sent and channel and role:
            welcome_sent = True
            await channel.send(
                f"こんにちは！{role.mention} の皆さん。"
                f"『おしゃべりを始める前に、もういくつかステップが残っています。』"
                f"と出ているので、『了解』を押してルールに同意してください。"
                f"その後、https://discord.com/channels/1165775639798878288/1165775640918773843 で認証し、みんなとお話ししましょう！"
            )
            await asyncio.sleep(wait_time)
            welcome_sent = False
        elif not channel:
            logger.warning("チャンネルが見つかりません。welcome_channel_id を確認してください。")
        elif not role:
            logger.warning("ロールが見つかりません。role_id を確認してください。")
    except Exception as e:
        error_message = f"新規メンバー参加時のエラー: {e}"
        logger.error(error_message)
        await notify_admins(f"⚠️ 新規メンバー参加時のエラー:\n{error_message}")

# リクエストログを記録するミドルウェア（/health へのアクセスは除外）
@web.middleware
async def log_requests(request, handler):
    response = await handler(request)
    if request.path != "/health":
        peername = request.transport.get_extra_info("peername")
        client_ip = peername[0] if peername else "不明なIP"
        client_port = peername[1] if peername else "不明なポート"
        logger.info(f"{client_ip}:{client_port} - {request.method} {request.path}")
    return response

# ヘルスチェックエンドポイント：アップタイム、参加サーバー数、現在時刻を返す
async def health_check(request):
    logger.info("ヘルスチェックエンドポイントが呼び出されました")
    uptime = time.time() - start_time
    guild_count = len(bot.guilds) if hasattr(bot, "guilds") else 0
    return web.json_response({
        "status": "ok",
        "uptime": uptime,
        "guild_count": guild_count,
        "time": datetime.utcnow().isoformat() + "Z"
    })

# aiohttpベースのWebサーバー起動（環境変数 PORT を利用）
async def start_web_server():
    logger.info("Webサーバーを起動しています...")
    app = web.Application(middlewares=[log_requests])
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Webサーバーがポート {port} で起動しました")

# keep_alive タスク：RAILWAY_URL に定期Pingしてアイドル状態を防止
async def keep_alive():
    logger.info("keep_alive タスクを開始します...")
    railway_url = os.environ.get("RAILWAY_URL", "https://your-project-name.up.railway.app")
    async with ClientSession() as session:
        while True:
            try:
                async with lock:
                    async with session.get(f"{railway_url}/health") as resp:
                        logger.info(f"Railway URL へ Ping を送信しました: {resp.status}")
            except Exception as e:
                logger.error(f"Railway URL への Ping 送信に失敗しました: {e}")
            await asyncio.sleep(300)

# 1時間ごとに指定ユーザーへDM送信するタスク（状況報告付き）
@tasks.loop(hours=1)
async def send_dm():
    logger.info("send_dm タスクを実行中です...")
    no_errors = True
    for user_id in target_user_ids:
        try:
            user = await bot.fetch_user(user_id)
            if user:
                async with lock:
                    await user.send("これは1時間ごとのDMテストメッセージです。")
                logger.info(f"{user.name} さんへDMを送信しました。")
            else:
                logger.warning(f"ユーザーID {user_id} が見つかりませんでした。")
        except Exception as e:
            no_errors = False
            error_message = f"ユーザーID {user_id} へのDM送信中にエラーが発生しました: {e}"
            logger.error(error_message)
            await notify_admins(f"⚠️ エラー:\n{error_message}")
    if no_errors:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await notify_admins(f"✅ 過去1時間、エラーは発生しませんでした。\n時刻: {current_time}")

@bot.event
async def on_ready():
    logger.info(f"{bot.user} としてログインしました")
    if not send_dm.is_running():
        logger.info("send_dm タスクを開始します...")
        send_dm.start()
    else:
        logger.info("send_dm タスクは既に実行中です")

# メイン関数：Discord Bot、Webサーバー、keep_alive を並行実行
async def main():
    logger.info("メイン関数を開始します...")
    await asyncio.gather(
        bot.start(token),
        start_web_server(),
        keep_alive()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Botをシャットダウンしています…")
