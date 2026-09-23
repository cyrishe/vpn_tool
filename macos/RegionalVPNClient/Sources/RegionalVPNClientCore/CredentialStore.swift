import Foundation
import Security

public protocol CredentialStoring: Sendable {
    func loadAccessToken() -> String?
    func saveAccessToken(_ token: String) throws
    func clearAccessToken() throws
}

public enum CredentialStoreError: LocalizedError, Sendable {
    case keychain(OSStatus)

    public var errorDescription: String? {
        switch self {
        case let .keychain(status):
            return "无法访问钥匙串（\(status)）。"
        }
    }
}

public final class KeychainCredentialStore: CredentialStoring, @unchecked Sendable {
    private let service: String
    private let account = "access-token"

    public init(service: String = "com.regionalvpn.client") {
        self.service = service
    }

    public func loadAccessToken() -> String? {
        var item: CFTypeRef?
        let status = SecItemCopyMatching(
            [
                kSecClass: kSecClassGenericPassword,
                kSecAttrService: service,
                kSecAttrAccount: account,
                kSecReturnData: true,
                kSecMatchLimit: kSecMatchLimitOne,
            ] as CFDictionary,
            &item
        )
        guard status == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    public func saveAccessToken(_ token: String) throws {
        try clearAccessToken(allowMissing: true)
        let status = SecItemAdd(
            [
                kSecClass: kSecClassGenericPassword,
                kSecAttrService: service,
                kSecAttrAccount: account,
                kSecValueData: Data(token.utf8),
                kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            ] as CFDictionary,
            nil
        )
        guard status == errSecSuccess else {
            throw CredentialStoreError.keychain(status)
        }
    }

    public func clearAccessToken() throws {
        try clearAccessToken(allowMissing: true)
    }

    private func clearAccessToken(allowMissing: Bool) throws {
        let status = SecItemDelete(
            [
                kSecClass: kSecClassGenericPassword,
                kSecAttrService: service,
                kSecAttrAccount: account,
            ] as CFDictionary
        )
        if status != errSecSuccess && !(allowMissing && status == errSecItemNotFound) {
            throw CredentialStoreError.keychain(status)
        }
    }
}

public final class InMemoryCredentialStore: CredentialStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var token: String?

    public init(token: String? = nil) {
        self.token = token
    }

    public func loadAccessToken() -> String? {
        lock.withLock { token }
    }

    public func saveAccessToken(_ token: String) throws {
        lock.withLock { self.token = token }
    }

    public func clearAccessToken() throws {
        lock.withLock { token = nil }
    }
}

