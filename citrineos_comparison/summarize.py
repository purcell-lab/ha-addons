"""Render a bounded comparison from completed reports; fail on missing evidence."""
import json
from pathlib import Path
import sys

def summarize(directory, pins):
    reports = {}
    for version in ("release", "next"):
        runtime = json.loads((directory / version / "runtime.json").read_text())
        static = json.loads((directory / version / "schema.json").read_text())
        assert runtime["commit"] == static["commit"] == pins[version]["commit"]
        assert runtime["station_commands"] == 0
        assert runtime["deployment_allowed"] is False
        assert runtime["scope"] == "compiled_components_with_inert_handlers"
        reports[version] = (runtime, static)
    columns = []
    for version in ("release", "next"):
        runtime, static = reports[version]
        columns.append([
            runtime["legacy_ping_registered"],
            runtime["tariff_read_registered"],
            runtime["inline"]["compilation"]["status"],
            runtime["shared"]["compilation"]["status"],
            static["staged_query_fields_present"],
            static["evse_deactivation_uses_database_key_source_pattern"],
            runtime["staleness"]["helper_checks_passed"],
        ])
    labels = [
        "Legacy HA ping registered", "Tariff read route registered",
        "Inline-schema component compilation", "Shared-schema component compilation",
        "Staged HA query fields present (static)", "EVSE database-key fix pattern (static)",
        "Command-expiry helper checks pass",
    ]
    lines = [
        "# CitrineOS: pinned release versus next comparison", "",
        "These are CI component and static-source checks, not a live server or charger acceptance test.", "",
        f"Release: `{pins['release']['commit']}`. Next: `{pins['next']['commit']}`.", "",
        "| Check | v2.0.1 | Pinned next |", "| --- | --- | --- |",
    ]
    for label, a, b in zip(labels, *columns):
        lines.append(f"| {label} | {a} | {b} |")
    lines.extend(["", "## Interpretation", "",
        "A green workflow means the comparison completed and its invariants passed. "
        "It does not authorise deployment or require either upstream schema mode to pass.",
        "",
        "Shared-schema results use the compiled API components and upstream AJV but do not "
        "initialise the complete server, Swagger UI or authentication stack. Failures are "
        "component-harness findings, not proof of a production default-mode boot failure.",
        "",
        "Expiry tests exercise the deadline helper only. They do not prove broker TTL, "
        "dead-letter delivery, reconnect behaviour or station acceptance.",
        "",
        "No full server, database, broker, migration, HA instance or charger was started. "
        "Both existing staged PRs and all deployed versions remain unchanged.",
        "",
        "## Evidence", "",
        f"- [Release source](https://github.com/citrineos/citrineos-core/tree/{pins['release']['commit']})",
        f"- [Pinned next source](https://github.com/citrineos/citrineos-core/tree/{pins['next']['commit']})",
        f"- [Staged client source](https://github.com/purcell-lab/CitrineOS-HA-Integration/tree/{pins['staged_client_commit']})",
        "- The artifact includes both raw runtime reports and static-schema reports.",
    ])
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    directory = Path(sys.argv[1])
    pins = json.loads(Path(__file__).with_name("pins.json").read_text())
    output = summarize(directory, pins)
    (directory / "comparison.md").write_text(output)
    print(output)
