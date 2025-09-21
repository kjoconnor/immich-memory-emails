from datetime import datetime
from urllib.parse import urljoin

import requests


class Immich:
    def __init__(self, immich_base_url: str, api_token: str):
        self._immich_base_url = immich_base_url
        self._session = requests.Session()
        self._session.headers = {"X-Api-Key": api_token}

    def search_random(
        self, taken_before: datetime, taken_after: datetime, person_id: str
    ) -> list[dict]:
        response = self._session.post(
            urljoin(self._immich_base_url, "/api/search/random"),
            json={
                "takenBefore": taken_before.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3]
                + "Z",
                "takenAfter": taken_after.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z",
                "personIds": [
                    person_id,
                ],
                "type": "IMAGE",
            },
        )

        response.raise_for_status()

        return response.json()

    def download_asset(self, id: str) -> bytes:
        response = self._session.get(
            urljoin(self._immich_base_url, f"/api/assets/{id}/original")
        )

        response.raise_for_status()

        return response.content
