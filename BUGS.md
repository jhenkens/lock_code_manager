# Lock Code Manager - Bug Tracker

This file tracks active bugs found in Home Assistant log analysis. Fixed bugs are archived separately.

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
- Related to BUG-003 (fixed)

---

### BUG-006: Entity States Reset to Unknown After Config Change
**Priority:** HIGH
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
When making a configuration change to the integration (e.g., toggling read-only mode, changing slot configuration), all entity states reset to "unknown". The states remain unknown until the integration is disabled and re-enabled, at which point they return to their correct values.

**User Report:**
> "When you make a config change while the integration is running, all entities go to unknown state. If you disable and then reenable the integration, all the states go back to normal."

**Root Cause Analysis:**

The issue is in `async_update_listener()` in `__init__.py`. When processing config changes:

1. **Current data structure** (`config_entry.data[CONF_SLOTS]`):
   ```python
   {
       "1": {
           CONF_PIN: "1234",        # Runtime value set by text entity
           CONF_NAME: "Guest",      # Runtime value set by text entity
           CONF_ENABLED: True,      # Runtime value set by switch entity
           CONF_NUMBER_OF_USES: 0,  # Runtime value set by number entity
           CONF_CALENDAR: "calendar.events",
       }
   }
   ```

2. **Options data structure** (`config_entry.options[CONF_SLOTS]`):
   ```python
   {
       "1": {
           CONF_CALENDAR: "calendar.events",
           # PIN, name, enabled, number_of_uses NOT present - these come from YAML/initial config
       }
   }
   ```

3. **The problem** (lines 732-747):
   ```python
   # Build new_slots from options (YAML structure)
   new_slots = config_entry.options.get(CONF_SLOTS, {})

   # Merge runtime values from current data
   merged_slots = copy.deepcopy(new_slots)
   for slot_key in merged_slots:
       if slot_key in curr_slots:
           # Preserve runtime values
           for runtime_key in (CONF_PIN, CONF_NAME, CONF_ENABLED, CONF_NUMBER_OF_USES):
               if runtime_key in curr_slots[slot_key]:
                   merged_slots[slot_key][runtime_key] = curr_slots[slot_key][runtime_key]

   new_data = {
       CONF_LOCKS: new_locks,
       CONF_SLOTS: merged_slots,
       CONF_READ_ONLY: config_entry.options.get(CONF_READ_ONLY, False),
   }
   hass.config_entries.async_update_entry(config_entry, data=new_data)
   ```

**Wait - the fix is already in the code!** This should be preserving runtime values. Let me check if there's another issue...

**Potential Issues:**

1. **The merge only happens for slots in `new_slots`**: If a slot is removed from options, it won't be in `merged_slots` at all
2. **The merge only happens if slot exists in BOTH**: `if slot_key in curr_slots` - what if options adds a NEW slot?
3. **Text entities might be writing state AFTER the merge**: Race condition?

**Additional Investigation Needed:**
- Check if text/switch/number entities are initialized with default values when first created
- Check if the merge logic handles all cases (new slots, removed slots, existing slots)
- Check entity initialization order - do entities write their state before or after `async_update_entry()`?

**Impact:**
- Major user experience issue
- Requires integration reload to recover
- May trigger unwanted lock code syncing if states show as "unknown" → out of sync

**Potential Fixes:**

**Option 1: Ensure entities initialize with default values**
When creating text/switch/number entities, initialize them with sensible defaults instead of leaving them unset.

**Option 2: Check merge logic edge cases**
```python
# Handle NEW slots not in current data
merged_slots = copy.deepcopy(new_slots)
for slot_key in merged_slots:
    if slot_key in curr_slots:
        # Preserve runtime values from existing slots
        for runtime_key in (CONF_PIN, CONF_NAME, CONF_ENABLED, CONF_NUMBER_OF_USES):
            if runtime_key in curr_slots[slot_key]:
                merged_slots[slot_key][runtime_key] = curr_slots[slot_key][runtime_key]
    else:
        # New slot - initialize with defaults
        merged_slots[slot_key].setdefault(CONF_PIN, "")
        merged_slots[slot_key].setdefault(CONF_NAME, "")
        merged_slots[slot_key].setdefault(CONF_ENABLED, False)
        merged_slots[slot_key].setdefault(CONF_NUMBER_OF_USES, 0)
```

**Option 3: Use RestoreEntity**
Change entities to inherit from `RestoreEntity` so they can restore their last state after reload.

**Files Involved:**
- `custom_components/lock_code_manager/__init__.py:732-747` (merge logic)
- `custom_components/lock_code_manager/text.py` (PIN and name entities)
- `custom_components/lock_code_manager/switch.py` (enabled entity)
- `custom_components/lock_code_manager/number.py` (number of uses entity)

**Testing Required:**
1. Set up integration with slots configured
2. Set PIN, name, enabled state via UI
3. Make a config change (e.g., toggle read-only)
4. Verify entities maintain their state values
5. Add a new slot via config change
6. Verify new slot initializes with sensible defaults

---

### BUG-007: Sync Logic Doesn't Clear Codes When Active=Off and PIN=Unknown
**Priority:** MEDIUM
**Status:** Open
**Discovered:** 2025-10-21

