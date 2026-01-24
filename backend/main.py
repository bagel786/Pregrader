from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx

from services.pokemon_tcg import PokemonTCGClient

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Pokemon Pregrader API",
    description="Backend API for Pokemon card pre-grading application",
    version="1.0.0"
)

# Configure CORS for Flutter app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the Pokemon TCG client
pokemon_client = PokemonTCGClient()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/cards/search")
async def search_cards(
    q: str = Query(..., description="Search query for card name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page")
):
    """
    Search for Pokemon cards by name.
    
    Args:
        q: Search query (card name)
        page: Page number for pagination
        page_size: Number of results per page (max 100)
        
    Returns:
        List of matching cards with metadata
    """
    try:
        result = await pokemon_client.search_cards(q, page, page_size)
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/cards/{card_id}")
async def get_card(card_id: str):
    """
    Get a specific card by its ID.
    
    Args:
        card_id: The unique identifier of the card
        
    Returns:
        Card data including images, prices, and metadata
    """
    try:
        result = await pokemon_client.get_card_by_id(card_id)
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Card not found")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/sets")
async def get_sets():
    """
    Get all available Pokemon card sets.
    
    Returns:
        List of all sets with metadata
    """
    try:
        result = await pokemon_client.get_sets()
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Pokemon TCG API error: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
