# Authentication session recovery release — 15 October 2026

Released **2.6.4**, Git tag `v2.6.4`, from source commit
`0fc2c8adb8db9a0427cd483d549e8164c38b79a5`.

## Changes

- Verify the session cookie once per protected request and share that result
  between authentication, refresh, and view-cache identity.
- Clear rejected host-only session cookies at `Path=/`, retaining redirects and
  API 401 responses. Allow logout to clear invalid cookies without refreshing them.
- Serve the login page's exact `extension_handoff.js` asset before authentication.
- Preserve successful OTP cookie issuance and strict signature, algorithm,
  expiration, and token-type checks. Bearer-authenticated cache keys follow the
  authenticated user rather than a separate session cookie.

The original incident findings and remaining attribution uncertainty are in
[the investigation](2026-10-14-auth-signature-investigation.md). This release
does not establish which key signed the incident cookie or attribute it to a user.

## Validation

- Full Python suite on the updated checkout and again inside the published
  Python 3.11 release image: **105 tests run, 100 passed, five disposable-MariaDB
  tests skipped**. The image run disabled networking and used a synthetic key.
- Eleven focused authentication regression tests cover signature failure,
  expiry, wrong algorithm/type, cookie cleanup, one verification per request,
  refresh, logout, OTP replacement, and bearer identity/cache isolation.
- All **six Chromium extension browser checks passed**, including handoff
  storage/consumption, rejection/expiry, region capture, and failure recovery.
- Live OTP delivery to the account owner succeeded. Browser verification reached
  the authenticated home page showing `v2.6.4`. Logout returned to sign-in, and
  a subsequent visit to `/` required login again.
- Production HTTP checks confirmed bad-cookie redirect/401 and cleanup,
  invalid-cookie logout, public login/handoff JavaScript with an invalid cookie,
  and continued protection of other static assets.
- A private synthetic signature probe created before recreation still accessed
  a protected static asset after deployment; the same asset without a cookie
  redirected to login. The probe was then removed.
- Deployed application, auth helper, login template, and handoff-script hashes
  match the committed and tested release.
- A live capture through an installed extension was not completed: the connected
  Chrome profile did not expose Send to Scrappl. Extension evidence consists of
  the browser regression checks and deployed asset/unauthenticated-route checks.

## Production preservation and rollback

Both web and cache-worker are healthy on 2.6.4. All environment variables in
both containers are exactly equal to their pre-release values, including the
web signing secret. No signing-key or environment configuration changes were made.
The final check found zero restarts, tracebacks, or HTTP 5xx responses. The two
signature-error writes match the two deliberately wrong-key smoke requests.

Deployment supplied the existing interpolation values explicitly to Compose
after checking the rendered service environments against every running service.
Only web and cache-worker were recreated. Database, Redis, and phpMyAdmin
container identities remained unchanged; mounts, ports, and networks were preserved.
Portainer's maintained `docker-compose.yml` and saved `stack.env` are
byte-for-byte unchanged.

The previous image is retained as `staugustine1/scrapbook:rollback-2.6.3`.
Private rollback/environment snapshots are in `/tmp/scrappl-release-2.6.4` on
the production host, with directory mode 0700 and file mode 0600. A rollback
must supply those exact existing variables; the compose file alone is insufficient.

Published `v2.6.4`, `2.6.4`, and `latest` images support `linux/amd64` and
`linux/arm64`. Registry manifest:
`sha256:e6dc291ddfc14e760296db349138c618be4a6581e6d711cbac02a793575e7111`.

The [tag-triggered GitHub build](https://github.com/isaaclee0/scrapbook/actions/runs/38658879293)
again failed at Docker Hub login. The established local multi-architecture build
successfully published this release, and deployment verified its digest and
source revision before rollout.
