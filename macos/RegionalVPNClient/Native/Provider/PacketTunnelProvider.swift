import Foundation
import NetworkExtension
import WireGuardKit

final class PacketTunnelProvider: NEPacketTunnelProvider {
    private lazy var adapter = WireGuardAdapter(with: self) { _, _ in }

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        do {
            guard let data = options?[TunnelStart.option] as? Data, data.count <= 4096 else {
                throw NativeVPNError.missingOptions
            }
            let start = try JSONDecoder().decode(TunnelStart.self, from: data)
            try start.validate()
            guard let privateKey = PrivateKey(base64Key: start.privateKey),
                  let publicKey = PublicKey(base64Key: start.serverPublicKey),
                  let endpoint = Endpoint(from: start.endpoint),
                  let address = IPAddressRange(from: start.clientAddress),
                  let v6Address = IPAddressRange(from: "fd77:7265:6769::2/128"),
                  let v4Default = IPAddressRange(from: "0.0.0.0/0"),
                  let v6Default = IPAddressRange(from: "::/0") else {
                throw NativeVPNError.invalidProfile
            }
            var interface = InterfaceConfiguration(privateKey: privateKey)
            interface.addresses = [address, v6Address]
            interface.dns = start.dnsServers.compactMap { DNSServer(from: $0) }
            var peer = PeerConfiguration(publicKey: publicKey)
            peer.endpoint = endpoint
            peer.allowedIPs = [v4Default, v6Default]
            peer.persistentKeepAlive = 25
            adapter.start(tunnelConfiguration: TunnelConfiguration(
                name: "Regional VPN", interface: interface, peers: [peer]
            )) { error in
                completionHandler(error == nil ? nil : NativeVPNError.startFailed)
            }
        } catch {
            completionHandler(error)
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        adapter.stop { _ in completionHandler() }
    }
}
