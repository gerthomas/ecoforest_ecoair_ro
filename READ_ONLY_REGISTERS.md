# Read-only HP register coverage

The EATM00 (ecoGEO HP) map contains 570 named readings: the 263 entries in
Ecoforest's Modbus 2023 v02 HP tables (pp. 11–17), plus 307 settings/status fields
mapped by the installed EGW_v2.18 `gama2` web client. Domestic models retain
their separate existing map. Do not apply domestic addresses or blanket offsets
to the HP controller.

`modbus_info.json` and `registers.py` are identical in this repository and its
companion (ostracon/ecoforest-ecogeo-api / ostracon/ecoforest_ecogeo). Maintain
both copies together. Each HP field specifies its key, bank, address, scale,
unit type, source and any limitations. Existing entity keys are preserved.
Integer web-array index n maps to HTTP register n+5001; analog and boolean
indices are used directly. Check the field's source before adding an address.

## Read-only enforcement

The HTTP transport accepts only operations 2001 (coil read) and 2002 (register
read), with exactly the address/count arguments. Every other operation or
payload is rejected before network I/O, including inherited control methods.
No number, switch, button or climate platform is loaded by Home Assistant.
`rw` in the source map describes the manufacturer's register capability; it
never grants the client permission to write.

Reads are sequential, confined to mapped addresses, grouped into blocks of at
most 64 and separated by 50 ms. HA retains its 60-second polling interval.
New fields are optional: a rejected block is bisected until only unsupported
individual addresses become unavailable rather than zero or stale data; core telemetry continues. Required HA reads retry up to
three times; exhausted retries make the coordinator unavailable. Authentication
failures always propagate. Responses must match the requested operation,
address, count and payload format. Signed decoding includes 0x8000; absent
probes (-999.9°C) become unavailable. Coils are exposed as numeric 0/1 sensors.

## Interpretation and limits

- Heating adjustment 5072–5076 is an enum: 0..4 means -4,-2,0,+2,+4°C.
  It is separate from DT start (117), DT heating (141), and DT supply (65).
- Registers 5003 and 5005 are live controller-commanded and inverter-reported compressor references, decoded from tenths of a percent. Comparing them with RPM helps distinguish a controller cap from inverter-side limiting.
- Registers 5111–5130 hold the selected alarm-history record, not continuously live drive telemetry. For alarm code 18, the gateway renders 5118–5128 and 5130 as A1L/A1H, A2L/A2H, W1L/W1H, W2L/W2H, EWL, SW, DI and EWH. They are exposed as raw diagnostic words with stable existing entity keys; the record timestamp must be checked before treating them as a new fault.
- Demand slots 5139–5142 decode the web client's demand list. They are not
  valve-position feedback or proof of uninterrupted service changeover.
- Mode inputs 5085–5088 are raw inputs used jointly by the web status icons;
  they are not exclusive active-service enums.
- Priority selections 5039–5043 and delay 5173 remain explicitly unvalidated.
  A zero does not establish equal priorities or disabled protection. No
  minutes-per-hour setting has been verified for this controller.
- The 210 additional web-backed fields promoted in two October 2026 batches were checked
  against the existing keys, names and bank/address pairs before inclusion.
  They remain optional and read-only; the retained proposal ledger documents
  the ambiguous, action-like and live-rejected references that were deliberately deferred.
- Existing energy-counter units and annual PF scaling are not reinterpreted.
  The new energy-unit flags expose evidence for a separate validation; do not
  use unvalidated counters for billing. The map preserves existing IDs.
- HA attributes include source, register address/bank, raw value and notes.
  Optional fields accepted by the gateway can still be unused on a particular
  firmware/model. Availability alone does not prove their meaning.

This update does not change compressor protection, priorities, temperatures,
service selection or any heat-pump settings. It supplies diagnostic evidence;
it does not assert a cause or remedy for pool-to-buffer compressor stops.

## Offline validation

Run the unittest suite with httpx and (for the HA API tests) pyecoforest 0.4.0.
Tests use a mock HTTP transport; HA API tests isolate runtime imports and do
not pretend to validate the HA frontend. They cover transport write rejection,
response validation, sign/scaling, request coverage, optional failures,
authentication and required retry exhaustion. Live testing is separate.

## ecoAIR mode (this fork)

`family: ecoair` reads eight whitelisted block operations (2103, 2104, 2108, 2125, 2148, 2149, 2150, 2151), each
sent as `idOperacion=<n>` with no address or count; `ecoair_registers.py` holds the sensor positions. Operations 2011
and 2012 (writes) and any other operation are rejected before network I/O. Operation numbers and positions come from
radutopala/ecoforest_ecoair and are unverified on other models. The model code is read once from operation 2125
(first five characters); a failure there is fatal, while a failure in any other block only marks its sensors unavailable
(core blocks 2148, 2149 and 2151 are retried three times). If every block fails the update raises.
