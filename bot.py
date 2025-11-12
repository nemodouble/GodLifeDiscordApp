import os
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

from ui.views import MainPanelView  # 추가: 영속 뷰 등록

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("DISCORD_TOKEN이 .env에 설정되어 있지 않습니다. .env 파일을 확인하세요.")
    raise SystemExit(1)

# 최소 권한 인텐트: guilds만 허용 (슬래시 명령 등록/수신에 필요)
intents = discord.Intents.none()
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"로그인 성공: {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        print("Slash 명령어 동기화 완료.")
    except Exception as e:
        print("명령어 동기화 실패:", e)

async def main():
    try:
        # 코그 로드 시도
        try:
            # load_extension이 비동기 코루틴일 수 있으므로 await 처리
            await bot.load_extension("cogs.open_cog")
            print("cogs.open_cog 로드 완료")
        except Exception as e:
            print("코그 로드 실패:", e)

        try:
            await bot.load_extension("cogs.ui_cog")
            print("cogs.ui_cog 로드 완료")
        except Exception as e:
            print("ui 코그 로드 실패:", e)

        try:
            await bot.load_extension("cogs.routine")
            print("cogs.routine 로드 완료")
        except Exception as e:
            print("routine 코그 로드 실패:", e)

        try:
            await bot.load_extension("cogs.report")
            print("cogs.report 로드 완료")
        except Exception as e:
            print("report 코그 로드 실패:", e)

        try:
            await bot.load_extension("cogs.scheduler")
            print("cogs.scheduler 로드 완료")
        except Exception as e:
            print("scheduler 코그 로드 실패:", e)

        # 영속 뷰 등록: 재시작 후에도 버튼이 동작하도록 함
        try:
            bot.add_view(MainPanelView())
            print("MainPanelView 영속 뷰 등록 완료")
        except Exception as e:
            print("영속 뷰 등록 실패:", e)

        await bot.start(TOKEN)
    except Exception as e:
        print("봇 실행 중 예외 발생:", e)
        raise

if __name__ == "__main__":
    asyncio.run(main())
