"""Default clock/battery capsule and passive amber Mochi."""
import asyncio
import json
from pathlib import Path
import time

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'tasks/capsule-default'
RUN = OUTPUT / f'browser-{time.time_ns()}'


async def main():
    RUN.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 760, 'height': 700})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.clock.install()
        await page.goto('http://127.0.0.1:1420')
        surface, mochi = page.locator('.surface'), page.locator('.character')
        await expect(surface).to_have_attribute('data-mode', 'rest')
        await expect(surface).to_have_css('width', '288px')
        await expect(surface).to_have_css('height', '32px')
        await expect(surface).to_have_css('background-color', 'rgb(0, 0, 0)')
        await expect(page.locator('.clock-time')).to_be_visible()
        await expect(page.locator('.clock-date')).to_be_visible()
        await expect(mochi).to_have_attribute('role', 'img')
        await expect(mochi.locator('svg .orb-body')).to_have_count(1)
        await expect(page.locator('canvas,.mochi-overview,.mochi-popover')).to_have_count(0)

        before = await surface.bounding_box()
        for _ in range(3):
            await mochi.click()
        assert await surface.bounding_box() == before
        assert await mochi.get_attribute('data-reaction') is None
        await expect(mochi.locator('.orb-body')).to_have_css('animation-name', 'none')
        await expect(surface).to_have_attribute('data-mode', 'rest')
        await page.screenshot(path=str(RUN / 'default-capsule.png'))

        await page.locator('.rest-clock').click()
        command = page.get_by_role('combobox', name='FRIDAY command')
        await expect(command).to_be_visible()
        await expect(surface).to_have_css('width', '640px')
        await command.fill('Keep this command draft')
        for _ in range(3):
            await mochi.click()
        await expect(command).to_have_value('Keep this command draft')
        assert await command.evaluate('node => document.activeElement === node')
        await expect(page.locator('.mochi-popover')).to_have_count(0)
        await expect(mochi.locator('.orb-body')).to_have_css('animation-name', 'none')

        await page.get_by_role('button', name='Settings', exact=True).first.click()
        await page.get_by_role('button', name='Look', exact=True).click()
        setting = page.get_by_label('When idle')
        await setting.evaluate('node => { node.dataset.kept = "same DOM"; }')
        for _ in range(3):
            await mochi.click()
        await expect(setting).to_have_attribute('data-kept', 'same DOM')
        await page.keyboard.press('Escape')
        await page.mouse.move(0, 500)
        await expect(surface).to_have_attribute('data-mode', 'rest')
        await expect(surface).to_have_css('width', '288px')
        await expect(page.locator('.clock-time')).to_be_visible()
        assert not errors, errors
        result = {'passed': True, 'default_capsule': True, 'no_click_reaction': True,
            'command_draft_and_focus_preserved': True, 'settings_preserved': True,
            'browser_errors': errors, 'screenshots': RUN.relative_to(ROOT).as_posix()}
        (OUTPUT / 'browser.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
