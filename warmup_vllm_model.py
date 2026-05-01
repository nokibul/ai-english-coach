from __future__ import annotations

import asyncio

from english_learner_app.ai_service import AIAnalyzer
from english_learner_app.config import AppConfig


async def main() -> None:
    config = AppConfig.from_env()
    analyzer = AIAnalyzer(config)
    try:
        await analyzer.warmup_vllm_model()
        print(f"vLLM model is ready: {config.vllm_model}")
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
