"""Lock Code Manager Integration."""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    DOMAIN as LL_DOMAIN,
)
from homeassistant.components.text import TextMode
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryError
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    CONF_ENABLED,
    CONF_ID,
    CONF_NAME,
    CONF_PIN,
    CONF_URL,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import (
    CoreState,
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.core_config import Config
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)

from homeassistant.const import CONF_ENABLED, CONF_NAME, CONF_PIN

from .const import (
    ATTR_ACTIVE,
    ATTR_CODE,
    ATTR_CONFIGURED_PLATFORMS,
    ATTR_INITIALIZATION_COMPLETE,
    ATTR_IN_SYNC,
    CONF_LOCKS,
    CONF_NUMBER_OF_USES,
    CONF_READ_ONLY,
    CONF_SLOTS,
    COORDINATORS,
    DOMAIN,
    EVENT_PIN_USED,
    PLATFORM_MAP,
    PLATFORMS,
    SERVICE_HARD_REFRESH_USERCODES,
    STRATEGY_FILENAME,
    STRATEGY_PATH,
    Platform,
)
from .coordinator import LockUsercodeUpdateCoordinator
from .data import get_entry_data
from .helpers import async_create_lock_instance, get_locks_from_targets
from .providers import BaseLock
from .utils import (
    generate_entity_unique_id,
    generate_lock_entity_unique_id,
    generate_slot_device_identifier,
)
from .websocket import async_setup as async_websocket_setup

# Import entity classes for centralized creation
from .binary_sensor import (
    LockCodeManagerActiveEntity,
    LockCodeManagerCodeSlotInSyncEntity,
)
from .event import LockCodeManagerCodeSlotEventEntity
from .number import LockCodeManagerNumber
from .sensor import LockCodeManagerCodeSlotSensorEntity
from .switch import LockCodeManagerSwitch
from .text import LockCodeManagerText

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """Set up integration."""
    hass.data.setdefault(DOMAIN, {CONF_LOCKS: {}, COORDINATORS: {}, "resources": False})
    # Expose strategy javascript
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STRATEGY_PATH, Path(__file__).parent / "www" / STRATEGY_FILENAME, False
            )
        ]
    )
    _LOGGER.debug("Exposed strategy module at %s", STRATEGY_PATH)

    resources: ResourceStorageCollection | ResourceYAMLCollection | None = None
    if lovelace_data := hass.data.get(LL_DOMAIN):
        resources = lovelace_data.resources
    if resources:
        # Load resources if needed
        if not resources.loaded:
            await resources.async_load()
            _LOGGER.debug("Manually loaded resources")
            resources.loaded = True

        try:
            res_id = next(
                data.get(CONF_ID)
                for data in resources.async_items()
                if data[CONF_URL] == STRATEGY_PATH
            )
        except StopIteration:
            if isinstance(resources, ResourceYAMLCollection):
                _LOGGER.warning(
                    "Strategy module can't automatically be registered because this "
                    "Home Assistant instance is running in YAML mode for resources. "
                    "Please add a new entry in the list under the resources key in "
                    'the lovelace section of your config as follows:\n  - url: "%s"'
                    "\n    type: module",
                    STRATEGY_PATH,
                )
            else:
                # Register strategy module
                data = await resources.async_create_item(
                    {CONF_RESOURCE_TYPE_WS: "module", CONF_URL: STRATEGY_PATH}
                )
                _LOGGER.debug(
                    "Registered strategy module (resource ID %s)", data[CONF_ID]
                )
                hass.data[DOMAIN]["resources"] = True
        else:
            _LOGGER.debug(
                "Strategy module already registered with resource ID %s", res_id
            )

    # Set up websocket API
    await async_websocket_setup(hass)
    _LOGGER.debug("Finished setting up websocket API")

    # Hard refresh usercodes
    async def _hard_refresh_usercodes(service: ServiceCall) -> None:
        """Hard refresh all usercodes."""
        _LOGGER.debug("Hard refresh usercodes service called: %s", service.data)
        locks = get_locks_from_targets(hass, service.data)
        results = await asyncio.gather(
            *(lock.async_internal_hard_refresh_codes() for lock in locks),
            return_exceptions=True,
        )
        errors = [err for err in results if isinstance(err, Exception)]
        if errors:
            errors_str = "\n".join(str(errors))
            raise HomeAssistantError(
                "The following errors occurred while processing this service "
                f"request:\n{errors_str}"
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_HARD_REFRESH_USERCODES,
        _hard_refresh_usercodes,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Optional(ATTR_AREA_ID): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
                }
            ),
            cv.has_at_least_one_key(ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID),
            cv.has_at_most_one_key(ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID),
        ),
    )

    return True


