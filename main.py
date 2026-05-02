import hashlib
import time
import os
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import Optional, Any, Dict
from functools import wraps
from collections import OrderedDict
import threading

load_dotenv()

APP_ID = os.getenv("QOBUZ_APP_ID")
APP_SECRET = os.getenv("QOBUZ_APP_SECRET")
AUTH_TOKEN = os.getenv("QOBUZ_AUTH_TOKEN")

BASE = "https://www.qobuz.com/api.json/0.2"

# Cache configuration
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", 1000))  # Default 1000 entries

# Endpoint-specific TTL configuration (in seconds)
CACHE_TTL_SEARCH = int(os.getenv("CACHE_TTL_SEARCH", 300))  # Search: 5 minutes
CACHE_TTL_TRACK = int(os.getenv("CACHE_TTL_TRACK", 600))  # Track: 10 minutes
CACHE_TTL_STREAM = int(os.getenv("CACHE_TTL_STREAM", 60))  # Stream: 1 minute
CACHE_TTL_ALBUM = int(os.getenv("CACHE_TTL_ALBUM", 600))  # Album: 10 minutes
CACHE_TTL_ARTIST = int(os.getenv("CACHE_TTL_ARTIST", 600))  # Artist: 10 minutes
CACHE_TTL_PLAYLIST = int(os.getenv("CACHE_TTL_PLAYLIST", 300))  # Playlist: 5 minutes

app = FastAPI(title="Qobuz API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class LRUCache:
    """Thread-safe LRU cache with TTL support"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
    
    def _generate_key(self, endpoint: str, **kwargs) -> str:
        """Generate a unique cache key from endpoint and parameters"""
        key_parts = [endpoint]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if exists and not expired"""
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            if time.time() > entry["expires_at"]:
                # Entry expired, remove it
                del self._cache[key]
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return entry["value"]
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None, endpoint: Optional[str] = None) -> None:
        """Set value in cache with optional TTL and endpoint tracking"""
        with self._lock:
            # If key exists, remove old entry first
            if key in self._cache:
                del self._cache[key]
            
            # Evict oldest entries if at capacity
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = {
                "value": value,
                "expires_at": time.time() + (ttl or self.default_ttl),
                "endpoint": endpoint,
                "ttl": ttl or self.default_ttl
            }
    
    def invalidate(self, pattern: Optional[str] = None) -> int:
        """Invalidate cache entries. If pattern is None, clear all."""
        with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            
            # Invalidate keys matching pattern (simple substring match)
            keys_to_remove = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self._cache[key]
            return len(keys_to_remove)
    
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics"""
        with self._lock:
            now = time.time()
            total = len(self._cache)
            expired = sum(1 for e in self._cache.values() if now > e["expires_at"])
            
            # Count entries by endpoint
            endpoints: Dict[str, int] = {}
            for entry in self._cache.values():
                endpoint = entry.get("endpoint", "unknown")
                endpoints[endpoint] = endpoints.get(endpoint, 0) + 1
            
            return {
                "size": total,
                "max_size": self.max_size,
                "expired_entries": expired,
                "active_entries": total - expired,
                "endpoints": endpoints
            }


# Global cache instance (using a default TTL, but endpoints override this)
cache = LRUCache(max_size=CACHE_MAX_SIZE, default_ttl=CACHE_TTL_SEARCH)


def cached_endpoint(endpoint_name: str, ttl: Optional[int] = None):
    """Decorator to cache endpoint responses"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract function arguments for cache key
            func_kwargs = {}
            for arg_name, arg_value in kwargs.items():
                if arg_name not in ['request', 'background_tasks']:
                    func_kwargs[arg_name] = arg_value
            
            cache_key = cache._generate_key(endpoint_name, **func_kwargs)
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Call the actual function
            result = await func(*args, **kwargs)
            
            # Store in cache with endpoint info
            cache.set(cache_key, result, ttl, endpoint=endpoint_name)
            
            return result
        return wrapper
    return decorator


def get_token() -> str:
    if not AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="QOBUZ_AUTH_TOKEN env var not set")
    return AUTH_TOKEN


def stream_sig(track_id: str, format_id: int, ts: str) -> str:
    raw = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{ts}{APP_SECRET}"
    return hashlib.md5(raw.encode()).hexdigest()


@app.get("/")
async def index():
    return {"service": "qobuz-api", "status": "ok", "token_set": bool(AUTH_TOKEN), "app_id_set": bool(APP_ID)}


@app.get("/search")
@cached_endpoint("search", ttl=CACHE_TTL_SEARCH)  # Cache search results for 5 minutes
async def search(q: str = Query(...), limit: int = 20, artist: Optional[str] = Query(None, description="Filter search results by artist name")):
    token = get_token()
    async with httpx.AsyncClient() as client:
        # Build the query string with optional artist filter
        query_string = q
        if artist:
            query_string = f"{q} artist:\"{artist}\""
        
        params = {
            "query": query_string,
            "limit": limit,
            "app_id": APP_ID,
            "user_auth_token": token
        }
        r = await client.get(f"{BASE}/catalog/search", params=params)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/track/{track_id}")
@cached_endpoint("track", ttl=CACHE_TTL_TRACK)  # Cache track info for 10 minutes
async def get_track(track_id: str):
    token = get_token()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/track/get", params={
            "track_id": track_id,
            "app_id": APP_ID,
            "user_auth_token": token
        })
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/stream/{track_id}")
@cached_endpoint("stream", ttl=CACHE_TTL_STREAM)  # Cache stream URLs for 1 minute (they expire)
async def stream(
    track_id: str,
    format_id: int = Query(default=27, description="27=HiRes 192kHz, 7=HiRes 96kHz, 6=FLAC 16-bit, 5=MP3 320")
):
    token = get_token()
    ts = str(int(time.time()))
    sig = stream_sig(track_id, format_id, ts)
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/track/getFileUrl", params={
            "track_id": track_id,
            "format_id": format_id,
            "intent": "stream",
            "request_ts": ts,
            "request_sig": sig,
            "app_id": APP_ID,
            "user_auth_token": token
        })
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/album/{album_id}")
@cached_endpoint("album", ttl=CACHE_TTL_ALBUM)  # Cache album info for 10 minutes
async def get_album(album_id: str):
    token = get_token()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/album/get", params={
            "album_id": album_id,
            "app_id": APP_ID,
            "user_auth_token": token
        })
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/artist/{artist_id}")
@cached_endpoint("artist", ttl=CACHE_TTL_ARTIST)  # Cache artist info for 10 minutes
async def get_artist(artist_id: str, limit: int = 25):
    token = get_token()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/artist/get", params={
            "artist_id": artist_id,
            "limit": limit,
            "app_id": APP_ID,
            "user_auth_token": token
        })
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/playlist/{playlist_id}")
@cached_endpoint("playlist", ttl=CACHE_TTL_PLAYLIST)  # Cache playlist info for 5 minutes
async def get_playlist(playlist_id: str):
    token = get_token()
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/playlist/get", params={
            "playlist_id": playlist_id,
            "app_id": APP_ID,
            "user_auth_token": token
        })
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Qobuz token expired — update QOBUZ_AUTH_TOKEN")
        r.raise_for_status()
        return r.json()


@app.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics"""
    return cache.stats()


@app.delete("/cache")
async def clear_cache(pattern: Optional[str] = None):
    """Clear cache entries. If pattern is provided, only clear matching entries."""
    count = cache.invalidate(pattern)
    return {"cleared": count, "pattern": pattern}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
