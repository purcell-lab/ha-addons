# Upstream and provenance

- **Software:** [Open Dynamic Export](https://github.com/longzheng/open-dynamic-export)
  by Long Zheng, MIT licence (`/usr/share/doc/open-dynamic-export/LICENSE`
  in the image).
- **Version:** v0.20.0, commit `bc807abbc4c58be3294257ee76f0348dc87c4945`.
  The build fetches exactly that commit and checks it; dependencies come
  from upstream's `pnpm-lock.yaml` (`--frozen-lockfile`).
- **Base image:** `node:24-alpine3.22`, pinned by index digest in the
  Dockerfile.

## Changes to upstream

`ingress.patch` is the only source change. It lets the web UI work under
Home Assistant Ingress, which serves it below `/api/hassio_ingress/<token>/`:

- `src/ui/ingress.ts` (new) detects that prefix in the browser;
- the TanStack router gets it as `basepath`, and the API client as
  `baseUrl`, so routes, NextUI links and API calls stay inside Ingress;
- Vite builds with relative asset URLs, and `index.html` icons are
  relative;
- the `/api` docs redirect and the Redoc spec URL are relative.

Without a prefix (the optional LAN port) the UI behaves as upstream. The
server, control logic and CSIP-AUS client are unchanged.

## This App's own code

`rootfs/opt/ode-ha/run.mjs` maps the App options to ODE's environment and
config directory and runs `node dist/app.js`. The rotating log files ODE
writes under `./logs` go to `/tmp` (not persisted or backed up); its
stdout log is in the Home Assistant App log.

## Credit

The idea of packaging ODE as a Home Assistant App, and of making its UI
work under Ingress, follows
[Stuart0411/Open-Dynamic-Export-Home-Assistant-Addon](https://github.com/Stuart0411/Open-Dynamic-Export-Home-Assistant-Addon)
and the discussion in
[open-dynamic-export#63](https://github.com/longzheng/open-dynamic-export/issues/63).
That repository has no licence, so none of its code is used here; the
launcher and patch were written independently. Its CSIP-AUS onboarding
workarounds (an empty DER list and a rejected connection point
registration) are not included; report such issues upstream.
