import httpx
from app.config import settings

class TellerClient:
    base_url="https://api.teller.io"

    def __init__(self, access_token: str):
        self.access_token=access_token

    async def _get(self, path: str, params=None):
        cert = None
        if settings.teller_cert_path and settings.teller_key_path:
            cert=(settings.teller_cert_path, settings.teller_key_path)
        async with httpx.AsyncClient(cert=cert, timeout=30) as c:
            r=await c.get(
                self.base_url+path,
                params=params,
                auth=(self.access_token,""),
                headers={"Teller-Version":"2020-10-12"},
            )
            r.raise_for_status()
            return r.json()

    async def accounts(self):
        return await self._get("/accounts")

    async def transactions(self, account_id: str, start_date=None, end_date=None):
        params={k:v for k,v in {"start_date":start_date,"end_date":end_date}.items() if v}
        return await self._get(f"/accounts/{account_id}/transactions", params=params)
