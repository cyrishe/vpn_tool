import Foundation

@main
enum TunnelContractCheck {
    static func main() throws {
        let key = Data(repeating: 1, count: 32).base64EncodedString()
        let profile = TunnelStart(privateKey: key, serverPublicKey: key,
            endpoint: "203.0.113.12:51820", clientAddress: "10.77.0.2/32", dnsServers: ["223.5.5.5"])
        let encoded = try JSONEncoder().encode(profile)
        let decoded = try JSONDecoder().decode(TunnelStart.self, from: encoded)
        try decoded.validate()
        precondition(decoded.endpointIP == "203.0.113.12")
        for (endpoint, address, dns, serverKey) in [
            ("203.0.113.12:0", "10.77.0.2/32", ["223.5.5.5"], key),
            ("203.0.113.12:51820", "10.77.0.2/0", ["223.5.5.5"], key),
            ("203.0.113.12:51820", "192.168.0.2/32", ["223.5.5.5"], key),
            ("203.0.113.12:51820", "10.77.0.2/32", ["not-a-dns-ip"], key),
            ("203.0.113.12:51820", "10.77.0.2/32", ["223.5.5.5"], Data(repeating: 0, count: 32).base64EncodedString()),
        ] {
            let invalid = TunnelStart(privateKey: key, serverPublicKey: serverKey,
                endpoint: endpoint, clientAddress: address, dnsServers: dns)
            do {
                try invalid.validate()
                preconditionFailure("Invalid configuration accepted")
            } catch NativeVPNError.invalidProfile {}
        }
        print("Tunnel contract: round trip and 5 rejection cases passed")
    }
}
