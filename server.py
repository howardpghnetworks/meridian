"""FastAPI wrapper for Docker/Azure deployment."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lib.advisor import stream_recommendation

app = FastAPI(title="Meridian", description="Microsoft 365 Licensing Advisor")


class AdviseRequest(BaseModel):
    needs: str = ""
    chips: list[str] = []


@app.post("/api/advise")
def advise(req: AdviseRequest):
    def generate():
        for event in stream_recommendation(req.needs, req.chips):
            yield f"data: {event}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


app.mount("/", StaticFiles(directory="public", html=True), name="static")
