from __future__ import annotations

from pathlib import Path

import nodriver as nd


_PROFILE_DIR = (
    Path(__file__).resolve().parent.parent
    / ".chrome_profile_nd"
)


async def create_browser(
    headless: bool = False,
) -> nd.Browser:
    """
    Start a nodriver Chrome browser using a persistent profile.
    """

    _PROFILE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    browser = await nd.start(
        user_data_dir=str(_PROFILE_DIR),
        lang="en-AU",
        headless=headless,
        no_sandbox=True,
    )

    return browser