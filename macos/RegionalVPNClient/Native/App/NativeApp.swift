import CryptoKit
import NetworkExtension
import Security
import SwiftUI

@MainActor
final class NativeModel: ObservableObject {
    @Published var email = ""
    @Published var password = ""
    @Published var user: User?
    @Published var regions: [LogicalRegion] = []
    @Published var region = ""
    @Published var activity: String?
    @Published var message: String?
    @Published var exitIP: String?
    @Published var connectedRegion: String?
    @Published var connectedCode: String?
    @Published var needsStop = false
    private let vpn = SystemVPN()
    private let credentials = KeychainCredentialStore(service: "com.regionalvpn.native.session")
    private let identity = DeviceIdentityProvider()
    private let api: ControlPlaneClient?
    private var token: String?
    private var deviceID: String?
    private var initialized = false

    var canConnect: Bool {
        regions.contains { $0.code == region && $0.isAvailable }
            && (!needsStop || (connectedCode != nil && connectedCode != region))
    }

    init() {
        let bundle = Bundle.main
        let address = bundle.object(forInfoDictionaryKey: "RegionalVPNControlURL") as? String
        let certificateURL = bundle.url(forResource: "control", withExtension: "cer")
        let certificate = certificateURL.flatMap {
            (try? Data(contentsOf: $0)).flatMap { SecCertificateCreateWithData(nil, $0 as CFData) }
        }
        if certificateURL != nil, certificate == nil {
            api = nil
            message = "打包的中心证书无法读取。"
        } else if let address, let url = URL(string: address), url.scheme == "https", url.host != nil {
            let center = certificate.map { DirectSessionDelegate.PrivateCenter(url: url, certificate: $0) }
            api = ControlPlaneClient(baseURL: url, session: DirectSessionDelegate.make(center: center))
        } else {
            api = nil
            message = "构建时未设置 HTTPS 中心地址。"
        }
    }

    func initialize() async {
        guard !initialized else { return }
        initialized = true
        activity = "正在读取 VPN 设置…"
        defer { activity = nil }
        try? await vpn.load()
        updateStatus()
        guard let api, let saved = credentials.loadAccessToken() else { return }
        activity = "正在恢复会话…"
        do {
            let account = try await api.me(accessToken: saved)
            try await signIn(api, account: account, token: saved, remember: false)
        } catch let error as ControlPlaneError {
            if case .server(let code, _) = error, code == "invalid_token" { try? credentials.clearAccessToken() }
            else { message = error.localizedDescription }
        } catch { message = error.localizedDescription }
    }

    func updateStatus() {
        needsStop = vpn.needsStop
        if !needsStop { exitIP = nil; connectedRegion = nil; connectedCode = nil }
    }

    private func signIn(_ api: ControlPlaneClient, account: User, token: String, remember: Bool) async throws {
        let authorized = try await api.regions(accessToken: token)
        self.token = token
        self.user = account
        deviceID = UserDefaults.standard.string(forKey: "regional-vpn-native-device-\(account.id)")
        regions = authorized
        region = authorized.first(where: \.isAvailable)?.code ?? ""
        if remember { try? credentials.saveAccessToken(token) }
    }

    func login() async {
        guard activity == nil, let api else { return }
        activity = "正在登录…"
        message = nil
        defer { password = ""; activity = nil }
        do {
            let response = try await api.login(email: email, password: password)
            try await signIn(api, account: response.user, token: response.accessToken, remember: true)
        } catch { message = error.localizedDescription }
    }

    func refresh() async {
        guard activity == nil, let api, let token else { return }
        activity = "正在刷新…"
        defer { activity = nil }
        do {
            regions = try await api.regions(accessToken: token)
            if !regions.contains(where: { $0.code == region && $0.isAvailable }) {
                region = regions.first(where: \.isAvailable)?.code ?? ""
            }
            message = nil
        } catch { message = error.localizedDescription }
    }

