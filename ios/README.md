# Native iPhone client — build and device-test instructions

This folder contains an Xcode project and Swift source, **not an installable IPA**.
It has not been compiled or tested on Apple hardware in this workspace. Use it as
a development build; do not market lock-screen reliability as proven yet.

## Build on a Mac

1. Copy the full `ios` folder to a Mac with Xcode and an iOS SDK. The project targets
   iOS 16+ and Swift 5 language mode. Use an Xcode version compatible with your iPhone.
2. Open `PhoneMic.xcodeproj` and select the **PhoneMic** scheme.
3. Select the app target → Signing & Capabilities → choose your own signing team.
   Change `com.example.PhoneMic` to a unique bundle identifier. Configure the test
   target too if you will run tests. No team/account has been supplied in this project.
4. Connect and select your physical iPhone, follow Xcode's device/developer-mode
   prompts, then Build and Run. Code-signing eligibility and provisioning come from
   your Apple account; this package does not configure them for you.
5. Allow Microphone, Camera and Local Network access when prompted. A simulator is
   useful for unit tests, but is not a substitute for lock-screen/audio device tests.

`generate_project.py` regenerates the checked-in Xcode project and Info.plist using
Python; regeneration replaces project edits. `project.yml` is an optional XcodeGen
alternative, not a required dependency.

## Pair and use

1. Start the Windows 0.2 receiver. In the window, click **Native iPhone QR**.
2. In the iPhone app, tap **Scan Native iPhone QR**. Scan directly from the trusted
   laptop. Alternatively copy/paste its `phonemic://pair?...` link into the app.
3. Tap Start. Choose CABLE Output in the Windows calling/recording application.
4. Check audio, mute and Stop before trying screen locking.
5. Pairing is remembered. On subsequent launches tap Start; no QR unless the IP or
   pairing changes. A native CA pin avoids system-wide certificate-profile installation.
6. **Stop** always cancels pending retries. **Forget this laptop** deletes the local
   Keychain entry. To revoke the old credential on Windows too, stop the receiver and
   click **Quên ghép nối**, then pair again.

## Recovery policy

- Session intent, network generation and capture generation are distinct. Old async
  permission, capture and socket callbacks cannot restart a stopped/replaced session.
- Short network failures retain the user-started audio capture while discarding
  unsent speech. The bounded capture mailbox holds at most eight packets; the wire
  permits at most twelve unacknowledged packets before reconnecting.
- Retries use 0.5 s exponential backoff capped around 8 s plus jitter, with a total
  two-minute budget. Ten seconds of stable acknowledged audio resets the budget.
- The active recording category plus `UIBackgroundModes = audio` provides the native
  route for background/screen-lock recording. This configuration is not proof that
  every iPhone/iOS version will maintain the session.
- A call interruption closes the link and pauses capture. On interruption end,
  resume only if iOS supplies `shouldResume`. If activation fails or iOS does not
  allow resumption, Stop and show instructions to tap Start again.
- Route changes and media-service resets rebuild capture. No fake/silent playback,
  VoIP push trick, microphone capture during a phone call, or background-task abuse.
- iOS can suspend/terminate apps. Force-quit never relaunches automatically. A long
  Wi-Fi outage in background may require returning to the app even before retry expiry.

## Mandatory device acceptance checks before a release

Record the iPhone model/iOS, Windows version, VB-CABLE version, Wi-Fi/router and
observed results for each run. Do not fill this checklist from simulated tests.

| Scenario | Expected result to verify |
|---|---|
| 30-minute stream including 10 minutes screen locked | Continuous fresh audio or explicit recovery; no growing latency |
| Incoming call answered and ended, screen locked/unlocked | Pause for call; resume only with iOS permission, or request a tap |
| User Stop while call is active | No resumption after call |
| Wi-Fi off 5 s, 30 s, >120 s | Reconnect first two if iOS still schedules the app; long outage stops |
| Receiver crash/restart at same IP | Reconnect with retained token/CA within retry window |
| Windows explicit Stop | Connected phone stops; no unattended reconnect |
| Laptop sleep/wake | No pre-sleep speech replay; verify recovery or tap-to-restart path |
| Remove/restore VB-CABLE | Receiver stops with actionable message; manual restart works |
| Headset plugged/unplugged | Built-in input restored or visible stopped state, never silent success |
| Stop/restart repeatedly, including during permission prompt | No duplicate capture, sockets or delayed restart |
| Wrong CA/host/expired certificate/wrong token | No audio transmitted to the unverified receiver |
| Another phone connects | Active owner is not displaced |
| App force-quit | Capture ends; manually reopen to start |

Run XCTest in Xcode (Product → Test). Supplied tests check retry budget, QR parsing
and shared wire bytes. They do not exercise AVAudioSession or TLS delegation; the
physical acceptance checks above are still required.

Apple references:
- https://developer.apple.com/documentation/avfaudio/handling-audio-interruptions
- https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/record
- https://developer.apple.com/documentation/security/sectrustevaluatewitherror(_:_:)
