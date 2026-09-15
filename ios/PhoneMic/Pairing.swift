import Foundation
import Security
import CryptoKit

struct Pairing: Codable {
    let host: String
    let port: Int
    let token: String
    let ca: String
    let clientID: String
    var endpoint: URL { URL(string: "wss://\(host):\(port)/audio")! }
    var origin: String { "https://\(host):\(port)" }

    init(link: String) throws {
        guard let url = URLComponents(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "phonemic", url.host == "pair" else { throw PairError.invalid }
        let items = url.queryItems ?? []
        guard Set(items.map(\.name)).count == items.count else { throw PairError.invalid }
        func item(_ key: String) -> String? { items.first { $0.name == key }?.value }
        guard let host = item("host"), Self.isPrivateIPv4(host),
              let port = item("port").flatMap(Int.init), (1...65535).contains(port),
              let token = item("token"), token.count == 32,
              token.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }),
              let ca = item("ca")?.lowercased(), ca.count == 64,
              ca.allSatisfy({ "0123456789abcdef".contains($0) }) else { throw PairError.invalid }
        self.host = host; self.port = port; self.token = token; self.ca = ca
        self.clientID = UUID().uuidString
    }
    static func isPrivateIPv4(_ host: String) -> Bool {
        let pieces = host.split(separator: ".", omittingEmptySubsequences: false)
        guard pieces.count == 4 else { return false }
        let numbers = pieces.compactMap { Int($0) }
        guard numbers.count == 4, numbers.allSatisfy({ (0...255).contains($0) }),
              zip(pieces, numbers).allSatisfy({ String($0.0) == String($0.1) }) else { return false }
        return numbers[0] == 10 || (numbers[0] == 192 && numbers[1] == 168) ||
            (numbers[0] == 172 && (16...31).contains(numbers[1]))
    }
    enum PairError: LocalizedError {
        case invalid
        var errorDescription: String? { "Scan the Native iPhone QR from PhoneMic 0.2 on Windows." }
    }
}

enum PairStore {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "PhoneMic.Pairing", kSecAttrAccount as String: "laptop"]
    }
    static func load() -> Pairing? {
        var q = query; q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }
    static func save(_ pairing: Pairing) throws {
        let data = try JSONEncoder().encode(pairing)
        let updates: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
        if status == errSecItemNotFound {
            var q = query; updates.forEach { q[$0.key] = $0.value }
            status = SecItemAdd(q as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }
    static func remove() { SecItemDelete(query as CFDictionary) }
}

// Per-connection immutable pin; never disable certificate validation globally.
final class PinnedTrust: NSObject, URLSessionWebSocketDelegate {
    let pair: Pairing
    var closed: ((Int) -> Void)?
    var rejected: (() -> Void)?
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) { closed?(closeCode.rawValue) }
    init(_ pair: Pairing) { self.pair = pair }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              challenge.protectionSpace.host == pair.host,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let root = chain.first(where: {
                  SHA256.hash(data: SecCertificateCopyData($0) as Data).map { String(format: "%02x", $0) }.joined() == pair.ca
              }) else { rejected?(); completionHandler(.cancelAuthenticationChallenge, nil); return }
        guard SecTrustSetPolicies(trust, SecPolicyCreateSSL(true, pair.host as CFString)) == errSecSuccess,
              SecTrustSetAnchorCertificates(trust, [root] as CFArray) == errSecSuccess,
              SecTrustSetAnchorCertificatesOnly(trust, true) == errSecSuccess,
              SecTrustEvaluateWithError(trust, nil) else {
            rejected?(); completionHandler(.cancelAuthenticationChallenge, nil); return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}
