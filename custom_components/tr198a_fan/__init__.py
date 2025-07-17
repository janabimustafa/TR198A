from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from .const import DOMAIN
from .fan import Tr198aFan
from .button import register_buttons

async def async_setup(hass, config):
    return True   # YAML is now discouraged – UI flow does it all

async def async_setup_entry(hass, entry: ConfigEntry):
    data = entry.data
    remote_id   = data["remote_entity_id"]
    handset_id  = data["handset_id"]
    name        = data.get(CONF_NAME, f"TR198A Fan {handset_id:04X}")

    fan = Tr198aFan(hass, name, remote_id, handset_id)
    # store for service-dispatch
    hass.data.setdefault(DOMAIN, {})[fan.unique_id] = fan

    # add the entities
    platform = hass.helpers.entity_platform.async_get_current_platform()
    platform.async_add_entities([fan])
    await register_buttons(hass, fan)

    return True