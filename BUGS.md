# Lock Code Manager - Bug Tracker

This file tracks bugs found in Home Assistant log analysis. Issues are prioritized and categorized for systematic resolution.

## Critical Bugs

### BUG-001: Platform Already Setup ValueError
**Priority:** HIGH
**Status:** FIXED
**Discovered:** 2025-10-21
**Fixed:** 2025-10-21

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

**Fix Applied:**
Changed initialization of `ATTR_CONFIGURED_PLATFORMS` from `set(PLATFORMS)` to an empty `set()`, and explicitly mark platforms as configured after they're forwarded.

The bug was caused by pre-populating `configured_platforms` with all core platforms before they were actually set up. This caused the update listener logic to incorrectly think platforms were already configured when they weren't, leading to duplicate setup attempts.

Solution:
1. Initialize `ATTR_CONFIGURED_PLATFORMS` as empty set (line 218)
2. Forward core platforms in `async_setup_entry()` (line 231)
3. Mark them as configured immediately after forwarding (line 233)
4. Update listener now correctly tracks which platforms are actually configured

**Files Changed:**
- `custom_components/lock_code_manager/__init__.py:218,231-233`

**Testing:**
- All 26 tests passing
- No more "platform already setup" errors in test output

---

### BUG-002: Duplicate Entity ID Registration
**Priority:** HIGH
**Status:** FIXED
**Discovered:** 2025-10-21
**Fixed:** 2025-10-21

**Description:**
Home Assistant reports duplicate unique IDs when trying to register sensor entities, causing sensors to be ignored and not created. This occurred both during initial setup and when updating config entry settings (e.g., toggling read_only mode).

**Log Evidence:**
```
ERROR Platform lock_code_manager does not generate unique IDs. ID 01K82F0V7Q5E4V1FNAYNRPYWTB|1|code|lock.back_door already exists - ignoring sensor.back_door_lock_code_slot_1
ERROR Platform lock_code_manager does not generate unique IDs. ID 01K841CPSS0GPZWRM9A7PKBNMY|3|code|lock.front_door already exists - ignoring sensor.front_door_lock_code_slot_3
```

**Occurrences:**
- Multiple instances for all locks during initial setup
- Affects slots 1-9
- Also triggered when changing config entry settings

**Root Cause:**
Initially thought to be due to non-idempotent dispatcher handlers, but the real root cause was **BUG-001** (platform setup errors) causing dispatcher signals to fire multiple times during initial setup.

After fixing BUG-001, realized we were over-engineering the solution by manually tracking entities. Home Assistant's `entity_platform.py` **already has built-in duplicate prevention** based on `unique_id`.

**Impact:**
- Duplicate entity registration errors in logs during initial setup (caused by BUG-001)
- User confusion from error messages
- Directly caused by BUG-001 platform setup issues

**Fix Applied:**
**FINAL FIX (correct approach):** Removed all manual duplicate tracking and let Home Assistant's built-in duplicate prevention handle it.

Home Assistant's entity platform automatically:
1. Checks if an entity with the same `unique_id` already exists in the entity registry
2. If it exists, calls `entity.add_to_platform_abort()` and skips adding the duplicate
3. Logs appropriate error messages for debugging

**Key Insight:** When entities have properly set `unique_id` attributes, `async_add_entities()` can be safely called multiple times. The platform handles deduplication automatically.

**Initial (incorrect) approach:**
We initially tried to manually track entities using `entities_added_tracker` set, checking before calling `async_add_entities()`. This caused "Entity not found" errors after restart because:
- Entity registry persists across restarts
- Our manual check would see entities in registry and skip creation
- But entities weren't actually loaded in current session

**Files Changed:**
- `custom_components/lock_code_manager/sensor.py:36-37` - Added explanatory comment
- `custom_components/lock_code_manager/binary_sensor.py:83-84` - Added explanatory comment
- Removed manual tracking code entirely

**Testing:**
- All 26 tests passing
- Entities created correctly on initial setup
- Entities load correctly after Home Assistant restart
- Config updates work without errors

---

## High Priority Bugs

### BUG-003: NoEntitySpecifiedError During Binary Sensor Creation
**Priority:** HIGH
**Status:** FIXED
**Discovered:** 2025-10-21
**Fixed:** 2025-10-21

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

**Fix Applied:**
Added `_entity_added` flag to track whether the entity has been fully added to Home Assistant. All `async_write_ha_state()` calls in `_async_update_state()` are now guarded with a check:
```python
if self._entity_added:
    self.async_write_ha_state()
```

The flag is set to `True` in `async_added_to_hass()` after all initialization is complete.

**Files Changed:**
- `custom_components/lock_code_manager/binary_sensor.py:217` - Added `_entity_added` flag
- `custom_components/lock_code_manager/binary_sensor.py:363,396,424` - Guard state writes with flag check
- `custom_components/lock_code_manager/binary_sensor.py:436` - Set flag after entity fully added

**Additional Improvements:**
- Added `get_slot_value()` helper method to coordinator for type-safe slot lookups
- Changed coordinator data type from `dict[int, int | str]` to `dict[str, str]` for consistency
- All slot keys are now stored as strings to support non-numeric slots (e.g., 'A', 'B')

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
**Critical:** 2 (both FIXED ✅)
**High:** 1 (FIXED ✅)
**Medium:** 1 (Open)

**Status:**
- BUG-001: Platform Already Setup ValueError - **FIXED** ✅
- BUG-002: Duplicate Entity ID Registration - **FIXED** ✅
- BUG-003: NoEntitySpecifiedError During Binary Sensor Creation - **FIXED** ✅
- BUG-004: Inappropriate ERROR-Level Logging During Startup - **Open** (partially addressed with INFO logging)

**Common Root Cause:**
Most issues stemmed from BUG-001 (platform setup errors), which caused a cascade of problems:
1. Platforms set up multiple times → ValueError (FIXED)
2. Dispatcher signals fire multiple times → Duplicate entities (FIXED with idempotent handlers)
3. Binary sensors update before ready → Update errors (FIXED with entity_added flag)

**Fix Summary:**
1. ✅ Fixed BUG-001 by properly tracking platform configuration state
2. ✅ Fixed BUG-002 by making dispatcher handlers idempotent
3. ✅ Fixed BUG-003 by deferring state writes until entity fully added
4. 🔄 Partially addressed BUG-004 by changing ERROR to INFO for normal sync operations

**Remaining Work:**
- Complete BUG-004: Improve startup state detection to reduce INFO logging during initialization
- Consider adding DEBUG-level logging for initialization events
- Implement proper log level strategy throughout integration

---

## Notes

- Log analyzed: `Home Assistant Log Oct 21 2025.log`
- All issues related to config entry `01K82F0V7Q5E4V1FNAYNRPYWTB` (House Locks)
- Integration appears functional despite errors (read-only mode working)
- No crashes or data corruption observed
