import Foundation
import AVFoundation
import Network
import Combine

final class MicSession: ObservableObject {
    @Published private(set) var status = "Pair your laptop to begin"
    @Published private(set) var detail = "Open PhoneMic 0.2 on Windows, then scan its Native iPhone QR."
    @Published private(set) var active = false
    @Published private(set) var muted = false
    @Published private(set) var level: Float = 0
    @Published private(set) var laptop = PairStore.load()?.host ?? "Not paired"
    private let queue = DispatchQueue(label: "PhoneMic.session")
    private let capture = AudioCapture()
    private let path = NWPathMonitor()
    private var pair = PairStore.load()
    private var observers: [NSObjectProtocol] = []
    private var timer: DispatchSourceTimer?
    private var retryWork: DispatchWorkItem?
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var budget = RetryBudget()
    private var wanted = false, interrupted = false, connected = false, isMuted = false, capturing = false
    private var intent = 0, linkGeneration = 0, captureGeneration = 0
    private var sequence: UInt32 = 0, ack: UInt32 = 0
    private var lastAck: TimeInterval = 0, connectedAt: TimeInterval = 0, lastCapture: TimeInterval = 0
    // At most one captured packet awaits the session queue. Newest speech wins.
    private let mailboxLock = NSLock()
    private var mailbox: [(Data, TimeInterval, Float, Int)] = []
    private var mailboxScheduled = false
    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    init() {
        let notifications = NotificationCenter.default
        observers.append(notifications.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { [weak self] note in
            self?.queue.async { self?.interruption(note) }
        })
        observers.append(notifications.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: nil) { [weak self] note in
            guard let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  let reason = AVAudioSession.RouteChangeReason(rawValue: raw),
                  [.oldDeviceUnavailable, .newDeviceAvailable, .noSuitableRouteForCategory].contains(reason) else { return }
            self?.queue.async { self?.rebuildCapture() }
        })
        observers.append(notifications.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: nil) { [weak self] _ in
            self?.queue.async { self?.rebuildCapture() }
        })
        path.pathUpdateHandler = { [weak self] network in
            guard let self = self, self.wanted, self.capturing, !self.interrupted else { return }
            if network.status == .satisfied, !self.connected { self.connect() }
            else if network.status != .satisfied { self.retry("Waiting for Wi-Fi") }
        }
        path.start(queue: queue)
    }
    deinit {
        observers.forEach(NotificationCenter.default.removeObserver)
        path.cancel(); timer?.cancel(); retryWork?.cancel()
        socket?.cancel(with: .goingAway, reason: nil);session?.invalidateAndCancel()
        capture.stop()
    }
    private func display(_ title: String, _ explanation: String = "") {
        let active = wanted, muted = isMuted
        DispatchQueue.main.async { [weak self] in
            self?.status = title; self?.detail = explanation; self?.active = active; self?.muted = muted
        }
    }
    func pair(link: String) {
        queue.async {
            do {
                let value = try Pairing(link: link)
                try PairStore.save(value)
                self.finish("Paired", "Tap Start. The pairing is stored on this iPhone.")
                self.pair = value
                DispatchQueue.main.async { self.laptop = value.host }
            } catch { self.display("Could not pair", error.localizedDescription) }
        }
    }
    func forget() {
        queue.async {
            self.finish("Pairing removed");PairStore.remove();self.pair = nil
            DispatchQueue.main.async { self.laptop = "Not paired" }
        }
    }
    func start() {
        queue.async {
            guard !self.wanted else { return }
            guard self.pair != nil else { self.display("Pair your laptop first");return }
            self.wanted = true;self.interrupted = false;self.intent += 1;self.budget.reset()
            let intent = self.intent
            self.display("Requesting microphone permission")
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                self.queue.async {
                    guard self.wanted, self.intent == intent else { return }
                    guard granted else { self.finish("Microphone permission needed", "Enable Microphone for PhoneMic in Settings.");return }
                    self.beginCapture()
                }
            }
        }
    }
    func stop() { queue.async { self.finish("Stopped", "The microphone is released. Automatic reconnect is off.") } }
    func toggleMute() {
        queue.async {
            self.isMuted.toggle()
            self.display(self.connected ? (self.isMuted ? "Muted" : "Streaming") : "Reconnecting", "Mute is preserved across reconnections.")
        }
    }
    private func beginCapture() {
        guard wanted, !interrupted else { return }
        guard AVAudioSession.sharedInstance().recordPermission == .granted else { finish("Microphone permission needed");return }
        captureGeneration += 1
        let generation = captureGeneration
        do {
            try capture.start(deliver: { [weak self] data, stamp, peak in
                self?.enqueue(data, stamp, peak, generation)
            }, failure: { [weak self] in
                self?.queue.async {
                    guard let self = self, self.wanted, self.captureGeneration == generation else { return }
                    self.finish("Microphone conversion failed", "Tap Start to try again.")
                }
            })
            capturing = true;lastCapture = now
            startWatchdog();connect()
        } catch { finish("Could not start microphone", error.localizedDescription + " Return to PhoneMic and tap Start.") }
    }
    private func enqueue(_ data: Data, _ stamp: TimeInterval, _ peak: Float, _ generation: Int) {
        mailboxLock.lock()
        if mailbox.count >= 8 { mailbox.removeFirst() }
        mailbox.append((data, stamp, peak, generation))
        let schedule = !mailboxScheduled;mailboxScheduled = true
        mailboxLock.unlock()
        if schedule {
            queue.async { [weak self] in
                guard let self = self else { return }
                self.mailboxLock.lock()
                let latest = self.mailbox;self.mailbox.removeAll(keepingCapacity: true);self.mailboxScheduled = false
                self.mailboxLock.unlock()
                for packet in latest { self.consume(packet.0, packet.1, packet.2, packet.3) }
            }
        }
    }
    private func consume(_ pcm: Data, _ stamp: TimeInterval, _ peak: Float, _ generation: Int) {
        guard wanted, !interrupted, generation == captureGeneration else { return }
        lastCapture = now
        guard connected, let socket = socket else { return } // Drop while disconnected; no replay.
        guard now-stamp <= 0.2, sequence >= ack, sequence-ack < 12 else { retry("Audio delivery stalled; dropping old audio");return }
        if sequence == UInt32.max { retry("Refreshing long session");return }
        sequence += 1
        let data = isMuted ? Data(count: pcm.count) : pcm
        let packet = Wire.frame(pcm: data, sequence: sequence, milliseconds: stamp * 1000)
        let link = linkGeneration
        socket.send(.data(packet)) { [weak self] error in
            guard error != nil else { return }
            self?.queue.async { if self?.linkGeneration == link { self?.retry("Send failed") } }
        }
        let meter = isMuted ? 0 : peak
        DispatchQueue.main.async { [weak self] in self?.level = meter }
    }
    private func disconnect() {
        linkGeneration += 1;retryWork?.cancel();retryWork = nil;connected = false
        socket?.cancel(with: .goingAway, reason: nil);socket = nil
        session?.invalidateAndCancel();session = nil
        DispatchQueue.main.async { [weak self] in self?.level = 0 }
    }
    private func connect() {
        guard wanted, capturing, !interrupted, let pair = pair else { return }
        if let deadline = budget.deadline, now >= deadline { finish("Reconnect timed out", "Check Wi-Fi and the receiver, then tap Start.");return }
        disconnect()
        let link = linkGeneration
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 5;config.waitsForConnectivity = false
        config.allowsCellularAccess = false
        let delegate = PinnedTrust(pair)
        delegate.closed = { [weak self] code in
            self?.queue.async { if self?.linkGeneration == link { self?.closed(code) } }
        }
        delegate.rejected = { [weak self] in
            self?.queue.async {
                if self?.linkGeneration == link { self?.finish("Laptop identity could not be verified", "Check the laptop and scan its Native iPhone QR again.") }
            }
        }
        let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
        self.session = session
        var request = URLRequest(url: pair.endpoint)
        request.setValue(pair.origin, forHTTPHeaderField: "Origin")
        let socket = session.webSocketTask(with: request);self.socket = socket
        socket.maximumMessageSize = 8192
        socket.resume()
        let hello: [String: Any] = ["token": pair.token, "rate": 48000, "protocol": 2, "client_id": pair.clientID]
        guard let json = try? JSONSerialization.data(withJSONObject: hello), let text = String(data: json, encoding: .utf8) else { finish("Pairing error");return }
        display("Connecting", "Your microphone remains active during retries. Tap Stop to release it.")
        socket.send(.string(text)) { [weak self] error in
            self?.queue.async {
                guard let self = self, self.linkGeneration == link, self.wanted else { return }
                if error != nil { self.closed(socket.closeCode.rawValue) }
                else { self.receive(socket, link) }
            }
        }
        queue.asyncAfter(deadline: .now()+5) { [weak self] in
            guard let self = self, self.wanted, self.linkGeneration == link, !self.connected else { return }
            self.retry("Laptop did not answer")
        }
    }
    private func receive(_ socket: URLSessionWebSocketTask, _ link: Int) {
        socket.receive { [weak self] result in
            self?.queue.async {
                guard let self = self, self.wanted, self.linkGeneration == link else { return }
                switch result {
                case .failure: self.closed(socket.closeCode.rawValue)
                case .success(let message):
                    if case .string(let text) = message, let data = text.data(using: .utf8),
                       let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                        if obj["type"] as? String == "ready", !self.connected {
                            self.connected = true;self.sequence = 0;self.ack = 0
                            self.lastAck = self.now;self.connectedAt = self.now
                            self.display(self.isMuted ? "Muted" : "Streaming", "You can try locking the screen. Calls may pause the microphone.")
                        } else if obj["type"] as? String == "ack", let ack = obj["seq"] as? UInt32,
                                  ack > self.ack, ack <= self.sequence {
                            self.ack = ack;self.lastAck = self.now
                            if self.now-self.connectedAt >= 10 { self.budget.reset() }
                        }
                    }
                    if self.linkGeneration == link { self.receive(socket, link) }
                }
            }
        }
    }
    private func closed(_ code: Int) {
        if code <= 0 || code == 1006 {
            let link = linkGeneration, old = socket
            queue.asyncAfter(deadline: .now()+0.1) { [weak self] in
                guard let self = self, self.wanted, self.linkGeneration == link else { return }
                let final = old?.closeCode.rawValue ?? 0
                if [1008,4000,4001,4003].contains(final) { self.closed(final) }
                else { self.retry("Connection lost") }
            }
            return
        }
        switch code {
        case 4000: finish("Receiver stopped", "Tap Start after starting the Windows receiver again.")
        case 4001: finish("Session replaced", "This phone is no longer transmitting.")
        case 4003: finish("Laptop is busy", "Stop the other phone before starting this one.")
        case 1008: finish("Pairing or protocol rejected", "Scan the Native iPhone QR again.")
        default: retry(code == 4004 ? "Windows audio device is recovering" : "Connection lost")
        }
    }
    private func retry(_ reason: String) {
        guard wanted, !interrupted else { return }
        disconnect()
        guard let delay = budget.next(now: now) else { finish("Reconnect timed out", "Check Wi-Fi and laptop, then tap Start.");return }
        display("Reconnecting", reason + ". No audio is saved while disconnected.")
        let link = linkGeneration
        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.wanted, !self.interrupted, self.linkGeneration == link else { return }
            self.connect()
        }
        retryWork = work;queue.asyncAfter(deadline: .now()+delay, execute: work)
    }
    private func startWatchdog() {
        timer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now()+0.25, repeating: 0.25)
        timer.setEventHandler { [weak self] in
            guard let self = self, self.wanted, self.capturing, !self.interrupted else { return }
            if self.now-self.lastCapture > 2.5 { self.finish("Microphone stopped", "Return to PhoneMic and tap Start.") }
            else if self.connected && self.now-self.lastAck > 1.5 { self.retry("Laptop stopped acknowledging audio") }
        }
        self.timer = timer;timer.resume()
    }
    private func interruption(_ note: Notification) {
        guard wanted, let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        if type == .began {
            interrupted = true;intent += 1;captureGeneration += 1;disconnect();capturing = false;capture.stop();timer?.cancel();timer = nil
            display("Paused by iOS", "A call or another audio session interrupted the mic. It will resume only if iOS allows it.")
        } else {
            let rawOptions = note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let options = AVAudioSession.InterruptionOptions(rawValue: rawOptions)
            if options.contains(.shouldResume) {
                interrupted = false;budget.reset();beginCapture()
            } else { finish("Ready to resume", "Return to PhoneMic and tap Start when your call is finished.") }
        }
    }
    private func rebuildCapture() {
        guard wanted, !interrupted else { return }
        disconnect();captureGeneration += 1;capturing = false;capture.stop();beginCapture()
    }
    private func finish(_ title: String, _ explanation: String = "") {
        wanted = false;interrupted = false;intent += 1;captureGeneration += 1
        disconnect();capturing = false;capture.stop();timer?.cancel();timer = nil;budget.reset()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        display(title, explanation)
    }
}
