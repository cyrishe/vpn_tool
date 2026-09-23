import Foundation

public protocol TunnelDriving: Sendable {
    func publicKey() async throws -> String
    func prepare(profile: TunnelProfile) async throws
    func activatePrepared() async throws
    func restorePrevious() async
    func disconnect() async
}

public enum TunnelDriverError: LocalizedError, Equatable, Sendable {
    case invalidProfile
    case noPreparedProfile
    case activationFailed

    public var errorDescription: String? {
        switch self {
        case .invalidProfile:
            return "服务器下发的隧道配置无效。"
        case .noPreparedProfile:
            return "没有可激活的隧道配置。"
        case .activationFailed:
            return "新地区连接失败，已恢复原连接。"
        }
    }
}

public actor MockTunnelDriver: TunnelDriving {
    private var activeProfile: TunnelProfile?
    private var preparedProfile: TunnelProfile?
    private var previousProfile: TunnelProfile?
    private let mockPublicKey: String

    public init(mockPublicKey: String = "mock-macos-public-key") {
        self.mockPublicKey = mockPublicKey
    }

    public func publicKey() async throws -> String {
        mockPublicKey
    }

    public func prepare(profile: TunnelProfile) async throws {
        guard
            !profile.endpoint.isEmpty,
            !profile.serverPublicKey.isEmpty,
            profile.allowedIps.contains("0.0.0.0/0")
        else {
            throw TunnelDriverError.invalidProfile
        }
        previousProfile = activeProfile
        preparedProfile = profile
    }

    public func activatePrepared() async throws {
        guard let preparedProfile else {
            throw TunnelDriverError.noPreparedProfile
        }
        activeProfile = preparedProfile
        self.preparedProfile = nil
    }

    public func restorePrevious() async {
        activeProfile = previousProfile
        preparedProfile = nil
        previousProfile = nil
    }

    public func disconnect() async {
        activeProfile = nil
        preparedProfile = nil
        previousProfile = nil
    }

    public func activeRegionCode() -> String? {
        activeProfile?.regionCode
    }
}

