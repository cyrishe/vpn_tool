import SwiftUI
import RegionalVPNClientCore

@MainActor
final class AppModel: ObservableObject {
    @Published var email = ""
    @Published var password = ""
    @Published var regions: [LogicalRegion] = []
    @Published var selectedRegion = ""
    @Published var user: User?
    @Published var busy = false
    @Published var errorMessage: String?
    @Published var connectedRegion: String?
    private let api: ControlPlaneClient
    private let driver: MockTunnelDriver
    private let coordinator: ConnectionCoordinator
    private let identity = DeviceIdentityProvider()
    private var token: String?
    private var device: Device?

    init() {
        let address = ProcessInfo.processInfo.environment["VPN_CONTROL_PLANE_URL"]
            ?? "http://127.0.0.1:8000"
        api = ControlPlaneClient(baseURL: URL(string: address) ?? URL(string: "http://127.0.0.1:8000")!)
        driver = MockTunnelDriver()
        coordinator = ConnectionCoordinator(api: api, driver: driver)
    }

    func login() async {
        busy = true
        errorMessage = nil
        defer { busy = false }
        do {
            let response = try await api.login(email: email, password: password)
            let fetched = try await api.regions(accessToken: response.accessToken)
            let deviceId = identity.clientDeviceId()
            let registered = try await api.registerDevice(
                accessToken: response.accessToken, clientDeviceId: deviceId,
                name: identity.deviceName(), tunnelPublicKey: "mock-\(deviceId)"
            )
            token = response.accessToken
            device = registered
            regions = fetched
            selectedRegion = fetched.first(where: \.isAvailable)?.code ?? ""
            user = response.user
            password = ""
        } catch { errorMessage = error.localizedDescription }
    }

    func connect() async {
        guard let token, let device else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        do {
            try await coordinator.connect(token: token, deviceId: device.id, region: selectedRegion)
            connectedRegion = selectedRegion
        } catch { errorMessage = error.localizedDescription }
    }

    func disconnect() async {
        guard let token, let device else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        await driver.disconnect()
        connectedRegion = nil
        do {
            _ = try await api.disconnectDevice(accessToken: token, deviceId: device.id)
        } catch { errorMessage = error.localizedDescription }
    }

    func logout() async {
        await disconnect()
        guard errorMessage == nil else { return }
        token = nil
        device = nil
        user = nil
        regions = []
    }
}

@main
struct RegionalVPNApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Regional VPN") {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Image(systemName: "network").font(.title2).foregroundStyle(.teal)
                    Text("Regional VPN").font(.title2.bold())
                    Spacer()
                    if model.busy { ProgressView().controlSize(.small) }
                }
                Divider()
                if let user = model.user {
                    HStack {
                        Text(user.email).foregroundStyle(.secondary)
                        Spacer()
                        Button { Task { await model.logout() } } label: {
                            Image(systemName: "rectangle.portrait.and.arrow.right")
                        }.help("退出账号")
                    }
                    Label(model.connectedRegion == nil ? "未连接" : "模拟连接已就绪",
                          systemImage: model.connectedRegion == nil ? "circle" : "checkmark.circle.fill")
                        .foregroundStyle(model.connectedRegion == nil ? Color.secondary : Color.green)
                    if model.regions.isEmpty {
                        ContentUnavailableView("暂无可用地域", systemImage: "globe")
                    } else {
                        Picker("地域", selection: $model.selectedRegion) {
                            ForEach(model.regions) { region in
                                Text(region.name + (region.isAvailable ? "" : " · 暂不可用"))
                                    .tag(region.code).disabled(!region.isAvailable)
                            }
                        }
                        HStack {
                            Button(model.connectedRegion == nil ? "连接" : "切换地域") {
                                Task { await model.connect() }
                            }.buttonStyle(.borderedProminent)
                                .disabled(model.selectedRegion.isEmpty)
                            Button("断开") { Task { await model.disconnect() } }
                                .disabled(model.connectedRegion == nil)
                        }
                    }
                } else {
                    TextField("邮箱", text: $model.email).textContentType(.username)
                    SecureField("密码", text: $model.password).textContentType(.password)
                    Button("登录") { Task { await model.login() } }
                        .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                        .disabled(model.email.isEmpty || model.password.isEmpty)
                }
                if let message = model.errorMessage {
                    Text(message).foregroundStyle(.red).font(.callout).textSelection(.enabled)
                }
                Spacer(minLength: 0)
                Text("开发预览 · 模拟隧道").font(.caption).foregroundStyle(.secondary)
            }
            .padding(24).frame(minWidth: 380, idealWidth: 440, minHeight: 340)
            .disabled(model.busy)
        }.defaultSize(width: 440, height: 380)
    }
}
