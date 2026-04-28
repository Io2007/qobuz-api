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

### Cache Configuration

The API uses an LRU cache with TTL (Time To Live) support. You can configure endpoint-specific TTL values via environment variables:

```env
CACHE_MAX_SIZE=1000         # Maximum number of cached entries (default: 1000)

# Endpoint-specific TTL values (in seconds)
CACHE_TTL_SEARCH=300        # Search endpoint: 5 minutes (default)
CACHE_TTL_TRACK=600         # Track endpoint: 10 minutes (default)
CACHE_TTL_STREAM=60         # Stream endpoint: 1 minute (default)
CACHE_TTL_ALBUM=600         # Album endpoint: 10 minutes (default)
CACHE_TTL_ARTIST=600        # Artist endpoint: 10 minutes (default)
CACHE_TTL_PLAYLIST=300      # Playlist endpoint: 5 minutes (default)
```

**Endpoint-specific TTL values:**
- `/search` - Configurable via `CACHE_TTL_SEARCH` (default: 300 seconds / 5 minutes)
- `/track/{track_id}` - Configurable via `CACHE_TTL_TRACK` (default: 600 seconds / 10 minutes)
- `/stream/{track_id}` - Configurable via `CACHE_TTL_STREAM` (default: 60 seconds / 1 minute)
- `/album/{album_id}` - Configurable via `CACHE_TTL_ALBUM` (default: 600 seconds / 10 minutes)
- `/artist/{artist_id}` - Configurable via `CACHE_TTL_ARTIST` (default: 600 seconds / 10 minutes)
- `/playlist/{playlist_id}` - Configurable via `CACHE_TTL_PLAYLIST` (default: 300 seconds / 5 minutes)

**Cache management endpoints:**
- `GET /cache/stats` - Get cache statistics (size, expired entries, etc.)
- `DELETE /cache` - Clear all cache entries
- `DELETE /cache?pattern=<pattern>` - Clear cache entries matching a pattern

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