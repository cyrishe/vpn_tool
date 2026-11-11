import Foundation

public actor ConnectionCoordinator {
    private let api: any ControlPlaneAPI
    private let driver: any TunnelDriving

    public init(api: any ControlPlaneAPI, driver: any TunnelDriving) {
        self.api = api
        self.driver = driver
    }

    public func connect(token: String, deviceId: String, region: String) async throws {
        var operation = try await api.prepareSwitch(
            accessToken: token, deviceId: deviceId,
            targetRegionCode: region, idempotencyKey: UUID().uuidString
        )
        do {
            for _ in 0..<60 {
                if operation.profile != nil || operation.status != "prepared" { break }
                try await Task.sleep(for: .milliseconds(500))
                operation = try await api.switchStatus(accessToken: token, operationId: operation.operationId)
            }
            guard operation.status == "prepared", let profile = operation.profile else {
                throw TunnelDriverError.invalidProfile
            }
            try await driver.prepare(profile: profile)
            try await driver.activatePrepared()
        } catch {
            await driver.restorePrevious()
            _ = try? await api.confirmSwitch(
                accessToken: token, operationId: operation.operationId, success: false
            )
            throw error
        }
        // A lost confirmation response is ambiguous; keep the tunnel and surface
        // the error instead of falsely claiming the server rolled the switch back.
        let confirmed = try await api.confirmSwitch(
            accessToken: token, operationId: operation.operationId, success: true
        )
        guard confirmed.status == "committed" else {
            await driver.restorePrevious()
            throw TunnelDriverError.activationFailed
        }
    }
}
