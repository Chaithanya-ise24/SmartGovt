# SmartGovt

## Gemini demo setup

The student doubt-chat demo uses the Google GenAI SDK. Copy `.env.example` to
`.env`, add your Google AI Studio API key as `GEMINI_API_KEY`, and keep `.env`
local (it is ignored by Git). The configured model is `GEMINI_MODEL` in
`config.py` / `.env`; the default is `gemini-3.8-flash`.

Install the project dependencies and create your local environment file with:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` to add your API key before starting the app. In VS Code, select
the same Python interpreter used to install the dependencies.

Run a real Gemini connectivity check with:

```powershell
python scripts\test_gemini.py
```

The student chat is available at `/student/chat`. Each student can make at
most 20 AI requests per rolling hour. Every valid chat question is recorded in
`DoubtLog`, and AI request timestamps are stored separately to enforce the
limit across server workers. Quiz-generation callers should use
`reserve_ai_call(student_id)` in `app.py` before making their model request.

The service functions are `chat_reply(question, history=None, language="en")`
and `generate_quiz(subject, chapter, grade, language="en")`.