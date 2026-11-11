import Foundation

public enum ControlPlaneError: LocalizedError, Equatable, Sendable {
    case invalidBaseURL
    case invalidResponse
    case server(code: String, message: String)
    case transport(String)

    public var errorDescription: String? {
        switch self {
        case .invalidBaseURL:
            return "控制面地址无效。"
        case .invalidResponse:
            return "服务器返回了无法识别的响应。"
        case let .server(_, message):
            return message
        case let .transport(message):
            return "网络请求失败：\(message)"
        }
    }
}

public protocol ControlPlaneAPI: Sendable {
    func login(email: String, password: String) async throws -> LoginResponse
    func regions(accessToken: String) async throws -> [LogicalRegion]
    func registerDevice(
        accessToken: String,
        clientDeviceId: String,
        name: String,
        tunnelPublicKey: String
    ) async throws -> Device
    func prepareSwitch(
        accessToken: String,
        deviceId: String,
        targetRegionCode: String,
        idempotencyKey: String
    ) async throws -> SwitchOperation
    func confirmSwitch(
        accessToken: String,
        operationId: String,
        success: Bool
    ) async throws -> SwitchOperation
    func switchStatus(accessToken: String, operationId: String) async throws -> SwitchOperation
}

public struct ControlPlaneClient: ControlPlaneAPI, Sendable {
    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    public func disconnectDevice(accessToken: String, deviceId: String) async throws -> Device {
        try await requestWithoutBody(
            path: "/v1/devices/\(deviceId)/disconnect", method: "POST", accessToken: accessToken
        )
    }

    public func switchStatus(accessToken: String, operationId: String) async throws -> SwitchOperation {
        try await requestWithoutBody(path: "/v1/switches/\(operationId)", method: "GET", accessToken: accessToken)
    }

    public func login(email: String, password: String) async throws -> LoginResponse {
        try await request(
            path: "/v1/auth/login",
            method: "POST",
            body: LoginRequest(email: email, password: password),
            accessToken: nil,
            additionalHeaders: [:]
        )
    }

    public func regions(accessToken: String) async throws -> [LogicalRegion] {
        try await requestWithoutBody(
            path: "/v1/regions",
            method: "GET",
            accessToken: accessToken
        )
    }

    public func me(accessToken: String) async throws -> User {
        try await requestWithoutBody(path: "/v1/me", method: "GET", accessToken: accessToken)
    }

    public func registerDevice(
        accessToken: String,
        clientDeviceId: String,
        name: String,
        tunnelPublicKey: String
    ) async throws -> Device {
        try await request(
            path: "/v1/devices",
            method: "POST",
            body: DeviceCreateRequest(
                clientDeviceId: clientDeviceId,
                name: name,
                platform: "macos",
                tunnelPublicKey: tunnelPublicKey
            ),
            accessToken: accessToken,
            additionalHeaders: [:]
        )
    }

    public func prepareSwitch(
        accessToken: String,
        deviceId: String,
        targetRegionCode: String,
        idempotencyKey: String
    ) async throws -> SwitchOperation {
        try await request(
            path: "/v1/devices/\(deviceId)/switches",
            method: "POST",
            body: SwitchPrepareRequest(targetRegionCode: targetRegionCode),
            accessToken: accessToken,
            additionalHeaders: ["Idempotency-Key": idempotencyKey]
        )
    }

    public func confirmSwitch(
        accessToken: String,
        operationId: String,
        success: Bool
    ) async throws -> SwitchOperation {
        try await request(
            path: "/v1/switches/\(operationId)/confirm",
            method: "POST",
            body: SwitchConfirmRequest(success: success),
            accessToken: accessToken,
            additionalHeaders: [:]
        )
    }

    private func request<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body,
        accessToken: String?,
        additionalHeaders: [String: String]
    ) async throws -> Response {
        var request = try makeRequest(
            path: path,
            method: method,
            accessToken: accessToken,
            additionalHeaders: additionalHeaders
        )
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(body)
        return try await perform(request)
    }

    private func requestWithoutBody<Response: Decodable>(
        path: String,
        method: String,
        accessToken: String
    ) async throws -> Response {
        let request = try makeRequest(
            path: path,
            method: method,
            accessToken: accessToken,
            additionalHeaders: [:]
        )
        return try await perform(request)
    }

    private func makeRequest(
        path: String,
        method: String,
        accessToken: String?,
        additionalHeaders: [String: String]
    ) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
            throw ControlPlaneError.invalidBaseURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let accessToken {
            request.setValue(
                "Bearer \(accessToken)",
                forHTTPHeaderField: "Authorization"
            )
        }
        for (name, value) in additionalHeaders {
            request.setValue(value, forHTTPHeaderField: name)
        }
        return request
    }

    private func perform<Response: Decodable>(
        _ request: URLRequest
    ) async throws -> Response {
        do {
            let (data, response) = try await session.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw ControlPlaneError.invalidResponse
            }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            if (200..<300).contains(httpResponse.statusCode) {
                do {
                    return try decoder.decode(Response.self, from: data)
                } catch {
                    throw ControlPlaneError.invalidResponse
                }
            }
            if let envelope = try? decoder.decode(ErrorEnvelope.self, from: data) {
                throw ControlPlaneError.server(
                    code: envelope.error.code,
                    message: envelope.error.message
                )
            }
            throw ControlPlaneError.invalidResponse
        } catch let error as ControlPlaneError {
            throw error
        } catch {
            throw ControlPlaneError.transport(error.localizedDescription)
        }
    }
}

