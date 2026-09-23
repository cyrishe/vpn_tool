import Foundation

public protocol DeviceIdentityProviding: Sendable {
    func clientDeviceId() -> String
    func deviceName() -> String
}

public final class DeviceIdentityProvider: DeviceIdentityProviding, @unchecked Sendable {
    private let defaults: UserDefaults
    private let key = "regional-vpn-client-device-id"

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func clientDeviceId() -> String {
        if let existing = defaults.string(forKey: key) {
            return existing
        }
        let value = UUID().uuidString.lowercased()
        defaults.set(value, forKey: key)
        return value
    }

    public func deviceName() -> String {
        Host.current().localizedName ?? "Mac"
    }
}

