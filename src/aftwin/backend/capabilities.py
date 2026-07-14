"""Backend capability declarations used by profile preflight."""

from enum import StrEnum


class BackendCapability(StrEnum):
    """One verifiable runtime capability a platform backend provides."""

    BGP_IPV4_UNICAST = "bgp-ipv4-unicast"
    ECMP_MULTIPATH = "ecmp-multipath"
    VRF_ENDPOINT = "vrf-endpoint"
    BGP_OBSERVED_STATE = "bgp-observed-state"
    ROUTE_OBSERVED_STATE = "route-observed-state"
    PING_PROBE = "ping-probe"
    BATFISH_ASSURANCE = "batfish-assurance"
