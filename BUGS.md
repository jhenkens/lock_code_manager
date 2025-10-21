# Lock Code Manager - Bug Tracker

This file tracks bugs found in Home Assistant log analysis. Issues are prioritized and categorized for systematic resolution.

## Critical Bugs

### BUG-001: Platform Already Setup ValueError
**Priority:** HIGH
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
Multiple `ValueError` exceptions when setting up platforms during integration load. The integration attempts to set up the same platforms (text, switch) multiple times for the same config entry, causing failures.

**Log Evidence:**
```
ValueError: Config entry House Locks (01K82F0V7Q5E4V1FNAYNRPYWTB) for lock_code_manager.text has already been setup!
ValueError: Config entry House Locks (01K82F0V7Q5E4V1FNAYNRPYWTB) for lock_code_manager.switch has already been setup!
```

**Stack Trace:**
```
Traceback (most recent call last):
  File "/usr/src/homeassistant/homeassistant/config_entries.py", line 761, in __async_setup_with_context
    result = await component.async_setup_entry(hass, self)
  File "/usr/src/homeassistant/homeassistant/components/switch/__init__.py", line 79, in async_setup_entry
    return await hass.data[DATA_COMPONENT].async_setup_entry(entry)
  File "/usr/src/homeassistant/homeassistant/helpers/entity_component.py", line 210, in async_setup_entry
    raise ValueError(...)
```

**Occurrences:**
- 3 text platform errors
- 7 switch platform errors
- Happens during initial setup at 11:34:54

**Root Cause:**
Home Assistant's `entity_component.py` tracks which platforms have been set up for each config entry. When `async_forward_entry_setups()` is called for a platform that's already been set up, it raises a ValueError.

This indicates `async_update_listener()` is being called **during** the initial setup phase (when `async_setup_entry()` already sets up platforms), or platforms are being forwarded multiple times.

**Impact:**
- Prevents proper platform initialization
- Entities may not be created correctly
- Log spam with error messages
- Triggers cascade of other issues (BUG-002)

**Fix Strategy:**
1. Investigate why `async_update_listener()` is called during initial setup
2. Ensure platforms are only forwarded when actually new (not already in `configured_platforms`)
3. Consider only setting up platforms in `async_setup_entry()`, not in update listener
4. Or: Only call update listener after initial setup is complete

**Related Code:**
- `custom_components/lock_code_manager/__init__.py:370-383` (async_update_listener)
- `custom_components/lock_code_manager/__init__.py:228` (async_setup_entry - initial platform setup)

---

### BUG-002: Duplicate Entity ID Registration
**Priority:** HIGH
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
Home Assistant reports duplicate unique IDs when trying to register sensor entities, causing sensors to be ignored and not created.

**Log Evidence:**
```
ERROR Platform lock_code_manager does not generate unique IDs. ID 01K82F0V7Q5E4V1FNAYNRPYWTB|1|code|lock.back_door already exists - ignoring sensor.back_door_lock_code_slot_1
ERROR Platform lock_code_manager does not generate unique IDs. ID 01K82F0V7Q5E4V1FNAYNRPYWTB|2|code|lock.front_door already exists - ignoring sensor.front_door_lock_code_slot_2
```

**Occurrences:**
- Multiple instances for all locks (back_door, front_door, garage_door)
- Affects slots 1-9
- Happens shortly after initial setup (11:35:03)

**Root Cause:**
The integration appears to be trying to register the same sensor entities twice, possibly due to:
1. BUG-001 causing platforms to be set up multiple times
2. Event handlers firing multiple times
3. Dispatcher signals being sent when entities already exist

**Impact:**
- Sensors are not created properly
- User cannot see lock codes in UI
- Data not available for automations

**Fix Strategy:**
1. Fix BUG-001 first (root cause of duplicate registrations)
2. Add checks before dispatching entity creation signals
3. Ensure dispatcher handlers are idempotent

**Related Code:**
- `custom_components/lock_code_manager/__init__.py` (dispatcher signals)
- `custom_components/lock_code_manager/sensor.py` (entity registration)

---

## High Priority Bugs

### BUG-003: NoEntitySpecifiedError During Binary Sensor Creation
**Priority:** HIGH
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
Binary sensor entities crash with `NoEntitySpecifiedError` when trying to write state during the `async_device_update()` call that happens as part of entity registration. The entity tries to write state before it's fully added to Home Assistant's entity registry.

**Log Evidence:**
```
ERROR [custom_components.lock_code_manager.binary_sensor] Updating lock.back_door code slot 1 because it is out of sync. Current states: pin=Unknown, name=Unknown, active=Unknown, code_on_lock=Unknown, coordinator_data=4269, is_on=None
ERROR [homeassistant.components.binary_sensor] lock_code_manager: Error on device update!
```

