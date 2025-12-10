import re
import html
from urllib.parse import unquote, urlparse, parse_qs
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import httpx

app = FastAPI(title="HoYoLAB Embed Fixer")

# --- Constants ---
HEADERS = {
    "User-Agent": "HoYoLAB/4.3.0",
    "x-rpc-app_version": "4.3.0"
}

# --- Utilities ---

def extract_post_id(url: str):
    """
    Returns dict with {'id': str, 'is_pre_post': bool} or None
    """
    patterns = [
        (r"hoyolab\.com/article_pre/(\d+)", True),
        (r"hoyolab\.com/article/(\d+)", False),
        (r"hoyolab\.com/#/article/(\d+)", False),
        (r"m\.hoyolab\.com/#/article/(\d+)", False),
    ]
    
    for pattern, is_pre_post in patterns:
        match = re.search(pattern, url)
        if match:
            return {"id": match.group(1), "is_pre_post": is_pre_post}
    return None

async def follow_redirects(url: str) -> str:
    """Follows redirects to get the final destination URL."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, follow_redirects=True)
            return str(resp.url)
        except:
            return url

async def resolve_short_query(query_id: str) -> str | None:
    """Handles the transit?q= logic."""
    url = f"https://bbs-api-os.hoyolab.com/community/misc/api/transit?q={query_id}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, follow_redirects=True)
            final_url = str(resp.url)
            
            # Logic from your docs: extracting url from social_sea_share
            if "social_sea_share/redirectUrl" in final_url:
                parsed = urlparse(final_url)
                qs = parse_qs(parsed.query)
                if 'url' in qs:
                    # decodeURIComponent equivalent
                    return unquote(qs['url'][0])
            
            return final_url
        except:
            return None

async def get_actual_post_id(pre_post_id: str) -> str | None:
    """Converts article_pre ID to real Post ID."""
    url = f"https://bbs-api-os.hoyolab.com/community/post/wapi/getPostID?id={pre_post_id}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url)
            data = resp.json()
            return data.get("data", {}).get("post_id")
        except:
            return None

async def fetch_post_data(post_id: str, lang: str = "en-us") -> dict | None:
    """Fetches full post data from HoYoLAB API."""
    url = f"https://bbs-api-os.hoyolab.com/community/post/wapi/getPostFull?post_id={post_id}&read=1&scene=1"
    req_headers = HEADERS.copy()
    req_headers["x-rpc-language"] = lang
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=req_headers)
            data = resp.json()
            if data.get("retcode") != 0:
                return None
            return data["data"]["post"]
        except:
            return None

# --- HTML Generator ---

def generate_embed_html(post: dict, post_url: str) -> str:
    p = post["post"]
    u = post["user"]
    video = post.get("video")
    game = post.get("game", {})
    
    # Image logic
    images = post.get("cover_list") if p.get("has_cover") else post.get("image_list")
    main_image = images[0]["url"] if images else ""
    
    # Video logic
    if p.get("view_type") == 5 and video:
        main_image = video.get("cover", main_image)
        
    # Clean description (remove HTML tags)
    subject = html.escape(p.get("subject", ""))
    clean_desc = html.escape(re.sub(r"<[^>]*>", "", p.get("desc", "")))
    nickname = html.escape(u.get("nickname", ""))
    theme_color = game.get("color", "#25A0E7")
    
    # Gallery HTML
    gallery_html = ""
    if images:
        imgs = "".join([f'<img src="{i["url"]}">' for i in images[:4]])
        gallery_html = f'<div class="image-gallery">{imgs}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta property="og:type" content="article">
<meta property="og:url" content="{post_url}">
<meta property="og:title" content="{subject}">
<meta property="og:description" content="{clean_desc}">
{'<meta property="og:image" content="' + main_image + '">' if main_image else ''}
<meta property="og:site_name" content="HoYoLAB">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{subject}">
<meta name="twitter:description" content="{clean_desc}">
{'<meta name="twitter:image" content="' + main_image + '">' if main_image else ''}
<meta name="theme-color" content="{theme_color}">
<meta name="author" content="{nickname}">
<title>{subject} - HoYoLAB</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto; max-width: 800px; margin: 40px auto; padding: 20px; background: #f5f5f5; }}
  .container {{ background: white; border-radius: 12px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,.1); }}
  .author {{ display:flex; align-items:center; gap:12px; margin-bottom:20px; }}
  .author img {{ width:48px; height:48px; border-radius:50%; }}
  h1 {{ margin:0 0 16px 0; }}
  .image-gallery {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; margin-top:20px; }}
  .image-gallery img {{ width:100%; border-radius:8px; }}
  .redirect-btn {{ display:inline-block; background:{theme_color}; color:white; padding:12px 24px; border-radius:8px; margin-top:20px; text-decoration:none; font-weight:600; }}
</style>
<script>setTimeout(() => {{ window.location.href="{post_url}" }}, 3000);</script>
</head>
<body>
<div class="container">
  <div class="author"><img src="{u['avatar_url']}"><div>{nickname}</div></div>
  <h1>{subject}</h1>
  <div>{clean_desc}</div>
  {gallery_html}
  <a class="redirect-btn" href="{post_url}">View on HoYoLAB</a>
</div>
</body>
</html>"""

