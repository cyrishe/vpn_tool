import Foundation
import Network
import Security

final class DirectSessionDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    struct PrivateCenter {
        let url: URL
        let certificate: SecCertificate

        func accepts(_ space: URLProtectionSpace) -> Bool {
            guard space.protocol == "https", space.host.caseInsensitiveCompare(url.host ?? "") == .orderedSame,
                  space.port == (url.port ?? 443), let trust = space.serverTrust,
                  let leaf = (SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first,
                  SecCertificateCopyData(leaf) as Data == SecCertificateCopyData(certificate) as Data else { return false }
            // The pilot ships its self-signed server certificate as an exact, origin-scoped pin.
            let dates = [kSecOIDX509V1ValidityNotBefore, kSecOIDX509V1ValidityNotAfter]
            guard let values = SecCertificateCopyValues(leaf, dates as CFArray, nil) as? [String: [String: Any]],
                  let start = values[dates[0] as String]?[kSecPropertyKeyValue as String] as? NSNumber,
                  let end = values[dates[1] as String]?[kSecPropertyKeyValue as String] as? NSNumber else { return false }
            let now = Date().timeIntervalSinceReferenceDate
            return start.doubleValue <= now && now < end.doubleValue
        }
    }

    private let center: PrivateCenter?

    init(center: PrivateCenter? = nil) { self.center = center }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard let center, challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        guard let trust = challenge.protectionSpace.serverTrust, center.accepts(challenge.protectionSpace) else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    static func make(center: PrivateCenter? = nil) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary = ["HTTPEnable": 0, "HTTPSEnable": 0, "SOCKSEnable": 0]
        config.timeoutIntervalForRequest = 8
        config.timeoutIntervalForResource = 15
        return URLSession(configuration: config, delegate: DirectSessionDelegate(center: center), delegateQueue: nil)
    }
}

struct ExitCheck {
    static func verify(_ expected: String) async throws -> String {
        let session = DirectSessionDelegate.make()
        defer { session.finishTasksAndInvalidate() }
        for url in [URL(string: "https://ifconfig.co/ip")!, URL(string: "https://api.ipify.org")!] {
            guard let (body, response) = try? await session.data(from: url),
                  (response as? HTTPURLResponse)?.statusCode == 200,
                  let value = String(data: body, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
                  IPv4Address(value) != nil else { continue }
            if value == expected { return value }
        }
        throw NativeVPNError.egressMismatch
    }
}
