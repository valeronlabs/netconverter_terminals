# Synthetic example

`demo-asa.cfg` contains documentation-only addresses, one TCP-80 permit, an
explicit catch-all deny, a default route, and an unreferenced network object.
It is intended for upload, migration, and analysis demos; it is not a production
firewall template.

After upload and completed analysis, inspect `/unused_objects` for `DEMO_UNUSED`.
Use source `192.0.2.10`, destination `198.51.100.10`, TCP port 80 for the permit
case and port 81 for the deny case. Always inspect the returned coverage limits;
a policy finding does not prove live reachability. See the [quick start](../QUICK_START.md).