@callback
def _setup_entry_after_start(
    hass: HomeAssistant, config_entry: ConfigEntry, event: Event | None = None
) -> None:
    """
    Set up config entry.

    Should only be run once Home Assistant has started.
    """
    config_entry.async_on_unload(
        config_entry.add_update_listener(async_update_listener)
    )

    if config_entry.data:
        # Move data from data to options so update listener can work
        hass.config_entries.async_update_entry(
            config_entry, data={}, options={**config_entry.data}
        )
    else:
        hass.async_create_task(
            async_update_listener(hass, config_entry),
            f"Initial setup for entities for {config_entry.entry_id}",
        )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    ent_reg = er.async_get(hass)
    entry_id = config_entry.entry_id
    try:
        entity_id = next(
            entity_id
            for entity_id in get_entry_data(config_entry, CONF_LOCKS, [])
            if not ent_reg.async_get(entity_id)
        )
    except StopIteration:
        pass
    else:
        config_entry.async_start_reauth(hass, context={"lock_entity_id": entity_id})
        raise ConfigEntryError(
            f"Unable to start because lock {entity_id} can't be found"
        )

    hass.data.setdefault(DOMAIN, {CONF_LOCKS: {}, COORDINATORS: {}, "resources": False})
    hass.data[DOMAIN][entry_id] = {
        CONF_LOCKS: {},
        COORDINATORS: {},
        ATTR_CONFIGURED_PLATFORMS: set(),  # Track which platforms are configured
        ATTR_INITIALIZATION_COMPLETE: False,  # Track if initial setup is complete
        "add_entities_callbacks": {},  # Store async_add_entities callbacks per platform
        "entities": {},  # Track created entities for removal: {platform: {slot_key: [entity, ...]}}
    }

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Lock Code Manager",
        name=config_entry.title,
        serial_number=entry_id,
    )

    # Set up core platforms that are always needed
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    # Mark them as configured
    hass.data[DOMAIN][entry_id][ATTR_CONFIGURED_PLATFORMS].update(PLATFORMS)

    if hass.state == CoreState.running:
        _setup_entry_after_start(hass, config_entry)
    else:
        # One-time listeners auto-cleanup after firing, don't register with async_on_unload
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            functools.partial(_setup_entry_after_start, hass, config_entry),
        )

    return True


