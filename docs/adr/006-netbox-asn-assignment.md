# ADR-006: Associate Devices with Native ASN Objects

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

NetBox provides a native `ipam.asn` model, but the project also needs an
explicit, queryable association between each fabric router and its local ASN.
Duplicating the ASN as an unconstrained integer on the device would weaken the
source-of-truth model.

## Decision

Create a Device custom field named `bgp_asn` with type `object` and related
object type `ipam.asn`. The fixture seeder creates native ASN objects first and
stores their object IDs in each network device's `bgp_asn` field.

Compute endpoints may omit `bgp_asn`. Fabric spines and leaves require it at
the policy layer introduced in M2.

## Consequences

- ASN uniqueness and metadata remain owned by NetBox IPAM.
- Device-to-ASN intent is directly available through REST and GraphQL custom
  field data.
- The adapter must resolve the custom-field object ID against fetched ASN
  records.
- Environments adopting aftwin must create this custom field; the development
  seeder creates it idempotently.

## References

- [NetBox custom object fields](https://netbox.readthedocs.io/en/stable/customization/custom-fields/#custom-object-fields)
- [NetBox ASN model](https://netbox.readthedocs.io/en/stable/models/ipam/asn/)