**Description:**
The binary sensor's sync logic doesn't properly handle the case where:
- Active (enabled) state = OFF (slot should be disabled)
- Current PIN on lock = some value (e.g., "1234")
- Desired PIN from text entity = "unknown" (not initialized)

In this case, the integration should clear the code from the lock (because active=OFF), but instead it doesn't sync because the PIN is unknown.

**User Report:**
> "If desired pin in unknown / not initialized, then we don't sync the state properly, even if active = false. I think this is a bug in the binary_sensor state comparison? But I'm not sure... We also maybe should just initialize that text field when first created?"

**Root Cause Analysis:**

In `binary_sensor.py:374-381`, the `_should_update()` method checks:
```python
def _should_update(self):
    desired_state = self._get_entity_state(ATTR_ACTIVE)
    desired_pin = self._get_entity_state(CONF_PIN)
    current_pin = self._get_entity_state(ATTR_CODE)
    desired_state_is_set = desired_state in (STATE_ON, STATE_OFF)
    current_pin_matches_desired = (
        (desired_state == STATE_OFF and current_pin == "") or
        (desired_state == STATE_ON and desired_pin is not None and desired_pin == current_pin)
    )
    return desired_state_is_set and not current_pin_matches_desired
```

**The Problem:**
When `desired_state == STATE_OFF` and `current_pin == "1234"` (not empty), the comparison is:
- `current_pin_matches_desired = (STATE_OFF and "1234" == "")` → **False**
- `return True and not False` → **True** (should update)
- This SHOULD trigger a sync to clear the code! ✅

Wait, that looks correct... Let me check the validation logic that happens before `_should_update()`:

In `binary_sensor.py:302-314`:
```python
# Before checking if we should update, verify all states are valid
for key in (CONF_PIN, CONF_NAME, ATTR_ACTIVE):
    state = self._get_entity_state(key)
    if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        _LOGGER.debug(
            "Skipping sync check for %s slot %s: %s state is %s",
            ...
        )
        return  # ← THIS IS THE BUG!
```

**THERE IT IS!** The validation checks if CONF_PIN is UNKNOWN, and if so, returns early without checking if we need to clear the code!

**The Real Root Cause:**
The validation logic checks if PIN is UNKNOWN and skips sync entirely, even when:
- Active = OFF (we should clear the code)
- Current PIN on lock = "1234" (code exists)
- PIN state doesn't matter when active=OFF!

**Impact:**
- Slots with active=OFF but unknown PIN don't get cleared from the lock
- Lock may have codes that should be disabled but remain active
- Security issue if old codes aren't cleared

**Fix Strategy:**
The validation should allow sync when active=OFF, regardless of PIN state:

```python
# Before checking if we should update, verify all states are valid
# Exception: if active=OFF, we don't need a valid PIN to clear the code
desired_state = self._get_entity_state(ATTR_ACTIVE)

for key in (CONF_PIN, CONF_NAME, ATTR_ACTIVE):
    state = self._get_entity_state(key)
    if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        # Allow clearing codes when active=OFF even if PIN is unknown
        if key == CONF_PIN and desired_state == STATE_OFF:
            continue
        _LOGGER.debug(
            "Skipping sync check for %s slot %s: %s state is %s",
            self.lock.lock.entity_id,
            self.slot_key,
            key,
            state,
        )
        return
```

**Alternative Fix:**
Initialize PIN text entity with empty string ("") instead of leaving it unset/unknown:
- In `text.py`, ensure new PIN entities have `_attr_native_value = ""`
- This way PIN is never "unknown"

**Recommended Approach:**
Both fixes:
1. Initialize PIN entities with empty string (prevents the issue)
2. Update validation logic to allow clearing when active=OFF (defense in depth)

**Files Involved:**
- `custom_components/lock_code_manager/binary_sensor.py:302-314` (validation logic)
- `custom_components/lock_code_manager/text.py` (PIN entity initialization)

**Testing Required:**
1. Create new slot (PIN will be unknown/empty)
2. Set active=OFF
3. Manually set a code on the lock for that slot
4. Verify integration clears the code despite PIN being unknown
5. Verify log messages are appropriate (DEBUG, not ERROR)

---

## Summary

**Total Active Bugs:** 3
- **High Priority:** 1 (BUG-006)
- **Medium Priority:** 2 (BUG-004, BUG-007)

**Status:**
- BUG-004: Inappropriate ERROR-Level Logging - **Open**

- BUG-006: Entities Reset to Unknown After Config Change - **Open**
- BUG-007: Sync Logic Doesn't Clear When PIN=Unknown - **Open**

**Priority Order for Fixes:**
1. **BUG-006** (HIGH) - Entities resetting to unknown breaks user experience
2. **BUG-007** (MEDIUM) - Security concern if codes aren't cleared
3. **BUG-004** (MEDIUM) - Logging cleanup, cosmetic issue

---

## Notes

- Original logs analyzed: `Home Assistant Log Oct 21 2025.log`
- Config entry: `01K841CPSS0GPZWRM9A7PKBNMY` (House Locks)
- Fixed bugs: BUG-001, BUG-002, BUG-003, BUG-005
