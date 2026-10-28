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
   - **Controller family**: `ecoair` (default) reads the documented ecoAIR Modbus table through the register and coil reads that Easynet Geo gateways answer; `geo` is the original ecoGEO register map; `ecoair_blocks` is an experimental mode using block reads that did not work on an Easynet Geo 2.13 gateway

Do not run this at the same time as another Ecoforest integration polling the same gateway.

## Check your unit first

```
ECOFOREST_URL=http://192.168.1.200 ECOFOREST_USER=<serial> ECOFOREST_PASSWORD=<first 8 chars> python3 tools/probe.py
```

The probe uses only the Python standard library, sends only read requests, and prints the raw replies.
If a block is rejected or the values look wrong, open an issue with the output (remove nothing but your serial number).

## ecoAIR sensors

The default `ecoair` family exposes 160 read-only sensors from the documented table: temperatures on both units,
pressures, valve and fan/pump regulation, setpoints, instantaneous heating/cooling/electric power and COP/EER,
compressor speed and reference, digital inputs and outputs (coils, as 0/1), and annual/monthly energy counters.
Monthly counters, performance factors and BUS setpoints are disabled by default. Entity ids start with `air_`
(for example `sensor.<model>_air_outdoor_temperature`, `..._air_electric_power`).
Energy counters are raw numbers: kWh or MWh depends on the annual-unit coils (203-205).
Documented oddities: register 3 is labelled a temperature but has unit bar, so it is exposed as an unverified raw measurement.
A block the gateway rejects is bisected until only the unsupported addresses are unavailable.

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
