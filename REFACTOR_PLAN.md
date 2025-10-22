# Refactoring Plan: Remove Dispatcher Anti-Pattern

## Goal
Remove all `async_dispatcher_send` / `async_dispatcher_connect` usage and replace with direct entity management from a centralized `async_update_listener` in `__init__.py`.

## Current Architecture (Dispatcher-based)

### Entity Creation Flow:
1. **Platform Setup** (`async_setup_entry` in each platform file):
   - Registers dispatcher handlers that listen for signals
   - Handlers receive parameters and call `async_add_entities`

2. **Config Changes** (`async_update_listener` in `__init__.py`):
   - Analyzes config changes (added/removed slots, locks, entities)
   - Sends dispatcher signals with parameters

3. **Dispatcher Handlers** (in platform files):
   - Listen for signals
   - Create entity instances
   - Call `async_add_entities`

### Dispatcher Signals Inventory:

**Entity Creation Signals (sent from `__init__.py`):**
- `{DOMAIN}_{entry_id}_add_lock_slot` → Creates sensor + binary_sensor per lock/slot
- `{DOMAIN}_{entry_id}_add` → Creates PIN active binary_sensor
- `{DOMAIN}_{entry_id}_add_{key}` → Creates text, switch, number, event entities

**Entity Removal Signals (sent from `__init__.py`):**
- `{DOMAIN}_{entry_id}_remove_{slot_key}` → Remove all entities for slot
- `{DOMAIN}_{entry_id}_remove_{slot_key}_{key}` → Remove specific entity
- `{DOMAIN}_{entry_id}_remove_lock` → Remove lock-specific entities

**Entity Update Signals (listened by entities):**
- `{DOMAIN}_{entry_id}_add_locks` → Notify entities about new locks

### Files Using Dispatchers:
- `__init__.py` - Sends all signals
- `binary_sensor.py` - Listens for add signals, creates entities
- `sensor.py` - Listens for add signals, creates entities
- `text.py` - Listens for add signals, creates entities
- `switch.py` - Listens for add signals, creates entities
- `number.py` - Listens for add signals, creates entities
- `event.py` - Listens for add signals, creates entities
- `entity.py` - Base entities listen for remove/update signals

## Proposed Architecture (Direct Management)

### New Entity Creation Flow:
1. **Platform Setup** (`async_setup_entry` in each platform):
   - Store `async_add_entities` callback in `hass.data[DOMAIN][entry_id]`
   - Return immediately (minimal setup)

2. **Centralized Entity Management** (`async_update_listener` in `__init__.py`):
   - Analyzes config changes
   - **Directly creates entity instances** (no signals)
   - **Directly calls** the appropriate `async_add_entities` callback
   - Manages entity removal directly

3. **Entity Removal**:
   - Entities register removal listeners during `async_added_to_hass`
   - `async_update_listener` tracks which entities to remove
   - Calls `entity.async_remove()` directly on entities that need removal

### Key Changes:

#### 1. Platform Setup (Minimal)
Each platform's `async_setup_entry` will:
```python
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up platform."""
    # Store callback for later use
    hass.data[DOMAIN][config_entry.entry_id][f"{PLATFORM}_add_entities"] = async_add_entities
    return True
```

#### 2. Centralized Entity Creation (`__init__.py`)
Move all entity creation logic to `async_update_listener`:

```python
async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle config updates."""
    # Get all async_add_entities callbacks
    add_binary_sensor = hass_data[entry_id]["binary_sensor_add_entities"]
    add_sensor = hass_data[entry_id]["sensor_add_entities"]
    add_text = hass_data[entry_id]["text_add_entities"]
    # ... etc

    # Analyze config changes
    slots_to_add = ...
    slots_to_remove = ...

    # Create entities directly
    for slot_key in slots_to_add:
        # Create binary sensor entities
        binary_sensors = [
            LockCodeManagerActiveEntity(hass, ent_reg, config_entry, slot_key, ATTR_ACTIVE)
        ]
        add_binary_sensor(binary_sensors)

        # Create text entities
        text_entities = [
            LockCodeManagerNameEntity(hass, ent_reg, config_entry, slot_key, CONF_NAME),
            LockCodeManagerPinEntity(hass, ent_reg, config_entry, slot_key, CONF_PIN),
        ]
        add_text(text_entities)

        # Create per-lock entities
        for lock in locks:
            sensors = [
                LockCodeManagerCodeSlotSensorEntity(hass, ent_reg, config_entry, lock, coordinator, slot_key)
            ]
            add_sensor(sensors)

            binary_sensors = [
                LockCodeManagerCodeSlotInSyncEntity(hass, ent_reg, config_entry, coordinator, lock, slot_key)
            ]
            add_binary_sensor(binary_sensors)

    # Remove entities directly
    for slot_key in slots_to_remove:
        # Track entities to remove, call async_remove() on them
```

