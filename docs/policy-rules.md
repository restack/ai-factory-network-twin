# Static Policy Rule Catalog

Rule IDs are part of the public machine-readable validation contract. Existing
IDs must not be repurposed; behavioral changes require tests and release notes.

## General

| ID | Error condition |
| --- | --- |
| `GEN001` | A selected device is missing the profile's required tag. |
| `GEN002` | A spine or leaf uses an unsupported network platform. |
| `GEN003` | A spine or leaf has no native ASN association. |
| `GEN004` | A spine or leaf has no normalized loopback address. |
| `GEN005` | A link references an unknown node or interface. |
| `GEN006` | One IP is assigned to multiple interfaces. |
| `GEN007` | One ASN is assigned to multiple network devices. |
| `GEN008` | One interface terminates multiple links. |

## Plane

| ID | Error condition |
| --- | --- |
| `PLN001` | A network device is outside the profile's required planes. |
| `PLN002` | A compute/storage host interface has an invalid plane. |
| `PLN003` | Link and endpoint interface planes are inconsistent. |
| `PLN004` | A compute/storage node is missing a required plane interface. |
| `PLN005` | One compute/storage node uses the same leaf for multiple planes. |

## Clos

| ID | Error condition |
| --- | --- |
| `CLS001` | Spine inventory or a leaf's spine-neighbor set differs from policy. |
| `CLS002` | A fabric link does not connect exactly one spine and one leaf. |
| `CLS003` | A host link has invalid endpoint node/interface roles. |
| `CLS004` | A host interface does not terminate exactly one host link. |
| `CLS005` | A spine or leaf has no fabric neighbor. |

## Addressing

| ID | Error condition |
| --- | --- |
| `ADR001` | A network device lacks exactly one IPv4 `/32` loopback. |
| `ADR002` | A fabric link does not use one shared profile-sized P2P subnet. |
| `ADR003` | A host link does not use one shared profile-sized P2P subnet. |
| `ADR005` | Address pools configured for different planes overlap. |
| `ADR006` | A non-management interface address is outside its plane pools. |

`ADR004` is reserved for management-prefix advertisement. Assigned interface
data cannot prove advertisement behavior; M3 enforces this rule when generating
routing configuration and expected state, as recorded in ADR-007.

The MVP domain has no shared border-node role. Every non-management cross-plane
link therefore fails `PLN003`; management links are outside fabric-plane policy.

## Target Keys

Targets use a stable `<kind>:<key>` string:

- `fabric:<site>`
- `plane:<a|b>`
- `node:<device>`
- `interface:<device>/<interface>`
- `link:<sorted-endpoint>--<sorted-endpoint>`
- `address:<IPv4-address>`
- `asn:<decimal-ASN>`

Every finding includes severity, target, message, and a remediation hint.
Reports sort findings deterministically by severity, rule ID, and target.
