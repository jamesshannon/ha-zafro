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

Other models in the same family are matched by model prefix, and anything unrecognised
falls back to a minimal capability set — power, mode, setpoint and the ambient readings —
rather than refusing to set up. If you have a model that is not fully supported, see
[Adding a model](#adding-a-model).

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

## Installation

### HACS

1. HACS → **Custom repositories** → add `https://github.com/jamesshannon/ha-zafro`,
   category **Integration**.
2. Search for **Zafro**, install, and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Zafro**.

### Manual

Copy `custom_components/zafro` into your `config/custom_components/` directory and
restart Home Assistant.

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
wall shows as unavailable rather than stale.

## Known limitations

- **Devices added in the app after setup do not appear until you reload the entry.**
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
pip install pyzafro
pyzafro-diagnose report -e you@example.com -o zafro-report.json
```

Support for a new model is a change to `pyzafro`'s capability table alone. This
integration reads what a device can do from the library and builds entities accordingly,
so nothing here needs editing.