#### 3. Entity Removal Tracking
Maintain a registry of created entities in `hass.data[DOMAIN][entry_id]`:

```python
# Store entity references when created
hass_data[entry_id]["entities"] = {
    "binary_sensor": {},  # slot_key -> [entity, entity, ...]
    "sensor": {},
    "text": {},
    # ... etc
}

# When removing:
for entity in hass_data[entry_id]["entities"]["text"][slot_key]:
    await entity.async_remove()
```

#### 4. Remove Dispatcher-Related Code
From `entity.py`, remove these methods from `BaseLockCodeManagerEntity`:
- `dispatcher_connect()` - No longer needed
- All dispatcher signal listeners in `async_added_to_hass`
- Dispatcher-based removal handlers

Keep only:
- Direct removal via `async_remove()` calls from `async_update_listener`
- Update listeners for lock availability tracking

## Implementation Steps

### Phase 1: Preparation
1. ✅ Create this refactoring plan
2. Add entity tracking to `hass.data` structure
3. Add `async_add_entities` callback storage per platform

### Phase 2: Migrate Platform by Platform
For each platform (binary_sensor, sensor, text, switch, number, event):

1. **Simplify `async_setup_entry`**:
   - Remove dispatcher handler registration
   - Store `async_add_entities` callback

2. **Update `async_update_listener`**:
   - Add direct entity creation for this platform
   - Store entity references

3. **Test thoroughly** before moving to next platform

### Phase 3: Clean Up
1. Remove all dispatcher imports
2. Remove `dispatcher_connect()` method from `entity.py`
3. Remove dispatcher-based removal logic
4. Update entity removal to use direct `async_remove()` calls
5. Clean up any dispatcher-related constants

### Phase 4: Testing
1. Test initial setup
2. Test adding slots
3. Test removing slots
4. Test adding locks
5. Test removing locks
6. Test changing slot properties
7. Test integration reload
8. Run full test suite

## Benefits

### Improved Code Clarity
- All entity creation logic in one place (`async_update_listener`)
- Easy to see what entities get created for each config
- No hidden signal handlers scattered across files

### Reduced Complexity
- Remove ~100+ lines of dispatcher boilerplate
- Fewer indirection layers
- Easier to debug (no async message passing)

### Better Performance
- No signal dispatching overhead
- Direct function calls
- Fewer async context switches

### Easier Maintenance
- Changes to entity creation all in one place
- No need to track signal names across files
- Clearer ownership of entity lifecycle

## Risks & Mitigation

### Risk: Breaking Entity Lifecycle
**Mitigation**: Implement incrementally, test each platform thoroughly

### Risk: Entity Removal Issues
**Mitigation**: Store entity references, use existing `async_remove()` API

### Risk: Platform Reload Issues
**Mitigation**: Ensure `async_add_entities` callbacks are properly stored/restored

### Risk: Test Failures
**Mitigation**: Run test suite after each phase

## Estimated Effort
- **Phase 1**: 1-2 hours (setup)
- **Phase 2**: 4-6 hours (6 platforms × ~1 hour each)
- **Phase 3**: 1-2 hours (cleanup)
- **Phase 4**: 2-3 hours (testing)
- **Total**: ~8-13 hours

## Files to Modify

### Major Changes:
- `custom_components/lock_code_manager/__init__.py` - Centralize entity creation
- `custom_components/lock_code_manager/entity.py` - Remove dispatcher code

### Per-Platform Changes:
- `custom_components/lock_code_manager/binary_sensor.py`
- `custom_components/lock_code_manager/sensor.py`
- `custom_components/lock_code_manager/text.py`
- `custom_components/lock_code_manager/switch.py`
- `custom_components/lock_code_manager/number.py`
- `custom_components/lock_code_manager/event.py`

### Test Updates:
- All test files may need updates to match new entity creation flow

## Open Questions

1. **Should we still use `async_forward_entry_setups`?**
   - Yes, platforms still need to be set up for HA to know they exist
   - But they'll be mostly empty, just storing callbacks

2. **How to handle entity updates when locks are added/removed?**
   - Store entity references, call methods directly instead of signals
   - Entities can still listen to state changes for availability

3. **What about the `_handle_add_locks` in entity.py?**
   - This is for notifying existing entities about new locks
   - Can be replaced with direct method calls on stored entity references

4. **Should entity removal be synchronous or asynchronous?**
   - Keep async, use `await entity.async_remove()` in update listener

## Success Criteria

- ✅ All tests pass
- ✅ No dispatcher imports remain
- ✅ Entity creation is centralized in `async_update_listener`
- ✅ Integration reload works correctly
- ✅ Adding/removing slots works correctly
- ✅ Adding/removing locks works correctly
- ✅ Code is more maintainable and easier to understand
