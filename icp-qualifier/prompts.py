from pathlib import Path
from config import config

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_SCREENSHOT_NOTE = " and a SCREENSHOT of the homepage"

_STYLE_SECTION = """
## TASK 2: Classify the website design

USE THE SCREENSHOT to evaluate visual design. This is your primary source for design classification.

Website_style — choose exactly one:

● Legacy — clearly outdated (pre-2018 feel):
  - Narrow layout, small typography, cramped content, limited whitespace
  - Heavy generic stock photography
  - Cluttered navigation, no clear primary action
  - Weak or missing hero message, no obvious CTA
  - Inconsistent visual language
  - Poor mobile-readiness signals

● Modern — follows recent SaaS/product patterns (2021+):
  - Wide layout, clear hierarchy, generous spacing
  - Large readable typography, consistent styling
  - Strong hero with specific value proposition and clear CTA
  - Consistent visual system, product UI screenshots
  - Clean navigation with clear primary action

● Mixed — between Legacy and Modern:
  - Some sections modern, others dated or inconsistent
  - Modern hero but old stock photos or messy layout elsewhere
  - Reasonable structure but lacking polish

"""

_STYLE_JSON = ',\n  "website_style": "Legacy" or "Mixed" or "Modern"'


def load_prompt() -> str:
    path = PROMPTS_DIR / f"{config.PROFILE}.txt"
    if not path.exists():
        available = [f.stem for f in PROMPTS_DIR.glob("*.txt")]
        raise FileNotFoundError(
            f"Profile '{config.PROFILE}' not found. Available: {available}"
        )

    template = path.read_text(encoding="utf-8")

    if config.USE_SCREENSHOTS:
        template = template.replace("{screenshot_note}", _SCREENSHOT_NOTE)
    else:
        template = template.replace("{screenshot_note}", "")

    if config.PROFILE == "fintech":
        if config.USE_SCREENSHOTS:
            template = template.replace("{style_section}", _STYLE_SECTION)
            template = template.replace("{style_json}", _STYLE_JSON)
        else:
            template = template.replace("{style_section}", "")
            template = template.replace("{style_json}", "")

    return template
