# Lock Code Manager - TODO

## Critical Issues (Breaking in 2025.1+)

## Errors in Test Output

### 4. Fix config entry unload KeyError
**Priority:** MEDIUM

**Issue:**
```
ERROR:homeassistant.config_entries:Error unloading entry test for lock_code_manager
KeyError: '01K83Y2Z4W1W1TVC63DGHWRRR0'
```

**Description:**
During test teardown, unloading the config entry raises a KeyError, indicating that some data structure is not properly cleaned up or the entry ID is not found where expected.

**Possible Causes:**
1. Data stored in `hass.data[DOMAIN]` is being removed before the unload completes
2. The entry ID is being used as a key in a dict that doesn't contain it
3. Coordinators or lock instances are being removed prematurely

**Investigation Steps:**
1. Add try/except with logging around `hass.data` access during unload
2. Check `async_unload_entry()` in `__init__.py` for KeyError sources
3. Verify all data cleanup happens in the correct order
4. Check if coordinators are being removed before entities are unloaded

**Fix Strategy:**
1. Use `.get()` or `.pop()` with defaults instead of direct dict access
2. Ensure proper cleanup order: entities → coordinators → data structures
3. Add defensive checks for missing keys

**Testing:**
- Run `pytest -v` and verify error no longer appears
- Run individual tests multiple times to check for race conditions
- Test actual config entry unload in live HA instance

---

### 5. Reduce ERROR-level logging for expected sync operations
**Priority:** LOW

**Issue:**
```
ERROR:custom_components.lock_code_manager.binary_sensor:Updating lock.test_1 code slot 1
because it is out of sync. Current states: pin=Unknown, name=Unknown, active=Unknown,
code_on_lock=Unknown, coordinator_data=1234, is_on=None
```

**Description:**
The binary sensor logs sync operations at ERROR level, but these are often expected during initial setup or when entities haven't fully initialized yet. "Unknown" states during startup are normal.

**Location:**
- `custom_components/lock_code_manager/binary_sensor.py`

**Root Cause:**
The integration uses ERROR-level logging for what should be DEBUG or INFO-level messages. The "out of sync" state during initial startup is expected behavior, not an error.

**Fix Strategy:**
1. Change ERROR logs to INFO or DEBUG for routine sync operations
2. Only use ERROR for actual error conditions (e.g., failed to set usercode)
3. Add logic to detect "startup sync" vs "unexpected sync" and log accordingly:
   ```python
   # During initial load with Unknown states
   _LOGGER.debug("Initial sync for %s slot %s", lock_entity_id, slot_num)

   # During normal operation when sync is needed
   _LOGGER.info("Syncing %s slot %s (code mismatch detected)", lock_entity_id, slot_num)

   # Only on actual errors
   _LOGGER.error("Failed to sync %s slot %s: %s", lock_entity_id, slot_num, error)
   ```

**Testing:**
- Run `pytest -v -s` and check log levels
- Verify no ERROR messages for normal startup
- Confirm actual errors still log at ERROR level

---

## Warnings (Non-breaking)

### 6. zlib_ng and isal performance warning
**Priority:** LOW (environment-specific)

**Issue:**
```
WARNING:aiohttp_fast_zlib:zlib_ng and isal are not available, falling back to zlib,
performance will be degraded.
```

**Description:**
This is a third-party library warning about missing optional performance libraries. It doesn't affect functionality, only performance of HTTP compression.

**Fix Strategy:**
This is typically a test environment issue and can be ignored. If performance is critical:
1. Install `zlib-ng` or `isal` in the test environment
2. Or suppress this specific warning in pytest configuration

**Testing:**
Not required - this is an environmental warning, not a code issue.

---

## Dev Tasks

### 7. Reevaluate logging strategy
**Priority:** MEDIUM

**Description:**
Review the entire logging strategy to ensure appropriate log levels are used throughout the integration:
- DEBUG: Detailed diagnostic information
- INFO: General informational messages about normal operations
- WARNING: Something unexpected but not necessarily an error
- ERROR: Actual errors that affect functionality

**Actions:**
1. Audit all `_LOGGER.error()` calls - most should probably be INFO or DEBUG
2. Audit all `_LOGGER.warning()` calls - ensure they're truly warnings
3. Add more DEBUG logging for troubleshooting
4. Consider user-visible vs developer-visible logging

---

## Test Tasks

### 8. Test strategy UI
**Priority:** MEDIUM

**Description:**
Add tests for the Lovelace strategy that generates the dashboard UI.

**Files to test:**
- `ts/generate-view.ts`
- `ts/types.ts`
- Strategy registration in `__init__.py`

---

### 9. Test handling when a state is missing for binary sensor
**Priority:** MEDIUM

**Description:**
Add specific test cases for when the binary sensor's dependent entities (pin, name, active, code_on_lock) are in Unknown or Unavailable states.

**Test scenarios:**
- Startup with Unknown states (already covered to some extent)
- Mid-operation state becomes unavailable
- Entity disabled/re-enabled scenarios

---

### 10. Test lock providers comprehensively
**Priority:** HIGH

**Description:**
Expand test coverage for lock provider implementations.

**Current coverage:**
- Basic provider tests exist
- Z-Wave JS provider partially tested
- Virtual provider tested

**Gaps:**
- Error handling in providers
- Edge cases (connection loss, timeout, etc.)
- Provider-specific event handling
- Hard refresh functionality

---

### 11. Test availability logic
**Priority:** MEDIUM

**Description:**
Add tests specifically for entity availability logic:
- When coordinator is unavailable
- When lock entity is removed
- When lock integration is unloaded
- Recovery after temporary unavailability

---

## Future Enhancements

### 12. Support additional lock integrations
**Priority:** LOW

See CLAUDE.md section "Adding Lock Provider Support" for details on the 60+ potential lock integrations that could be supported.

**Top candidates:**
- ZHA (Zigbee Home Automation)
- Matter
- ESPHome
- MQTT

---

## Notes

- All "BREAKING" items have specific Home Assistant version deadlines
- Critical issues should be addressed before their respective HA versions are released
- Test coverage improvements are ongoing and can be done incrementally
- Log level fixes are cosmetic but improve user experience




# Old TODO:
Dev:
- Reevaluate logging

Test:
- Test strategy
- Test handling when a state is missing for binary sensor
- Test lock providers
- Test availability logic
