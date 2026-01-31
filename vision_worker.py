# vision_worker.py
import os
import sys

# Add project root to path for subprocess execution
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from pathlib import Path
import time

# CPU thread limits - set BEFORE importing torch
# This prevents CPU instances from fighting for cores
CPU_THREADS = max(4, os.cpu_count() // 2) if os.cpu_count() else 4
os.environ["OMP_NUM_THREADS"] = str(CPU_THREADS)
os.environ["MKL_NUM_THREADS"] = str(CPU_THREADS)
os.environ["OPENBLAS_NUM_THREADS"] = str(CPU_THREADS)

import torch
from transformers import AutoProcessor, AutoModelForCausalLM
from huggingface_hub import snapshot_download
from PIL import Image
import gc
from core import logger

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Track if running on CPU for throttling
is_cpu_mode = False

SCRIPT_DIR = Path(__file__).parent
MODELS_DIR = SCRIPT_DIR / "models"
FLORENCE_MODEL_DIR = MODELS_DIR / "florence2-large"
REPO_ID = "microsoft/Florence-2-large"

model = None
processor = None
device = None


def load_model(target_device: str):
    global model, processor, device, is_cpu_mode

    if model is not None:
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"[Florence-2 Worker] Model directory: {MODELS_DIR}")

    config_file = FLORENCE_MODEL_DIR / "config.json"
    if not config_file.exists():
        logger.info(f"[Florence-2 Worker] Downloading {REPO_ID} ...")
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(FLORENCE_MODEL_DIR),
            local_dir_use_symlinks=False,
            max_workers=8,
            tqdm_class=None,
        )
        logger.info("[Florence-2 Worker] Download complete!")
    else:
        logger.info("[Florence-2 Worker] Model already exists.")

    # Determine if CPU mode
    is_cpu_mode = not target_device.startswith("cuda")

    # Set PyTorch thread limits for CPU to be friendly
    if is_cpu_mode:
        torch.set_num_threads(CPU_THREADS)
        torch.set_num_interop_threads(max(1, CPU_THREADS // 2))
        logger.info(f"[Florence-2 Worker] CPU mode: using {CPU_THREADS} threads")

    torch_dtype = torch.float16 if target_device.startswith("cuda") else torch.float32
    device = torch.device(target_device)

    logger.info(f"[Florence-2 Worker] Loading model onto {device} ...")
    processor = AutoProcessor.from_pretrained(str(FLORENCE_MODEL_DIR), trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(FLORENCE_MODEL_DIR),
        trust_remote_code=True,
        torch_dtype=torch_dtype,
    ).to(device).eval()

    logger.info(f"[Florence-2 Worker] Loaded successfully on {device}")


def generate_caption(image_path: str, detailed: bool = True) -> str:
    global model, processor, device

    if model is None:
        return "[ERROR] Model not loaded"

    try:
        image = Image.open(image_path).convert("RGB")
        image_size = (image.width, image.height)

        task_prompt = "<MORE_DETAILED_CAPTION>" if detailed else "<CAPTION>"
        inputs = processor(text=task_prompt, images=image, return_tensors="pt").to(device, model.dtype)

        with torch.no_grad():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=200,
                do_sample=False,
                num_beams=3,
            )

        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(generated_text, task=task_prompt, image_size=image_size)
        caption = parsed.get(task_prompt, "").strip()

        return caption

    except Exception as e:
        return f"[ERROR] {str(e)}"


def full_analysis(image_path: str, request_id: int = None, need_objects: bool = True) -> dict:
    global model, processor, device, is_cpu_mode

    if model is None:
        return {"error": "Model not loaded"}

    try:
        image = Image.open(image_path).convert("RGB")
        image_size = (image.width, image.height)

        def run_task(task_prompt: str, max_new_tokens: int = 1024):
            inputs = processor(text=task_prompt, images=image, return_tensors="pt").to(device, model.dtype)

            with torch.no_grad():
                generated_ids = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                    num_beams=3,
                )

            generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed = processor.post_process_generation(generated_text, task=task_prompt, image_size=image_size)
            return parsed.get(task_prompt, {} if '<OD>' in task_prompt else "")

        results = {"caption": "", "objects": []}

        # Always run detailed caption
        caption = run_task('<MORE_DETAILED_CAPTION>', max_new_tokens=300)

        # Remove common repetitive prefixes and clean up capitalization
        prefixes = [
            "The image shows ",
            "The image is ",
            "The image depicts ",
            "The photo shows ",
            "The picture shows ",
            "This image shows ",
            "The image features "
        ]

        cleaned = caption.strip()
        for prefix in prefixes:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()
                break

        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]

        results["caption"] = cleaned

        # Only run object detection if requested
        if need_objects:
            od = run_task('<OD>', max_new_tokens=300)
            objects = od.get('labels', [])
            unique_objects = list(set(obj.strip().lower() for obj in objects if obj.strip() and len(obj.strip()) > 2))
            unique_objects.sort()
            results["objects"] = unique_objects

        # CPU throttle: small delay to prevent system overload
        if is_cpu_mode:
            time.sleep(0.1)  # 100ms breathing room

        return results

    except Exception as e:
        return {"error": str(e)}


def unload():
    global model, processor
    if model is not None:
        del model
        model = None
    if processor is not None:
        del processor
        processor = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    logger.info("[Florence-2 Worker] Unloaded.")


def main():
    logger.info("=== FLORENCE-2 WORKER STARTED ===")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
            command = data.get("command")

            if command == "load":
                target_device = data.get("device", "cpu")
                load_model(target_device)
                print(json.dumps({"status": "loaded"}), flush=True)

            elif command == "caption":
                if model is None:
                    print(json.dumps({"error": "Model not loaded", "request_id": data.get("request_id")}), flush=True)
                    continue
                image_path = data["image_path"]
                detailed = data.get("detailed", True)
                caption = generate_caption(image_path, detailed)
                print(json.dumps({"caption": caption, "request_id": data.get("request_id")}), flush=True)

            elif command == "full_analysis":
                if model is None:
                    print(json.dumps({"error": "Model not loaded", "request_id": data.get("request_id")}), flush=True)
                    continue
                image_path = data["image_path"]
                req_id = data.get("request_id")
                need_objects = data.get("need_objects", True)
                result = full_analysis(image_path, req_id, need_objects)
                print(json.dumps({"analysis": result, "request_id": req_id}), flush=True)

            elif command == "exit":
                unload()
                break

        except Exception as e:
            print(json.dumps({"error": str(e), "request_id": data.get("request_id")}), flush=True)

    logger.info("=== FLORENCE-2 WORKER EXITING ===")


if __name__ == "__main__":
    main()
