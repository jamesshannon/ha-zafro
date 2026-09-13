# Zafro for Home Assistant

Control Zafro / i4Season air conditioners from Home Assistant, over the same cloud
connection the phone app uses.

This is a HACS custom integration. It follows the conventions of a core integration —
config flow, runtime data, translated entities, diagnostics, strict typing — with the
intention of proposing it for core once it has run against more than one model.

All protocol work lives in [`pyzafro`](https://github.com/jamesshannon/pyzafro); this
repository is only the Home Assistant half.

## Supported devices

Confirmed against a **90038EAC0-12K-ZAZ** 12,000 BTU window unit.

Other models in the same family are matched by model prefix. Anything unrecognised still
sets up: the library watches what the device reports in its first state frame and builds
entities from that, rather than refusing to start or inventing controls the unit does not
have.

If you own a Zafro product that is not an air conditioner at all, it will register as a
device with no controls, and you will see a warning naming the model. That is the library
telling you it has never handled that product class — not a failure. See
[Adding a model](#adding-a-model); it is a change to `pyzafro` alone.

## What you get

One device per air conditioner, with:

| Entity | Notes |
| --- | --- |
| **Climate** | Power, mode, setpoint, fan speed, both swing axes. Ambient temperature and humidity are attributes of this entity. |
| **Switches** | Sleep, eco, child lock, display light, beeper. |
| **Binary sensor** | Problem, from the device's fault code. |
| **Sensors** | Ambient temperature and humidity, Wi-Fi signal, operating time, filter life, water level, fault code. **All disabled by default** — the first two duplicate climate attributes and exist for long-term statistics; the rest are diagnostics. Enable the ones you want on the device page. |

Sleep and eco are switches rather than climate presets because the app has separate
buttons for them and they can be on at the same time. Presets are mutually exclusive, so
one of the two states would always be misrepresented.

Temperatures are reported in whatever unit the device says it uses, and Home Assistant
converts for display. A Fahrenheit unit therefore works correctly in a Celsius household
and vice versa.

## Use cases

The point of putting a window unit on the cloud API rather than an IR blaster is that
state flows *back*. You know what the unit is actually doing, not what you last told it
to do, so the things people normally want from a smart air conditioner become reliable:

- **Cool the bedroom before you go to sleep, not all evening.** Schedule the setpoint
  rather than the plug, and let eco mode hold it.
- **Stop cooling an empty house.** Tie the unit to presence, a door sensor, or a window
  contact — anything that already lives in Home Assistant.
- **Notice a problem early.** The fault-code binary sensor and the water-level sensor
  surface a blocked drain or a failing unit before the room gets warm.
- **See what a unit actually costs you.** Operating time and filter life are recorded as
  long-term statistics, so runtime per week is a chart rather than a guess.
- **Use one dashboard for a mixed household.** A Fahrenheit unit and a Celsius one report
  in their own units and Home Assistant converts both.

## Example automations

Cool the bedroom down before bedtime, but only when it is actually warm:

```yaml
automation:
  - alias: Pre-cool the bedroom
    triggers:
      - trigger: time
        at: "21:30:00"
    conditions:
      - condition: numeric_state
        entity_id: climate.bedroom_ac
        attribute: current_temperature
        above: 74
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.bedroom_ac
        data:
          temperature: 68
          hvac_mode: cool
      - action: switch.turn_on
        target:
          entity_id: switch.bedroom_ac_sleep_mode
```

Shut the unit off when a window opens, and put it back as it was when the window shuts:

```yaml
automation:
  - alias: Pause cooling while the window is open
    triggers:
      - trigger: state
        entity_id: binary_sensor.bedroom_window
        to: "on"
        for: "00:02:00"
    actions:
      - action: climate.turn_off
        target:
          entity_id: climate.bedroom_ac
```

Tell someone when the unit reports a fault:

```yaml
automation:
  - alias: Air conditioner fault
    triggers:
      - trigger: state
        entity_id: binary_sensor.bedroom_ac_problem
        to: "on"
    actions:
      - action: notify.persistent_notification
        data:
          title: Air conditioner problem
          message: >-
            {{ state_attr('sensor.bedroom_ac_fault_code', 'friendly_name') }}
            reported fault code {{ states('sensor.bedroom_ac_fault_code') }}.
```

The fault-code sensor is disabled by default; enable it on the device page before using
the last example.

## Branding

The integration ships its own icon in `custom_components/zafro/brand/`. Home Assistant
2026.3 and later serve a custom integration's local brand images in preference to the
CDN, so no submission to `home-assistant/brands` is needed for the icon to appear.

## Installation

### HACS

1. HACS → **Custom repositories** → add `https://github.com/jamesshannon/ha-zafro`,
   category **Integration**.
2. Search for **Zafro**, install, and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Zafro**.

### Manual

Copy `custom_components/zafro` into your `config/custom_components/` directory and
restart Home Assistant.

### The pyzafro dependency

`pyzafro` is not on PyPI yet, so the manifest asks for it by git tag:

```json
"requirements": ["pyzafro@git+https://github.com/jamesshannon/pyzafro@v0.1.2"]
```

Home Assistant installs this itself at setup, the same way it installs any other
requirement — there is nothing extra to do. Two consequences worth knowing:

- Resolving a URL requirement needs `git` on the host and a reachable GitHub on
  **every** start, because Home Assistant cannot tell whether a URL is already
  satisfied and so re-runs the install each time. A version pinned on PyPI is checked
  against what is installed and touches the network only once, ever.
- Upgrading the library means bumping the tag here, not just tagging `pyzafro`.

This reverts to `pyzafro==0.1.2` once the library is published.

## Configuration

| Field | Meaning |
| --- | --- |
| **Email** | The address your Zafro account is registered to. |
| **Password** | Your Zafro account password. |

Every device on the account is added. Disable the ones you do not want from the device
page — that way a unit you buy later shows up on its own instead of needing a
reconfigure.

The password is stored in the config entry so the connection can be renewed without
prompting you. Home Assistant keeps config entries as plaintext JSON in
`.storage/core.config_entries`; there is no separate secret store available to
integrations, and this is what every cloud integration does. Whoever can read that file
can read the credential.

The session token expires after seven days and is refreshed silently. You are only
prompted to re-authenticate if the password itself stops working — if you change it in
the app, for instance.

### Removal

**Settings → Devices & services → Zafro → ⋮ → Delete**. Nothing is left behind, and no
change is made to your Zafro account. Remove the repository from HACS afterwards if you
want the files gone too.

## How data is updated

The integration is `cloud_push`. It holds one MQTT-over-WebSocket connection per account
and receives state as the device reports it — there is no polling interval to tune.

Two details worth knowing:

- **Commands are not acknowledged synchronously.** Changing something applies
  immediately in the UI and the device confirms a moment later on the same push stream.
  If a command is rejected the device says nothing at all, so anything still unconfirmed
  after five seconds triggers a full state re-read, and the device's answer wins.
- **The device rewrites fields you did not send.** Turning on sleep also mutes the beeper
  and drops the fan speed; eco moves the setpoint. Those consequences are never guessed —
  they appear when the device reports them, a second or so later.

Availability comes from the device's MQTT last-will topic, so a unit unplugged at the
wall shows as unavailable rather than stale — immediately, because that is the device
speaking for itself.

Losing the connection to the cloud is treated differently. The broker drops the socket
every so often and the reconnect takes a second or two, with the unit reachable either
side of it. Entities are only marked unavailable if the connection is still down after a
minute, so a routine reconnect is never visible.

### Devices added or removed later

The account is re-checked every five minutes, so a unit you add in the app appears on
its own without a restart or a reload.

Removal is deliberately slower. A device has to be missing from **fifteen minutes of
consecutive successful checks** before its entities go, and a check that fails outright
does not count against anything — a cloud API having a bad minute looks exactly like a
deleted device in any single response, and only persistence tells them apart.

When a device does go, Home Assistant keeps its identity: history is untouched, and if
the unit comes back the original entity IDs, names and area assignments come back with
it. You can also delete a device by hand from its device page, but only once the account
has genuinely stopped listing it — otherwise the next check would simply add it again.

## Known limitations

- **Schedules are not exposed.** The cloud stores them server-side; use Home Assistant
  automations instead.
- **Heat mode is untested.** The protocol has a value for it; no unit that supports it
  has been observed.
- **Fault codes are raw numbers.** Only `0` has ever been seen, so the vocabulary for
  anything else is unknown. The "Problem" binary sensor tells you *that* something is
  wrong; the fault code sensor is there so you can report *what*.
- **Which swing axis is which is a considered guess.** `oscset1` is treated as
  horizontal. If your louvres disagree, please open an issue — it is a one-line fix.

## Troubleshooting

**Setup fails with "Failed to connect".** The integration has to reach both
`zafro.nbrowan.com` over HTTPS and its broker on port 443. Check that Home Assistant has
outbound access to both.

**The connection drops every few seconds.** Two MQTT clients sharing an identifier evict
each other in a loop. The integration generates a unique one at setup and never changes
it, so this should not happen — but if you have restored a backup onto a second Home
Assistant instance, both are now using the same identifier. Remove and re-add the
integration on one of them.

**Entities are unavailable.** Either the device is unplugged or the cloud connection is
down. Enable debug logging to tell which:

```yaml
logger:
  default: warning
  logs:
    custom_components.zafro: debug
    pyzafro: debug
```

**Something on your unit is missing, or shows a stale value.** The library notices when a
device reports something it cannot use and says so, once per distinct key rather than on
every push:

- A **field it has never seen** — new firmware, or a product that is not fully supported —
  is logged at INFO. Nothing breaks; you are just missing a sensor. Raise `pyzafro` to
  `info` in the block above to see these.
- A **field it supports carrying a value it cannot read** — a mode number outside the
  known range, say — is logged at WARNING, because that field will keep showing its last
  known value and Home Assistant has no way to tell.
- A device **operating outside its capability entry** — a fan speed or setpoint beyond
  what the model is recorded as supporting — is also a WARNING. It means the table is too
  narrow for your unit.

You do not need to have had logging enabled to report any of this. All three are recorded
against the device and included in the diagnostics download.

## Adding a model

If your unit is recognised but some feature is missing — or it is not recognised at all —
download diagnostics from the device page and attach them to an issue. The dump carries
the model, firmware and the full reported state, and deliberately carries no serial
number, MAC address, Wi-Fi name, device name or room name.

For a device that needs characterising from scratch, `pyzafro` ships a CLI that records
what your unit does while you exercise it from the app:

```bash
pip install git+https://github.com/jamesshannon/pyzafro
pyzafro-diagnose report -e you@example.com -o zafro-report.json
```

Support for a new model is a change to `pyzafro`'s capability table alone. This
integration reads what a device can do from the library and builds entities accordingly,
so nothing here needs editing.
