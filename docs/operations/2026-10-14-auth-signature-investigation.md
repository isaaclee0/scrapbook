# Authentication signature failures — 14 October 2026

The most likely immediate cause was a browser repeatedly sending a stale or foreign `session_token` JWT whose signature did not match the current web process's signing key. A token whose signed bytes were altered would produce the same error. The investigation confirms rejection of the cookie and the mechanism behind the burst; it does **not** establish that the 13 October deployment changed the key, that the cookie belonged to Shelley, or which key originally signed it.

Two application defects amplify this situation: each protected cookie request verifies the JWT twice, and the public login page requests an authentication-protected `extension_handoff.js`. Failed cookies are retained. OTP login can replace the cookie and restore access, matching the reported recovery.

This report records the investigation against release 2.6.1 at commit `207c56cd0`; source line references below describe that historical version. At investigation time, application code and production configuration were not changed. Production inspection was read-only; reproduction used synthetic credentials and mocked DB/Redis/email dependencies locally. No secret values or complete tokens are included here. The subsequent 2.6.4 correction implements the cookie recovery, shared verification, and public handoff-script changes recommended below, with focused regression tests in `tests/test_auth_sessions.py`.

**Confirmed incident sequence (UTC)**

I read the raw web-container logs for 05:46:45–05:48:15, retaining only error categories and request/status metadata. The relevant sequence is:

| Initial request | Result | Subsequent login-page asset request | Signature-error writes |
| --- | --- | --- | --- |
| 05:46:53 `GET /` | 302 to login | `GET /static/js/extension_handoff.js` → 302 to login | 2 + 2 |
| 05:47:01 `GET /` | 302 to login | Same script → 302 to login | 2 + 2 |
| 05:47:09 `GET /` | 302 to login | Same script → 302 to login | 2 + 2 |
| 05:47:14 `GET /board/369` | 302 to login | Same script → 302 to login | 2 + 2 |
| 05:47:25 OTP email, then `POST /auth/login` | 200 | — | 0 |
| 05:47:54 `POST /auth/login`, then `GET /` | Both 200 | Handoff script → 200 | 0 |

These eight protected requests account for all **16 signature-error writes** in that window. Each redirect is followed by `GET /auth/login` returning 200. The second login-page GET in each cycle is consistent with following the script's redirect; it is not another OTP submission. The browser receives login HTML where JavaScript was requested. This does not itself create an infinite navigation loop.

The raw window had no byte-identical duplicate records. The paired error writes have separate timestamps and are explained by two application calls, without needing a log-export duplication hypothesis. Other copied or aggregated logs may still duplicate records. Do not interpret 16 lines as 16 authentication attempts. Access entries share one logged client address, but a proxy address and timing do not identify a user. Shelley's association remains inferred.

**Exact error and reachable paths**

[auth_utils.py:78](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:78) calls `jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])`. The handler at [auth_utils.py:89](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:89) prints `Invalid token: {e}`. Production uses PyJWT 2.8.0; its signature verifier raises `InvalidSignatureError("Signature verification failed")` when cryptographic verification fails. This is the sole application source of the exact message.

The current application's three direct `verify_token` call sites all expect `type='session'`: user resolution at [app.py:541](/Users/isaaclee/scrapbook/scrapbook/app.py:541), session refresh through [auth_utils.py:123](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:123), and view-cache identity at [app.py:113](/Users/isaaclee/scrapbook/scrapbook/app.py:113). A suitably formed foreign or altered JWT in the cookie can fail before its type is known; the error alone does not authenticate any payload claims.

The global hook at [app.py:595](/Users/isaaclee/scrapbook/scrapbook/app.py:595) checks the cookie on every non-exempt request. This includes `/`, boards, `/api/*`, `/cached/*`, most static files, `/auth/logout`, `/auth/verify`, and even unmatched protected paths. Its exceptions are listed at [app.py:570](/Users/isaaclee/scrapbook/scrapbook/app.py:570): login paths, health/browser metadata paths, the login CSS/logo/backgrounds, and public signed image paths. `/auth/login` itself does not verify the old JWT, so the two login POSTs are not the source of these signature failures.

**Token lifecycle and separation**

