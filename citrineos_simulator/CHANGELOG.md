# Changelog

## 0.1.1

- New `archive_and_rebind` option (#29): moves `mo_store` and the destination
  binding into `/data/archive-<UTC timestamp>/`, then binds the configured
  destination. Nothing is deleted.
- The Supervisor DNS lookup is shared with the MicroOCPP Apps and no longer
  fails start-up when `/etc/resolv.conf` has no IPv4 nameserver.

## 0.1.0

- Initial dedicated CitrineOS lab charger.
