import os
from pathlib import Path
import httpx
from dotenv import load_dotenv

# Load .env from backend directory
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


class PokemonTCGClient:
    """Client for interacting with the Pokemon TCG API."""
    
    BASE_URL = "https://api.pokemontcg.io/v2"
    
    def __init__(self):
        self.api_key = os.getenv("POKEMON_TCG_API_KEY")
        if not self.api_key:
            raise ValueError("POKEMON_TCG_API_KEY environment variable is not set")
        
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
    
    async def search_cards(self, query: str, page: int = 1, page_size: int = 20) -> dict:
        """
        Search for Pokemon cards by name or other attributes.
        
        Args:
            query: Search query (card name, set, etc.)
            page: Page number for pagination
            page_size: Number of results per page
            
        Returns:
            Dictionary containing card data and pagination info
        """
        params = {
            "q": f"name:*{query}*",
            "page": page,
            "pageSize": page_size
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/cards",
                headers=self.headers,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_card_by_id(self, card_id: str) -> dict:
        """
        Get a specific card by its ID.
        
        Args:
            card_id: The unique identifier of the card
            
        Returns:
            Dictionary containing card data
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/cards/{card_id}",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_sets(self) -> dict:
        """
        Get all available card sets.
        
        Returns:
            Dictionary containing set data
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/sets",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
