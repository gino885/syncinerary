# Anthropic BYOK deployment

Production trips use the trip creator's Anthropic API key. Other travelers do
not enter a key. Their trip-wide model work is charged to the creator's
Anthropic account.

## Secret storage

Set `SYNC_CREDENTIAL_ENCRYPTION_KEYS` through the cloud host's secret manager.
The value is a JSON keyring. Generate the first 32-byte AES key locally:

```bash
.venv/bin/python -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
```

Store the result in this shape, without committing it:

```text
SYNC_CREDENTIAL_ENCRYPTION_KEYS={"1":"generated-value"}
SYNC_CREDENTIAL_ENCRYPTION_ACTIVE_VERSION=1
```

Keep `ANTHROPIC_API_KEY` empty in production. It remains only for legacy trips
and local development. An account-owned trip is explicitly prevented from
falling back to that server key.

The database stores AES-256-GCM ciphertext, a unique nonce, the last four
characters for identification, and the keyring version. Authenticated data
binds each ciphertext to its account ID and provider, so copying a credential
row to another account does not decrypt.

## Rotation

Add a new numbered key while retaining the old key, then change the active
version. New and replaced credentials use the active version. Keep every old
version until its rows have been re-encrypted or removed.

```text
SYNC_CREDENTIAL_ENCRYPTION_KEYS={"1":"old-value","2":"new-value"}
SYNC_CREDENTIAL_ENCRYPTION_ACTIVE_VERSION=2
```

Do not remove version 1 merely because version 2 is active. Rows record their
encryption version and still need the matching key for decryption.

## Operational controls

- Use TLS from the iOS app to the API. Never accept this endpoint over HTTP in production.
- Restrict production database and secret-manager access to the API and worker identities.
- Encrypt database backups and exclude request bodies from application, proxy, and APM logs.
- Keep Anthropic and deployment keys separate across development, staging, and production.
- Enable Anthropic usage monitoring and spend limits. Revoke a suspected key in the Anthropic Console, then remove or replace it in AI access.
- Run `alembic upgrade head` before starting API or worker processes.

Saving a key requires explicit in-app consent that identifies the trip data
sent to Anthropic and warns that the creator may incur API charges. The API
never returns the full key. Removing it deletes the encrypted row and prevents
new creator-funded discovery or model steps.
