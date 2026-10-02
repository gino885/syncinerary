# Production backend deployment

The repository now has one production image for both required processes. Run
the default command for the web service and override the command with
`python -m syncinerary.workers.gather` for the worker. Do not run the local
Docker Compose file in production. It publishes database and observability
ports and uses development credentials.

## Required topology

- One public HTTPS web service built from `Dockerfile`.
- One private worker built from the same image.
- Managed PostgreSQL 16 with the pgvector extension.
- Managed Redis reachable only by the web service and worker.
- A transactional SMTP provider for password recovery. Signup does not send email.
- Persistent private storage for uploaded screenshots, or an object-storage
  replacement before allowing uploads on an ephemeral platform.
- Encrypted database backups that expire within the retention period stated
  in the privacy policy.

The API must be the only public backend port. PostgreSQL, Redis, the worker,
and Phoenix must remain private. The reverse proxy must support WebSockets.

## Release procedure

1. Create PostgreSQL and enable pgvector.
2. Create Redis and private service networking.
3. Add every production environment value through the host's secret manager.
4. Build the image from the repository root.
5. Run `alembic upgrade head` as a one-off release job before sending traffic
   to the new image. Do not run migrations concurrently in every web replica.
6. Start the web service and one worker. Scale workers only after observing
   queue time and provider limits.
7. Confirm `GET /health` returns HTTP 200 through the public HTTPS hostname.
8. Create two test accounts, join one trip from both, grant AI permission from
   both accounts, save the creator's Anthropic key, run discovery, vote, and
   create an itinerary.
9. Delete one joined account and confirm the trip remains. Delete the creator
   test account and confirm its trip is gone.
10. Point the iOS Release build's `SYNC_API_BASE_URL` at this hostname.

## Production environment

Start from `.env.example`, but never upload the file itself. At minimum set:

- `DATABASE_URL` to the managed PostgreSQL asyncpg URL.
- `REDIS_URL` to the managed Redis URL.
- `SYNC_CREDENTIAL_ENCRYPTION_KEYS` to versioned AES-256 keys generated and
  stored in the cloud secret manager.
- `SYNC_CREDENTIAL_ENCRYPTION_ACTIVE_VERSION` to the active key version.
- `GOOGLE_MAPS_API_KEY` and `BRAVE_SEARCH_API_KEY`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, and `SMTP_FROM`.
- `SYNC_TRACE_SENSITIVE_CONTENT=false`.
- `FORWARDED_ALLOW_IPS` to the trusted proxy addresses supplied by the host.

Leave the global `ANTHROPIC_API_KEY` empty. Production model calls use the
trip creator's encrypted key. Keep every old encryption-key version until all
records using it have been re-encrypted or deleted.

If Phoenix is enabled, use a private endpoint and access controls. The default
production trace configuration excludes prompts and responses.

## Security and operations

- Require TLS from the phone to the public proxy and from services to managed
  databases when the host supports it.
- Restrict secret access to the API and worker service identities.
- Alert on HTTP 5xx rate, worker failures, queue age, database saturation,
  Redis availability, email failures, and backup failures.
- Test restoration from backup before launch and on a recurring schedule.
- Set a deletion policy so backups expire within 30 days, matching the public
  privacy policy.
- Keep a documented encryption-key rotation and emergency revocation process.
- Do not enable sensitive trace content in production.

The container intentionally does not run migrations or the worker inside the
web process. Those have different lifecycle and scaling requirements.