**Stack Trace:**
```
Traceback (most recent call last):
  File "/usr/src/homeassistant/homeassistant/helpers/entity_platform.py", line 807, in _async_add_entity
    await entity.async_device_update(warning=False)
  File "/usr/src/homeassistant/homeassistant/helpers/entity.py", line 1314, in async_device_update
    await self.async_update()
  File "/config/custom_components/lock_code_manager/binary_sensor.py", line 298, in async_update
    await self._async_update_state()
  File "/config/custom_components/lock_code_manager/binary_sensor.py", line 366, in _async_update_state
    self.async_write_ha_state()
  File "/usr/src/homeassistant/homeassistant/helpers/entity.py", line 1023, in async_write_ha_state
    self._async_verify_state_writable()
  File "/usr/src/homeassistant/homeassistant/helpers/entity.py", line 1006, in _async_verify_state_writable
    raise NoEntitySpecifiedError(...)
```

**Occurrences:**
- Happens for all locks and all slots during startup
- Multiple waves of errors at 11:34:54 and 11:35:03
- Triggered during `_async_add_entity` in entity platform

**Root Cause:**
When Home Assistant adds a new entity to a platform, it calls `async_device_update()` to get the initial state. The binary sensor's `async_update()` method calls `_async_update_state()` which in turn calls `async_write_ha_state()` at line 366.

However, at this point the entity is **not yet fully registered** with Home Assistant (the add process is still in progress), so calling `async_write_ha_state()` raises `NoEntitySpecifiedError`.

**Impact:**
- Entity creation fails or is delayed
- Error spam in logs (confusing for users)
- May prevent binary sensors from being created correctly
- Likely contributes to BUG-002 (duplicate entity registration attempts)

**Fix Strategy:**
1. **Don't call `async_write_ha_state()` in `async_update()`** - Let Home Assistant handle state writing
2. In `_async_update_state()`, only update internal state properties, don't write to HA
3. Use the `@property` methods to return current state when HA asks for it
4. Or: Add a check to see if entity is registered before calling `async_write_ha_state()`

**Related Code:**
- `custom_components/lock_code_manager/binary_sensor.py:298` (async_update)
- `custom_components/lock_code_manager/binary_sensor.py:366` (_async_update_state calling async_write_ha_state)

**Note:** This is related to TODO #5 "Reduce ERROR-level logging for expected sync operations"

---

## Medium Priority Bugs

### BUG-004: Inappropriate ERROR-Level Logging During Startup
**Priority:** MEDIUM
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
The integration logs sync operations at ERROR level during normal startup when entities have "Unknown" states. This is expected behavior during initialization and should not be logged as an error.

**Log Evidence:**
```
ERROR Updating lock.back_door code slot 1 because it is out of sync. Current states: pin=Unknown, name=Unknown, active=Unknown, code_on_lock=Unknown, coordinator_data=4269, is_on=None
```

**Occurrences:**
- 27 ERROR messages during initial startup (9 slots × 3 locks)
- Repeats on each coordinator update until entities stabilize

**Root Cause:**
The binary sensor's sync detection logic treats Unknown states during startup the same as out-of-sync states during normal operation, logging both at ERROR level.

**Impact:**
- User confusion (logs full of "errors" during normal operation)
- Harder to identify actual errors
- Poor user experience

**Fix Strategy:**
1. Detect startup/initialization phase vs. normal operation
2. Log startup sync as DEBUG or INFO
3. Only use ERROR for actual failure conditions (can't set code, lock unavailable, etc.)
4. Follow Home Assistant logging best practices

**Related Code:**
- `custom_components/lock_code_manager/binary_sensor.py` (logging statements)

**Related Issues:**
- This is TODO #5 in TODO.md
- Related to BUG-003

---

## Analysis Summary

**Total Issues Found:** 4
**Critical:** 2
**High:** 1
**Medium:** 1

**Common Root Cause:**
Most issues appear to stem from BUG-001 (platform setup errors), which causes a cascade of problems:
1. Platforms set up multiple times → ValueError
2. Dispatcher signals fire multiple times → Duplicate entities (BUG-002)
3. Binary sensors update before ready → Update errors (BUG-003)

**Recommended Fix Order:**
1. Fix BUG-001 first (platform setup)
2. Verify BUG-002 is resolved (should be fixed by #1)
3. Fix BUG-003 and BUG-004 together (logging and startup state)

**Next Steps:**
- Investigate why `async_update_listener()` is being called during initial setup
- Add defensive checks in `configured_platforms` tracking
- Improve startup state detection in binary sensors
- Implement proper log level strategy

---

## Notes

- Log analyzed: `Home Assistant Log Oct 21 2025.log`
- All issues related to config entry `01K82F0V7Q5E4V1FNAYNRPYWTB` (House Locks)
- Integration appears functional despite errors (read-only mode working)
- No crashes or data corruption observed
