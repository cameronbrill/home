import os
from pylitterbot import LitterRobot4, FeederRobot
from pylitterbot.account import Account
import asyncio

WHISKER_USERNAME = os.getenv("WHISKER_USERNAME")
WHISKER_PASSWORD = os.getenv("WHISKER_PASSWORD")

async def _get_robots(account: Account) -> tuple[FeederRobot, LitterRobot4]:
    feeder: FeederRobot
    litter_box: LitterRobot4

    try:
        print(f"Connecting to Whisker with username: {WHISKER_USERNAME}")
        await account.connect(username=WHISKER_USERNAME, password=WHISKER_PASSWORD, load_robots=True)
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

async def main():
    account = Account()
    feeder, litter_box = await _get_robots(account)
    print(f"Feeder: {feeder}")
    print(f"Litter Box: {litter_box}")

    

if __name__ == "__main__":
    asyncio.run(main())
