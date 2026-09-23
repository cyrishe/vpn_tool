import Foundation

public struct User: Codable, Equatable, Sendable {
    public let id: String
    public let email: String
    public let status: String

    public init(id: String, email: String, status: String) {
        self.id = id
        self.email = email
        self.status = status
    }
}

public struct LoginResponse: Codable, Equatable, Sendable {
    public let accessToken: String
    public let tokenType: String
    public let expiresAt: String
    public let user: User
}

public struct LogicalRegion: Codable, Equatable, Identifiable, Sendable {
    public var id: String { code }

    public let code: String
    public let name: String
    public let provinceCode: String
    public let availability: String

    public init(
        code: String,
        name: String,
        provinceCode: String,
        availability: String
    ) {
        self.code = code
        self.name = name
        self.provinceCode = provinceCode
        self.availability = availability
    }

    public var isAvailable: Bool {
        availability == "available"
    }
}

public struct Device: Codable, Equatable, Sendable {
    public let id: String
    public let clientDeviceId: String
    public let name: String
    public let platform: String
    public let tunnelPublicKey: String
    public let activeRegionCode: String?
    public let configVersion: Int

    public init(
        id: String,
        clientDeviceId: String,
        name: String,
        platform: String,
        tunnelPublicKey: String,
        activeRegionCode: String?,
        configVersion: Int
    ) {
        self.id = id
        self.clientDeviceId = clientDeviceId
        self.name = name
        self.platform = platform
        self.tunnelPublicKey = tunnelPublicKey
        self.activeRegionCode = activeRegionCode
        self.configVersion = configVersion
    }
}

public struct TunnelProfile: Codable, Equatable, Sendable {
    public let profileId: String
    public let configVersion: Int
    public let regionCode: String
    public let gatewayId: String
    public let endpoint: String
    public let serverPublicKey: String
    public let clientAddress: String
    public let dnsServers: [String]
    public let allowedIps: [String]

    public init(
        profileId: String,
        configVersion: Int,
        regionCode: String,
        gatewayId: String,
        endpoint: String,
        serverPublicKey: String,
        clientAddress: String,
        dnsServers: [String],
        allowedIps: [String]
    ) {
        self.profileId = profileId
        self.configVersion = configVersion
        self.regionCode = regionCode
        self.gatewayId = gatewayId
        self.endpoint = endpoint
        self.serverPublicKey = serverPublicKey
        self.clientAddress = clientAddress
        self.dnsServers = dnsServers
        self.allowedIps = allowedIps
    }
}

public struct SwitchOperation: Codable, Equatable, Sendable {
    public let operationId: String
    public let status: String
    public let deviceId: String
    public let targetRegionCode: String
    public let profile: TunnelProfile?

    public init(
        operationId: String,
        status: String,
        deviceId: String,
        targetRegionCode: String,
        profile: TunnelProfile?
    ) {
        self.operationId = operationId
        self.status = status
        self.deviceId = deviceId
        self.targetRegionCode = targetRegionCode
        self.profile = profile
    }
}

struct LoginRequest: Encodable, Sendable {
    let email: String
    let password: String
}

struct DeviceCreateRequest: Encodable, Sendable {
    let clientDeviceId: String
    let name: String
    let platform: String
    let tunnelPublicKey: String
}

struct SwitchPrepareRequest: Encodable, Sendable {
    let targetRegionCode: String
}

struct SwitchConfirmRequest: Encodable, Sendable {
    let success: Bool
}

struct ErrorEnvelope: Decodable, Sendable {
    struct APIErrorBody: Decodable, Sendable {
        let code: String
        let message: String
    }

    let error: APIErrorBody
    let requestId: String?
}

