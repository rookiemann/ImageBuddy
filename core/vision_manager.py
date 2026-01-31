# core/vision_manager.py
import subprocess
import json
import threading
import os
import tkinter as tk
from typing import Optional, Callable, Dict, Any
from core import logger


class VisionManager:
    def __init__(self, root: Optional[tk.Tk] = None):
        self.process: Optional[subprocess.Popen] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.root = root
        self.on_loaded_callback = None
        self.on_error_callback = None

        # For async request/response matching
        self.pending_callbacks: Dict[int, Callable[[Dict[str, Any]], None]] = {}
        self.next_request_id = 0

    def load(self, device_spec):
        if self.process is not None:
            self.unload()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        worker_path = os.path.join(script_dir, "..", "vision_worker.py")

        env = os.environ.copy()

        if isinstance(device_spec, int):
            env["CUDA_VISIBLE_DEVICES"] = str(device_spec)
            worker_device = "cuda:0"
        else:
            worker_device = "cpu"

        logger.info("=== STARTING VISION WORKER SUBPROCESS ===")
        logger.info(f"Worker path: {worker_path}")
        logger.info(f"Device spec: {device_spec} -> worker_device: {worker_device}")

        self.process = subprocess.Popen(
            [os.sys.executable, worker_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        def reader():
            logger.debug("[VISION MANAGER] Reader thread started")
            if self.process.stdout is None:
                logger.error("[VISION MANAGER] stdout is None!")
                return

            for line in self.process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                logger.debug(f"[VISION WORKER OUTPUT] {line}")

                try:
                    data = json.loads(line)

                    if data.get("status") == "loaded":
                        logger.info("[VISION] Model loaded callback triggered")
                        if self.on_loaded_callback:
                            if self.root:
                                self.root.after(0, self.on_loaded_callback)
                            else:
                                self.on_loaded_callback()

                    elif "analysis" in data:
                        result = data["analysis"]
                        req_id = data.get("request_id")
                        callback_info = self.pending_callbacks.pop(req_id, None)
                        if callback_info:
                            callback, direct = callback_info if isinstance(callback_info, tuple) else (callback_info, False)
                            if self.root and not direct:
                                self.root.after(0, lambda cb=callback, r=result: cb({"analysis": r}))
                            else:
                                callback({"analysis": result})

                    elif "error" in data:
                        error_msg = data["error"]
                        req_id = data.get("request_id")
                        callback_info = self.pending_callbacks.pop(req_id, None)
                        if callback_info:
                            callback, direct = callback_info if isinstance(callback_info, tuple) else (callback_info, False)
                            if self.root and not direct:
                                self.root.after(0, lambda cb=callback, e=error_msg: cb({"error": e}))
                            else:
                                callback({"error": error_msg})
                        else:
                            if self.on_error_callback:
                                if self.root:
                                    self.root.after(0, lambda e=error_msg: self.on_error_callback(e))
                                else:
                                    self.on_error_callback(error_msg)

                except json.JSONDecodeError:
                    pass

        self.reader_thread = threading.Thread(target=reader, daemon=True)
        self.reader_thread.start()

        # Send load command
        load_cmd = {"command": "load", "device": worker_device}
        try:
            logger.info("=== SENDING LOAD COMMAND ===")
            print(json.dumps(load_cmd), file=self.process.stdin, flush=True)
        except Exception as e:
            logger.error(f"[VISION LOAD SEND FAILED] {e}")

    def send_analysis(
        self,
        image_path: str,
        callback: Callable[[Dict[str, Any]], None],
        need_objects: bool = True,
        direct_callback: bool = False
    ):
        """Send an image for analysis."""
        if not self.is_loaded():
            callback({"error": "Worker not loaded"})
            return

        request_id = self.next_request_id
        self.next_request_id += 1

        if direct_callback:
            self.pending_callbacks[request_id] = (callback, True)
        else:
            self.pending_callbacks[request_id] = callback

        cmd = {
            "command": "full_analysis",
            "image_path": image_path,
            "request_id": request_id,
            "need_objects": need_objects
        }
        try:
            self.process.stdin.write(json.dumps(cmd) + "\n")
            self.process.stdin.flush()
        except Exception as e:
            self.pending_callbacks.pop(request_id, None)
            callback({"error": f"Send failed: {str(e)}"})

    def unload(self):
        self.pending_callbacks.clear()

        if self.process is not None:
            try:
                print(json.dumps({"command": "exit"}), file=self.process.stdin, flush=True)
            except:
                pass

            self.process.kill()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

            self.process = None
            logger.info("=== VISION WORKER TERMINATED ===")

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def is_loaded(self) -> bool:
        return self.process is not None and self.process.poll() is None
