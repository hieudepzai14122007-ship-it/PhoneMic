import Foundation

struct RetryBudget {
    private(set) var deadline: TimeInterval?
    private var attempts = 0
    mutating func reset() { deadline = nil; attempts = 0 }
    mutating func next(now: TimeInterval, jitter: Double = Double.random(in: 0.85...1.15)) -> TimeInterval? {
        if deadline == nil { deadline = now + 120 }
        guard let deadline = deadline, now < deadline else { return nil }
        let delay = min(8, 0.5 * pow(2, Double(min(attempts, 4)))) * jitter
        attempts += 1
        return min(delay, deadline-now)
    }
}

enum Wire {
    static func frame(pcm: Data, sequence: UInt32, milliseconds: Double) -> Data {
        var result = Data([80, 77, 48, 50])
        var seq = sequence.littleEndian, stamp = milliseconds.bitPattern.littleEndian
        withUnsafeBytes(of: &seq) { result.append(contentsOf: $0) }
        withUnsafeBytes(of: &stamp) { result.append(contentsOf: $0) }
        result.append(pcm)
        return result
    }
}
