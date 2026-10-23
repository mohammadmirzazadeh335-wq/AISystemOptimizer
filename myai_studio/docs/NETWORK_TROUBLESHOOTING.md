# Provider connection problems — a checklist

The API page reports one of four sentences. Each one names a different layer,
so the fix is different too. The **Connectivity** card on the same page runs a
staged probe (proxy → DNS → TCP → TLS → HTTP) and prints the stage that failed
together with the operating system's error text.

## 1. "Could not open a connection to the provider in time" (`provider.timeout`, stage `tcp`)

Nothing accepted the TCP connection. Almost always one of:

- **A proxy/VPN is running but the app does not know about it.** Browsers follow
  the Windows system proxy; this app used to read only environment variables.
  Version `0.8.0` reads the Windows registry (and `scutil` on macOS) as well.
  If that fails, set **Proxy → Manual** and enter the HTTP port your VPN client
  shows (Clash `7890`, v2rayN `10809`, Xray `10808`, …). The address may be
  typed as `127.0.0.1:10809` — the scheme defaults to `http://`.
- The provider is blocked outright and no proxy is involved. Nothing in the app
  can fix that; the app cannot bypass a firewall by design.
- A corporate proxy requires credentials: `http://user:pass@host:port` is
  accepted, and the password never appears in the UI or the log (it is masked
  to `http://***@host:port`).

## 2. "The TLS handshake failed" (`provider.network`, stage `tls`)

The TCP connection opened but the encrypted session was closed during the
handshake (`SSLZeroReturnError`, `EOF`, `SSLError`). This is the signature of a
middlebox that inspects or resets TLS for that hostname — a national firewall,
a school/work network, or an antivirus HTTPS scanner with a broken rule. The
app cannot complete that handshake because it refuses to disable certificate
verification. Use a tunnel/proxy that is not reset (the Connectivity card will
then show `proxy` or `http`, not `tls`).

## 3. "OpenRouter rejected the API key" (`provider.auth`, HTTP 401/403)

The network is fine and the provider answered. The key is wrong, revoked, or
copied with a stray space. Keys look like `sk-or-v1-` followed by 64 hex
characters; the app rejects anything else before it is stored.

## 4. "Insufficient credits" (`provider.credit`, HTTP 402)

The key is valid, the account has no balance. Free models (`:free`) still work.

## What "the app forgot my key" is not

The key is stored encrypted (Windows DPAPI, or a Fernet vault elsewhere) and is
never written to logs, backups or the database. Deleting it in the UI also
removes the stored copy.

## Testing the path without the internet

`tests/unit/test_network.py` covers proxy discovery, address normalisation,
masking, and the staged probe against real local sockets.
`tests/ui/test_network_page.py` covers the card itself. A stub server that
speaks the provider's API is used to prove the whole app path (key → catalogue →
connection test → streaming chat) works on a healthy network; that is a test of
the application, **not** of OpenRouter or of any particular key.
