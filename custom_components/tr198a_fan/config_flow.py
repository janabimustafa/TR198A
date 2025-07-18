from __future__ import annotations
import random
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import selector
from .const import DOMAIN

HANDSET_ID_BITS = 0x1FFF  # 13-bit max

class Tr198aConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _LOGGER = __import__("logging").getLogger(__name__)

    # ───────────────── STEP: USER ─────────────────
    async def async_step_user(self, user_input=None):
        errors = {}
        # Build schema with auto_pair option
        schema = vol.Schema(
            {
                vol.Required("remote_entity_id"): selector({"entity": {"domain": "remote"}}),
                vol.Optional("power_switch_entity_id"): selector({"entity": {"domain": "switch"}}),
                vol.Optional(CONF_NAME): str,
                vol.Optional("auto_pair", default=True): bool,
            }
        )

        if user_input is not None:
            auto_pair = user_input.get("auto_pair", True)
            power_switch = user_input.get("power_switch_entity_id")
            if auto_pair and not power_switch:
                errors["auto_pair"] = "auto_pair_requires_power_switch"
                return self.async_show_form(
                    step_id="user",
                    data_schema=schema,
                    errors=errors,
                    description_placeholders={
                        "auto_pair_disabled": True
                    },
                )
            # 1. generate a unique handset-id
            handset_id = random.randint(0, HANDSET_ID_BITS)

            # 2. ensure *ConfigEntry* unique-id uniqueness
            unique_id = f"tr198a_{handset_id:04x}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            data = {
                "remote_entity_id": user_input["remote_entity_id"],
                "handset_id": handset_id,
                CONF_NAME: user_input.get(CONF_NAME) or f"TR198A Fan {handset_id:04X}",
                "auto_pair": auto_pair,
            }
            if power_switch:
                data["power_switch_entity_id"] = power_switch
            title = data[CONF_NAME]
            return self.async_create_entry(title=title, data=data)
        else:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
            )

    # ───────────────── (optional) OPTIONS FLOW ─────────────────
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Tr198aOptionsFlow(config_entry)


class Tr198aOptionsFlow(config_entries.OptionsFlow):
    """Let the user change the friendly-name or swap the RM4 without re-adding."""
    def __init__(self, entry):
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Required(
                        "remote_entity_id",
                        default=self.entry.data["remote_entity_id"],
                    ): selector({"entity": {"domain": "remote"}}),
                    vol.Optional(
                        "power_switch_entity_id",
                        default=(
                            self.entry.options.get("power_switch_entity_id")
                            or self.entry.data.get("power_switch_entity_id")
                        ),
                    ): selector({"entity": {"domain": "switch"}}),
                    vol.Optional(
                        CONF_NAME, default=self.entry.data.get(CONF_NAME, "")
                    ): str,
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        data = dict(self.entry.data)
        data["remote_entity_id"] = user_input["remote_entity_id"]
        if user_input.get(CONF_NAME):
            data[CONF_NAME] = user_input[CONF_NAME]
        if user_input.get("power_switch_entity_id"):
            data["power_switch_entity_id"] = user_input["power_switch_entity_id"]
        else:
            data.pop("power_switch_entity_id", None)

        return self.async_create_entry(title="", data=data)