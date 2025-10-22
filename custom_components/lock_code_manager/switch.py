"""Switch for lock_code_manager."""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import async_create
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENABLED, CONF_PIN, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BaseLockCodeManagerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up config entry."""
    # Store callback for centralized entity management
    hass.data[DOMAIN][config_entry.entry_id]["add_entities_callbacks"][
        "switch"
    ] = async_add_entities
    return True


class LockCodeManagerSwitch(BaseLockCodeManagerEntity, SwitchEntity):
    """Switch entity for lock code manager."""

    _pin_entity_id: str = ""

    @property
    def is_on(self) -> bool:
        """Return native value."""
        return self._state

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on switch."""
        if not self._pin_entity_id:
            self._pin_entity_id = self.ent_reg.async_get_entity_id(
                Platform.TEXT, DOMAIN, self._get_uid(CONF_PIN)
            )
        if (
            self._pin_entity_id
            and (state := self.hass.states.get(self._pin_entity_id))
            and state.state in (None, "", STATE_UNKNOWN)
        ):
            async_create(
                self.hass,
                (
                    f"PIN is required to enable slot {self.slot_key} on the lock "
                    f"configuration {self.config_entry.title}."
                ),
                "Problem with Lock Code Manager",
                f"{DOMAIN}_{self.config_entry.entry_id}_{self.slot_key}_pin_required",
            )
            return
        self._update_config_entry(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off switch."""
        self._update_config_entry(False)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await BaseLockCodeManagerEntity.async_added_to_hass(self)
        await SwitchEntity.async_added_to_hass(self)
