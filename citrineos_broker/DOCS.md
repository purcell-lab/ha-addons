# CitrineOS lab broker

Dedicated pinned RabbitMQ 3.13.7 transport. Management plugins and host ports
are disabled. Data persists at `/data/mnesia`, with a stable Erlang node name.
Configure a generated 64-hex password, also supplied to the server App.
This is independent of Home Assistant's existing MQTT broker. See the sibling
`citrineos_server/DOCS.md` for startup, backup, isolation and rollback.
