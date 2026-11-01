# ruff: noqa: E501
import asyncio
import json

from patchright.async_api import async_playwright


async def main():
    rows = []
    async with async_playwright() as p:
        for name, args in [
            ("default", []),
            ("angle-gl", ["--use-gl=angle", "--use-angle=gl"]),
            ("angle-egl", ["--use-gl=angle", "--use-angle=gles"]),
            ("angle-gl-unblocked", ["--use-gl=angle", "--use-angle=gl", "--ignore-gpu-blocklist"]),
        ]:
            try:
                b = await p.chromium.launch(headless=False, args=args)
                page = await b.new_page()
                value = await page.evaluate(
                    """() => {const c=document.createElement('canvas');const gl=c.getContext('webgl');const ext=gl&&gl.getExtension('WEBGL_debug_renderer_info');return {webgl:!!gl,webgl2:!!document.createElement('canvas').getContext('webgl2'),vendor:ext?gl.getParameter(ext.UNMASKED_VENDOR_WEBGL):null,renderer:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):null};}"""
                )
                rows.append({"profile": name, "args": args, **value})
                await b.close()
            except Exception as e:
                rows.append({"profile": name, "error": str(e)[:500]})
    print(json.dumps(rows, indent=2))


asyncio.run(main())
