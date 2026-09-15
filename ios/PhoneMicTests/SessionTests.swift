import XCTest
@testable import PhoneMic

final class SessionTests: XCTestCase {
    func testRetryDeadlineAndReset() {
        var retry = RetryBudget()
        XCTAssertEqual(retry.next(now: 0, jitter: 1), 0.5)
        XCTAssertEqual(retry.next(now: 1, jitter: 1), 1)
        XCTAssertNil(retry.next(now: 120, jitter: 1))
        retry.reset()
        XCTAssertEqual(retry.next(now: 200, jitter: 1), 0.5)
    }
    func testOnlyPrivateIPv4Pairing() throws {
        let suffix = "&port=8765&token=" + String(repeating: "a", count: 32) + "&ca=" + String(repeating: "b", count: 64)
        let pair = try Pairing(link: "phonemic://pair?host=192.168.1.12" + suffix)
        XCTAssertEqual(pair.host, "192.168.1.12")
        XCTAssertThrowsError(try Pairing(link: "phonemic://pair?host=example.com" + suffix))
        XCTAssertThrowsError(try Pairing(link: "phonemic://pair?host=8.8.8.8" + suffix))
        XCTAssertThrowsError(try Pairing(link: "phonemic://pair?host=192.168.1.12" + suffix + "&host=10.0.0.1"))
    }
    func testWireMatchesPythonAndBrowser() {
        let frame = Wire.frame(pcm: Data([0,128,255,127]), sequence: 1, milliseconds: 1000)
        XCTAssertEqual(frame.map { String(format: "%02x", $0) }.joined(), "504d3032010000000000000000408f400080ff7f")
    }
}