# --- Routes ---

@app.get("/")
async def root():
    return {
        "message": "HoYoLAB Embed Fixer (Python)",
        "endpoints": {
            "short_query": "/q?q={query_id}&lang={lang}",
            "short_redirect": "/sh?redirect={short_link_id}",
            "long_link": "/post?post_id={post_id}&lang={lang}",
        }
    }

@app.get("/post")
async def handle_post(post_id: str, lang: str = "en-us"):
    actual_id = post_id
    
    # Handle extremely long IDs (usually pre-post IDs mistakenly passed as direct IDs)
    if len(post_id) > 15:
        resolved = await get_actual_post_id(post_id)
        if resolved:
            actual_id = resolved
            
    post_data = await fetch_post_data(actual_id, lang)
    if not post_data:
        return JSONResponse({"error": "Failed to fetch post"}, status_code=500)
        
    html_content = generate_embed_html(post_data, f"https://www.hoyolab.com/article/{actual_id}")
    return HTMLResponse(content=html_content)

@app.get("/sh")
async def handle_short_link(redirect: str, lang: str = "en-us"):
    if not redirect:
        return JSONResponse({"error": "Missing redirect param"}, status_code=400)
        
    final_url = await follow_redirects(f"https://hoyo.link/{redirect}")
    extracted = extract_post_id(final_url)
    
    # LOGIC UPDATE: Redirect non-HoYoLAB links immediately
    if not extracted:
        return RedirectResponse(final_url)
        
    post_id = extracted["id"]
    if extracted["is_pre_post"]:
        actual = await get_actual_post_id(post_id)
        if not actual:
            return JSONResponse({"error": "Failed to resolve pre-post ID"}, status_code=500)
        post_id = actual
        
    post_data = await fetch_post_data(post_id, lang)
    if not post_data:
        return JSONResponse({"error": "Failed to fetch post"}, status_code=500)
        
    html_content = generate_embed_html(post_data, f"https://www.hoyolab.com/article/{post_id}")
    return HTMLResponse(content=html_content)

@app.get("/q")
async def handle_query_link(q: str, lang: str = "en-us"):
    if not q:
        return JSONResponse({"error": "Missing q param"}, status_code=400)
        
    final_url = await resolve_short_query(q)
    if not final_url:
        return JSONResponse({"error": "Failed to resolve short link"}, status_code=500)
        
    extracted = extract_post_id(final_url)
    
    # LOGIC UPDATE: Redirect non-HoYoLAB links immediately
    if not extracted:
        return RedirectResponse(final_url)
        
    post_id = extracted["id"]
    if extracted["is_pre_post"]:
        actual = await get_actual_post_id(post_id)
        if not actual:
            return JSONResponse({"error": "Failed to resolve pre-post ID"}, status_code=500)
        post_id = actual
        
    post_data = await fetch_post_data(post_id, lang)
    if not post_data:
        return JSONResponse({"error": "Failed to fetch post"}, status_code=500)
        
    html_content = generate_embed_html(post_data, f"https://www.hoyolab.com/article/{post_id}")
    return HTMLResponse(content=html_content)