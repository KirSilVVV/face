import asyncio
import aiohttp
from src.config import FACECHECK_API_KEY, FACECHECK_BASE_URL


class FaceCheckClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or FACECHECK_API_KEY
        self.base_url = FACECHECK_BASE_URL

    async def upload_image(self, image_bytes: bytes, filename: str = "photo.jpg") -> str | None:
        """Upload image and get search ID."""
        headers = {"Authorization": self.api_key}

        form = aiohttp.FormData()
        form.add_field("images", image_bytes, filename=filename, content_type="image/jpeg")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/upload_pic",
                headers=headers,
                data=form
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("id_search")
                return None

    async def search(self, id_search: str, demo: bool = True) -> dict | None:
        """Execute face search and wait for results."""
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "id_search": id_search,
            "with_progress": True,
            "status_only": False,
            "demo": demo
        }

        async with aiohttp.ClientSession() as session:
            while True:
                async with session.post(
                    f"{self.base_url}/search",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status != 200:
                        return None

                    data = await response.json()

                    if data.get("error"):
                        return {"error": data.get("error")}

                    progress = data.get("progress")
                    if progress and progress >= 100:
                        return data

                    await asyncio.sleep(2)

    async def find_face(self, image_bytes: bytes, demo: bool = True) -> dict | None:
        """Full pipeline: upload image and search."""
        id_search = await self.upload_image(image_bytes)
        if not id_search:
            return {"error": "Failed to upload image"}

        return await self.search(id_search, demo=demo)
