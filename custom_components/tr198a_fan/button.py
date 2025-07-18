"""Dynamic creation of one ButtonEntity per function *and* matching services."""
from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import Entity
from .const import (
    DOMAIN,
    SERVICE_PAIR,
    SERVICE_LIGHT_TOGGLE,
    SERVICE_DIM_UP,
    SERVICE_DIM_DOWN,
    ATTR_LIGHT
)
from .codec import build_pair_command
import asyncio
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .fan import Tr198aFan

_LOGGER = logging.getLogger(__name__)

BUTTONS = {
    SERVICE_PAIR:         "Pair Remote",
    SERVICE_LIGHT_TOGGLE: "Toggle Light",
    SERVICE_DIM_UP:       "Dim Up",
    SERVICE_DIM_DOWN:     "Dim Down",
}

async def register_buttons(hass: HomeAssistant, fan_entity: "Tr198aFan"):
    entities: list[Entity] = []
    for svc, label in BUTTONS.items():
        button = _Tr198aButton(fan_entity, svc, label)
        entities.append(button)
    # add_entities is only available during platform setup; instead use EntityPlatform
    platform = hass.data["entity_platform"][fan_entity.platform.platform_name]
    platform.async_add_entities(entities)

    # register matching services once
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if "services_registered" in hass.data[DOMAIN]:
        return
    hass.services.async_register(
        DOMAIN, SERVICE_PAIR, lambda call: _dispatch(hass, call, SERVICE_PAIR))
    hass.services.async_register(
        DOMAIN, SERVICE_LIGHT_TOGGLE, lambda call: _dispatch(hass, call, SERVICE_LIGHT_TOGGLE))
    hass.services.async_register(
        DOMAIN, SERVICE_DIM_UP, lambda call: _dispatch(hass, call, SERVICE_DIM_UP))
    hass.services.async_register(
        DOMAIN, SERVICE_DIM_DOWN, lambda call: _dispatch(hass, call, SERVICE_DIM_DOWN))
    hass.data[DOMAIN]["services_registered"] = True

async def _dispatch(hass: HomeAssistant, call, svc: str):
    """call.data MUST contain entity_id of the fan"""
    for eid in hass.helpers.entity_component.async_extract_entity_ids(call):
        fan = hass.data[DOMAIN].get(eid)
        if fan:
            await _execute(fan, svc)

async def _execute(fan: "Tr198aFan", svc: str):
    if svc == SERVICE_PAIR:
        # Handle power switch logic for pairing
        power_switch_id = getattr(fan, '_power_switch_id', None)
        hass = getattr(fan, 'hass', None)
        if power_switch_id and hass:
            state = hass.states.get(power_switch_id)
            if state:
                if state.state == "on":
                    # Flick off then on
                    await hass.services.async_call("switch", "turn_off", {"entity_id": power_switch_id}, blocking=True)
                    await asyncio.sleep(0.5)  # brief pause to allow relay to drop
                    await hass.services.async_call("switch", "turn_on", {"entity_id": power_switch_id}, blocking=True)
                    # Wait for state to reflect ON
                    for _ in range(20):
                        await asyncio.sleep(0.1)
                        st = hass.states.get(power_switch_id)
                        if st and st.state == "on":
                            break
                else:
                    # If off, just turn on
                    await hass.services.async_call("switch", "turn_on", {"entity_id": power_switch_id}, blocking=True)
                    for _ in range(20):
                        await asyncio.sleep(0.1)
                        st = hass.states.get(power_switch_id)
                        if st and st.state == "on":
                            break
        cmd = build_pair_command(fan._handset_id)
        await fan._send_base64(cmd)          # pairing packet is special
        return
    if svc == SERVICE_LIGHT_TOGGLE:
        await fan._send_state(light_toggle=True)
        fan._state[ATTR_LIGHT] = not fan._state[ATTR_LIGHT]

    else:  # DIM UP / DOWN  — send 2 steps
        steps = 2
        radio = 0xC9 + (steps - 1) * 4
        trailer = 394
        dir_ = "up" if svc == SERVICE_DIM_UP else "down"
        await fan._send_state(dim=dir_, radio_repeats=radio, trailer_us=trailer)
    fan.async_write_ha_state()

class _Tr198aButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass, entry_id: str, fan_unique_id: str,
                 svc: str, label: str):
        self.hass = hass
        self._entry_id = entry_id
        self._fan_uid  = fan_unique_id
        self._svc      = svc
        self._attr_name = label
        self._attr_unique_id = f"{fan_unique_id}_{svc}"
        # share the same HA Device as the fan
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, fan_unique_id.split("_")[1])}
        )

    async def async_press(self):
        fan = self.hass.data[DOMAIN][self._entry_id]["fan_entity"]
        await _execute(fan, self._svc)

# ─────────────────────────────────────────────────────────────────────────────
# Platform-loader
# ─────────────────────────────────────────────────────────────────────────────
async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    fan_uid = store.get("fan_unique_id")
    if fan_uid is None:
        # fan platform will set it; wait one tick
        await hass.async_add_executor_job(lambda: None)
        fan_uid = store["fan_unique_id"]

    entities = [
        _Tr198aButton(hass, entry.entry_id, fan_uid, svc, label)
        for svc, label in BUTTONS.items()
    ]
    async_add_entities(entities)

    # Register helper-services exactly once
    if store.get("services_registered"):
        return
    async def _service_handler(call):
        svc   = call.service
        for eid in hass.helpers.entity_component.async_extract_entity_ids(call):
            fan_ent = hass.data[DOMAIN][entry.entry_id].get("fan_entity")
            if fan_ent and fan_ent.entity_id == eid:
                await _execute(fan_ent, svc)
    for svc in BUTTONS:
        hass.services.async_register(DOMAIN, svc, _service_handler)
    store["services_registered"] = True