"""Base entity class for Lock Code Manager."""

from __future__ import annotations

import copy
import logging
from typing import Any, final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.components.lock import LockState
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.helpers.event import TrackStates, async_track_state_change_filtered

from .const import (
    ATTR_CODE_SLOT,
    ATTR_TO,
    CONF_CALENDAR,
    CONF_LOCKS,
    CONF_SLOTS,
    DOMAIN,
)
from .data import get_slot_data
from .providers import BaseLock
from .utils import generate_entity_unique_id, generate_lock_entity_unique_id

_LOGGER = logging.getLogger(__name__)


class BaseLockCodeManagerEntity(Entity):
    """Base Lock Code Manager Entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_should_poll = False
    _default_value = None

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        config_entry: ConfigEntry,
        slot_key: int,
        key: str,
    ) -> None:
        """Initialize base entity."""
        self._hass = hass
        self.config_entry = config_entry
        self.entry_id = self.base_unique_id = config_entry.entry_id
        self.locks: list[BaseLock] = list(
            hass.data[DOMAIN][config_entry.entry_id][CONF_LOCKS].values()
        )
        self.slot_key = slot_key
        self.key = key
        self.ent_reg = ent_reg

        self._uid_cache: dict[str, str] = {}

        self._attr_translation_key = key
        self._attr_translation_placeholders = {"slot_key": slot_key}

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry_id}|{slot_key}")},
            name=f"{config_entry.title} Code slot {slot_key}",
            manufacturer="Lock Code Manager",
            model="Code Slot",
            via_device=(DOMAIN, self.entry_id),
        )

        self._attr_unique_id = generate_entity_unique_id(
            self.base_unique_id, slot_key, key
        )
        self._attr_extra_state_attributes: dict[str, int | list[str]] = {
            ATTR_CODE_SLOT: int(slot_key)
        }

    @final
    @property
    def _state(self) -> Any:
        """Return state of entity."""
        return get_slot_data(self.config_entry, self.slot_key).get(self.key, self._default_value)

    @final
    @property
    def _calendar_entity_id(self) -> str | None:
        """Return calendar entity ID for this slot."""
        return get_slot_data(self.config_entry, self.slot_key).get(CONF_CALENDAR)

    @final
    def _get_uid(self, key: str) -> str:
        """Get and cache unique id for a given key."""
        if key not in self._uid_cache:
            self._uid_cache[key] = f"{self.base_unique_id}|{self.slot_key}|{key}"
        return self._uid_cache[key]

    @callback
    @final
    def _update_config_entry(self, value: Any) -> None:
        """Update config entry data."""
        _LOGGER.debug(
            "%s (%s): Updating %s to %s",
            self.config_entry.entry_id,
            self.config_entry.title,
            self.key,
            value,
        )
        data = copy.deepcopy(dict(self.config_entry.data))
        data[CONF_SLOTS][self.slot_key][self.key] = value
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.async_write_ha_state()

    async def _internal_async_remove(self) -> None:
        """
        Handle entity removal.

        Should not be overwritten by platforms.
        """
        _LOGGER.debug(
            "%s (%s): Removing entity %s",
            self.config_entry.entry_id,
            self.config_entry.title,
            self.entity_id,
        )
        await self._async_remove()
        await self.async_remove(force_remove=True)
        if self.ent_reg.async_get(self.entity_id):
            self.ent_reg.async_remove(self.entity_id)

    async def _async_remove(self) -> None:
        """
        Handle entity removal.

        Can be overwritten by platforms.
        """
        pass

    @callback
    def _event_filter(self, event_data: dict[str, Any]) -> bool:
        """Filter events."""
        return (
            any(
                event_data[ATTR_ENTITY_ID] == lock.lock.entity_id for lock in self.locks
            )
            and event_data[ATTR_CODE_SLOT] == int(self.slot_key)
            and event_data[ATTR_TO] == LockState.UNLOCKED
        )

    @callback
    def _is_available(self) -> bool:
        """Return whether entity should be available."""
        return any(
            state.state != STATE_UNAVAILABLE
            for lock in self.locks
            if (state := self.hass.states.get(lock.lock.entity_id))
        )

    @callback
    def _handle_available_state_update(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Update binary sensor state by getting dependent states."""
        entity_id: str | None = None
        from_state: State | None = None
        to_state: State | None = None
        if event:
            entity_id = event.data["entity_id"]
            from_state = event.data["old_state"]
            to_state = event.data["new_state"]

        if entity_id is not None and entity_id not in (
            lock.lock.entity_id for lock in self.locks
        ):
            return

        if (from_state and STATE_UNAVAILABLE != from_state.state) and (
            to_state and STATE_UNAVAILABLE != to_state.state
        ):
            return

        if (new_available := self._is_available()) != self._attr_available:
            self._attr_available: bool = new_available
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await Entity.async_added_to_hass(self)

        self.async_on_remove(
            async_track_state_change_filtered(
                self.hass,
                TrackStates(True, set(), set()),
                self._handle_available_state_update,
            ).async_remove
        )
        self._handle_available_state_update()

        _LOGGER.debug(
            "%s (%s): Adding entity %s",
            self.config_entry.entry_id,
            self.config_entry.title,
            self.entity_id,
        )


class BaseLockCodeManagerCodeSlotPerLockEntity(BaseLockCodeManagerEntity):
    """Base LockCode Manager Code Slot Entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        ent_reg: er.EntityRegistry,
        config_entry: ConfigEntry,
        lock: BaseLock,
        slot_key: int,
        key: str,
    ) -> None:
        """Initialize entity."""
        BaseLockCodeManagerEntity.__init__(
            self, hass, ent_reg, config_entry, slot_key, key
        )
        self.lock = lock
        if lock.device_entry:
            self._attr_device_info = DeviceInfo(
                connections=lock.device_entry.connections,
                identifiers=lock.device_entry.identifiers,
            )

        self._attr_unique_id = generate_lock_entity_unique_id(
            self.base_unique_id, slot_key, self.key, lock.lock.entity_id
        )

    @callback
    def _is_available(self) -> bool:
        """Return whether entity is available."""
        return (
            state := self.hass.states.get(self.lock.lock.entity_id)
        ) and state.state != STATE_UNAVAILABLE

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await BaseLockCodeManagerEntity.async_added_to_hass(self)
