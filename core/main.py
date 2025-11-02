import asyncio
from datetime import UTC, date, datetime, timedelta
import os
from typing import TYPE_CHECKING, cast

from aiohttp import ClientSession
from pylitterbot import FeederRobot, LitterRobot4
from pylitterbot.account import Account
from pylitterbot.enums import LitterBoxStatus
from roborock.web_api import RoborockApiClient, UserWebApiClient
import sentry_sdk

from core.logging import get_logger

if TYPE_CHECKING:
    from roborock import HomeDataDevice, HomeDataScene

logger = get_logger(__name__)

SENTRY_DSN = os.getenv("SENTRY_DSN", "")

sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=True,
)


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
        logger.info("Connecting to Whisker", username=WHISKER_USERNAME)
        await account.connect(username=WHISKER_USERNAME, password=WHISKER_PASSWORD, load_robots=True)
        logger.info("Connected to Whisker", robots=[str(robot) for robot in account.robots])
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


async def _get_vacuum(username: str, password: str) -> tuple[UserWebApiClient, HomeDataDevice]:
    logger.info("Logging in to Roborock", username=username)
    # Login via your password
    web_api = RoborockApiClient(username=username)
    user_data = await web_api.pass_login(password=password)
    user_web_api = UserWebApiClient(web_api, user_data)

    home_data = await user_web_api.get_home_data()
    logger.debug("Retrieved Roborock home data", home_data=home_data)
    vacuum_device = home_data.devices[0]
    return user_web_api, vacuum_device


async def main() -> None:
    async with ClientSession() as session:
        account = Account(websession=session)
        feeder, litter_box = await _get_robots(account)
        logger.info("Feeder connected", feeder=feeder)
        logger.info("Litter box connected", litter_box=litter_box)
        roborock_api_client, vacuum_device = await _get_vacuum(username=ROBOROCK_USERNAME, password=ROBOROCK_PASSWORD)
        logger.info("Vacuum device connected", vacuum_device=vacuum_device)

        while True:
            logger.info("Refreshing litter box")
            await litter_box.refresh()
            activity_history = await litter_box.get_activity_history(1)
            latest_activity = activity_history[0]
            if latest_activity.action != LitterBoxStatus.CLEAN_CYCLE_COMPLETE:
                logger.warning("Litter box clean cycle not completed", latest_activity=latest_activity)
                await asyncio.sleep(60)
                continue
            if isinstance(latest_activity.timestamp, date):  # pyright: ignore[reportUnnecessaryIsInstance]: timestamp could be a datetime
                logger.error("Litter box clean cycle timestamp is a date", latest_activity=latest_activity)
                await asyncio.sleep(60)
                continue

            now = datetime.now(tz=UTC)
            if now - cast("datetime", latest_activity.timestamp) > timedelta(minutes=10):
                logger.warning(
                    "Litter box clean cycle not detected in the last 10 minutes",
                    latest_activity=latest_activity,
                    now=now,
                )
                await asyncio.sleep(60)
                continue

            logger.info(
                "Litter box clean cycle completed in the last 10 minutes. Vacuuming",
            )

            logger.debug("Vacuum device ready", vacuum_device=vacuum_device)
            vacuum_routines = await roborock_api_client.get_routines(vacuum_device.duid)
            litter_routine: HomeDataScene | None = None
            for routine in vacuum_routines:
                if routine.name != "Litter":
                    continue

                litter_routine = routine
                break

            if not litter_routine:
                logger.warning("No litter routine found")
                await asyncio.sleep(10)
                continue

            logger.info("Executing litter routine", routine=litter_routine)
            await roborock_api_client.execute_routine(litter_routine.id)

            logger.info("Vacuuming complete. Waiting 15 minutes before next vacuum")
            await asyncio.sleep(60 * 15)


if __name__ == "__main__":
    asyncio.run(main())