| Credential | Creation and storage | Retrieval and verification | Can explain this exact error? |
| --- | --- | --- | --- |
| Session JWT | OTP success calls `generate_session_token`; claims are user ID, email, `type=session`, issued-at and expiry. Default lifetime is 30 days. Signed with configured JWT key/algorithm. Stored in the browser cookie, not a server session table. | `request.cookies.get('session_token')`; signature/claims verified, then expected type checked. | Yes; this is the active path. |
| OTP | Six digits; default lifetime 10 minutes. Redis `otp:<email>` with TTL, or `otp_codes` with expiry. Deleted on successful verification. | Redis string comparison or DB comparison after expiry filtering. | No JWT or signature verification. |
| Legacy magic-link JWT | Helper still exists, default lifetime 30 minutes, same JWT key/algorithm. | No active issuing caller; `/auth/verify` only redirects to login. | Not through its query parameter. If put into the session cookie, a correctly signed magic-link token fails the type check silently; a wrong-key JWT fails earlier with the signature error. |
| Personal access token | Opaque `sp_pat_` random value; plaintext returned once, SHA-256 digest stored in `api_tokens`. | `Authorization: Bearer` takes precedence in user resolution; DB lookup requires an unrevoked digest. | Not from PAT verification. An accompanying invalid session cookie can still be checked by the refresh hook. |
| Extension handoff | Random nonce in URL fragment; image data, source URL, title and timestamp passed by `window.postMessage` and temporarily stored in `sessionStorage`. | Same-window/origin, nonce and image-format checks; one-use consumption with 10-minute TTL. | No signing key, JWT creation, cookie writing, or authentication-token verification. |
| CSRF token | HMAC of session cookie, using `JWT_SECRET_KEY` or its own fallback. | Constant-time comparison, with 403 on failure. | No; separate verification and error. |
| Public image token | `itsdangerous.URLSafeTimedSerializer`; configured image-link key, otherwise JWT key, `SECRET_KEY`, then a constant fallback; distinct salt. | `/public/pin-image/<token>` verifies with max age. | No; bad signatures return 404 `Invalid image link`, expiry returns 410. |

Lifecycle references: [auth_utils.py:22](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:22), [auth_utils.py:43](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:43), [auth_utils.py:151](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:151), [app.py:841](/Users/isaaclee/scrapbook/scrapbook/app.py:841), [app.py:900](/Users/isaaclee/scrapbook/scrapbook/app.py:900), [app.py:977](/Users/isaaclee/scrapbook/scrapbook/app.py:977), [app.py:1008](/Users/isaaclee/scrapbook/scrapbook/app.py:1008), [auth_utils.py:209](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:209), [app.py:551](/Users/isaaclee/scrapbook/scrapbook/app.py:551), [app.py:4025](/Users/isaaclee/scrapbook/scrapbook/app.py:4025), [csrf.py:14](/Users/isaaclee/scrapbook/scrapbook/csrf.py:14), [app.py:707](/Users/isaaclee/scrapbook/scrapbook/app.py:707), [app.py:2242](/Users/isaaclee/scrapbook/scrapbook/app.py:2242), [app.py:2271](/Users/isaaclee/scrapbook/scrapbook/app.py:2271).

[app.py:763](/Users/isaaclee/scrapbook/scrapbook/app.py:763) sets `session_token` with `HttpOnly`, `SameSite=Lax`, `Secure` outside development, and default `Path=/` with no Domain attribute (host-only). The default Max-Age is 30 days. Successful OTP login overwrites the cookie at that scope. Refresh verifies the old JWT and reissues a session when fewer than seven whole days remain; [app.py:624](/Users/isaaclee/scrapbook/scrapbook/app.py:624) writes the refreshed cookie after the request. Expired or invalid JWTs are not refreshed.

The extension opens the configured site's root in a browser tab at [chrome-extension/background.js:30](/Users/isaaclee/scrapbook/scrapbook/chrome-extension/background.js:30), relying on the browser's normal cookie. It stores only the base URL in extension configuration. [static/js/extension_handoff.js:14](/Users/isaaclee/scrapbook/scrapbook/static/js/extension_handoff.js:14) receives the image handoff; [static/js/extension_handoff.js:37](/Users/isaaclee/scrapbook/scrapbook/static/js/extension_handoff.js:37) consumes it. It has no fetch/retry loop. The script is loaded by [templates/login.html:323](/Users/isaaclee/scrapbook/scrapbook/templates/login.html:323) and [templates/base.html:63](/Users/isaaclee/scrapbook/scrapbook/templates/base.html:63). Its omission from the pre-auth asset allowlist is confirmed, and affects ordinary login-page visits even without an installed extension.

**Signing-key persistence and deployment evidence**

