import asyncio
from datetime import UTC, datetime, timedelta
import os
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from aiohttp import ClientSession
from pylitterbot import FeederRobot, LitterRobot4
from pylitterbot.account import Account
from pylitterbot.enums import LitterBoxStatus
from roborock.web_api import RoborockApiClient, UserWebApiClient
import sentry_sdk

from core.logging import get_logger
from core.roborock_auth import (
    RoborockAuthenticationError,
    discover_api_base_url,
    login_from_session,
    login_with_password,
)

if TYPE_CHECKING:
    from roborock import HomeDataDevice, HomeDataScene  # pyright: ignore[reportPrivateImportUsage]

logger = get_logger(__name__)

SENTRY_DSN = os.getenv("SENTRY_DSN", "")

sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=False,
    include_local_variables=False,
)


WHISKER_USERNAME = os.getenv("WHISKER_USERNAME", "")
WHISKER_PASSWORD = os.getenv("WHISKER_PASSWORD", "")
ROBOROCK_USERNAME = os.getenv("ROBOROCK_USERNAME", "")
ROBOROCK_PASSWORD = os.getenv("ROBOROCK_PASSWORD", "")
ROBOROCK_SESSION = os.getenv("ROBOROCK_SESSION", "")

if not all([WHISKER_USERNAME, WHISKER_PASSWORD, ROBOROCK_USERNAME]):
    raise ValueError("Missing required environment variables")
if not ROBOROCK_SESSION and not ROBOROCK_PASSWORD:
    raise ValueError("Missing Roborock session or password")


async def _get_robots(account: Account) -> tuple[FeederRobot, LitterRobot4]:
    feeder: FeederRobot
    litter_box: LitterRobot4

    try:
        logger.info("Connecting to Whisker")
        await account.connect(username=WHISKER_USERNAME, password=WHISKER_PASSWORD, load_robots=True)
        logger.info(
            "Connected to Whisker",
            robot_count=len(account.robots),
            robot_types=[type(robot).__name__ for robot in account.robots],
        )
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
    username: str, password: str, stored_session: str, session: ClientSession
) -> tuple[UserWebApiClient, HomeDataDevice]:
    if stored_session:
        logger.info("Using stored Roborock session")
        try:
            login_result = login_from_session(stored_session)
        except RoborockAuthenticationError as error:
            logger.exception(
                "Stored Roborock session is invalid; refresh ROBOROCK_SESSION",
                reason=str(error),
            )
            raise
    else:
        logger.info("Logging in to Roborock")
        login_result = await login_with_password(
            session=session,
            username=username,
            password=password,
        )
    base_url = login_result.base_url
    if base_url is None:
        base_url = await discover_api_base_url(session, username)
    web_api = RoborockApiClient(username=username, base_url=base_url, session=session)
    user_web_api = UserWebApiClient(web_api, login_result.user_data)

    home_data = await user_web_api.get_home_data()
    logger.debug("Retrieved Roborock home data", device_count=len(home_data.devices))
    vacuum_device = home_data.devices[0]
    return user_web_api, vacuum_device


async def main() -> None:
    async with ClientSession() as session:
        account = Account(websession=session)
        feeder, litter_box = await _get_robots(account)
        logger.info("Feeder connected", feeder=feeder)
        logger.info("Litter box connected", litter_box=litter_box)
        roborock_api_client, vacuum_device = await _get_vacuum(
            username=ROBOROCK_USERNAME,
            password=ROBOROCK_PASSWORD,
            stored_session=ROBOROCK_SESSION,
            session=session,
        )
        logger.info("Vacuum device connected", device_name=vacuum_device.name)

        while True:
            logger.info("Refreshing litter box")
            await litter_box.refresh()
            activity_history = await litter_box.get_activity_history(1)
            latest_activity = activity_history[0]
            if latest_activity.action != LitterBoxStatus.CLEAN_CYCLE_COMPLETE:
                logger.warning("Litter box clean cycle not completed", latest_activity=latest_activity)
                await asyncio.sleep(60)
                continue
            if not isinstance(latest_activity.timestamp, datetime):
                logger.error("Litter box clean cycle timestamp is a date", latest_activity=latest_activity)
                await asyncio.sleep(60)
                continue

            now = datetime.now(tz=UTC)
            if now - latest_activity.timestamp > timedelta(minutes=10):
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

            logger.debug("Vacuum device ready", device_name=vacuum_device.name)

            now_pacific_time = now.astimezone(tz=ZoneInfo("America/Los_Angeles"))
            relevant_litter_routine_name: Literal["Litter"] | Literal["Litter (quiet)"] = "Litter"
            if now_pacific_time.hour < 9 or now_pacific_time.hour > 22:
                relevant_litter_routine_name = "Litter (quiet)"

            vacuum_routines = await roborock_api_client.get_routines(vacuum_device.duid)
            litter_routine: HomeDataScene | None = None
            for routine in vacuum_routines:
                if routine.name != relevant_litter_routine_name:
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
