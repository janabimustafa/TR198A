import sys
import os
import types
import asyncio
from types import SimpleNamespace
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ---- minimal Home Assistant stubs -----
ha = types.ModuleType('homeassistant')
sys.modules.setdefault('homeassistant', ha)

core = types.ModuleType('homeassistant.core')
ha.core = core
sys.modules['homeassistant.core'] = core
class HomeAssistant: pass
core.HomeAssistant = HomeAssistant

components = types.ModuleType('homeassistant.components')
ha.components = components
sys.modules['homeassistant.components'] = components

fan_mod = types.ModuleType('homeassistant.components.fan')
components.fan = fan_mod
sys.modules['homeassistant.components.fan'] = fan_mod
class FanEntity:
    def async_write_ha_state(self):
        pass
    def async_on_remove(self, func):
        pass
class FanEntityFeature:
    SET_SPEED = 1
    DIRECTION = 2
    TURN_ON = 4
    TURN_OFF = 8
    PRESET_MODE = 16
fan_mod.FanEntity = FanEntity
fan_mod.FanEntityFeature = FanEntityFeature

helpers = types.ModuleType('homeassistant.helpers')
ha.helpers = helpers
sys.modules['homeassistant.helpers'] = helpers

restore_state = types.ModuleType('homeassistant.helpers.restore_state')
helpers.restore_state = restore_state
sys.modules['homeassistant.helpers.restore_state'] = restore_state
class RestoreEntity:
    async def async_get_last_state(self):
        return None
    async def async_get_last_extra_data(self):
        return None
restore_state.RestoreEntity = RestoreEntity
class ExtraStoredData(dict):
    def as_dict(self):
        return dict(self)
restore_state.ExtraStoredData = ExtraStoredData

helpers.device_registry = types.ModuleType('homeassistant.helpers.device_registry')
sys.modules['homeassistant.helpers.device_registry'] = helpers.device_registry
class DeviceInfo(dict):
    pass
helpers.device_registry.DeviceInfo = DeviceInfo

helpers.entity_platform = types.ModuleType('homeassistant.helpers.entity_platform')
sys.modules['homeassistant.helpers.entity_platform'] = helpers.entity_platform
class AddEntitiesCallback: pass
helpers.entity_platform.AddEntitiesCallback = AddEntitiesCallback

helpers.event = types.ModuleType('homeassistant.helpers.event')
sys.modules['homeassistant.helpers.event'] = helpers.event
async def async_track_state_change_event(hass, entity_ids, callback):
    return lambda: None
helpers.event.async_track_state_change_event = async_track_state_change_event

ha.util = types.ModuleType('homeassistant.util')
sys.modules['homeassistant.util'] = ha.util
ha.util.percentage = types.ModuleType('homeassistant.util.percentage')
sys.modules['homeassistant.util.percentage'] = ha.util.percentage
def ranged_value_to_percentage(range_, val):
    start, end = range_
    if val == 0:
        return 0
    return (val - start) * 100 / (end - start)

def percentage_to_ranged_value(range_, pct):
    start, end = range_
    return start + pct * (end - start) / 100
ha.util.percentage.ranged_value_to_percentage = ranged_value_to_percentage
ha.util.percentage.percentage_to_ranged_value = percentage_to_ranged_value

ha.util.scaling = types.ModuleType('homeassistant.util.scaling')
sys.modules['homeassistant.util.scaling'] = ha.util.scaling
def int_states_in_range(range_):
    start, end = range_
    return end - start + 1
ha.util.scaling.int_states_in_range = int_states_in_range

ha.const = types.ModuleType('homeassistant.const')
sys.modules['homeassistant.const'] = ha.const
ha.const.CONF_NAME = 'name'

ha.config_entries = types.ModuleType('homeassistant.config_entries')
sys.modules['homeassistant.config_entries'] = ha.config_entries
class ConfigEntry: pass
ha.config_entries.ConfigEntry = ConfigEntry

# ---- import module under test ----
from custom_components.tr198a_fan.const import DOMAIN, ATTR_SPEED, ATTR_BREEZE, ATTR_LIGHT
from custom_components.tr198a_fan.fan import Tr198aFan, cycle_power_and_pair

# ---- helpers ----
class FakeState:
    def __init__(self, state):
        self.state = state
        self.attributes = {}

class FakeStates:
    def __init__(self):
        self._data = {}
    def get(self, entity_id):
        return self._data.get(entity_id)
    def set(self, entity_id, state):
        self._data[entity_id] = FakeState(state)

class FakeServices:
    def __init__(self, hass):
        self.hass = hass
        self.calls = []
    async def async_call(self, domain, service, data, *, blocking=False):
        self.calls.append((domain, service, data, blocking))
        if domain == 'switch':
            new_state = 'on' if service == 'turn_on' else 'off'
            self.hass.states.set(data['entity_id'], new_state)

class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.services = FakeServices(self)
        self.data = {DOMAIN: {'entry1': {}}}
    def async_on_remove(self, func):
        pass

# fixture to bypass asyncio.sleep delays
@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fake_sleep(_):
        pass
    monkeypatch.setattr(asyncio, 'sleep', fake_sleep)

# fixture to capture async_track_state_change_event
@pytest.fixture
def track_patch(monkeypatch):
    callbacks = []
    def fake_track(hass, entity_ids, cb):
        callbacks.append(cb)
        return lambda: None
    monkeypatch.setattr(sys.modules['custom_components.tr198a_fan.fan'],
                        'async_track_state_change_event', fake_track)
    return callbacks

# ---- tests ----
@pytest.mark.asyncio
async def test_ensure_power_on_no_action():
    hass = FakeHass()
    hass.states.set('switch.main', 'on')
    fan = Tr198aFan(hass, 'Fan', 'remote', 1, power_switch='switch.main')
    await fan._ensure_power_on()
    assert hass.services.calls == []

@pytest.mark.asyncio
async def test_ensure_power_on_turns_on():
    hass = FakeHass()
    hass.states.set('switch.main', 'off')
    fan = Tr198aFan(hass, 'Fan', 'remote', 1, power_switch='switch.main')
    await fan._ensure_power_on()
    assert ('switch', 'turn_on', {'entity_id': 'switch.main'}, True) in hass.services.calls
    assert hass.states.get('switch.main').state == 'on'

@pytest.mark.asyncio
async def test_power_switch_listener(track_patch):
    hass = FakeHass()
    hass.states.set('switch.main', 'on')
    fan = Tr198aFan(hass, 'Fan', 'remote', 1, power_switch='switch.main')
    fan._entry_id = 'entry1'
    hass.data[DOMAIN]['entry1']['light_entity'] = None
    fan._prev_speed = 3
    fan._prev_light = True

    fan._subscribe_power_switch()
    assert track_patch
    cb = track_patch[0]

    # turn off
    hass.states.set('switch.main', 'off')
    await cb(SimpleNamespace(data={'new_state': hass.states.get('switch.main')}))
    assert fan._state[ATTR_SPEED] == 0
    assert fan._state[ATTR_LIGHT] is False

    # turn on -> restore prev
    hass.states.set('switch.main', 'on')
    await cb(SimpleNamespace(data={'new_state': hass.states.get('switch.main')}))
    assert fan._state[ATTR_SPEED] == 3
    assert fan._state[ATTR_LIGHT] is True

