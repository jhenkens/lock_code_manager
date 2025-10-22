"""Text for lock_code_manager."""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import async_create
from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENABLED, CONF_NAME, CONF_PIN, STATE_ON, Platform
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
        "text"
    ] = async_add_entities
    return True


class LockCodeManagerText(BaseLockCodeManagerEntity, TextEntity):
    """Text entity for lock code manager."""

    _attr_native_min = 0
    _enabled_entity_id: str = ""

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        config_entry: ConfigEntry,
        slot_key: int,
        key: str,
        text_mode: TextMode,
    ) -> None:
        """Initialize Text entity."""
        BaseLockCodeManagerEntity.__init__(
            self, hass, ent_reg, config_entry, slot_key, key
        )
        self._attr_mode = text_mode
        self._default_value = ""
        if text_mode == TextMode.PASSWORD:
            self._attr_native_max = 8
            self._attr_pattern: str = "^[0-9A-Z]*$"

    @property
    def native_value(self) -> str | None:
        """Return native value."""
        return self._state

    async def async_set_value(self, value: str) -> None:
        """Set value of text."""
        if not self._enabled_entity_id:
            self._enabled_entity_id = self.ent_reg.async_get_entity_id(
                Platform.SWITCH, DOMAIN, self._get_uid(CONF_ENABLED)
            )
        if (
            self.key == CONF_PIN
            and not value.strip()
            and self._enabled_entity_id
            and (state := self.hass.states.get(self._enabled_entity_id))
            and state.state == STATE_ON
        ):
            async_create(
                self.hass,
                (
                    f"PIN must be a valid value because slot {self.slot_key} is "
                    f"enabled on the lock configuration {self.config_entry.title}."
                ),
                "Problem with Lock Code Manager",
                f"{DOMAIN}_{self.config_entry.entry_id}_{self.slot_key}_pin_required",
            )
            return

        self._update_config_entry(value)

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await BaseLockCodeManagerEntity.async_added_to_hass(self)
        await TextEntity.async_added_to_hass(self)
