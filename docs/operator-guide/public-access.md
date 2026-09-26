# Public Access and TLS Termination

Docker Compose publishes the Nginx `gateway` service; Flask/Gunicorn `web`
stays internal-only. Terminate TLS either with a Cloudflare Tunnel or a
host reverse proxy.

Docker Compose publishes the Nginx `gateway` service. The Flask/Gunicorn `web`
service is internal-only. Nginx proxies application requests and serves
authorized individual artifacts or optional ZIP bytes with an internal
`X-Accel-Redirect`. The gateway mounts only `${SERVER_DIR}/results` and mounts
it read-only.

## Option A: Cloudflare Tunnel

Point Cloudflare Tunnel at the gateway's published `${PORT}`. Do not target the
internal Gunicorn service directly.

A tunnel origin is a plain-HTTP hop. Cloudflare itself connects over TLS and
rewrites `X-Forwarded-Proto` at the edge, but that header only reaches the app
if every hop between the edge and the app preserves it; a tunnel that forwards
the request without it leaves the app seeing `http`, which suppresses HSTS and
lets Cloudflare substitute the evicting `max-age=0`. Confirm the live value
(`curl -sI https://<host>/ | grep -i strict-transport-security`) and, when the
chain cannot be made to report HTTPS, set `FORCE_HSTS=true` on the HTTPS-only
deployment instead of relying on the header. Never enable it while the public
URL is plain HTTP.

Because the tunnel may reach the gateway from a host interface rather than
loopback, a `GATEWAY_BIND=0.0.0.0` deployment must restrict host access to the
tunnel's address at the firewall: the app's socket peer is always the compose
gateway, so `TRUSTED_PROXY_IPS` cannot distinguish a tunnel from a LAN peer —
see the client-IP section of `configuration.md`.

Reference: [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)

## Option B: Additional host reverse proxy or TLS termination

An additional host-level proxy may sit in front of the container gateway when
custom TLS termination, routing, or rate limits are required.

You can start from:

- `nginx_sites/REvoCompute.app`

The example forwards `X-Forwarded-Proto $scheme` so the app can mark auth
cookies `Secure` and add HSTS; keep that header in any custom proxy config.
Gunicorn trusts forwarded headers only from the compose gateway
(`--forwarded-allow-ips 127.0.0.1,172.16.0.0/12`), so client-supplied
`X-Forwarded-Proto` values are ignored. On HTTPS-only deployments, also set
`AUTH_COOKIE_SECURE=true` and `FORCE_HSTS=true` as belt-and-braces forces.
