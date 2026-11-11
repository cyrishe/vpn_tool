import XCTest
@testable import RegionalVPNClientCore

private actor FakeAPI: ControlPlaneAPI {
    var confirmations: [Bool] = []
    func login(email: String, password: String) async throws -> LoginResponse { fatalError() }
    func regions(accessToken: String) async throws -> [LogicalRegion] { [] }
    func switchStatus(accessToken: String, operationId: String) async throws -> SwitchOperation { fatalError() }
    func registerDevice(accessToken: String, clientDeviceId: String, name: String,
                        tunnelPublicKey: String) async throws -> Device { fatalError() }
    func prepareSwitch(accessToken: String, deviceId: String, targetRegionCode: String,
                       idempotencyKey: String) async throws -> SwitchOperation {
        SwitchOperation(operationId: "op", status: "prepared", deviceId: deviceId,
            targetRegionCode: targetRegionCode,
            profile: TunnelProfile(profileId: "profile", configVersion: 1,
                regionCode: targetRegionCode, gatewayId: "gateway", endpoint: "127.0.0.1:1234",
                serverPublicKey: "mock-key", clientAddress: "10.77.1.2/32",
                dnsServers: [], allowedIps: ["0.0.0.0/0"]))
    }
    func confirmSwitch(accessToken: String, operationId: String, success: Bool) async throws -> SwitchOperation {
        confirmations.append(success)
        return SwitchOperation(operationId: operationId, status: success ? "committed" : "rolled_back",
            deviceId: "device", targetRegionCode: "shanghai", profile: nil)
    }
}

private actor FailingDriver: TunnelDriving {
    var restored = false
    func publicKey() async throws -> String { "mock-key" }
    func prepare(profile: TunnelProfile) async throws {}
    func activatePrepared() async throws { throw TunnelDriverError.activationFailed }
    func restorePrevious() async { restored = true }
    func disconnect() async {}
}

final class ConnectionCoordinatorTests: XCTestCase {
    func testSuccessfulSwitchCommits() async throws {
        let api = FakeAPI()
        let driver = MockTunnelDriver()
        let coordinator = ConnectionCoordinator(api: api, driver: driver)
        try await coordinator.connect(token: "token", deviceId: "device", region: "shanghai")
        let region = await driver.activeRegionCode()
        let confirmations = await api.confirmations
        XCTAssertEqual(region, "shanghai")
        XCTAssertEqual(confirmations, [true])
    }

    func testActivationFailureRestoresAndRollsBack() async throws {
        let api = FakeAPI()
        let driver = FailingDriver()
        let coordinator = ConnectionCoordinator(api: api, driver: driver)
        do {
            try await coordinator.connect(token: "token", deviceId: "device", region: "shanghai")
            XCTFail("Expected activation failure")
        } catch {
            XCTAssertEqual(error as? TunnelDriverError, .activationFailed)
        }
        let restored = await driver.restored
        let confirmations = await api.confirmations
        XCTAssertTrue(restored)
        XCTAssertEqual(confirmations, [false])
    }
}
