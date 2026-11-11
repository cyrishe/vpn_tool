import Foundation
import Network

struct TunnelStart: Codable, Sendable {
    static let option = "regional-vpn-start-v1"

    let privateKey: String
    let serverPublicKey: String
    let endpoint: String
    let clientAddress: String
    let dnsServers: [String]

    var endpointIP: String? {
        let parts = endpoint.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, let port = UInt16(parts[1]), port > 0,
              let ip = IPv4Address(String(parts[0])) else { return nil }
        return ip.debugDescription
    }

    func validate() throws {
        let address = clientAddress.split(separator: "/", omittingEmptySubsequences: false)
        guard endpointIP != nil, address.count == 2, address[1] == "32",
              let ip = IPv4Address(String(address[0])),
              Array(ip.rawValue.prefix(2)) == [10, 77],
              !dnsServers.isEmpty, dnsServers.count <= 4,
              dnsServers.allSatisfy({ IPv4Address($0) != nil }),
              Self.isKey(privateKey), Self.isKey(serverPublicKey) else {
            throw NativeVPNError.invalidProfile
        }
    }

    private static func isKey(_ value: String) -> Bool {
        guard let key = Data(base64Encoded: value) else { return false }
        return key.count == 32 && key.contains { $0 != 0 }
    }
}

enum NativeVPNError: LocalizedError {
    case invalidProfile, missingOptions, extensionRestart
    case startFailed, stopFailed, egressMismatch, confirmationUnknown

    var errorDescription: String? {
        switch self {
        case .invalidProfile: return "节点返回了无效的连接配置。"
        case .missingOptions: return "请在 Regional VPN 中重新连接。"
        case .extensionRestart: return "系统要求重启后才能启用新版 VPN 扩展。"
        case .startFailed: return "VPN 没有成功启动，请检查系统批准状态。"
        case .stopFailed: return "VPN 尚未断开，请重试或在系统设置中关闭。"
        case .egressMismatch: return "未验证到该节点的出口 IP，连接没有完成。"
        case .confirmationUnknown: return "中心未确认连接，已尝试停止隧道。"
        }
    }
}
