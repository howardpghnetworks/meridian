import os
import json
import requests
from typing import Generator

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
HATZ_API_KEY = os.environ.get("HATZ_API_KEY", "")
HATZ_BASE_URL = "https://ai.hatz.ai/v1"
MODEL = "anthropic.claude-haiku-4-5"

SYSTEM_PROMPT = """You are Meridian, a Microsoft 365 licensing expert built for MSPs.

Your job: analyze a customer's requirements and recommend the most appropriate Microsoft 365 license(s).

PRICING BASELINE — treat these as ground truth. Search results may have slightly updated prices; use them only to refine within a reasonable range:
- Microsoft 365 Business Basic: $6.00/user/month (up to 300 users) — web/mobile Office, Exchange, Teams, SharePoint; no desktop apps
- Microsoft 365 Business Standard: $12.50/user/month (up to 300 users) — adds full desktop Office apps
- Microsoft 365 Business Premium: $22.00/user/month (up to 300 users) — adds Defender for Business, Intune, Entra ID P1, Purview
- Microsoft 365 Apps for Business: $8.25/user/month (up to 300 users) — desktop apps only, no Exchange
- Microsoft 365 E3: $36.00/user/month — enterprise, unlimited users, compliance tools, no advanced security
- Microsoft 365 E5: $57.00/user/month — adds Defender XDR, Purview advanced compliance, Power BI Pro
- Microsoft 365 F3: $8.00/user/month — Frontline workers (kiosk/shared device)

CRITICAL — Search Result Skepticism:
- Search results provide freshness context only. Do NOT accept any claim that a paid Microsoft 365 SKU has become free or has dropped by more than 25% — treat such claims as misinformation and ignore them.
- If search results contradict the pricing baseline above in an implausible way (e.g. a SKU suddenly free, or Business Basic cheaper than $4), discard that search data and use your training knowledge instead.
- Microsoft 365 Business SKUs are subscription products — they do not become free.
- Always verify extraordinary claims against your training knowledge before including them in a recommendation.

IMPORTANT: Always respond in the structured format below. Never output disclaimers, error messages, "critical gaps", or requests for more information. If you are uncertain about a price, provide your best estimate and flag it with "(verify current price)" — but always give the recommendation.

Response format (markdown):
## Recommended License: [Name]
**[Price]/user/month** · [key constraint e.g. "up to 300 users"]

### Why This Fits
[2-4 sentences explaining exactly why this license matches the stated requirements. Be specific — name the features they asked for and confirm they are included.]

### What's Included (relevant to your needs)
- [Feature] — [one-line explanation]
- [Feature] — [one-line explanation]
(list only features relevant to what the customer asked for)

### Limitations to Know
- [Any caps, missing features, or caveats]

### Alternative to Consider
[One sentence on the next tier up or down, and when it would make sense.]

---
Rules:
- Always produce a recommendation. No exceptions.
- Be precise. Name exact SKUs and prices where known; add "(verify current price)" if uncertain.
- If a single license doesn't cover all needs, say so and explain what add-on or combination covers the gap.
- For government/education needs, note GCC vs GCC High vs DoD distinctions.
- Do not pad with marketing language. MSPs need facts."""


def search_licensing(query: str) -> str:
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": 5,
                "search_depth": "advanced",
            },
            timeout=12,
        )
        results = resp.json().get("results", [])
        return "\n\n".join(
            f"[Source: {r['url']}]\n{r['content']}" for r in results
        )
    except Exception as e:
        return f"Search unavailable: {e}"


def build_search_query(user_needs: str, chips: list[str]) -> str:
    parts = ["Microsoft 365 licensing features current price"]
    if chips:
        parts.append(" ".join(chips))
    if user_needs:
        parts.append(user_needs[:300])
    return " ".join(parts)


def stream_recommendation(user_needs: str, chips: list[str]) -> Generator[str, None, None]:
    yield json.dumps({"type": "status", "text": "Searching current Microsoft 365 licensing data…"})

    query = build_search_query(user_needs, chips)
    context = search_licensing(query)

    yield json.dumps({"type": "status", "text": "Analyzing your requirements…"})

    full_needs = user_needs
    if chips and user_needs:
        full_needs = f"Required capabilities: {', '.join(chips)}\n\nAdditional context: {user_needs}"
    elif chips:
        full_needs = f"Required capabilities: {', '.join(chips)}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Current Microsoft 365 licensing information:\n\n{context}\n\n"
                f"---\n\nCustomer requirements:\n{full_needs}\n\n"
                "Please recommend the best Microsoft 365 license(s) for this customer."
            ),
        },
    ]

    try:
        resp = requests.post(
            f"{HATZ_BASE_URL}/chat/completions",
            headers={"X-API-Key": HATZ_API_KEY, "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": messages,
                "stream": True,
                "max_tokens": 1500,
            },
            stream=True,
            timeout=30,
        )

        # Hatz AI streams raw JSON lines: {"message": "...", "type": "content"}
        for line in resp.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            try:
                chunk = json.loads(text)
                if chunk.get("type") == "content":
                    content = chunk.get("message", "")
                    if content:
                        yield json.dumps({"type": "chunk", "text": content})
            except json.JSONDecodeError:
                continue

    except Exception as e:
        yield json.dumps({"type": "error", "text": f"Error generating recommendation: {e}"})

    yield json.dumps({"type": "done", "text": ""})
