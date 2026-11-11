# Development Plan

## Product scope

Personal regional VPN, planned subscription CNY 10-20/month. Short connections
for publishing workflows. Regions are server-managed; adding a region must not
require a client release. Shared gateways initially; spot instances later.
VPN changes network egress, not GPS. Validate platform-visible location separately.

## M1: Visible application trunk (in progress)

Implemented: development-only same-origin browser preview and disconnect API.
Browser verified: wrong password, login, server-provided regions, Shanghai
connection, Beijing switch, disconnect. Backend: 8 tests passed.
Native app/coordinator sources restored, but native build remains blocked by the
installed Command Line Tools PackageDescription linker/interface mismatch.
Swift tests have not executed; native client is not accepted as complete.
Preview screenshot: [M1](m1-preview.png).

- Restore missing macOS executable and buildable package.
- Login against the real API; fetch authorized regions dynamically.
- Register a device, prepare/confirm region switches, disconnect and release state.
- Show busy/error/empty states and explicitly label simulated connections.
- Accept: demo login, two region switches, disconnect, invalid login, rollback.
- Tunnel is simulated; no claim of IP/DNS/routing changes.

## M2: Real regional gateway

Server module implemented (not deployed): local region/gateway/user enrollment CLI,
gateway-scoped credentials, polling/acknowledgement API, real wg command agent,
short peer leases, Linux bootstrap and systemd watchdog unit. Protocol/command
tests run locally; actual Linux forwarding and native-client egress are not yet
verified. See [core-server.md](core-server.md). Prioritize this module over preview UI.

- Linux WireGuard bootstrap and narrowly privileged gateway agent.
- Device-generated keys, collision-free address allocation, user isolation.
- Reconcile peers incrementally; report readiness before returning a profile.
- Expire pending operations; serialize switches per device and reserve capacity.
- Accept: two accounts use two gateways, cannot reach each other or gateway admin
  networks, revoked keys stop working. Verify IPv4, IPv6, DNS and measured egress.

## M3: Real macOS connection and dynamic provisioning

Ubuntu center migration complete: HTTPS on 1.15.138.37, fixed SQLite path,
dedicated systemd user, direct local agent sync, daily online backup and restored
backup integrity verified. Mac center and reverse SSH tunnel retired. Native GUI,
IPv6 route handling and phone clients remain open. See ubuntu-deployment.md.

- Signed Xcode app + Packet Tunnel Extension + WireGuardKit.
- Reuse API/core models; private keys in Keychain, reconnect and rollback.
- Minimal admin CLI: account/expiry/region grants, region and gateway onboarding.
- Deploy by SSH; node identity is separate from region name and cloud IP.
- Node heartbeat timeout, spot termination/draining and replacement handling.
- Subscription expiry and device revocation enforced by gateway leases, including
  bounded behavior during control-plane outages.
- Accept: add server -> verify -> grant -> connect -> measure IP -> expire access.

## M4: Mobile and limited pilot

- Choose first phone platform from target users; share protocol, not OS tunnel code.
- Login, regions, connect/disconnect, Wi-Fi/cellular handover and background recovery.
- macOS/iOS may share Swift core; Android uses its platform tunnel library.
- Minimal operations: manual subscriptions, device revocation, gateway status.
- Accept: same account works on desktop/phone; failures and expiry are visible.

## Deferred

Payment automation, billing dashboards, cloud procurement, advanced quotas and
large node pools. Confirm commercial operating/distribution conditions before
public paid launch. Do not use a personal Tailscale account as the product backend.

## Working rule

Complete one milestone at a time; record verified behavior and limitations before
expanding. M1 is a visible workflow; M2/M3 deliver actual VPN connectivity.