async def async_unload_lock(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    lock_entity_id: str | None = None,
    remove_permanently: bool = False,
):
    """Unload lock."""
    hass_data = hass.data[DOMAIN]
    entry_id = config_entry.entry_id
    lock_entity_ids = (
        [lock_entity_id] if lock_entity_id else hass_data[entry_id][CONF_LOCKS].copy()
    )
    for _lock_entity_id in lock_entity_ids:
        if not any(
            entry != config_entry
            and _lock_entity_id
            in entry.data.get(CONF_LOCKS, entry.options.get(CONF_LOCKS, ""))
            for entry in hass.config_entries.async_entries(
                DOMAIN, include_disabled=False, include_ignore=False
            )
        ):
            lock: BaseLock = hass_data[CONF_LOCKS].pop(_lock_entity_id)
            await lock.async_unload(remove_permanently)

        hass_data[entry_id][CONF_LOCKS].pop(_lock_entity_id)

    for _lock_entity_id in lock_entity_ids:
        if not any(
            entry != config_entry
            and _lock_entity_id
            in entry.data.get(CONF_LOCKS, entry.options.get(CONF_LOCKS, ""))
            for entry in hass.config_entries.async_entries(
                DOMAIN, include_disabled=False, include_ignore=False
            )
        ):
            coordinator: LockUsercodeUpdateCoordinator = hass_data[COORDINATORS].pop(
                _lock_entity_id
            )
            await coordinator.async_shutdown()

        hass_data[entry_id][COORDINATORS].pop(_lock_entity_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    entry_id = config_entry.entry_id
    hass_data = hass.data[DOMAIN]

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry,
        hass_data[entry_id][ATTR_CONFIGURED_PLATFORMS],
    )

    if unload_ok:
        await async_unload_lock(hass, config_entry)
        hass_data.pop(entry_id, None)

    if {k: v for k, v in hass_data.items() if k != "resources"} == {
        CONF_LOCKS: {},
        COORDINATORS: {},
    }:
        resources: ResourceStorageCollection | ResourceYAMLCollection | None = None
        if lovelace_data := hass.data.get(LL_DOMAIN):
            resources = lovelace_data.resources
        if resources:
            if hass_data["resources"]:
                try:
                    resource_id = next(
                        data[CONF_ID]
                        for data in resources.async_items()
                        if data[CONF_URL] == STRATEGY_PATH
                    )
                except StopIteration:
                    _LOGGER.debug(
                        "Strategy module not found so there is nothing to remove"
                    )
                else:
                    await resources.async_delete_item(resource_id)
                    _LOGGER.debug(
                        "Removed strategy module (resource ID %s)", resource_id
                    )
            else:
                _LOGGER.debug(
                    "Strategy module not automatically registered, skipping removal"
                )

        hass.data.pop(DOMAIN)

    return unload_ok


