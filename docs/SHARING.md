# Private app sharing

Hushscript's recommended remote entry point is its **own Tailscale node** inside an isolated Docker network. Share the `hushscript` node with the coworker, not the Omphalos host node. The node serves only Hushscript on TCP 8445. Omphalos's existing Tailscale services and host ports remain on a different node and network namespace.

The browser and [HTTP API](API.md) use the same HTTPS address. A coworker who accepts the share can use both. API jobs use short-lived per-job capability tokens; Tailscale controls who can reach the app. There is no shell or host filesystem service in the app-only node.

This setup has passed a local isolated-network test with a throwaway TLS certificate and no authenticated Tailscale node. Actual node authentication, certificate issuance, and access from a coworker remain to be verified. The existing Omphalos service is still local-only until the steps below are completed.

## Owner setup on Omphalos

1. Build the runtime image and connect the dedicated node. This first step does not restart the current Hushscript app. It prompts you to log the new `hushscript` node into **your** Tailscale account in a browser:

~~~bash
cd /home/girgie/Projects/hushscript
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.tls.yaml -f compose.isolated.yaml build
python3 scripts/share_node.py setup
python3 scripts/share_node.py status
~~~

Tailscale keeps this node's login state in the Docker-managed `tailnet-state` volume. That state contains credentials, not recordings. The sidecar has no published host ports, uses userspace networking, and forwards raw TLS ciphertext to the app. No `TS_AUTHKEY` is placed in a Compose file or environment variable.

2. Stop the **old Hushscript launcher** in its terminal with Ctrl+C. Wait until its app container stops. Start isolated sharing in a terminal and leave it open:

~~~bash
python3 scripts/serve.py --gpu --elevate-inhibitor --isolated-share
~~~

The launcher refuses to replace a running Hushscript app. It checks the host sleep/shutdown inhibitor, starts the protected app in the isolated node's network space, gets the certificate using that node's Tailscale identity, verifies a healthy HTTPS response, then enables raw TCP Serve on 8445. On shutdown, the independent helper stops both containers before releasing the inhibitor. The original Omphalos Tailscale node and its services on 443, 8443, and 8444 are untouched.

3. The launcher prints the new `https://hushscript.<your-tailnet>.ts.net:8445` address. Verify it from one of your own Tailscale devices before inviting anyone. The API health endpoint is at `/api/health`; the browser interface is at `/`. Do not override certificate warnings.

## Invite the coworker

In Tailscale Admin Console → Machines, select the **hushscript** node, choose Share → Copy invite link, leave Reusable link off, and send the single-use link through your own channel. Never share the **omphalos** node. The coworker accepts from their own Tailscale account; they do not join your tailnet. Tailscale says a recipient needs to be an Owner, Admin, or IT admin of their own tailnet to accept a machine share.

After acceptance, confirm the recipient's displayed identity and test the browser and API from their device. The share gives them only this app node. For the strongest policy rule, also grant shared users only TCP 8445 to the new node and ensure no broader grant applies to it. The dedicated node remains separate from Omphalos even if a broad policy exists. Do not use Funnel or a public password endpoint.

The coworker can alternatively [clone the public repository](https://github.com/Andrew-Girgis/hushscript). Their local inference needs the platform-specific host protections documented in [WSL.md](WSL.md) or [PORTABILITY.md](PORTABILITY.md).

## Remove access

Revoke the share from the `hushscript` node's Share dialog in the admin console. Stopping the isolated launcher also stops the app and Tailscale sidecar. Revoking a share blocks the coworker's access without changing their GitHub access to the public source code.

The certificate is fetched with at least 48 hours remaining. Restart the launcher before it expires; hot reload is not implemented. The certificate private key is piped from the sidecar into app tmpfs and removed after loading. The app does not persist uploaded audio or server transcripts.

## References

- [Sharing a machine with an external user](https://tailscale.com/docs/features/sharing)
- [Tailscale Docker configuration](https://tailscale.com/docs/features/containers/docker/docker-params)
- [Userspace networking](https://tailscale.com/docs/concepts/userspace-networking)
- [Tailscale Serve raw TCP forwarding](https://tailscale.com/docs/reference/tailscale-cli/serve)
