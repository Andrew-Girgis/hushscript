# Private sharing

The agreed entry point is Tailscale Serve plus a single-use share link for Omphalos. The coworker can accept from their own Tailscale account without joining the owner's tailnet. Only Hushscript on TCP 8445 should be reachable through that share. Remote exposure is currently disabled; existing Serve services must be preserved.

## What is ready

Hushscript supports HTTPS inside its protected container. The launcher obtains the certificate from Tailscale's existing system credential store and sends it through stdin into a temporary container RAM file. The server loads and removes that file. Keys never appear in command arguments, environment variables, this repository, or a project key file.

Use raw TCP forwarding. Tailscale's normal HTTPS reverse-proxy mode terminates TLS in its host process, outside the app's memory protections.

Local TLS tests passed with both a temporary certificate and an actual Tailscale-managed certificate, with certificate verification enabled, a healthy app response, and confirmation that the one-use PEM was removed. These tests used loopback and did not enable a remote Serve entry. Device policy and remote connection tests remain pending.

## Review the access policy first

A share link makes **the machine** visible to the recipient; it does not limit the recipient to one URL by itself. Tailscale applies the existing tailnet access policy to connections to that machine. Omphalos also has services on 443, 8443, and 8444, so the complete policy must be reviewed before a link is created.

1. Read the current policy from Tailscale Admin Console → Access controls. Preserve access for the owner's existing devices and services.
2. Check every grant and legacy ACL matching external shared users, especially wildcard sources, destinations, or ports. Grants are additive: a narrow rule does not cancel a broad one.
3. Permit the shared recipient only TCP 8445 on Omphalos. Deny access to its other ports, including 443, 8443, 8444, and SSH, by ensuring no other rule grants them.
4. Save and verify the policy, then create a **single-use** share link for Omphalos from the Machines page. Send that link only to the intended coworker through your own channel. A reusable link is unnecessary.
5. After the recipient accepts, check the displayed identity, test that 8445 works and the other ports fail from their Tailscale connection, and revoke the share if the identity or tests are wrong.

A narrow grant can allow this port without knowing the recipient's device name in advance:

~~~json
{
  "src": ["autogroup:shared"],
  "dst": ["OMPHALOS_TAILSCALE_IP"],
  "ip": ["tcp:8445"]
}
~~~

This fragment is **not** a complete restrictive policy. An existing wildcard grant or ACL could still allow other ports. The policy should be checked and edited as a whole before enabling a share. Link-based sharing exposes only the selected machine to the recipient, not the rest of the tailnet; the port restriction is a separate policy decision.

A recipient needs a Tailscale account and must be an Owner, Admin, or IT admin of their own tailnet to accept a machine share. Treat the invite link as a secret until accepted. The public GitHub repository is an alternative if they prefer to run the app on their own machine; [WSL2 has host prerequisites](WSL.md) and has not been tested on Windows.

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

Visit https://MACHINE.TAILNET.ts.net:8445. The recipient uses the full owner-tailnet DNS name after accepting the share. Verify allowed and denied ports from their device before uploading recordings. Never use Funnel. To remove only this entry:

~~~bash
tailscale serve --tcp=8445 off
~~~

The launcher obtains a certificate with at least 48 hours remaining. It does not yet hot-reload certificates; restart it before the certificate expires. Do not bypass certificate warnings.

## References

- [Serve raw TCP forwarding](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Tailscale HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates)
- [Grants](https://tailscale.com/docs/features/access-control/grants)
- [Share a machine with an external user](https://tailscale.com/docs/features/sharing)

The public GitHub repository does not expose the running service or receive recordings.
