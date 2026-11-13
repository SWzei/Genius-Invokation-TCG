"""Browser end-to-end run of the lab (driven by ``tests/test_lab.py::test_browser_end_to_end``).

    python tests/e2e/lab_browser.py http://127.0.0.1:8780/ [screenshot dir]

Needs Playwright with a Chromium build. Plays a human-vs-model game through the page
(moves, advice, discussion, feedback, autopilot), reviews it, compares policies,
exports a corpus, then runs an AI-vs-AI game with one human override. Prints one
JSON line with what it saw.
"""

from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright


def main() -> int:
    base = sys.argv[1]
    shots = sys.argv[2] if len(sys.argv) > 2 else None
    report = {"console_errors": [], "human_moves": 0, "finished": False, "advice_shown": False,
              "chat_answered": False, "feedback_saved": False, "review_decisions": 0, "compare_rows": 0,
              "export_ok": False, "intervene_overrides": 0}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: report["console_errors"].append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: report["console_errors"].append(str(e)))

        def shot(name: str) -> None:
            if shots:
                page.screenshot(path=f"{shots}/{name}.png", full_page=True)

        # ---- human (seat 1) vs a model (seat 0) ----------------------------------
        page.goto(base)
        page.wait_for_selector("#deck0 option", state="attached")
        shot("lab_new")
        page.select_option("#kind0", "llm")
        page.select_option("#model0", "mock")
        page.select_option("#deck0", "natlan_battleship")
        page.select_option("#deck1", "superconduct_aggro")
        page.click("#start")
        while report["human_moves"] < 8:
            page.wait_for_selector("#action-body .opt, #confirm-pick, #to-review", timeout=60000)
            if page.query_selector("#to-review"):
                break
            if page.query_selector("#confirm-pick"):
                picks = page.query_selector_all("#board [data-pos]")
                if picks and report["human_moves"] % 2 == 0:
                    picks[0].click()
                page.click("#confirm-pick")
            else:
                page.query_selector_all("#action-body .opt")[0].click()
            report["human_moves"] += 1
            time.sleep(0.3)
        page.wait_for_selector("#advise", timeout=60000)
        shot("lab_play")
        page.click("#advise")
        page.wait_for_selector("#action-body .banner", timeout=20000)
        report["advice_shown"] = "的建议" in page.inner_text("#action-body .banner")
        page.click('#view-play .tabs button[data-tab="chat"]')
        page.fill("#chat-q", "现在该怎么打？")
        page.click("#chat-send")
        page.wait_for_selector("#chat-list .a", timeout=20000)
        report["chat_answered"] = bool(page.inner_text("#chat-list .a").strip())
        # rate the model's last move (its options are private while the game runs)
        page.click('#view-play .tabs button[data-tab="log"]')
        page.locator("#log div", has_text="0 号位").last.click()
        page.click('#view-play .tabs button[data-tab="decision"]')
        page.click('#tab-decision [data-rate="-1"]')
        page.wait_for_function("document.querySelector('#fb-saved').textContent.includes('已保存')", timeout=10000)
        report["feedback_saved"] = True
        page.click("#autopilot")
        page.wait_for_selector("#to-review", timeout=120000)
        report["finished"] = "获胜" in page.inner_text("#play-banner") or "平局" in page.inner_text("#play-banner")
        shot("lab_end")

        # ---- review, correction, comparison, export ------------------------------
        page.click("#to-review")
        page.wait_for_selector("#rv-log div", timeout=30000)
        report["review_decisions"] = len(page.query_selector_all("#rv-log div"))
        page.select_option("#rv-view", "0")
        page.wait_for_timeout(600)
        page.locator("#rv-log div", has_text="0 号位 · 策略").nth(3).click()
        page.wait_for_selector("#rfb-pref", timeout=10000)
        page.select_option("#rfb-pref", index=1)
        page.fill("#rfb-comment", "回放中的纠正")
        page.click('#rv-detail [data-rate="-1"]')
        page.wait_for_selector("#rv-options .preferred", timeout=10000)
        page.fill("#cmp-specs", "heuristic llm:mock")
        page.click("#cmp-run")
        page.wait_for_selector("#cmp-out table tr:nth-child(2)", timeout=120000)
        report["compare_rows"] = len(page.query_selector_all("#cmp-out table tr")) - 1
        shot("lab_review")
        page.locator("#sessions input[type=checkbox]").first.check()
        page.fill("#export-name", f"e2e_{int(time.time())}")
        page.click("#export-bc")
        page.wait_for_function("document.querySelector('#export-out').textContent.length > 10", timeout=120000)
        report["export_ok"] = "已写入" in page.inner_text("#export-out")

        # ---- AI vs AI with one human override ------------------------------------
        page.click('header nav button[data-view="new"]')
        page.select_option("#kind0", "policy")
        page.select_option("#kind1", "policy")
        page.check("#intervene")
        page.click("#start")
        for step in range(40):
            page.wait_for_selector("#approve, #to-review", timeout=60000)
            if page.query_selector("#to-review"):
                break
            options = page.query_selector_all("#action-body button.opt")
            if report["intervene_overrides"] == 0 and len(options) > 2:
                next(o for o in options if "proposed" not in (o.get_attribute("class") or "")).click()
                report["intervene_overrides"] += 1
                page.wait_for_timeout(500)
                shot("lab_intervene")
                page.wait_for_selector("#approve-all, #to-review", timeout=60000)
                if page.query_selector("#approve-all"):
                    page.click("#approve-all")
                break
            page.click("#approve")
            page.wait_for_timeout(250)
        page.wait_for_selector("#to-review", timeout=120000)
        browser.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