    private func deviceKey(for account: User) throws -> Curve25519.KeyAgreement.PrivateKey {
        let store = KeychainCredentialStore(service: "com.regionalvpn.native.wireguard.\(account.id)")
        if let saved = store.loadAccessToken() {
            guard let bytes = Data(base64Encoded: saved) else { throw NativeVPNError.invalidProfile }
            return try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: bytes)
        }
        let key = Curve25519.KeyAgreement.PrivateKey()
        try store.saveAccessToken(key.rawRepresentation.base64EncodedString())
        return key
    }

    func connect() async {
        guard activity == nil, canConnect, let api, let token, let user,
              let target = regions.first(where: { $0.code == region && $0.isAvailable }) else { return }
        let previous = vpn.needsStop ? vpn.currentStart : nil
        let previousRegion = connectedRegion
        let previousCode = connectedCode
        var operationID: String?
        var touchedTunnel = false
        activity = "正在检查 VPN 设置…"
        message = nil
        defer { updateStatus(); activity = nil }
        do {
            try await vpn.configure { self.activity = "等待系统批准 VPN 扩展…" }
            activity = "正在准备\(target.name)节点…"
            let key = try deviceKey(for: user)
            let device = try await api.registerDevice(accessToken: token, clientDeviceId: identity.clientDeviceId(),
                name: identity.deviceName(), tunnelPublicKey: key.publicKey.rawRepresentation.base64EncodedString())
            deviceID = device.id
            UserDefaults.standard.set(device.id, forKey: "regional-vpn-native-device-\(user.id)")
            if !vpn.needsStop, device.activeRegionCode != nil {
                _ = try await api.disconnectDevice(accessToken: token, deviceId: device.id)
            }
            var operation = try await api.prepareSwitch(accessToken: token, deviceId: device.id,
                targetRegionCode: target.code, idempotencyKey: UUID().uuidString)
            operationID = operation.operationId
            let deadline = ContinuousClock.now + .seconds(30)
            while operation.status == "prepared", operation.profile == nil, ContinuousClock.now < deadline {
                try await Task.sleep(for: .milliseconds(500))
                operation = try await api.switchStatus(accessToken: token, operationId: operation.operationId)
            }
            guard operation.status == "prepared", let profile = operation.profile, profile.regionCode == target.code else {
                throw NativeVPNError.invalidProfile
            }
            let start = TunnelStart(privateKey: key.rawRepresentation.base64EncodedString(),
                serverPublicKey: profile.serverPublicKey, endpoint: profile.endpoint,
                clientAddress: profile.clientAddress, dnsServers: profile.dnsServers)
            try start.validate()
            guard let expected = start.endpointIP else { throw NativeVPNError.invalidProfile }
            activity = "正在连接并验证出口…"
            touchedTunnel = true
            exitIP = nil
            connectedRegion = nil
            connectedCode = nil
            try await vpn.start(start)
            let ip = try await ExitCheck.verify(expected)
            let confirmation: SwitchOperation
            do {
                confirmation = try await api.confirmSwitch(accessToken: token, operationId: operation.operationId, success: true)
            } catch {
                guard let state = try? await api.switchStatus(accessToken: token, operationId: operation.operationId) else {
                    throw NativeVPNError.confirmationUnknown
                }
                confirmation = state
            }
            guard confirmation.status == "committed" else { throw NativeVPNError.confirmationUnknown }
            exitIP = ip
            connectedRegion = target.name
            connectedCode = target.code
        } catch {
            let rollback: SwitchOperation?
            if let operationID {
                rollback = try? await api.confirmSwitch(accessToken: token, operationId: operationID, success: false)
            } else { rollback = nil }
            if touchedTunnel {
                try? await vpn.stop()
                if rollback?.status == "rolled_back", let previous, let expected = previous.endpointIP {
                    do {
                        try await vpn.start(previous)
                        exitIP = try await ExitCheck.verify(expected)
                        connectedRegion = previousRegion
                        connectedCode = previousCode
                    } catch { try? await vpn.stop() }
                }
                if exitIP == nil, let deviceID { _ = try? await api.disconnectDevice(accessToken: token, deviceId: deviceID) }
            }
            message = error.localizedDescription
        }
    }

    func disconnect() async {
        guard activity == nil else { return }
        activity = "正在断开…"
        message = nil
        defer { updateStatus(); activity = nil }
        do { try await vpn.stop() }
        catch { message = error.localizedDescription; return }
        if let api, let token, let deviceID {
            do { _ = try await api.disconnectDevice(accessToken: token, deviceId: deviceID) }
            catch { message = "本机已断开，中心暂未确认释放。" }
        }
    }

    func logout() {
        guard !needsStop, activity == nil else { return }
        try? credentials.clearAccessToken()
        token = nil
        user = nil
        deviceID = nil
        regions = []
        message = nil
    }
}

