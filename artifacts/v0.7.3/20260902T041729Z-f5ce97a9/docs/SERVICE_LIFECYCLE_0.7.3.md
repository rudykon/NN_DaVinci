# Service lifecycle in 0.7.3

## Health contract

`GET /api/health` is machine-readable and reports `product_version`, PID,
uptime, host, port, source identity, build identity, readiness, authentication
status, and the LAN-risk flag. Readiness is checked after the launcher exits;
a background process that dies immediately is not a successful start.

The lifecycle scripts store a JSON state file containing the PID, Linux process
start ticks, command-line digest, source/build identities, host/port, log path,
and product version. Status and stop validate that identity before treating a
PID as NN_DaVinci. A reused or forged PID is refused without sending a signal.

## Commands

```bash
./scripts/start-0.7.3.sh
./scripts/status-0.7.3.sh
./scripts/restart-0.7.3.sh
./scripts/stop-0.7.3.sh
```

The defaults are `127.0.0.1:8765`. `NNDV_HOST`, `NNDV_PORT`,
`NNDV_SERVICE_STATE_DIR`, and `NN_DAVINCI_PYTHON` may select an isolated local
instance. The scripts detect listener conflicts and refuse to replace an
unrelated process. Stop confirms both process exit and port release.

The release lifecycle acceptance uses port 8766 and covers start, status,
restart, stop, post-stop status, unrelated listener conflict, and forged-PID
refusal. It must finish without a listener on either test port.

## Security boundary

The default loopback service is intended for one local user. It has no
authentication, authorization, TLS termination, tenant isolation, or safe
public deployment contract. Selecting `0.0.0.0` displays a prominent warning
that other LAN hosts may reach an unauthenticated service. Authentication and
multi-user deployment remain outside 0.7.3.
