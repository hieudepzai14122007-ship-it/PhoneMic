import AVFoundation
import Foundation

// Engine lifetime is serialized on MicSession's queue. Each tap owns its converter.
final class AudioCapture {
    private var engine: AVAudioEngine?
    private var tapInstalled = false
    func start(deliver: @escaping (Data, TimeInterval, Float) -> Void, failure: @escaping () -> Void) throws {
        stop()
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.record, mode: .measurement, options: [])
        try audio.setPreferredSampleRate(48000)
        try audio.setPreferredIOBufferDuration(0.02)
        try audio.setActive(true)
        if let builtIn = audio.availableInputs?.first(where: { $0.portType == .builtInMic }) {
            try audio.setPreferredInput(builtIn)
        }
        let engine = AVAudioEngine()
        self.engine = engine
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: format, to: target) else {
            throw NSError(domain: "PhoneMic.Audio", code: 1, userInfo: [NSLocalizedDescriptionKey: "The microphone is unavailable."])
        }
        input.installTap(onBus: 0, bufferSize: 960, format: format) { buffer, _ in
            let stamp = ProcessInfo.processInfo.systemUptime
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 48000 / format.sampleRate) + 32)
            guard let converted = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { failure(); return }
            var supplied = false
            var error: NSError?
            let status = converter.convert(to: converted, error: &error) { _, state in
                if supplied { state.pointee = .noDataNow; return nil }
                supplied = true; state.pointee = .haveData; return buffer
            }
            guard status != .error, error == nil, let samples = converted.floatChannelData?[0] else { failure(); return }
            var offset = 0
            while offset < Int(converted.frameLength) {
                let count = min(960, Int(converted.frameLength) - offset)
                var data = Data(capacity: count * 2), peak: Float = 0
                for index in offset..<(offset+count) {
                    let value = max(-1, min(1, samples[index])); peak = max(peak, abs(value))
                    var pcm = Int16((value * 32767).rounded()).littleEndian
                    withUnsafeBytes(of: &pcm) { data.append(contentsOf: $0) }
                }
                deliver(data, stamp, peak)
                offset += count
            }
        }
        tapInstalled = true
        engine.prepare()
        do { try engine.start() } catch { stop(); throw error }
    }
    func stop() {
        if let engine = engine {
            engine.stop(); if tapInstalled { engine.inputNode.removeTap(onBus: 0) }
        }
        engine = nil; tapInstalled = false
    }
}
