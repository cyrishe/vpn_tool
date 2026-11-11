import Foundation
import NetworkExtension
import SystemExtensions

@MainActor
final class ExtensionApproval: NSObject, OSSystemExtensionRequestDelegate {
    private var continuation: CheckedContinuation<Void, Error>?
    private var pending: OSSystemExtensionRequest?
    private var onApproval: (() -> Void)?

    func activate(_ identifier: String, onApproval: @escaping () -> Void) async throws {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            self.onApproval = onApproval
            let request = OSSystemExtensionRequest.activationRequest(forExtensionWithIdentifier: identifier, queue: .main)
            pending = request
            request.delegate = self
            OSSystemExtensionManager.shared.submitRequest(request)
        }
    }

    nonisolated func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        Task { @MainActor in self.onApproval?() }
    }

    nonisolated func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties,
                 withExtension replacement: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction {
        .replace
    }

    nonisolated func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        let completed = result == .completed
        Task { @MainActor in
            self.finish(completed ? .success(()) : .failure(NativeVPNError.extensionRestart))
        }
    }

    nonisolated func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        Task { @MainActor in self.finish(.failure(error)) }
    }

    private func finish(_ result: Result<Void, Error>) {
        let waiter = continuation
        continuation = nil
        pending = nil
        onApproval = nil
        waiter?.resume(with: result)
    }
}

@MainActor
final class SystemVPN {
    static var providerID: String { (Bundle.main.bundleIdentifier ?? "com.regionalvpn.client") + ".tunnel" }
    private let approval = ExtensionApproval()
    private var manager: NETunnelProviderManager?
    private(set) var currentStart: TunnelStart?

    var status: NEVPNStatus { manager?.connection.status ?? .disconnected }
    var needsStop: Bool { status != .disconnected && status != .invalid }

    func load() async throws {
        manager = try await NETunnelProviderManager.loadAllFromPreferences().first {
            ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == Self.providerID
        }
    }

    func configure(onApproval: @escaping () -> Void) async throws {
        try await load()
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
        if let manager, manager.isEnabled,
           (manager.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["build"] as? String == build {
            return
        }
        try await approval.activate(Self.providerID, onApproval: onApproval)
        let saved = manager ?? NETunnelProviderManager()
        let configuration = NETunnelProviderProtocol()
        configuration.providerBundleIdentifier = Self.providerID
        configuration.serverAddress = "Regional VPN"
        configuration.providerConfiguration = ["build": build]
        configuration.includeAllNetworks = true
        saved.protocolConfiguration = configuration
        saved.localizedDescription = "Regional VPN"
        saved.isEnabled = true
        saved.isOnDemandEnabled = false
        try await saved.saveToPreferences()
        try await saved.loadFromPreferences()
        manager = saved
    }

    func start(_ configuration: TunnelStart) async throws {
        try configuration.validate()
        guard let session = manager?.connection as? NETunnelProviderSession else { throw NativeVPNError.startFailed }
        if needsStop { try await stop() }
        let payload = try JSONEncoder().encode(configuration)
        try session.startTunnel(options: [TunnelStart.option: payload as NSData])
        for _ in 0..<80 {
            if session.status == .connected {
                currentStart = configuration
                return
            }
            if session.status == .invalid { break }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw NativeVPNError.startFailed
    }

    func stop() async throws {
        if needsStop { manager?.connection.stopVPNTunnel() }
        for _ in 0..<60 {
            if !needsStop {
                currentStart = nil
                return
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw NativeVPNError.stopFailed
    }
}
