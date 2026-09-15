# PhoneMic Wi-Fi 0.2 validation — 2026-09-14

Environment: Linux / Python 3.12 / Node. No Windows audio hardware, macOS, Xcode,
iPhone or iOS Simulator available. **Native source is uncompiled and unverified.**

## Executed successfully

`python -m unittest discover -s tests -v`: 14 tests.

- Streaming resampling, buffer wrap/prefill/stereo, bounded overflow.
- Stale pre-sleep audio discarded both before reading and when fresh audio arrives.
- Unique/stable local CA, updated server IP SAN, certificate-only Safari profile.
- Bad origin/token/rate rejected, single active phone, malformed PCM rejected.
- No-audio timeout and clearing of queued speech on disconnect.
- Protocol v2 sequence/timestamp validation; nonfinite/regressing timestamps rejected.
- Duplicate/stale frames not forwarded.
- Same-client handoff replaces an abandoned connection without an old cleanup handler
  clearing the new owner; another client is rejected.
- Shared wire byte vector checked against the browser encoder and supplied Swift test.
- Real loopback HTTPS and profile transfer, private-key URL access denied, same-port
  stop/restart and stable pairing token across receiver instances.

`node tests/test_worklet.cjs`: PCM framing, endian order, clipping, mute and silent
phone output. `node tests/test_browser_sessions.cjs`: simulated Safari controller
with controlled socket/timer/permission events verifies reconnect, mute retention,
stale callback isolation, Stop cancellation, late permission handling, background
pause, terminal receiver Stop, ACK backpressure, retry limit and wire bytes.

These browser tests run the actual client controller against fake browser APIs.
They do not establish real Safari media permissions or audio behavior.

## Not executed / release blockers

- Native iPhone compilation, Xcode XCTest, signing, installation and TLS pinning on iOS.
- Background recording, screen-lock, call interruption/resumption, route/media reset.
- Windows GUI/launcher, VB-CABLE/PortAudio device health and physical audio delivery.
- Real end-to-end latency, sustained audio quality, battery use, cross-router behavior.
- Windows ARM64 and automatic IP-change discovery (discovery is not implemented).

`ios/README.md` contains the device acceptance matrix. Until these checks pass,
this is a development prototype, not a commercially validated reliable-session release.
