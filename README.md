# Ecoforest EcoAir (read-only) for Home Assistant

Read-only Ecoforest heat pump integration PoC (proof of concept, thus may lack features or stability).
It is a fork of [ostracon/ecoforest_ecogeo](https://github.com/ostracon/ecoforest_ecogeo), itself a fork of
[bytestorm/ecoforest_ecogeo](https://github.com/bytestorm/ecoforest_ecogeo), with an ecoAIR (air-source) mode
whose block reads and register positions come from
[radutopala/ecoforest_ecoair](https://github.com/radutopala/ecoforest_ecoair). Credit to all three authors.
The integration never writes to the heat pump: only whitelisted read requests can leave the client.

**Status:** the ecoAIR mode has only been tested against simulated responses. Run `tools/probe.py` first
(below) and check the output matches before relying on the sensors.

## Install

1. In HACS, add this repository as a custom repository (category: Integration), install, restart Home Assistant.
2. Settings -> Devices & Services -> Add integration -> "Ecoforest EcoAir (read-only)".
3. Fields:
   - **Ecoforest Easynet URL**: the web address of the gateway, e.g. `http://192.168.1.200/`
   - **Username**: the heat pump serial number (same as the web interface)
   - **Password**: the first 8 characters of the original wireless network password (same as the web interface)
   - **Alias** (optional): used instead of the model name for entity prefixes
   - **Controller family**: `ecoair` (default) for air-source units, `geo` for the original ecoGEO register map

Do not run this at the same time as another Ecoforest integration polling the same gateway.

## Check your unit first

```
ECOFOREST_URL=http://192.168.1.200 ECOFOREST_USER=<serial> ECOFOREST_PASSWORD=<first 8 chars> python3 tools/probe.py
```

The probe uses only the Python standard library, sends only read requests, and prints the raw replies.
If a block is rejected or the values look wrong, open an issue with the output (remove nothing but your serial number).

## ecoAIR sensors

Outdoor temperature, DHW temperature, heating setpoint, electrical and heating power, COP, compressor
pressures, unit state, backup heater state, and read-back of the DHW / heating on-off states and DHW setpoints.
Brine sensors are copied from the ground-source map and are disabled by default; an air unit has no brine loop.
A block the gateway rejects only makes its own sensors unavailable; the others keep updating.

---

Custom visualization:

![flow](https://github.com/YOUR-GITHUB-USERNAME/ecoforest_ecoair_ro/blob/master/flow.png?raw=true)

<details>
  <summary>Details...</summary>

  This card is built using [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus). You can install it with HACS.<br />
  Just replace entity prefixes (ebfhbb in my case) with the model name or the alias of your heat pump.


```yaml
type: custom:power-flow-card-plus
entities:
  grid:
    entity: sensor.ebfhbb_power_electric
    display_state: one_way_no_zero
    name: Consumption
    color:
      consumption:
        - 78
        - 122
        - 39
  home:
    entity: sensor.ebfhbb_power_output
    icon: mdi:hvac
    subtract_individual: false
    override_state: true
    secondary_info:
      entity: sensor.ebfhbb_t_outdoor
      unit_of_measurement: °C
      decimals: 1
  individual:
    - entity: sensor.ebfhbb_power_cooling
      display_zero_state: false
      name: Cooling
      secondary_info:
        entity: sensor.ebfhbb_t_cooling
        unit_of_measurement: °C
        display_zero: false
        decimals: 1
      icon: mdi:snowflake
      display_zero: true
      color:
        - 0
        - 213
        - 255
    - entity: sensor.ebfhbb_power_heating
      display_zero: true
      name: Heating
      icon: mdi:heating-coil
      secondary_info:
        entity: sensor.ebfhbb_t_heating
        unit_of_measurement: °C
      color:
        - 203
        - 37
        - 37
      decimals: 1
      display_zero_state: false
    - name: DHW
      icon: mdi:water-boiler
      color:
        - 212
        - 154
        - 28
      decimals: 1
      display_zero: true
      secondary_info:
        entity: sensor.ebfhbb_t_dhw
        unit_of_measurement: °C
        decimals: 1
      display_zero_state: false
      entity: '0'
clickable_entities: true
display_zero_lines:
  mode: show
  transparency: 50
  grey_color:
    - 189
    - 189
    - 189
use_new_flow_rate_model: true
w_decimals: 0
kw_decimals: 1
min_flow_rate: 5
max_flow_rate: 5
max_expected_power: 2000
min_expected_power: 0.01
watt_threshold: 1000
transparency_zero_lines: 0
disable_dots: true
```
</details>
