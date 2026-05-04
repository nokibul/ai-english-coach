# AI English Learner

An image-to-English learning web app that turns uploaded photos into reusable study sessions with:

- image-based lesson generation
- simple and natural scene explanations
- saved vocabulary, phrases, and sentence patterns
- session quizzes plus adaptive mixed review
- spaced repetition with later review scheduling
- a daily 5-minute challenge
- XP, streaks, learner levels, and progress tracking
- email + password login with email OTP verification
- learner levels: `Beginner`, `Developing`, and `Advancing`

## Stack

- Backend: Python `aiohttp` + `sqlite3`
- Frontend: vanilla HTML, CSS, and JavaScript
- AI analysis: local vLLM-served Qwen vision-language model through the OpenAI-compatible API, with optional OpenAI hosted fallback

## Run it

1. Create a `.env` file from `.env.example`.
2. Create a virtual environment and install the requirements:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

3. Download Qwen2.5-VL-7B-Instruct-AWQ if you want local inference:

```bash
./scripts/download_qwen25_vl_awq.sh
```

By default this stores local model weights in `models/`, separate from app runtime
data. You can also set `MODEL_STORAGE_DIR=/path/to/models` or pass a destination
folder as the first script argument.

4. Start the vLLM server:

```bash
./scripts/start_vllm_qwen25_vl_awq.sh
```

This serves `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` at `http://127.0.0.1:8000/v1` using vLLM's AWQ-Marlin path by default. Set `VLLM_QUANTIZATION=awq` before running the script if you need plain AWQ.

5. In a second terminal, start the app:

```bash
.venv/bin/python app.py
```

6. Open `http://127.0.0.1:8099`

## Important setup notes

- Runtime app data lives in `app_data/` by default. That folder contains
  `english_learner.sqlite3` and uploaded images under `uploads/`, and sits next
  to `english_learner_app/`.
- Model weights are deliberately separate from the app database and uploads. The
  helper scripts use `models/` by default, and the Python app only talks to a
  configured AI backend (`vllm`, `openai`, or `demo`).
- To change app data locations, set `APP_DATA_DIR`, or set `DATABASE_PATH` and
  `UPLOADS_DIR` separately.
- `AI_BACKEND=vllm` keeps image analysis on your machine through a local vLLM OpenAI-compatible server.
- Qwen2.5-VL does not publish an official 8B checkpoint. This project uses the 7B AWQ checkpoint because it fits and runs locally on an RTX 3060 12 GB.
- `IMAGE_MAX_PIXELS` controls Qwen's image token budget before the app sends images to vLLM. Higher values may improve tiny-detail recognition but slow down uploads.
- The app queues local image-analysis calls and releases them to vLLM in short bursts so vLLM can continuously batch concurrent uploads. Tune `VLLM_MAX_CONCURRENCY`, `VLLM_BATCH_INTERVAL_MS`, and `VLLM_BATCH_MAX_SIZE` to match your GPU and `vllm serve` settings.
- When using local image files with vLLM, launch the server with `--allowed-local-media-path /home/nokib/ai/app_data/uploads`, or set `VLLM_ALLOWED_MEDIA_PATH` to match your `UPLOADS_DIR`.
- `DEMO_MODE=true` still lets the full product flow run without a live model. Uploads still create lessons, quiz items, review items, and progress updates, but the lesson content is demo content.
- To use hosted inference instead, set `AI_BACKEND=openai`, `DEMO_MODE=false`, and provide `OPENAI_API_KEY`.
- If SMTP is not configured, OTP codes are printed to the terminal so you can still verify accounts during development.
- Login and signup use email + password. Signup sends an email OTP before the account can log in.
- To send real OTP emails, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_SENDER`. For Gmail, use `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_STARTTLS=true`, `SMTP_USERNAME=<your Gmail address>`, `SMTP_PASSWORD=<a Google App Password>`, and `SMTP_SENDER=<your Gmail address>`.

## Product behavior

- Each uploaded image becomes a saved learning session with structured objects, actions, vocabulary, phrases, and quiz seeds.
- Review items are scheduled with default intervals of 1 hour, 1 day, 3 days, and 7 days, then adapted based on learner performance.
- Quiz selection prioritizes due review items, weak areas, and learner level so beginners see more support and strong learners get more production tasks.
- The daily challenge mixes due items, weak areas, and recent session content into a short 5-question run.
- Progress tracking includes XP, streaks, learner level, mastered words, mastered phrases, and a weekly accuracy summary.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
