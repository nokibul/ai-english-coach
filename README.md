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
- AI analysis: OpenAI-compatible cloud API, with a demo fallback for local smoke tests

## Run it

1. Create a `.env` file from `.env.example`.
2. Create a virtual environment and install the requirements:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

3. Configure cloud AI:

```bash
cp -n .env.example .env
nano .env
```

Set these values in `.env`:

```bash
AI_BACKEND=openai
DEMO_MODE=false
OPENAI_API_KEY=<your-api-key>
OPENAI_MODEL=gpt-4.1-mini
```

4. Start the app:

```bash
.venv/bin/python app.py
```

5. Open `http://127.0.0.1:8099`

## Run as a production background service on Amazon Linux EC2

Use systemd so the app keeps running after you close SSH, starts on boot, and
writes logs to `journalctl`.

From your EC2 instance, install the Python runtime and project dependencies:

```bash
cd /path/to/ai
sudo dnf install -y python3 python3-pip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
```

Edit `.env` before starting the service:

```bash
nano .env
```

For direct access from the EC2 public IP, set:

```bash
APP_HOST=0.0.0.0
APP_PORT=8099
APP_SECRET_KEY=<replace-with-a-long-random-secret>
AI_BACKEND=openai
DEMO_MODE=false
OPENAI_API_KEY=<your-api-key>
```

Also allow the port in the EC2 security group, or keep `APP_HOST=127.0.0.1`
when running behind Nginx or another reverse proxy.

On Amazon Linux 2, use `sudo yum install -y python3 python3-pip` instead of
the `dnf` command above.

Install and start the web app service:

```bash
./scripts/install_systemd_services.sh
sudo systemctl start ai-english-learner
sudo systemctl status ai-english-learner
```

After that you can close SSH. The app will keep running in the background and
will start automatically after reboot.

Useful service commands:

```bash
sudo systemctl restart ai-english-learner
sudo systemctl stop ai-english-learner
sudo journalctl -u ai-english-learner -f
```

## Important setup notes

- Runtime app data lives in `app_data/` by default. That folder contains
  `english_learner.sqlite3` and uploaded images under `uploads/`, and sits next
  to `english_learner_app/`.
- To change app data locations, set `APP_DATA_DIR`, or set `DATABASE_PATH` and
  `UPLOADS_DIR` separately.
- `DEMO_MODE=true` still lets the full product flow run without a live model. Uploads still create lessons, quiz items, review items, and progress updates, but the lesson content is demo content.
- To use cloud inference, set `AI_BACKEND=openai`, `DEMO_MODE=false`, and provide `OPENAI_API_KEY`.
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
