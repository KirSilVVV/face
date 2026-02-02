"""Client for search4faces.com API - VK face search."""
import base64
import logging
from typing import Callable

import httpx

from src.config import SEARCH4FACES_API_KEY

logger = logging.getLogger(__name__)

API_URL = "https://search4faces.com/api/json-rpc/v1"


class Search4FacesClient:
    """Client for search4faces.com VK search API."""

    def __init__(self):
        self.api_key = SEARCH4FACES_API_KEY

    async def _call_api(self, method: str, params: dict = None) -> dict:
        """Make JSON-RPC 2.0 call to search4faces API."""
        if not self.api_key:
            logger.error("SEARCH4FACES_API_KEY not configured")
            return {"error": "API key not configured"}

        headers = {
            "x-authorization-token": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {}
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(API_URL, headers=headers, json=payload)
                return response.json()
        except Exception as e:
            logger.error(f"search4faces API error: {e}")
            return {"error": str(e)}

    async def get_rate_limit(self) -> dict | None:
        """Check API key status and remaining requests."""
        result = await self._call_api("rateLimit")
        if "result" in result:
            return result["result"]
        return None

    async def detect_faces(self, image_bytes: bytes) -> dict | None:
        """Detect faces in image. Returns image reference and face data."""
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        result = await self._call_api("detectFaces", {"image": image_base64})

        if "result" in result:
            return result["result"]
        elif "error" in result:
            logger.error(f"detectFaces error: {result['error']}")
        return None

    async def search_vk(
        self,
        image_bytes: bytes,
        source: str = "vk_wall",
        results_count: int = 10,
        on_progress: Callable[[int], None] = None
    ) -> dict | None:
        """
        Search VK for faces matching the image.

        Args:
            image_bytes: Image data
            source: Search source (vk_wall, tt_avatar, etc.)
            results_count: Number of results to return
            on_progress: Optional callback for progress updates

        Returns:
            dict with profiles list or None on error
        """
        # Step 1: Detect faces in image
        if on_progress:
            await on_progress(10)

        detect_result = await self.detect_faces(image_bytes)

        if not detect_result:
            return {"error": "Failed to detect faces in image"}

        faces = detect_result.get("faces", [])
        if not faces:
            return {"error": "No faces found in image"}

        image_ref = detect_result.get("image")
        face_data = faces[0]  # Use first detected face

        if on_progress:
            await on_progress(30)

        # Step 2: Search VK database
        params = {
            "image": image_ref,
            "face": face_data,
            "source": source,
            "results": results_count
        }

        result = await self._call_api("searchFace", params)

        if on_progress:
            await on_progress(100)

        if "result" in result:
            return result["result"]
        elif "error" in result:
            error = result["error"]
            logger.error(f"searchFace error: {error}")
            return {"error": error.get("message", str(error)) if isinstance(error, dict) else str(error)}

        return None