@main
@MainActor
struct NativeApp: App {
    @StateObject private var model = NativeModel()

    var body: some Scene {
        WindowGroup("Regional VPN") {
            VStack(alignment: .leading, spacing: 16) {
                Label("Regional VPN", systemImage: "network")
                    .font(.title2.weight(.semibold))
                Divider()
                if let user = model.user {
                    Text(user.email).foregroundStyle(.secondary)
                    Label(model.connectedRegion.map { "已连接 · \($0)" } ?? (model.needsStop ? "系统隧道运行中" : "未连接"),
                          systemImage: model.exitIP == nil ? "circle" : "checkmark.circle.fill")
                        .foregroundStyle(model.exitIP == nil ? Color.secondary : Color.green)
                    LabeledContent("出口 IP", value: model.exitIP ?? "—")
                    if model.regions.isEmpty {
                        Text("暂无已开通地域").foregroundStyle(.secondary)
                    } else {
                        Picker("地域", selection: $model.region) {
                            if model.region.isEmpty { Text("暂无可用地域").tag("") }
                            ForEach(model.regions) { region in
                                Text(region.name + (region.isAvailable ? "" : " · 暂不可用")).tag(region.code)
                            }
                        }
                    }
                    HStack {
                        Button(model.needsStop ? "切换地域" : "连接") { Task { await model.connect() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(!model.canConnect)
                        if model.needsStop { Button("断开") { Task { await model.disconnect() } } }
                        Spacer()
                        Button { Task { await model.refresh() } } label: { Image(systemName: "arrow.clockwise") }
                            .help("刷新地域").accessibilityLabel("刷新地域")
                        Button { model.logout() } label: { Image(systemName: "rectangle.portrait.and.arrow.right") }
                            .help("退出账号").accessibilityLabel("退出账号").disabled(model.needsStop)
                    }
                } else {
                    TextField("邮箱", text: $model.email).textContentType(.username)
                    SecureField("密码", text: $model.password).textContentType(.password)
                    HStack {
                        Button("登录") { Task { await model.login() } }.buttonStyle(.borderedProminent)
                            .keyboardShortcut(.defaultAction).disabled(model.email.isEmpty || model.password.isEmpty)
                        if model.needsStop { Button("断开 VPN") { Task { await model.disconnect() } } }
                    }
                }
                if let activity = model.activity {
                    HStack { ProgressView().controlSize(.small); Text(activity).foregroundStyle(.secondary) }
                }
                if let message = model.message {
                    Text(message).font(.callout).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(24)
            .frame(minWidth: 420, idealWidth: 460, minHeight: 340)
            .disabled(model.activity != nil)
            .task { await model.initialize() }
            .onReceive(NotificationCenter.default.publisher(for: .NEVPNStatusDidChange)) { _ in model.updateStatus() }
        }.defaultSize(width: 460, height: 360)
    }
}
