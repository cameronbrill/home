import asyncio
import os
from datetime import datetime, timedelta, timezone

from aiohttp import ClientSession
from pylitterbot import FeederRobot, LitterRobot4
from pylitterbot.account import Account
from roborock import HomeDataDevice, HomeDataScene
from roborock.web_api import RoborockApiClient, UserWebApiClient

WHISKER_USERNAME = os.getenv("WHISKER_USERNAME", "")
WHISKER_PASSWORD = os.getenv("WHISKER_PASSWORD", "")
ROBOROCK_USERNAME = os.getenv("ROBOROCK_USERNAME", "")
ROBOROCK_PASSWORD = os.getenv("ROBOROCK_PASSWORD", "")

if not all([WHISKER_USERNAME, WHISKER_PASSWORD, ROBOROCK_USERNAME, ROBOROCK_PASSWORD]):
    raise ValueError("Missing required environment variables")


async def _get_robots(account: Account) -> tuple[FeederRobot, LitterRobot4]:
    feeder: FeederRobot
    litter_box: LitterRobot4

    try:
        print(f"Connecting to Whisker with username: {WHISKER_USERNAME}")
        await account.connect(
            username=WHISKER_USERNAME, password=WHISKER_PASSWORD, load_robots=True
        )
        print(f"Robots: {[str(robot) for robot in account.robots]}")
    finally:
        await account.disconnect()

    for robot in account.robots:
        if isinstance(robot, FeederRobot):
            feeder = robot
        elif isinstance(robot, LitterRobot4):
            litter_box = robot
    if not feeder or not litter_box:  # pyright: ignore[reportPossiblyUnboundVariable]: that's what we're checking for
        raise ValueError("No feeder or litterbox found")

    return feeder, litter_box


async def _get_vacuum(
    username: str, password: str
) -> tuple[UserWebApiClient, HomeDataDevice]:
    print(f"Logging in to Roborock with username: {username}")
    # Login via your password
    web_api = RoborockApiClient(username=username)
    user_data = await web_api.pass_login(password=password)  # pyright: ignore[reportArgumentType]
    user_web_api = UserWebApiClient(web_api, user_data)

    home_data = await user_web_api.get_home_data()
    print(f"Roborock home data: {home_data}")
    vacuum_device = home_data.devices[0]
    return user_web_api, vacuum_device


async def main():
    async with ClientSession() as session:
        account = Account(websession=session)
        feeder, litter_box = await _get_robots(account)
        print(f"Feeder: {feeder}")
        print(f"{'=' * 100}")
        print(f"Litter Box: {litter_box}")
        roborock_api_client, vacuum_device = await _get_vacuum(
            username=ROBOROCK_USERNAME, password=ROBOROCK_PASSWORD
        )

        while True:
            print("Refreshing litter box...")
            await litter_box.refresh()
            if not litter_box.last_seen:
                print("Litter box last seen is not set.")
                await asyncio.sleep(10)
                continue

            if datetime.now(tz=timezone.utc) - litter_box.last_seen > timedelta(
                minutes=10
            ):
                print("Litter box not seen in the last 10 minutes.")
                await asyncio.sleep(10)
                continue

            print(f"Vacuum device: {vacuum_device}")
            vacuum_routines = await roborock_api_client.get_routines(vacuum_device.duid)
            litter_routine: HomeDataScene | None = None
            for routine in vacuum_routines:
                if routine.name != "Litter":
                    continue

                litter_routine = routine
                break

            if not litter_routine:
                print("No litter routine found.")
                await asyncio.sleep(10)
                continue

            print(f"Executing litter routine: {litter_routine}")
            await roborock_api_client.execute_routine(litter_routine.id)

            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
