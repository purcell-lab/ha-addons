# Upstream

- **Project:** CitrineOS Operator UI, `apps/operator-ui` in
  https://github.com/citrineos/citrineos-core
- **Licence:** Apache-2.0 (`/usr/share/doc/citrineos-operator-ui/LICENSE`)
- **Pinned commit:** `4fd7599b91c2fb6e6065e7c9b94be69880cced27` (tag
  `v2.1.0`), the same release as the CitrineOS Isolated Lab server. The build
  checks the fetched commit.

## Local changes

`operator-ui.patch` (shipped in `/usr/share/doc/citrineos-operator-ui/`):

- an optional Next.js `basePath`, used with a placeholder the App's proxy
  rewrites to the Ingress prefix;
- same-origin, relative API URLs made absolute in the browser;
- an empty WebSocket URL turns GraphQL subscriptions off;
- `NEXT_PUBLIC_TRUSTED_PROXY_AUTH`: behind an authenticating reverse proxy
  the generic auth provider treats the operator as signed in, and the UI
  never asks the server for a Hasura admin secret;
- next-auth's client follows the base path.

The upstream development `.env.local` (which contains a Hasura admin
secret and admin password) is deleted before the build and is not shipped.

## Not changed

Pages, components, GraphQL queries and command payloads are upstream's.
