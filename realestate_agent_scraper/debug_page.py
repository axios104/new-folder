"""Quick test: can nodriver bypass Kasada on realestate.com.au?"""
import asyncio
import sys
from pathlib import Path

OUT = Path("debug_output")
OUT.mkdir(exist_ok=True)

async def main():
    import nodriver as uc

    print("Launching nodriver Chrome...", flush=True)
    browser = await uc.start(
        user_data_dir=str(Path(__file__).parent / ".chrome_profile_nd"),
        lang="en-AU",
    )

    print("Getting page...", flush=True)
    page = await browser.get("https://www.realestate.com.au/find-agent/darwin+city-nt-0800/")

    # Wait for the page to load / Kasada to resolve
    print("Waiting 20s for page load...", flush=True)
    await asyncio.sleep(20)

    # Screenshot
    await page.save_screenshot(str(OUT / "page_screenshot.png"))
    print("Saved screenshot", flush=True)

    # Get page source
    html = await page.get_content()
    (OUT / "page_html.html").write_text(html, encoding="utf-8")
    print(f"Saved HTML ({len(html)} chars)", flush=True)

    # Get body text
    body = await page.query_selector("body")
    body_text = ""
    if body:
        body_text = await body.get_html()  
    body_text_len = len(body_text)
    print(f"Body HTML ({body_text_len} chars)", flush=True)

    # Find all links
    links = await page.query_selector_all("a")
    print(f"Found {len(links)} links", flush=True)

    agent_links = []
    for link in links:
        try:
            href = await link.get_attribute("href") or ""
            if "/agent/" in href:
                text_node = link.text or ""
                agent_links.append({"href": href, "text": text_node[:80]})
        except Exception:
            pass

    print(f"Agent links: {len(agent_links)}", flush=True)
    for al in agent_links[:10]:
        print(f"  {al['href']}  |  {al['text']}", flush=True)

    # Kasada check
    if "KPSDK" in html or "ips.js" in html:
        print("\n!! KASADA CHALLENGE DETECTED", flush=True)
    else:
        print("\n>> No Kasada challenge - real page loaded!", flush=True)

    # Show first links if no agent links
    if not agent_links:
        for link in links[:15]:
            try:
                href = await link.get_attribute("href") or ""
                print(f"  Link: {href[:120]}", flush=True)
            except Exception:
                pass

    print(f"URL: {page.url}", flush=True)
    print(f"Title: {await page.get_title()}", flush=True)

    await browser.stop()
    print("Done.", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
