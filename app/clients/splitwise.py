import httpx

class SplitwiseClient:
    base_url="https://secure.splitwise.com/api/v3.0"

    def __init__(self, access_token: str): self.access_token=access_token

    async def _request(self, method, path, **kwargs):
        headers={"Authorization":f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.request(method, self.base_url+path, headers=headers, **kwargs)
            r.raise_for_status()
            return r.json()

    async def me(self): return await self._request("GET","/get_current_user")
    async def groups(self): return await self._request("GET","/get_groups")
    async def friends(self): return await self._request("GET","/get_friends")
    async def expenses(self, **params): return await self._request("GET","/get_expenses",params=params)

    async def create_expense(self, payload: dict):
        result=await self._request("POST","/create_expense",json=payload)
        if result.get("errors"):
            raise RuntimeError(f"Splitwise rejected expense: {result['errors']}")
        return result
