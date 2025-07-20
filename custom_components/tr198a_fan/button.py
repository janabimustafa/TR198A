"""Dynamic creation of one ButtonEntity per function *and* matching services."""
from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import (
    DOMAIN,
    SERVICE_PAIR,
    SERVICE_DIM_UP,
    SERVICE_SYNC_LIGHT,
    SERVICE_DIM_DOWN,
    DIM_STEP_SIZE
)
from .codec import build_pair_command
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .fan import Tr198aFan

_LOGGER = logging.getLogger(__name__)

BUTTONS = {
    SERVICE_PAIR,
    SERVICE_DIM_UP,
    SERVICE_DIM_DOWN,
    SERVICE_SYNC_LIGHT
}

async def _execute(fan: "Tr198aFan", svc: str):
    if svc == SERVICE_PAIR:
        power_switch_id = getattr(fan, '_power_switch_id', None)
        hass = getattr(fan, 'hass', None)
        if power_switch_id and hass:
            from .fan import cycle_power_and_pair
            await cycle_power_and_pair(hass, power_switch_id, fan._handset_id, fan._send_base64)
            # Mark as paired in config entry options
            entry_id = fan._entry_id if hasattr(fan, '_entry_id') else None
            if entry_id:
                entry = next((e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id == entry_id), None)
                if entry:
                    new_options = dict(entry.options)
                    new_options["paired"] = True
                    hass.config_entries.async_update_entry(entry, options=new_options)
            return
        cmd = build_pair_command(fan._handset_id)
        await fan._send_base64(cmd)
                    # Mark as paired in config entry options
        entry_id = fan._entry_id if hasattr(fan, '_entry_id') else None
        if entry_id:
            entry = next((e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id == entry_id), None)
            if entry:
                new_options = dict(entry.options)
                new_options["paired"] = True
                hass.config_entries.async_update_entry(entry, options=new_options)
        return
    if svc == SERVICE_SYNC_LIGHT:
        await fan._send_state(light_toggle=True)
    else:  # DIM UP / DOWN — use configured step size
        # Fetch dim_step_size from config entry options or data, default to 2
        entry_id = getattr(fan, '_entry_id', None)
        hass = getattr(fan, 'hass', None)
        step_size = 2
        if entry_id and hass:
            entry = next((e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id == entry_id), None)
            if entry:
                step_size = entry.options.get(DIM_STEP_SIZE, entry.data.get(DIM_STEP_SIZE, 2))
        steps = step_size
        radio = 0xC9 + (steps - 1) * 4
        trailer = 394
        dir_ = "up" if svc == SERVICE_DIM_UP else "down"
        await fan._send_state(dim=dir_, radio_repeats=radio, trailer_us=trailer)
    fan.async_write_ha_state()

class _Tr198aButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass, entry_id: str, fan_unique_id: str,
                 svc: str):
        self.hass = hass
        self._entry_id = entry_id
        self._fan_uid  = fan_unique_id
        self._svc      = svc
        self._attr_translation_key = svc
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
        _Tr198aButton(hass, entry.entry_id, fan_uid, svc)
        for svc in BUTTONS
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