# Security Policy

## Supported Version

SignalDesk is currently an MVP. Security fixes target the latest revision on `main`.

## Reporting a Vulnerability

Please use GitHub's private vulnerability reporting or contact the repository owner directly. Do not publish credentials, personal data, or exploit details in a public issue.

## Secrets

- Never commit `.env` or `.env.production`.
- Restrict the YouTube API key to YouTube Data API v3 and the deployment IP where possible.
- Use unique production values for database credentials and `PSEUDONYM_SALT`.
- Treat generated database dumps as sensitive and keep them outside the repository and Docker build context.

## Production Notes

The documented single-VPS deployment is intended for an early beta. Public registration, distributed rate limiting, account recovery, and multi-worker job claiming require additional hardening before broad public use.