[auth_utils.py:14](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:14) reads the JWT key and algorithm once at module import. Encoding and decoding use those same module constants. The fallback key is a fixed literal, not generated randomly. Docker's entrypoint does not generate or rotate signing secrets; it waits for DB, migrates, then executes the command ([docker-entrypoint.sh:34](/Users/isaaclee/scrapbook/scrapbook/docker-entrypoint.sh:34)). Recreating a container with the same environment and source preserves verification of existing tokens. Changing, dropping or emptying the environment variable can change the effective key; age or recreation alone cannot.

Read-only production checks established:

- The web container was created at **2026-10-13 08:03:07.548648207 UTC**, with zero subsequent restarts. Its command is `python app.py`, with one serving Python process and `FLASK_ENV=production`.
- `JWT_SECRET_KEY` is explicitly set, nonempty, and neither repository fallback. Its container environment matches PID 1's initial environment. A separate inspection process importing `auth_utils` resolves that same key. The effective algorithm is HS256. The inspection did not read the serving process's Python heap, but the source contains no key mutation/reload code.
- Running `app.py`, `auth_utils.py`, `templates/login.html`, and `static/js/extension_handoff.js` hashes exactly match this checkout at commit `207c56cd0`. The 2.6.0→2.6.1 source diff does not change auth signing or verification.
- The cache worker lacks a JWT environment variable. It imports app utilities for DB access but neither serves authentication requests nor mints session tokens. Its unused fallback is therefore not a competing signer. The separate legacy `scrapbook-web-1` has no `auth_utils.py` and no JWT/session-cookie implementation in its app source.
- Portainer's maintained `/data/compose/31/docker-compose.yml` and its `before-cache-worker-2.6.1-20261013T080132Z` backup have identical JWT-setting declarations. The key is supplied through a variable. This compares declarations, **not historical resolved values**.

The prior deployment record explicitly reports that the first direct Compose invocation omitted Portainer's separately saved variables, followed by recreation with the saved environment and equality checks for the JWT secret and other settings ([deployment record:82](/Users/isaaclee/scrapbook/scrapbook/docs/operations/2026-10-13-cache-worker-release.md:82)). This is evidence of a temporary configuration hazard, not proof that the failing cookie was minted during that interval or that the corrected key differs from the key used before deployment. Neither the original failing token nor a historical resolved environment was available for comparison.

There is a real development/deployment configuration inconsistency: local Compose supplies a different fixed fallback than direct Python startup ([docker-compose.yml:32](/Users/isaaclee/scrapbook/scrapbook/docker-compose.yml:32)), while the deployment example omits JWT settings ([docker-compose.example.yml:15](/Users/isaaclee/scrapbook/scrapbook/docker-compose.example.yml:15)). The local `.env` has no JWT setting. The application does not explicitly load `.env` before importing auth configuration, so direct `python app.py` depends on exported environment variables; Compose performs its own interpolation. Moving between these launch methods can invalidate cookies if the same browser cookie scope is reused. This does not show that production did so.

**Other hypotheses and invalid-token behavior**

- **Expiry alone is ruled out as the explanation for this message.** Correctly signed expired tokens log `Token has expired` at [auth_utils.py:86](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:86). PyJWT verifies the signature before expiration, so a wrong-key token can also be expired; this error cannot establish its expiry status. The unused `is_token_expired` helper also returns true for invalid tokens ([auth_utils.py:94](/Users/isaaclee/scrapbook/scrapbook/auth_utils.py:94)); it does not produce this log or participate in the current flow.
- **An ordinary algorithm mismatch has a different error.** An HS512 token with the verifier restricted to HS256 produces `The specified alg value is not allowed`, not the reported signature failure. The active sign/verify configuration is shared and uses HS256.
- **Token-type confusion does not explain a correctly signed token's signature failure.** The expected type is checked only after cryptographic verification. A valid magic-link JWT in the cookie is rejected without this log. An opaque PAT in the cookie produces a segment/format error. Bearer JWTs are treated as opaque PATs, not decoded as sessions.
- **Conflicting cookies remain possible, unconfirmed.** The app retrieves the first `session_token` value and does not detect duplicates. A parent-domain or more-specific-path cookie can coexist with the canonical host-only `/` cookie; cookies are also not isolated by port. Local probes confirm first-value selection, but browser cookie metadata was not available. No code in the current extension writes session cookies.
- **Invalid cookies persist.** Refresh fails and then user resolution verifies the same cookie again ([app.py:605](/Users/isaaclee/scrapbook/scrapbook/app.py:605), [app.py:618](/Users/isaaclee/scrapbook/scrapbook/app.py:618)). The response is a login redirect or JSON 401, without deleting the cookie. `get_current_user` memoizes its result, but refresh does not share that result. View-cache verification can be an additional call on requests that reach it; rejected cookie-only requests stop before the view cache.
- **Logout does not recover an already-invalid cookie.** Although [app.py:1016](/Users/isaaclee/scrapbook/scrapbook/app.py:1016) expires it, the global hook rejects the request before the logout route executes.
- **The exact error uses `print`, not Python logging handlers.** Logger propagation cannot explain its paired writes. Lazy image-cache initialization configures a root logging handler ([app.py:2973](/Users/isaaclee/scrapbook/scrapbook/app.py:2973), [scripts/image_cache_service.py:42](/Users/isaaclee/scrapbook/scrapbook/scripts/image_cache_service.py:42)); that is a separate possible explanation for duplicated access entries elsewhere, not needed to explain this window.