def _create_slot_entities_for_lock(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    config_entry: ConfigEntry,
    lock: BaseLock,
    slot_key: str,
) -> tuple[list, list]:
    """Create sensor and binary_sensor entities for a lock/slot combination.

    Returns: (sensor_entities, binary_sensor_entities)
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS][
        lock.lock.entity_id
    ]

    sensor_entities = [
        LockCodeManagerCodeSlotSensorEntity(
            hass, ent_reg, config_entry, lock, coordinator, slot_key
        )
    ]

    binary_sensor_entities = [
        LockCodeManagerCodeSlotInSyncEntity(
            hass, ent_reg, config_entry, coordinator, lock, slot_key
        )
    ]

    return sensor_entities, binary_sensor_entities


def _create_standard_slot_entities(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    config_entry: ConfigEntry,
    slot_key: str,
    slot_config: dict[str, Any],
) -> tuple[list, list, list, list, list]:
    """Create standard entities for a slot.

    Returns: (binary_sensor_entities, event_entities, text_entities, switch_entities, number_entities)
    """
    binary_sensor_entities = [
        LockCodeManagerActiveEntity(hass, ent_reg, config_entry, slot_key, ATTR_ACTIVE)
    ]

    event_entities = [
        LockCodeManagerCodeSlotEventEntity(
            hass, ent_reg, config_entry, slot_key, EVENT_PIN_USED
        )
    ]

    text_entities = [
        LockCodeManagerText(hass, ent_reg, config_entry, slot_key, CONF_NAME, TextMode.TEXT),
        LockCodeManagerText(hass, ent_reg, config_entry, slot_key, CONF_PIN, TextMode.PASSWORD),
    ]

    switch_entities = [
        LockCodeManagerSwitch(hass, ent_reg, config_entry, slot_key, CONF_ENABLED)
    ]

    number_entities = []
    if slot_config.get(CONF_NUMBER_OF_USES) not in (None, ""):
        number_entities = [
            LockCodeManagerNumber(hass, ent_reg, config_entry, slot_key, CONF_NUMBER_OF_USES)
        ]

    return binary_sensor_entities, event_entities, text_entities, switch_entities, number_entities


async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update listener."""
    # No need to update if there are no options because that only happens at the end
    # of this function
    if not config_entry.options:
        return

    hass_data = hass.data[DOMAIN]
    ent_reg = er.async_get(hass)

    entry_id = config_entry.entry_id
    entry_title = config_entry.title
    _LOGGER.info("%s (%s): Creating and/or updating entities", entry_id, entry_title)

    configured_platforms: set[Platform] = hass_data[entry_id][ATTR_CONFIGURED_PLATFORMS]

    curr_slots: dict[str, Any] = {**config_entry.data.get(CONF_SLOTS, {})}
    new_slots: dict[str, Any] = {**config_entry.options.get(CONF_SLOTS, {})}
    curr_locks: list[str] = [*config_entry.data.get(CONF_LOCKS, [])]
    new_locks: list[str] = [*config_entry.options.get(CONF_LOCKS, [])]

    # Set up any platforms that the new slot configs need that haven't already been
    # setup
    # Step 1: Collect all platforms needed by slot configurations
    needed_platforms: set[Platform] = set()
    for slot_config in new_slots.values():
        for key, platform in PLATFORM_MAP.items():
            if key in slot_config:
                needed_platforms.add(platform)

    # Step 2: Filter to only new platforms (not already configured, not calendar)
    new_platforms = [
        platform
        for platform in needed_platforms
        if platform not in configured_platforms and platform != Platform.CALENDAR
    ]

    if new_platforms:
        # Forward all new platforms at once
        await hass.config_entries.async_forward_entry_setups(config_entry, new_platforms)
        # Track that these platforms are now configured
        configured_platforms.update(new_platforms)

    # Identify changes that need to be made
    slots_to_add: dict[str, Any] = {
        k: v for k, v in new_slots.items() if k not in curr_slots
    }
    slots_to_remove: dict[str, Any] = {
        k: v for k, v in curr_slots.items() if k not in new_slots
    }
    locks_to_add: list[str] = [lock for lock in new_locks if lock not in curr_locks]
    locks_to_remove: list[str] = [lock for lock in curr_locks if lock not in new_locks]

    # Remove old lock entities (slot sensors)
    for lock_entity_id in locks_to_remove:
        _LOGGER.debug(
            "%s (%s): Removing lock %s entities", entry_id, entry_title, lock_entity_id
        )
        # Remove sensor and binary_sensor entities for this lock across all slots that exist
        for slot_key in curr_slots:
            # Remove sensor entity
            sensor_unique_id = generate_lock_entity_unique_id(
                entry_id, slot_key, ATTR_CODE, lock_entity_id
            )
            if sensor_entity_id := ent_reg.async_get_entity_id(
                Platform.SENSOR, DOMAIN, sensor_unique_id
            ):
                ent_reg.async_remove(sensor_entity_id)

            # Remove binary_sensor in-sync entity
            binary_sensor_unique_id = generate_lock_entity_unique_id(
                entry_id, slot_key, ATTR_IN_SYNC, lock_entity_id
            )
            if binary_sensor_entity_id := ent_reg.async_get_entity_id(
                Platform.BINARY_SENSOR, DOMAIN, binary_sensor_unique_id
            ):
                ent_reg.async_remove(binary_sensor_entity_id)

        lock: BaseLock = hass.data[DOMAIN][CONF_LOCKS][lock_entity_id]
        if lock.device_entry:
            dev_reg = dr.async_get(hass)
            dev_reg.async_update_device(
                lock.device_entry.id, remove_config_entry_id=entry_id
            )
        await async_unload_lock(
            hass, config_entry, lock_entity_id=lock_entity_id, remove_permanently=True
        )

    # Create slot PIN sensors for the new locks
    if locks_to_add:
        _LOGGER.debug(
            "%s (%s): Adding following locks: %s",
            entry_id,
            entry_title,
            locks_to_add,
        )
        for lock_entity_id in locks_to_add:
            if lock_entity_id in hass_data[CONF_LOCKS]:
                _LOGGER.debug(
                    "%s (%s): Reusing lock instance for lock %s",
                    entry_id,
                    entry_title,
                    hass_data[CONF_LOCKS][lock_entity_id],
                )
                lock = hass_data[entry_id][CONF_LOCKS][lock_entity_id] = hass_data[
                    CONF_LOCKS
                ][lock_entity_id]
            else:
                lock = hass_data[CONF_LOCKS][lock_entity_id] = hass.data[DOMAIN][
                    entry_id
                ][CONF_LOCKS][lock_entity_id] = async_create_lock_instance(
                    hass,
                    dr.async_get(hass),
                    ent_reg,
                    config_entry,
                    lock_entity_id,
                )
                _LOGGER.debug(
                    "%s (%s): Creating lock instance for lock %s",
                    entry_id,
                    entry_title,
                    lock,
                )
                await lock.async_setup()

            # The coordinator will handle lock availability - no need to block here
            # Entities will show as unavailable if lock is disconnected

            if lock_entity_id in hass_data[COORDINATORS]:
                _LOGGER.debug(
                    "%s (%s): Reusing coordinator for lock %s",
                    entry_id,
                    entry_title,
                    lock,
                )
                coordinator = hass_data[entry_id][COORDINATORS][lock_entity_id] = (
                    hass_data[COORDINATORS][lock_entity_id]
                )
            else:
                _LOGGER.debug(
                    "%s (%s): Creating coordinator for lock %s",
                    entry_id,
                    entry_title,
                    lock,
                )
                coordinator = hass_data[COORDINATORS][lock_entity_id] = hass_data[
                    entry_id
                ][COORDINATORS][lock_entity_id] = LockUsercodeUpdateCoordinator(
                    hass, lock, config_entry
                )
                await coordinator.async_request_refresh()
            # Get callbacks
            add_sensor = hass_data[entry_id]["add_entities_callbacks"].get("sensor")
            add_binary_sensor = hass_data[entry_id]["add_entities_callbacks"].get("binary_sensor")

            for slot_key in new_slots:
                _LOGGER.debug(
                    "%s (%s): Adding lock %s slot %s sensor and binary_sensor entities",
                    entry_id,
                    entry_title,
                    lock_entity_id,
                    slot_key,
                )
                # Create entities directly (only if callbacks are available)
                sensor_entities, binary_sensor_entities = _create_slot_entities_for_lock(
                    hass, ent_reg, config_entry, lock, slot_key
                )
                if add_sensor:
                    add_sensor(sensor_entities)
                if add_binary_sensor:
                    add_binary_sensor(binary_sensor_entities)

    # Remove slot entities that are no longer in the config
    for slot_key in slots_to_remove.keys():
        _LOGGER.debug(
            "%s (%s): Removing slot %s entities", entry_id, entry_title, slot_key
        )
        # Remove all entities for this slot
        # Standard entities (not lock-specific)
        for entity_platform, entity_key in [
            (Platform.BINARY_SENSOR, ATTR_ACTIVE),
            (Platform.EVENT, EVENT_PIN_USED),
            (Platform.TEXT, CONF_NAME),
            (Platform.TEXT, CONF_PIN),
            (Platform.SWITCH, CONF_ENABLED),
            (Platform.NUMBER, CONF_NUMBER_OF_USES),
        ]:
            unique_id = generate_entity_unique_id(entry_id, slot_key, entity_key)
            if entity_id := ent_reg.async_get_entity_id(entity_platform, DOMAIN, unique_id):
                ent_reg.async_remove(entity_id)

        # Lock-specific entities (sensor and binary_sensor for each lock that existed)
        for lock_entity_id in curr_locks:
            # Remove sensor entity
            sensor_unique_id = generate_lock_entity_unique_id(
                entry_id, slot_key, ATTR_CODE, lock_entity_id
            )
            if sensor_entity_id := ent_reg.async_get_entity_id(
                Platform.SENSOR, DOMAIN, sensor_unique_id
            ):
                ent_reg.async_remove(sensor_entity_id)

            # Remove binary_sensor in-sync entity
            binary_sensor_unique_id = generate_lock_entity_unique_id(
                entry_id, slot_key, ATTR_IN_SYNC, lock_entity_id
            )
            if binary_sensor_entity_id := ent_reg.async_get_entity_id(
                Platform.BINARY_SENSOR, DOMAIN, binary_sensor_unique_id
            ):
                ent_reg.async_remove(binary_sensor_entity_id)

        # Remove the device for this slot if it exists
        dev_reg = dr.async_get(hass)
        if device := dev_reg.async_get_device(
            identifiers={generate_slot_device_identifier(entry_id, slot_key)}
        ):
            dev_reg.async_remove_device(device.id)

    # Get all callbacks once, outside the loops
    # Use .get() to handle cases where platforms haven't been loaded yet
    add_sensor = hass_data[entry_id]["add_entities_callbacks"].get("sensor")
    add_binary_sensor = hass_data[entry_id]["add_entities_callbacks"].get("binary_sensor")
    add_event = hass_data[entry_id]["add_entities_callbacks"].get("event")
    add_text = hass_data[entry_id]["add_entities_callbacks"].get("text")
    add_switch = hass_data[entry_id]["add_entities_callbacks"].get("switch")
    add_number = hass_data[entry_id]["add_entities_callbacks"].get("number")

    # For each new slot, add standard entities and configuration entities. We also
    # add slot sensors for existing locks only since new locks were already set up
    # above.
    for slot_key, slot_config in slots_to_add.items():
        _LOGGER.debug(
            "%s (%s): Adding entities for slot %s",
            entry_id,
            entry_title,
            slot_key,
        )

        # Add lock-specific entities for existing locks (new locks already done above)
        for lock_entity_id, lock in hass_data[entry_id][CONF_LOCKS].items():
            if lock_entity_id in locks_to_add:
                continue
            sensor_entities, binary_sensor_in_sync_entities = _create_slot_entities_for_lock(
                hass, ent_reg, config_entry, lock, slot_key
            )
            if add_sensor:
                add_sensor(sensor_entities)
            if add_binary_sensor:
                add_binary_sensor(binary_sensor_in_sync_entities)

        # Create standard slot entities
        (
            binary_sensor_active_entities,
            event_entities,
            text_entities,
            switch_entities,
            number_entities,
        ) = _create_standard_slot_entities(hass, ent_reg, config_entry, slot_key, slot_config)

        # Add all entities (only if callbacks are available)
        if add_binary_sensor:
            add_binary_sensor(binary_sensor_active_entities)
        if add_event:
            add_event(event_entities)
        if add_text:
            add_text(text_entities)
        if add_switch:
            add_switch(switch_entities)
        if number_entities and add_number:
            add_number(number_entities)

    # For all slots that are in both the old and new config, check if any of the
    # configuration options have changed
    for slot_key in set(curr_slots).intersection(new_slots):
        # Check if number of uses has changed
        old_val = curr_slots[slot_key].get(CONF_NUMBER_OF_USES)
        new_val = new_slots[slot_key].get(CONF_NUMBER_OF_USES)

        # If number of uses value hasn't changed, skip
        if old_val == new_val:
            continue

        # If number of uses value has been removed, remove corresponding entity
        if old_val not in (None, "") and new_val in (None, ""):
            _LOGGER.debug(
                "%s (%s): Removing %s entity for slot %s due to changed configuration",
                entry_id,
                entry_title,
                CONF_NUMBER_OF_USES,
                slot_key,
            )
            # Find and remove the entity from entity registry
            unique_id = generate_entity_unique_id(entry_id, slot_key, CONF_NUMBER_OF_USES)
            if entity_id := ent_reg.async_get_entity_id(Platform.NUMBER, DOMAIN, unique_id):
                ent_reg.async_remove(entity_id)

        # If number of uses value has been added, create corresponding entity
        elif old_val in (None, "") and new_val not in (None, ""):
            _LOGGER.debug(
                "%s (%s): Adding %s entity for slot %s due to changed configuration",
                entry_id,
                entry_title,
                CONF_NUMBER_OF_USES,
                slot_key,
            )
            # Create number entity directly (only if callback is available)
            if add_number:
                number_entity = LockCodeManagerNumber(
                    hass, ent_reg, config_entry, slot_key, CONF_NUMBER_OF_USES
                )
                add_number([number_entity])

    # Existing entities will listen to updates and act on it
    new_data = {
        CONF_LOCKS: new_locks,
        CONF_SLOTS: new_slots,
        CONF_READ_ONLY: config_entry.options.get(CONF_READ_ONLY, False),
    }
    _LOGGER.info(
        "%s (%s): Done creating and/or updating entities", entry_id, entry_title
    )

    # Mark initialization as complete - entities can now perform sync operations
    hass_data[entry_id][ATTR_INITIALIZATION_COMPLETE] = True

    # Trigger a coordinator refresh to check sync status now that init is complete
    for coordinator in hass_data[entry_id][COORDINATORS].values():
        await coordinator.async_request_refresh()

    hass.config_entries.async_update_entry(config_entry, data=new_data, options={})
