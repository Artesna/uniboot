import os
import asyncio
import random
import shutil
import string
import tempfile
import aiofiles
from aiohttp import web

routes = web.RouteTableDef()


@routes.post("/api/v1/patch")
async def post_api_v1_patch(request: web.Request):
    # Request validation
    try:
        data = await request.post()
    except:
        return web.json_response({"status": "error", "message": "Bad POST payload"}, status=400)

    # Check for boot field
    try:
        boot = data["boot"]
    except:
        return web.json_response({"status": "error", "message": "Boot image was not sent"}, status=400)

    # Create random id (like Magisk does)
    random_id = "".join(random.choice(string.ascii_lowercase + string.ascii_uppercase + string.digits) for _ in range(5))

    # Get filename
    filename = boot.filename.split(".")[0] + "_patched_" + random_id + ".img"

    # Create temporary directory
    temp = tempfile.mkdtemp()

    # Write boot.img
    async with aiofiles.open(temp + "/boot.img", "wb") as f:
        await f.write(boot.file.read())  # pyright: ignore

    # Unpack boot.img
    try:
        await (await asyncio.create_subprocess_exec(
            request.app["config"]["bin"] + "/magiskboot", "unpack", "boot.img",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=temp
        )).communicate()
    except:
        shutil.rmtree(temp)
        return web.json_response({"status": "error", "message": "Unknown error occurred"}, status=500)

    # Create ramdisk directory
    os.mkdir(temp + "/ramdisk")

    # Unpack ramdisk.cpio
    try:
        p = await asyncio.create_subprocess_exec(
            request.app["config"]["bin"] + "/cpio", "-i",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=temp + "/ramdisk"
        )

        async with aiofiles.open(temp + "/ramdisk.cpio", "rb") as f:
            p.stdin.write(await f.read())  # pyright: ignore

        await p.communicate()
    except:
        shutil.rmtree(temp)
        return web.json_response({"status": "error", "message": "Unknown error occurred"}, status=500)

    # Delete old ramdisk.cpio
    os.remove(temp + "/ramdisk.cpio")

    # Patch fastbootd with different methods
    for method in [
        # Realme C21Y (ARM64)
        (
            "ff8302d1fd7b04a9fb2b00f9fa6706a9",  # Original
            "00008052c0035fd6fb2b00f9fa6706a9"   # Modified
        ),
        # Realme C30 (ARM)
        (
            "15f05cef2de9f04389b03c4800247844d0f80080d8f80000",  # Original
            "15f05cef2de9f0430020bde8f0837844d0f80080d8f80000"   # Modified
        ),
        # Realme C11 (2021) (ARM)
        (
            "2de9f04389b0394800247844d0f80080",  # Original
            "2de9f0430020bde8f0437844d0f80080"   # Modified
        )
    ]:
        try:
            await (await asyncio.create_subprocess_exec(
                request.app["config"]["bin"] + "/magiskboot", "hexpatch", "ramdisk/system/bin/fastbootd", method[0], method[1],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp
            )).communicate()
        except:
            shutil.rmtree(temp)
            return web.json_response({"status": "error", "message": "Unknown error occurred"}, status=500)

    # Search for FSR fstabs and disable AVB
    if os.path.isdir(f"{temp}/ramdisk/first_stage_ramdisk"):
        for entry in os.listdir(f"{temp}/ramdisk/first_stage_ramdisk"):
            if entry.startswith("fstab"):
                with open(f"{temp}/ramdisk/first_stage_ramdisk/{entry}", "r") as f:
                    data = f.read() \
                        .replace(",avb_keys=/avb/q-gsi.avbpubkey:/avb/r-gsi.avbpubkey:/avb/s-gsi.avbpubkey", "") \
                        .replace(",avb=vbmeta_system_ext", "") \
                        .replace(",avb=vbmeta_system", "") \
                        .replace(",avb=vbmeta_vendor", "") \
                        .replace(",avb=vbmeta_product", "")

                with open(f"{temp}/ramdisk/first_stage_ramdisk/{entry}", "w") as f:
                    f.write(data)

    # Search for AVB in DTB and disable it
    for dtb_file in ["kernel_dtb", "dtb"]:
        if os.path.isfile(f"{temp}/{dtb_file}"):
            async with aiofiles.open(f"{temp}/{dtb_file}", "rb") as file:
                data = bytearray(await file.read())
                data_len = len(data)

            for index in range(data_len):
                if data[index:index + 9] == b",avb_keys":
                    null_terminator_index = index

                    while data[null_terminator_index] != 0 and null_terminator_index < data_len:
                        null_terminator_index += 1

                    if null_terminator_index != data_len:
                        for avb_keys_index in range(index, null_terminator_index):
                            data[avb_keys_index] = b" "[0]
                elif data[index:index + 4] == b",avb":
                    for avb_index in range(index, index + 4):
                        data[avb_index] = b" "[0]

            async with aiofiles.open(f"{temp}/{dtb_file}", "wb") as file:
                await file.write(data)

    # Repack ramdisk.cpio
    try:
        p = await asyncio.create_subprocess_exec(
            request.app["config"]["bin"] + "/cpio", "-o", "-H", "newc",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=temp + "/ramdisk"
        )

        for root, dirs, files in os.walk(temp + "/ramdisk"):
            for dir in dirs:
                p.stdin.write((root.replace(temp + "/ramdisk", ".") + "/" + dir + "\n").encode())  # pyright: ignore

            for file in files:
                p.stdin.write((root.replace(temp + "/ramdisk", ".") + "/" + file + "\n").encode())  # pyright: ignore

        p.stdin.close()  # pyright: ignore

        async with aiofiles.open(temp + "/ramdisk.cpio", "wb") as f:
            while (data := await p.stdout.read()):  # pyright: ignore
                await f.write(data)

        await p.communicate()
    except:
        shutil.rmtree(temp)
        return web.json_response({"status": "error", "message": "Unknown error occurred"}, status=500)

    # Repack boot.img
    try:
        await (await asyncio.create_subprocess_exec(
            request.app["config"]["bin"] + "/magiskboot", "repack", "boot.img", filename,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=temp
        )).communicate()
    except:
        shutil.rmtree(temp)
        return web.json_response({"status": "error", "message": "Unknown error occurred"}, status=500)

    # Create response with patched boot.img
    async with aiofiles.open(f"{temp}/{filename}", "rb") as f:
        response = web.Response(body=await f.read(), headers={"Content-Disposition": f"filename={filename}"})

    # Cleanup
    shutil.rmtree(temp)

    return response
