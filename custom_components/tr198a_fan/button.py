"""Dynamic creation of one ButtonEntity per function *and* matching services."""
from __future__ import annotations
import random, logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import Entity
from homeassistant.core import HomeAssistant, callback
from .const import *
from .codec import build_pair_command, build_operational_command

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
    entity_ids = call.data.get("entity_id")
    for eid in hass.helpers.entity_component.async_extract_entity_ids(call):
        fan = hass.data[DOMAIN].get(eid)
        if fan:
            await _execute(fan, svc)

async def _execute(fan: "Tr198aFan", svc: str):
    if svc == SERVICE_PAIR:
        cmd = build_pair_command(fan._handset_id)
    elif svc == SERVICE_LIGHT_TOGGLE:
        cmd = build_operational_command(fan._handset_id, light_toggle=True)
        fan._state[ATTR_LIGHT] = not fan._state[ATTR_LIGHT]
    elif svc == SERVICE_DIM_UP:
        cmd = build_operational_command(fan._handset_id, dim="up")
    else:  # DIM_DOWN
        cmd = build_operational_command(fan._handset_id, dim="down")
    await fan.hass.services.async_call(
        "remote",
        "send_command",
        {
            "target": {"entity_id": [fan._remote_entity_id]},
            "command": [cmd],
        },
        blocking=True,
    )
    fan.async_write_ha_state()

class _Tr198aButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, fan: "Tr198aFan", svc: str, label: str):
        self._fan   = fan
        self._svc   = svc
        self._attr_name       = label
        self._attr_unique_id  = f"{fan.unique_id}_{svc}"

    async def async_press(self) -> None:
        await _execute(self._fan, self._svc)

# ─────────────────────────────────────────────────────────────────────────────
# Platform-loader
# ─────────────────────────────────────────────────────────────────────────────
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the four Button entities & register services once."""
    fan = hass.data[DOMAIN][entry.entry_id]["fan"]

    entities = [_Tr198aButton(fan, svc, label) for svc, label in BUTTONS.items()]
    async_add_entities(entities)

    # Register our four helper-services only the first time
    if hass.data[DOMAIN].get("services_registered"):
        return
    from homeassistant.core import callback

    @callback
    async def _service_handler(call):
        svc = call.service
        targets = call.data.get("entity_id")
        if not targets:
            return
        for eid in hass.helpers.entity_component.async_extract_entity_ids(call):
            # search across ALL entries because service may mix fans
            for entry_id in hass.data[DOMAIN]:
                fan_ = hass.data[DOMAIN][entry_id].get("fan")
                if fan_ and fan_.entity_id == eid:
                    await _execute(fan_, svc)

    for svc in BUTTONS:
        hass.services.async_register(DOMAIN, svc, _service_handler)

    hass.data[DOMAIN]["services_registered"] = True