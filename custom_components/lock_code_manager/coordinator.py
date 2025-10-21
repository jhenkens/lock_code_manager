"""Lock Code Manager Coordinators."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .exceptions import LockDisconnected
from .providers import BaseLock

_LOGGER = logging.getLogger(__name__)


class LockUsercodeUpdateCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Class to manage usercode updates."""

    def __init__(
        self, hass: HomeAssistant, lock: BaseLock, config_entry: ConfigEntry
    ) -> None:
        """Initialize the usercode update coordinator."""
        self._lock = lock
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {lock.lock.entity_id}",
            update_method=self.async_get_usercodes,
            update_interval=lock.usercode_scan_interval,
            config_entry=config_entry,
        )
        self.data: dict[str, str] = {}

    async def async_get_usercodes(self) -> dict[str, str]:
        """Update usercodes.

        Returns:
            Dictionary mapping slot keys (as strings) to usercode values (as strings).
            Empty string means slot is empty/cleared.
        """
        try:
            raw_data = await self._lock.async_internal_get_usercodes()
            logging.debug("Fetched usercodes for lock %s: %s", self._lock.lock.entity_id, raw_data)
            # Ensure all keys and values are strings
            return {str(k): str(v) if v else "" for k, v in raw_data.items()}
        except LockDisconnected as err:
            # We can silently fail if we've never been able to retrieve data
            if not self.data:
                return {}
            raise UpdateFailed from err

    def get_slot_value(self, slot_key: int | str) -> str | None:
        """Get the usercode for a specific slot.

        Args:
            slot_key: The slot key (will be converted to string)

        Returns:
            The usercode as a string, empty string if slot is cleared, or None if slot doesn't exist
        """
        return self.data.get(str(slot_key))
