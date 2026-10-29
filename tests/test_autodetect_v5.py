"""valeronlabs#5: vendor auto-detect in the guided flow.

Cisco `vlan N / name X` is not ArubaOS; IOS-XE switch vs router follows the
content; NX-OS (and Junos SRX) are reported as unsupported. Synthetic
snippets only, addresses from RFC 5737 / RFC 1918.
"""

import pytest

from netconverter_cli.guided import guess_vendor, unsupported_vendor

CANDIDATES = ["cisco_asa", "fortinet", "palo_alto_xml", "aruba_cx_switch", "aruba_os_switch",
              "cisco_ios_xe_router", "cisco_ios_xe_switch", "juniper_junos_router"]

IOSXE_SWITCH = """Building configuration...
version 17.6
hostname SW-ACCESS-1
vlan 10
 name USERS
vlan 20
 name VOICE
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
"""
# No header lines: only the VLAN block and switchports tell what it is.
IOSXE_SWITCH_BARE = """hostname SW-DIST-2
spanning-tree mode rapid-pvst
vlan 30
 name SERVERS
interface TenGigabitEthernet1/1/1
 switchport mode trunk
"""
IOSXE_ROUTER = """Building configuration...
version 17.3
hostname RTR-EDGE-1
interface GigabitEthernet1
 ip address 192.0.2.1 255.255.255.0
ip route 0.0.0.0 0.0.0.0 192.0.2.254
"""
NXOS = """!Command: show running-config
version 9.3(8) Bios:version 05.45
hostname NX-CORE-1
feature interface-vlan
feature lacp
vlan 10
  name SERVERS
interface Ethernet1/1
  switchport
"""
ARUBA_OS_SWITCH = """; J9729A Configuration Editor; Created on release #WC.16.10.0010
hostname "ARUBA-SW-1"
vlan 10
   name "USERS"
   untagged 1-24
   ip address 10.0.10.1 255.255.255.0
   exit
"""
ARUBA_OS_SWITCH_NO_HEADER = """hostname "ARUBA-SW-2"
ip routing
vlan 20
   name "VOICE"
   tagged 25-26
   exit
"""
JUNOS_SRX = """set system host-name SRX-EDGE-1
set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.10/24
set security zones security-zone trust interfaces ge-0/0/1.0
set security policies from-zone trust to-zone untrust policy allow-web match application junos-http
"""


@pytest.mark.parametrize("text,expected", [
    (IOSXE_SWITCH, "cisco_ios_xe_switch"),
    (IOSXE_SWITCH_BARE, "cisco_ios_xe_switch"),
    (IOSXE_ROUTER, "cisco_ios_xe_router"),
    (ARUBA_OS_SWITCH, "aruba_os_switch"),
    (ARUBA_OS_SWITCH_NO_HEADER, "aruba_os_switch"),
])
def test_detected_vendor(text, expected):
    assert guess_vendor(text, CANDIDATES) == expected


def test_switch_falls_back_to_the_offered_ios_xe_code():
    """A server that offers only the router code still gets a Cisco suggestion, never Aruba."""
    assert guess_vendor(IOSXE_SWITCH, ["aruba_os_switch", "cisco_ios_xe_router"]) == "cisco_ios_xe_router"


@pytest.mark.parametrize("text,name", [(NXOS, "Cisco NX-OS"), (JUNOS_SRX, "Juniper SRX")])
def test_unsupported_platforms_are_named_not_guessed(text, name):
    assert unsupported_vendor(text, CANDIDATES) == name
    assert guess_vendor(text, CANDIDATES) is None


def test_a_server_that_offers_the_platform_is_not_overruled():
    assert unsupported_vendor(NXOS, [*CANDIDATES, "cisco_nxos_switch"]) is None


def test_supported_files_are_not_flagged_unsupported():
    for text in (IOSXE_SWITCH, IOSXE_ROUTER, ARUBA_OS_SWITCH):
        assert unsupported_vendor(text, CANDIDATES) is None


def test_guided_flow_says_nxos_is_unsupported(tmp_path):
    from types import SimpleNamespace

    from netconverter_cli.catalog import Catalog
    from netconverter_cli.guided import Guided
    from netconverter_cli.workspace import Workspace

    (tmp_path / "nx-core.cfg").write_text(NXOS)
    vendors = [{"code": code, "name": code, "device_type": "switch", "roles": ["source"], "input": "text"}
               for code in CANDIDATES]
    catalog = Catalog.from_external({"job_types": ["validate"], "vendors": vendors, "paths": [],
                                     "limits": {"max_config_bytes": 5 * 1024 * 1024}})
    workspace = Workspace(tmp_path)
    controller = SimpleNamespace(workspace=workspace, catalog=catalog, max_bytes=lambda: 5 * 1024 * 1024,
                                 state={}, external=True)
    notes, asked = [], []
    app = SimpleNamespace(controller=controller, write_note=notes.append, show_error=notes.append,
                          ask_choice=lambda title, choices, callback, highlight=0: asked.append((choices, highlight)))
    guided = Guided(app)
    guided.job_type = "validate"
    guided.file_chosen(tmp_path / "nx-core.cfg")
    assert any("Cisco NX-OS" in note and "not supported" in note for note in notes)
    choices, _ = asked[-1]
    assert not any("detected" in label for label, _ in choices)
