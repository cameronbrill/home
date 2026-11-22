1. install mise CLI for your operating system: https://mise.jdx.dev/getting-started.html
2. ensure [mise is activated](https://mise.jdx.dev/cli/activate.html)
3. run `mise install`
4. run `infisical login`
5. install recommended vscode extensions
6. voila you are set up to lint/format/test/run the code

## Roborock session recovery

After a Roborock password reset, replace `ROBOROCK_SESSION`: the previous
session can fail `GET /api/v1/getHomeDetail` with code 2010. Complete the v4
email-code login with `RoborockApiClient.request_code_v4()` and
`RoborockApiClient.code_login_v4()` on the same client, validate the new
`UserData` with `RoborockApiClient._get_home_id()`, and store its `as_dict()` as
single-line JSON. Password-only login is not a recovery path when Roborock
returns code 2031 (`need two step validate`). No static egress IP or persistent
client identifier is required for the stored session.

Update the RWX vault's `ROBOROCK_SESSION`, then use the normal main deployment
to stage it through `flyctl secrets import`. Treat the session and its RRiot
fields as credentials: keep temporary files mode 600, never print them, and
remove them after updating the vault.

For disposable Fly checks, do not assume `flyctl machine run --env
ROBOROCK_SESSION=...` replaces the app's existing same-name secret. Use a
separate candidate variable in the probe and remap it to `ROBOROCK_SESSION` in
the probe entrypoint, or stage the intended secret deliberately. Otherwise an
older app secret can create a misleading 2010 even while the candidate session
is valid locally and from other Fly machines.
