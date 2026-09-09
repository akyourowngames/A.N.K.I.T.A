"""Manual browser smoke test against running real services; no fixture graph."""
from pathlib import Path
from playwright.sync_api import sync_playwright

output = Path(__file__).resolve().parents[1] / ".artifacts"
output.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="msedge")
    page = browser.new_page(viewport={"width": 1512, "height": 982}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://localhost:3000/knowledge", wait_until="domcontentloaded")
    page.get_by_label("Search graph").wait_for()
    page.wait_for_function("document.querySelector('.kg-saved')?.textContent !== '0 visible'")
    assert page.locator(".kg-inspector").count() == 0, "Unselected canvas should have no inspector"
    canvas = page.locator(".kg-canvas").bounding_box()
    assert canvas["width"] > 1300 and canvas["height"] > 800, canvas
    page.screenshot(path=str(output / "knowledge-desktop.png"), full_page=True)
    node = page.locator(".kg-canvas").evaluate("(el) => { const cy = el._cyreg.cy; const n = cy.nodes().filter(n => n.degree() > 0).first(); return n.renderedPosition(); }")
    page.mouse.click(canvas["x"] + node["x"], canvas["y"] + node["y"])
    page.locator(".kg-inspector .kg-evidence blockquote").first.wait_for()
    page.screenshot(path=str(output / "knowledge-evidence.png"))
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Add documents", exact=True).click()
    page.get_by_role("dialog", name="Add documents").wait_for()
    page.screenshot(path=str(output / "knowledge-upload.png"))
    page.get_by_role("button", name="Close upload").click()
    page.get_by_role("button", name="Documents", exact=True).click()
    page.get_by_role("button", name="Retry all failed", exact=True).wait_for()
    page.screenshot(path=str(output / "knowledge-documents.png"))
    page.get_by_role("button", name="Return to graph").click()
    page.get_by_role("button", name="Zumba memory", exact=False).click()
    page.get_by_role("heading", name="Your persistent memory").wait_for()
    page.screenshot(path=str(output / "knowledge-memory.png"))
    page.get_by_role("button", name="Return to graph").click()
    page.get_by_role("button", name="Filters", exact=True).click()
    page.get_by_label("Entity type").select_option("")
    page.get_by_role("button", name="Filters", exact=True).click()
    page.get_by_label("Graph layout").select_option("circle")
    page.get_by_role("button", name="Zoom in", exact=True).click()
    page.get_by_role("button", name="Fit graph", exact=True).click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "knowledge-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Horizontal overflow"
    assert not errors, errors
    print("Browser smoke passed: desktop, upload, memory, graph controls, mobile; no page errors.")
    browser.close()
