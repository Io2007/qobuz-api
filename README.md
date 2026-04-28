# Qobuz API - Docker & Traefik Setup

## Prerequisites

- Docker and Docker Compose installed
- Traefik v2+ running with:
  - An external network named `traefik-network`
  - TLS certificate resolver configured (named `myresolver` by default)

## Environment Variables

Create a `.env` file in the same directory with your Qobuz credentials:

```env
QOBUZ_APP_ID=your_app_id
QOBUZ_APP_SECRET=your_app_secret
QOBUZ_AUTH_TOKEN=your_auth_token
QOBUZ_HOST=qobuz-api.yourdomain.com
```

## Traefik Configuration

Ensure you have a Traefik instance running with the following:

1. **External Network**: Create the traefik-network if it doesn't exist:
   ```bash
   docker network create traefik-network
   ```

2. **Traefik Labels**: The service is configured with these Traefik labels:
   - `traefik.enable=true`
   - Router rule: `Host(\`${QOBUZ_HOST:-qobuz-api.localhost}\`)`
   - Entrypoint: `websecure` (HTTPS)
   - TLS certResolver: `myresolver`
   - LoadBalancer port: `8000`

## Usage

### Build and Start

```bash
docker compose up -d --build
```

### View Logs

```bash
docker compose logs -f qobuz-api
```

### Stop

```bash
docker compose down
```

## API Endpoints

- `GET /` - Health check
- `GET /search?q=query` - Search tracks
- `GET /track/{track_id}` - Get track details
- `GET /stream/{track_id}` - Get stream URL
- `GET /album/{album_id}` - Get album details
- `GET /artist/{artist_id}` - Get artist details
- `GET /playlist/{playlist_id}` - Get playlist details

## Customization

### Change Domain

Set `QOBUZ_HOST` in your `.env` file to change the domain.

### Disable HTTPS (for local testing)

Modify `docker-compose.yml`:
- Change `entrypoints=websecure` to `entrypoints=web`
- Remove the `tls.certresolver` label