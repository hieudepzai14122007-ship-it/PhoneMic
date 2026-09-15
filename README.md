# PhoneMic Wi-Fi 0.2 — session recovery prototype

**Windows + Safari recovery is implemented and has automated tests.**
**A native iPhone client is included as source with an Xcode project. It has not
been compiled, signed or tested on an iPhone here.** Screen-lock and phone-call
behavior must be verified on real iPhones before this is a dependable product.

## Upgrade from 0.1

1. Stop the old PhoneMic window and close its iPhone page.
2. Extract this ZIP into a new folder. Do not run both receivers at once.
3. Run `START.cmd` in the new folder. Existing Python and VB-CABLE can be reused;
   the launcher creates a fresh `.venv` for this version.
4. Select Wi-Fi IP + CABLE Input; click **Bắt đầu nhận mic**.
5. Safari users: scan the new Safari QR. The local CA is reused, so normally you
   do not need to reinstall the certificate profile from version 0.1.
6. In Zoom/Discord/etc., choose **CABLE Output** as the microphone.

`HUONG-DAN.html` retains the detailed Vietnamese Windows/Safari setup steps.
`ios/README.md` explains how to build/install the native client using a Mac.

## What changed

- Automatic network reconnect with exponential backoff and jitter, up to two
  minutes. Retry budget resets after 10 seconds of acknowledged streaming.
- Same-device reconnect replaces its own abandoned socket, without clearing
  a newer session. A different phone cannot interrupt the active owner.
- Microphone mute state survives network reconnects.
- Sequence/timestamp frames and receiver acknowledgements detect duplicate,
  delayed, or blocked audio. Old speech is discarded rather than replayed.
- Audio buffer drops queued pre-sleep speech after a 300 ms gap.
- Pairing token persists across receiver restarts; **Quên ghép nối** rotates it
  on next start and invalidates old QR links. Root certificate is retained.
- Explicit Stop cancels retries and releases capture. Windows Stop is terminal
  for connected clients. If Stop happens while the network is already broken,
  the phone cannot receive that signal: it retries until its two-minute budget
  expires or you tap Stop on the phone.
- Windows checks audio callback health. If VB-CABLE stops responding it stops
  the receiver and asks you to fix the device and press Start again.

## Platform behavior

| Event | Safari client | Native iPhone source |
|---|---|---|
| Brief network failure, same laptop IP | Retries while page/capture stay active | Retries while capture stays active; discards unsent audio |
| Screen locked / another app foreground | Stops; return and tap Start | Background recording is configured; needs device validation |
| Incoming call | Stops; return and tap Start | Pauses; resumes only if iOS signals `shouldResume` and activation succeeds; otherwise tap Start |
| Audio route change / media services reset | Requires another tap if interrupted | Rebuilds the audio engine; failure becomes a visible stopped state |
| User Stop | Cancels retries | Cancels retries, releases AVAudioSession |
| iOS force-quit / system termination | Page no longer works | No automatic relaunch; reopen and tap Start |
| Laptop IP changes | Rescan current QR | Rescan Native iPhone QR; automatic discovery is not implemented |
| Network outage exceeds 2 minutes | Stops and asks for a tap | Stops capture and asks for a tap |
| VB-CABLE disappears | Windows receiver stops | Same; restore device and manually Start again |

## Native client

Open `ios/PhoneMic.xcodeproj` in Xcode on a Mac, configure your signing team and
unique bundle identifier, and build to your iPhone. The **Native iPhone QR** button
on Windows displays the pairing link for the scanner inside the native app.

The native app pins the Windows CA fingerprint from that QR and verifies the TLS
chain and IP. It does **not** require installing the Safari root profile system-wide.
Pairing credentials are stored in the iPhone Keychain, available after first unlock,
not synced to other devices. Do not share a pairing QR/link.

No paid membership, TestFlight upload, App Store publication, signed IPA, driver
redistribution or EXE build has been performed. This is not a commercial release.

## Technical limits and privacy

- Local Wi-Fi only. No cloud, recordings, analytics, Bonjour or Internet relay.
- Native built-in microphone, mono 48 kHz, PCM16. Bluetooth headset input, audio
  enhancement and native gain control are outside this release; native has Mute.
- TLS 8765; setup-only HTTP 8766; bind to selected local IPv4, no router forwarding.
- Safari still needs the local certificate and an open foreground page.
- Python 3.12–3.14 + VB-CABLE on Windows 11 x64. ARM64 unverified.
- Pairing and certificates: `%LOCALAPPDATA%\PhoneMic-WiFi\certificates`.
- Buffer/timeout values are design settings, not measured end-to-end latency.
- Nothing can guarantee uninterrupted mic access through phone calls, force-quits
  or operating-system suspension. The fallback is an explicit paused/stopped state.

## Validation

See `TEST-REPORT.md`: Python integration tests + simulated browser lifecycle tests
passed. iOS XCTest sources are supplied but not run. No physical audio path was
available in this Linux workspace.
