# Private sharing

The agreed entry point is Tailscale Serve, restricted to an approved coworker device and approved owner devices. Remote exposure is currently disabled. Existing Serve services must be preserved.

## What is ready

Hushscript supports HTTPS inside its protected container. The launcher obtains the certificate from Tailscale's existing system credential store and sends it through stdin into a temporary container RAM file. The server loads and removes that file. Keys never appear in command arguments, environment variables, this repository, or a project key file.

Use raw TCP forwarding. Tailscale's normal HTTPS reverse-proxy mode terminates TLS in its host process, outside the app's memory protections.

Local TLS tests passed with both a temporary certificate and an actual Tailscale-managed certificate, with certificate verification enabled, a healthy app response, and confirmation that the one-use PEM was removed. These tests used loopback and did not enable a remote Serve entry. Device policy and remote connection tests remain pending.

## Finish the device policy first

1. Obtain the coworker's enrolled Tailscale device and the owner's approved devices.
2. Review the complete tailnet policy. Grants and ACLs are additive; adding a narrow grant does not override a broad existing allow rule.
3. Limit TCP port 8445 on this server to the chosen device addresses. Account for both IPv4 and IPv6 grants and any existing wildcard rules. Keep unrelated services working.
4. Add policy tests for allowed and denied devices, then verify actual connections from each.

A grant may look like this, using real enrolled device addresses in place of the placeholders:

~~~json
{
  "src": ["COWORKER_DEVICE_IP", "OWNER_DEVICE_IP"],
  "dst": ["SERVER_TAILSCALE_IP"],
  "ip": ["tcp:8445"]
}
~~~

This fragment alone is not a complete restrictive policy. Device approval by itself is not an application access rule. Node sharing can affect other services, so review the existing policy before inviting a device or sharing the server.

## Start after the policy is verified

Port 8445 is proposed because Omphalos already uses 443, 8443, and 8444. Confirm it remains unused. Stop the existing Hushscript launcher before starting TLS mode.

~~~bash
python3 scripts/serve.py --gpu --elevate-inhibitor --tls-domain MACHINE.TAILNET.ts.net
~~~

Use the real lowercase DNS name. Omit --gpu on CPU hosts. The command acquires host protection, starts the TLS container, and provisions its certificate. It does not modify tailnet access rules or expose the service itself.

Then enable only the new TCP entry:

~~~bash
tailscale serve --bg --tcp=8445 tcp://127.0.0.1:8787
~~~

Visit https://MACHINE.TAILNET.ts.net:8445. Verify allowed and denied devices before uploading recordings. Never use Funnel. To remove only this entry:

~~~bash
tailscale serve --tcp=8445 off
~~~

The launcher obtains a certificate with at least 48 hours remaining. It does not yet hot-reload certificates; restart it before the certificate expires. Do not bypass certificate warnings.

## References

- [Serve raw TCP forwarding](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Tailscale HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates)
- [Grants](https://tailscale.com/docs/features/access-control/grants)

The public GitHub repository does not expose the running service or receive recordings.
