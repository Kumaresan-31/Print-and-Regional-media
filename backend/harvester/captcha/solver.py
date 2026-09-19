import base64
import io
import re
import time
import logging
from typing import Optional, Dict, Any
from PIL import Image, ImageEnhance, ImageFilter
from harvester.config import settings

logger = logging.getLogger(__name__)


class CaptchaSolver:
    """
    Pluggable Anti-Bot & Captcha Solving Manager:
    - Stealth browser profile injection
    - Local OCR solver for alphanumeric image challenges
    - Remote 2Captcha / Anti-Captcha integration
    - Human-in-the-loop manual fallback
    """

    def __init__(self):
        self.pending_human_challenges: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def get_stealth_scripts() -> str:
        """
        JavaScript payload injected into Playwright pages to mask automation flags.
        """
        return """
        // Overwrite the `languages` property to use a custom getter.
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en', 'hi', 'te', 'ta'],
        });

        // Overwrite the `plugins` property to use a custom getter.
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Pass the Webdriver Test.
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        // Pass the Chrome Test.
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // Pass the Permissions Test.
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """

    def preprocess_captcha_image(self, image_bytes: bytes) -> Image.Image:
        """
        Cleans and thresholds an image to maximize OCR accuracy on distorted captchas.
        """
        img = Image.open(io.BytesIO(image_bytes)).convert("L")  # Convert to grayscale
        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        # Apply median filter to remove noise artifacts
        img = img.filter(ImageFilter.MedianFilter(size=3))
        # Binarize thresholding
        threshold = 140
        img = img.point(lambda p: 255 if p > threshold else 0)
        return img

    def solve_image_ocr(self, image_bytes: bytes) -> Optional[str]:
        """
        Solves image captcha using local OCR engine (RapidOCR / PyTesseract / easyocr).
        """
        try:
            # First try RapidOCR if available
            try:
                from rapidocr import RapidOCR
                engine = RapidOCR()
                processed = self.preprocess_captcha_image(image_bytes)
                buf = io.BytesIO()
                processed.save(buf, format="PNG")
                result, _ = engine(buf.getvalue())
                if result:
                    text = "".join([item[1] for item in result])
                    cleaned = re.sub(r'[^a-zA-Z0-9]', '', text)
                    if cleaned:
                        logger.info(f"Local RapidOCR solved captcha: {cleaned}")
                        return cleaned
            except ImportError:
                pass

            # Next try PyTesseract
            try:
                import pytesseract
                processed = self.preprocess_captcha_image(image_bytes)
                text = pytesseract.image_to_string(
                    processed,
                    config='--psm 8 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                )
                cleaned = re.sub(r'[^a-zA-Z0-9]', '', text)
                if cleaned:
                    logger.info(f"Local Tesseract solved captcha: {cleaned}")
                    return cleaned
            except (ImportError, Exception):
                pass

        except Exception as e:
            logger.warning(f"Local OCR solve encountered error: {e}")

        return None

    def solve_twocaptcha(self, sitekey: str, page_url: str) -> Optional[str]:
        """
        Solves reCAPTCHA/Turnstile via 2Captcha API.
        """
        if not settings.twocaptcha_api_key:
            logger.warning("2Captcha requested but TWOCAPTCHA_API_KEY is not configured.")
            return None

        import requests
        try:
            # Request token
            req_url = f"http://2captcha.com/in.php?key={settings.twocaptcha_api_key}&method=userrecaptcha&googlekey={sitekey}&pageurl={page_url}&json=1"
            res = requests.get(req_url, timeout=15).json()
            if res.get("status") != 1:
                logger.error(f"2Captcha submission failed: {res}")
                return None

            request_id = res.get("request")
            logger.info(f"2Captcha task submitted, id: {request_id}. Polling solution...")

            for _ in range(24):  # Poll up to 120 seconds
                time.sleep(5)
                poll_url = f"http://2captcha.com/res.php?key={settings.twocaptcha_api_key}&action=get&id={request_id}&json=1"
                poll_res = requests.get(poll_url, timeout=15).json()
                if poll_res.get("status") == 1:
                    token = poll_res.get("request")
                    logger.info("2Captcha successfully resolved token!")
                    return token
                if poll_res.get("request") != "CAPCHA_NOT_READY":
                    logger.error(f"2Captcha returned error: {poll_res}")
                    break
        except Exception as e:
            logger.error(f"Error communicating with 2Captcha: {e}")

        return None

    def register_human_challenge(self, challenge_id: str, prompt: str, image_bytes: Optional[bytes] = None) -> str:
        """
        Registers an interactive challenge requiring human resolution from the web dashboard.
        """
        img_b64 = None
        if image_bytes:
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")

        self.pending_human_challenges[challenge_id] = {
            "id": challenge_id,
            "prompt": prompt,
            "image_b64": img_b64,
            "solution": None,
            "created_at": time.time(),
        }
        logger.warning(f"Registered manual captcha challenge '{challenge_id}'. Awaiting human input.")
        return challenge_id

    def submit_human_solution(self, challenge_id: str, solution: str) -> bool:
        if challenge_id in self.pending_human_challenges:
            self.pending_human_challenges[challenge_id]["solution"] = solution
            logger.info(f"Received human solution for captcha challenge '{challenge_id}'")
            return True
        return False

    def wait_for_human_solution(self, challenge_id: str, timeout_seconds: int = 120) -> Optional[str]:
        start = time.time()
        while time.time() - start < timeout_seconds:
            if challenge_id in self.pending_human_challenges:
                sol = self.pending_human_challenges[challenge_id].get("solution")
                if sol:
                    del self.pending_human_challenges[challenge_id]
                    return sol
            time.sleep(1)
        return None


captcha_solver = CaptchaSolver()