**Smallest appropriate correction and focused tests**

Correct the demonstrated handling defects, while preserving strict cryptographic rejection:

1. Add exactly `/static/js/extension_handoff.js` to the existing pre-auth asset allowlist. Do not make all static/cached images public.
2. Reuse one verified session result per request for authentication and refresh. On an invalid cookie, expire the canonical host-only `session_token` at `Path=/` and retain the existing redirect/401 behavior. Ensure cleanup cannot overwrite a newly issued OTP/refresh cookie or turn a valid Bearer request into a failure. Let logout reach cookie cleanup even with an invalid session. Additional Domain/Path cleanup requires evidence of those cookie scopes.
3. If diagnostic logging is added, emit one event per request with request ID, route template, auth source, failure class, and process/config-version identifier. Do not log full tokens, cookie headers, secrets, or user claims taken from an unverified token.

Do **not** rotate the production key based on this incident alone, accept old/default keys speculatively, or disable signature/expiry/type checks. Separately, production configuration should require an explicitly supplied stable JWT key and fail startup on missing/empty configuration, while deployment uses Portainer's saved variables. Preserve the current key when introducing that guard.

Focused regression acceptance cases for that patch:

- A wrong-key or altered session cookie produces one classified failure, no protected content, the appropriate redirect/401, and a matching cookie deletion. Following the response no longer resends the canonical invalid cookie.
- A same-key expired token is rejected as expiry; a wrong-key expired token remains a signature failure. Disallowed algorithms and wrong token types remain rejected.
- The actual Flask login page and handoff script work without a cookie and with an invalid cookie; the script returns JavaScript 200, while cached/user images remain protected. Existing extension E2E tests use a static HTML fixture and do not exercise Flask's auth hook ([tests/e2e/extension-handoff.spec.js:3](/Users/isaaclee/scrapbook/scrapbook/tests/e2e/extension-handoff.spec.js:3)).
- OTP success replaces the invalid cookie with a valid Secure/HttpOnly/SameSite=Lax host-only `/` cookie; subsequent protected requests succeed. Cleanup does not erase the new session.
- Logout clears invalid and near-expiry sessions without a refreshed cookie restoring them. Normal near-expiry refresh still succeeds.
- Valid Bearer PATs authenticate through digest lookup even if an unrelated stale cookie is present; invalid PATs remain 401. Cookie authentication is not a fallback for a rejected explicit Bearer token.
- Separate processes using the same explicit key verify each other's sessions; changing the key fails verification. A production startup guard rejects missing/empty key configuration. Duplicate-cookie scenarios have a documented, deterministic handling policy.

Validation completed: **19 local characterization probes passed**, using PyJWT 2.8.0 copied read-only from the production package directory and the checkout's actual Flask hooks/routes. Network access was blocked during probe execution, and DB/Redis/email operations were mocked. They reproduced the exact 16-error pattern, retained invalid cookies, blocked logout/script, distinct expiry/algorithm/type errors, cookie selection, PAT behavior, public-image error separation, and OTP recovery. These characterize existing behavior; they are not a claim that the proposed patch has been implemented or its regression suite passes. Local Python was 3.13; production Python is 3.11.

Temporary probe harness: [reproduce.py](/private/tmp/scrappl-auth-investigation-20261014/reproduce.py). Run from this checkout with `.venv/bin/python /private/tmp/scrappl-auth-investigation-20261014/reproduce.py` while its temporary dependency directory exists. Only this report was added to the repository.
