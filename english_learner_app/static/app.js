const state = {
  user: null,
  stats: null,
  progress: null,
  sessions: [],
  visibleSessionCount: 0,
  learnView: "compose",
  currentSessionId: null,
  currentSession: null,
  questions: [],
  settings: {
    review_prompt_interval_seconds: 90,
    quiz_retake_minutes: 20,
    first_review_minutes: 60,
  },
  pendingVerificationEmail: "",
  quizTimer: null,
  quizDashboard: null,
  currentQuizRun: null,
  currentReviewSession: null,
  currentQuizLaunch: { mode: "mixed" },
  lastQuizReminderKey: "",
  challenge: null,
  review: null,
  quizQuestionStartedAt: null,
  quizConfidence: 2,
  uploadPreviewUrl: "",
  sessionFlow: {
    step: "learn",
    explanation: "",
    feedback: null,
    attempts: [],
  },
};

const els = {};
const SESSION_CHUNK_SIZE = 6;
let sessionListObserver = null;

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  bootstrap();
});

function cacheElements() {
  const ids = [
    "xpValue",
    "streakValue",
    "newSessionButton",
    "dashboardButton",
    "closeDashboardButton",
    "dashboardModal",
    "dashboardContent",
    "quizLauncherButton",
    "quizDueBadge",
    "userBadge",
    "learnIntro",
    "composePanel",
    "analyzeForm",
    "imageInput",
    "fileNameLabel",
    "uploadPlaceholder",
    "imagePreviewShell",
    "imagePreview",
    "analyzeButton",
    "sessionWorkspace",
    "sessionDetailPanel",
    "sessionLibrarySection",
    "sessionList",
    "sessionLoadSentinel",
    "authOverlay",
    "signupTab",
    "loginTab",
    "signupForm",
    "loginForm",
    "verifyForm",
    "signupButton",
    "loginButton",
    "assessmentQuestions",
    "verificationEmailLabel",
    "verificationEmailInput",
    "resendOtpButton",
    "quizModal",
    "quizModalLabel",
    "quizModalTitle",
    "quizContent",
    "closeQuizButton",
    "languageModal",
    "languageModalLabel",
    "languageModalTitle",
    "languageModalContent",
    "closeLanguageModalButton",
    "toast",
  ];

  ids.forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  els.signupTab.addEventListener("click", () => switchAuthTab("signup"));
  els.loginTab.addEventListener("click", () => switchAuthTab("login"));

  els.signupForm.addEventListener("submit", onSignup);
  els.loginForm.addEventListener("submit", onLogin);
  els.verifyForm.addEventListener("submit", onVerifyOtp);
  els.resendOtpButton.addEventListener("click", onResendOtp);

  els.imageInput.addEventListener("change", onFileChange);
  els.analyzeForm.addEventListener("submit", onAnalyze);
  els.newSessionButton.addEventListener("click", openNewSessionComposer);
  els.dashboardButton.addEventListener("click", openDashboardModal);
  els.closeDashboardButton.addEventListener("click", closeDashboardModal);
  els.quizLauncherButton.addEventListener("click", () => openQuizModal({ mode: "mixed" }));
  els.closeQuizButton.addEventListener("click", closeQuizModal);
  els.closeLanguageModalButton.addEventListener("click", closeLanguageModal);
  els.sessionDetailPanel.addEventListener("click", onLanguageCardClick);
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    state.questions = data.questions || [];
    state.settings = {
      ...state.settings,
      ...(data.settings || {}),
    };
    renderAssessmentQuestions();

    if (data.user) {
      applyUserState(data.user, data.stats, data.progress);
      state.quizDashboard = data.quiz || null;
      state.challenge = data.challenge || null;
      state.review = data.review || null;
      renderQuizButton();
      renderDashboardContent();
      await fetchSessions();
      startQuizPolling();
    } else {
      switchAuthTab("signup");
      renderQuizButton();
      renderDashboardContent();
      showAuthOverlay(true);
    }
  } catch (error) {
    showToast(error.message || "Unable to load the app.", true);
  }
}

function renderAssessmentQuestions() {
  els.assessmentQuestions.innerHTML = "";
  state.questions.forEach((question) => {
    const card = document.createElement("section");
    card.className = "assessment-card";
    card.innerHTML = `
      <p class="field-label">${escapeHtml(question.prompt)}</p>
      <div class="scale-options">
        ${[1, 2, 3, 4, 5]
          .map(
            (value) => `
            <label>
              <input
                type="radio"
                name="${question.id}"
                value="${value}"
                ${value === 3 ? "checked" : ""}
                required
              >
              <span>${value}</span>
            </label>
          `
          )
          .join("")}
      </div>
      <div class="field-row">
        <span class="muted">${escapeHtml(question.min_label)}</span>
        <span class="muted">${escapeHtml(question.max_label)}</span>
      </div>
    `;
    els.assessmentQuestions.appendChild(card);
  });
}

function switchAuthTab(mode) {
  const signupActive = mode === "signup";
  els.signupTab.classList.toggle("active", signupActive);
  els.loginTab.classList.toggle("active", !signupActive);
  els.signupForm.classList.toggle("hidden", !signupActive);
  els.loginForm.classList.toggle("hidden", signupActive);
  els.verifyForm.classList.add("hidden");
}

function showVerificationStep(email) {
  state.pendingVerificationEmail = email;
  els.verificationEmailLabel.textContent = email;
  els.verificationEmailInput.value = email;
  els.signupForm.classList.add("hidden");
  els.loginForm.classList.add("hidden");
  els.verifyForm.classList.remove("hidden");
  els.signupTab.classList.remove("active");
  els.loginTab.classList.remove("active");
}

function showAuthOverlay(visible) {
  els.authOverlay.classList.toggle("hidden", !visible);
}

function applyUserState(user, stats, progress) {
  state.user = user;
  state.stats = stats || null;
  state.progress = progress || null;
  state.learnView = "compose";
  els.userBadge.textContent = `${user.full_name} · ${user.difficulty_label || formatBand(user.difficulty_band)}`;
  els.dashboardButton.disabled = false;
  els.analyzeButton.disabled = !els.imageInput.files[0];
  showAuthOverlay(false);
  renderProgressHeader();
  renderLearnMode();
}

function clearUserState() {
  state.user = null;
  state.stats = null;
  state.progress = null;
  state.sessions = [];
  state.visibleSessionCount = 0;
  state.learnView = "compose";
  state.currentSessionId = null;
  state.currentSession = null;
  state.quizDashboard = null;
  state.currentQuizRun = null;
  state.challenge = null;
  state.review = null;
  state.lastQuizReminderKey = "";
  stopQuizPolling();
  teardownSessionObserver();
  resetUploadPreview();
  renderLearnPlaceholder();
  renderSessionLibrary();
  renderProgressHeader();
  renderQuizButton();
  renderDashboardContent();
  closeLanguageModal();
  els.userBadge.textContent = "Guest mode";
  els.dashboardButton.disabled = false;
  els.analyzeButton.disabled = true;
  showAuthOverlay(true);
  renderLearnMode();
}

function renderProgressHeader() {
  const safe = state.progress || { xp_points: 0, streak_days: 0 };
  els.xpValue.textContent = safe.xp_points || 0;
  els.streakValue.textContent = safe.streak_days || 0;
}

function renderQuizButton() {
  const dashboard = state.quizDashboard;
  const activeRun = dashboard?.active_run;
  const ready = Boolean(activeRun || dashboard?.can_start);
  const dueCount = dashboard?.due_count || 0;

  els.quizDueBadge.textContent = dueCount;
  els.quizLauncherButton.disabled = !ready;
  els.quizLauncherButton.classList.toggle("quiz-ready", ready);
  els.quizLauncherButton.classList.toggle(
    "quiz-pulse",
    Boolean(ready && (activeRun || dueCount > 0))
  );
  els.quizLauncherButton.querySelector(".floating-quiz-label").textContent = activeRun
    ? "Resume Quiz"
    : "Start Quiz";
}

function renderLearnPlaceholder() {
  if (state.learnView === "session" && state.currentSession) {
    renderSession(state.currentSession);
    return;
  }
  els.sessionDetailPanel.classList.add("hidden");
  els.sessionDetailPanel.innerHTML = "";
  renderLearnMode();
}

function renderSession(session) {
  state.currentSession = session;
  state.currentSessionId = session.id;
  state.learnView = "session";
  closeLanguageModal();
  renderLearnMode();
  els.sessionDetailPanel.classList.remove("hidden");
  state.sessionFlow = {
    step: "learn",
    explanation: "",
    feedback: null,
    attempts: [],
  };
  renderSessionStep("learn");
}

function renderSessionStep(step, updates = {}) {
  const session = state.currentSession;
  if (!session) {
    return;
  }
  state.sessionFlow = {
    ...state.sessionFlow,
    ...updates,
    step,
  };

  closeLanguageModal();
  els.sessionDetailPanel.classList.remove("hidden");

  if (step === "write") {
    setFocusedSessionLayout(true);
    renderWriteStep(session);
    animateStepTransition();
    return;
  }
  if (step === "feedback") {
    setFocusedSessionLayout(true);
    renderFeedbackStep(session, state.sessionFlow.feedback);
    animateStepTransition();
    return;
  }
  if (step === "improve") {
    setFocusedSessionLayout(true);
    renderImproveStep(session);
    animateStepTransition();
    return;
  }
  setFocusedSessionLayout(false);
  renderLearnStep(session);
  animateStepTransition();
}

function setFocusedSessionLayout(focused) {
  els.sessionWorkspace.classList.toggle("focused-session-layout", Boolean(focused));
  if (focused) {
    els.sessionLibrarySection.classList.add("hidden");
    els.sessionWorkspace.classList.remove("has-session-library");
  } else if (state.user && state.sessions.length && state.currentSession) {
    renderSessionLibrary();
  }
}

function renderStepProgress(activeStep) {
  const steps = [
    ["learn", "Learn"],
    ["write", "Write"],
    ["feedback", "Feedback"],
    ["improve", "Improve"],
    ["quiz", "Quiz"],
    ["reward", "Reward"],
  ];
  const activeIndex = steps.findIndex(([key]) => key === activeStep);

  return `
    <nav class="journey-steps" aria-label="Learning progress">
      ${steps
        .map(
          ([key, label], index) => `
            <span class="journey-step ${
              index < activeIndex ? "complete" : index === activeIndex ? "active" : ""
            }">
              <span class="journey-step-number">${index + 1}</span>
              <span>${label}</span>
            </span>
          `
        )
        .join("")}
    </nav>
  `;
}

function animateStepTransition() {
  const shell = els.sessionDetailPanel.querySelector(".journey-shell, .focused-step-shell");
  if (!shell || prefersReducedMotion()) {
    return;
  }
  shell.classList.remove("step-transition-in");
  requestAnimationFrame(() => {
    shell.classList.add("step-transition-in");
  });
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
}

function animateNumber(elementId, finalValue, options = {}) {
  const element = document.getElementById(elementId);
  const target = Math.max(0, Math.round(Number(finalValue) || 0));
  const suffix = options.suffix || "";
  if (!element) {
    return;
  }
  if (prefersReducedMotion()) {
    element.textContent = `${target}${suffix}`;
    return;
  }
  const duration = 520;
  const startTime = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    element.textContent = `${Math.round(target * eased)}${suffix}`;
    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  };
  requestAnimationFrame(tick);
}

function renderLearnStep(session) {
  const vocabulary = session.analysis.vocabulary || [];
  const phrases = session.analysis.phrases || [];
  const sentencePatterns = session.analysis.sentence_patterns || [];

  const vocabularyMarkup = vocabulary.length
    ? vocabulary
        .slice(0, 4)
        .map(
          (item, index) => `
            <button class="language-card language-card-button" type="button" data-language-kind="vocabulary" data-language-index="${index}">
              <div class="language-card-head">
                <span class="mini-pill">${escapeHtml(item.part_of_speech || "word")}</span>
                <strong>${escapeHtml(item.word)}</strong>
              </div>
              <p>${escapeHtml(item.meaning_simple || "")}</p>
              ${
                item.example
                  ? `<p class="muted language-example">${escapeHtml(item.example)}</p>`
                  : ""
              }
            </button>
          `
        )
        .join("")
    : `<div class="empty-copy">Vocabulary will appear here after explanation generation.</div>`;

  const phraseMarkup = phrases.length
    ? phrases
        .slice(0, 4)
        .map(
          (item, index) => `
            <button class="language-card language-card-button" type="button" data-language-kind="phrase" data-language-index="${index}">
              <div class="language-card-head">
                <span class="mini-pill">${escapeHtml(item.collocation_type || "phrase")}</span>
                <strong>${escapeHtml(item.phrase)}</strong>
                ${item.mastery_state ? `<span class="mini-pill">${escapeHtml(item.mastery_state)}</span>` : ""}
              </div>
              <p>${escapeHtml(item.meaning_simple || "")}</p>
              ${
                item.example
                  ? `<p class="muted language-example">${escapeHtml(item.example)}</p>`
                  : ""
              }
            </button>
          `
        )
        .join("")
    : `<div class="empty-copy">Reusable phrases will appear here after explanation generation.</div>`;

  const patternMarkup = sentencePatterns.length
    ? sentencePatterns
        .slice(0, 3)
        .map(
          (item, index) => `
            <button class="language-card language-card-button sentence-pattern-card" type="button" data-language-kind="pattern" data-language-index="${index}">
              <div class="language-card-head">
                <span class="mini-pill">structure</span>
                <strong>${escapeHtml(item.pattern)}</strong>
              </div>
              <p>${escapeHtml(item.usage_note || "Use this to build a natural image description.")}</p>
              ${
                item.example
                  ? `<p class="muted language-example">${escapeHtml(item.example)}</p>`
                  : ""
              }
            </button>
          `
        )
        .join("")
    : `<div class="empty-copy">Sentence structures will appear here after explanation generation.</div>`;

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell learn-step-shell">
      ${renderStepProgress("learn")}
      ${
        session.source_mode === "demo"
          ? `<div class="source-banner">The app is in demo mode, so this lesson uses demo teaching content instead of real image understanding.</div>`
          : ""
      }

      <section class="result-section hero-result-card">
        <div class="hero-image-shell">
          <img src="${session.image_url}" alt="Learning session image">
        </div>
        <div class="hero-result-copy">
          <p class="eyebrow">Step 1: Learn</p>
          <h3>${escapeHtml(session.title)}</h3>
          <p class="muted">
            Read the image explanation and skim a few useful language pieces. Then it is your turn.
          </p>
          <div class="lesson-guidance-row">
            <span class="guidance-pill">${escapeHtml(session.difficulty_label || formatBand(session.difficulty_band))}</span>
            <span class="guidance-pill">Saved ${escapeHtml(formatDate(session.created_at))}</span>
            <span class="guidance-pill">Mastery ${Math.round(session.mastery_percent || 0)}%</span>
          </div>
        </div>
      </section>

      <section class="result-section explanation-result-card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Read First</p>
            <h4>AI explanation</h4>
          </div>
        </div>
        <div class="highlighted-text explanation-text">${session.analysis.highlighted_html || ""}</div>
      </section>

      <section class="result-section language-result-card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Skim Next</p>
            <h4>Reusable language</h4>
          </div>
          <span class="section-badge">${Math.min(vocabulary.length, 4) + Math.min(phrases.length, 4) + Math.min(sentencePatterns.length, 3)}</span>
        </div>

        <div class="language-groups">
          <div class="language-group">
            <div class="language-group-head">
              <h5>Key words</h5>
            </div>
            <div class="language-grid">${vocabularyMarkup}</div>
          </div>

          <div class="language-group">
            <div class="language-group-head">
              <h5>Phrases</h5>
            </div>
            <div class="language-grid">${phraseMarkup}</div>
          </div>

          <div class="language-group">
            <div class="language-group-head">
              <h5>Sentence structures</h5>
            </div>
            <div class="language-grid">${patternMarkup}</div>
          </div>
        </div>
        <p class="muted language-help-copy">Tap a word, phrase, or sentence structure for examples. Only the most useful items are shown here.</p>
      </section>

      <div class="sticky-journey-cta">
        <button id="yourTurnButton" class="primary-button journey-primary-button" type="button">
          Your Turn →
        </button>
      </div>
    </div>
  `;

  const quickChallengeButton = document.getElementById("startSessionQuickChallenge");
  if (quickChallengeButton) {
    quickChallengeButton.addEventListener("click", () => {
      openQuizModal({ mode: "session", session_id: session.id });
    });
  }

  const yourTurnButton = document.getElementById("yourTurnButton");
  if (yourTurnButton) {
    yourTurnButton.addEventListener("click", () => {
      renderSessionStep("write");
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }
}

function onLanguageCardClick(event) {
  const card = event.target.closest("[data-language-kind]");
  if (!card || !els.sessionDetailPanel.contains(card) || !state.currentSession) {
    return;
  }

  const kind = card.dataset.languageKind;
  const index = Number(card.dataset.languageIndex);
  const analysis = state.currentSession.analysis || {};
  const vocabulary = analysis.vocabulary || [];
  const phrases = analysis.phrases || [];
  const sentencePatterns = analysis.sentence_patterns || [];
  const item =
    kind === "vocabulary"
      ? vocabulary[index]
      : kind === "pattern"
        ? sentencePatterns[index]
        : phrases[index];
  if (!item) {
    return;
  }
  openLanguageModal({ item, kind, session: state.currentSession });
}

function renderWriteStep(session) {
  const suggestions = buildWritingSuggestions(session);
  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell">
      ${renderStepProgress("write")}
      <section class="focused-writing-card">
        <img class="focused-image-preview" src="${session.image_url}" alt="Image to describe">
        <div class="focused-copy">
          <p class="eyebrow">Step 2: Write</p>
          <h3>Describe this image in your own words</h3>
        </div>
        <textarea
          id="learnerExplanationInput"
          class="focused-writing-input"
          rows="10"
          placeholder="Write your own explanation here..."
        >${escapeHtml(state.sessionFlow.explanation || "")}</textarea>
        ${
          suggestions.length
            ? `
              <details class="phrase-help-toggle">
                <summary>View help</summary>
                <div class="mini-suggestion-row">
                  ${suggestions
                    .map((item) => `<span class="guidance-pill">${escapeHtml(item)}</span>`)
                    .join("")}
                </div>
              </details>
            `
            : ""
        }
        <button id="submitWritingButton" class="primary-button journey-primary-button" type="button">
          Submit
        </button>
      </section>
    </div>
  `;

  document.getElementById("submitWritingButton").addEventListener("click", () => {
    submitExplanationFeedback(session, { mode: "first" });
  });
  window.setTimeout(() => {
    document.getElementById("learnerExplanationInput")?.focus();
  }, 50);
}

function renderFeedbackStep(session, feedback) {
  if (!feedback) {
    renderSessionStep("write");
    return;
  }

  const scores = feedback.scores || {};
  const totalScore = feedbackTotalScore(feedback);
  const retryRequired = Boolean(feedback.retry_required);
  const latestAttempt = (state.sessionFlow.attempts || []).at(-1) || null;
  const learnerText = latestAttempt?.text || state.sessionFlow.explanation || "";
  const alternatives = Array.isArray(feedback.word_phrase_upgrades)
    ? feedback.word_phrase_upgrades.slice(0, 3)
    : Array.isArray(feedback.alternatives)
    ? feedback.alternatives.slice(0, 3)
    : [];
  const didWell = cleanUiList(feedback.what_did_well, 2);
  const missingDetails = Array.isArray(feedback.missing_details)
    ? cleanUiList(feedback.missing_details, 3)
    : [];
  const fixThis = Array.isArray(feedback.fix_this_to_improve)
    ? cleanUiList(feedback.fix_this_to_improve, 3)
    : Array.isArray(feedback.improvements)
    ? cleanUiList(feedback.improvements, 3)
    : [];
  const phraseUsage = feedback.phrase_usage || {};
  const phraseUsageUsed = cleanUiList(phraseUsage.used, 5);
  const phraseUsageSuggested = cleanUiList(phraseUsage.suggested, 3);
  const phraseUsagePartial = cleanPhraseIssueList(phraseUsage.partial, true);
  const phraseUsageMisused = cleanPhraseIssueList(phraseUsage.misused, false);
  const betterVersion = retryRequired
    ? ""
    :
    cleanUiText(feedback.better_version) ||
    "Use your answer as the base, then add one stronger phrase and one clearer detail.";

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell">
      ${renderStepProgress("feedback")}
      <section class="feedback-screen-card">
        <div class="score-hero coach-reveal" ${coachRevealStyle(0)}>
          <p class="eyebrow">Step 3: Feedback</p>
          <span class="score-label">Score</span>
          <strong id="feedbackScoreValue" data-score="${totalScore}">0</strong>
          <span>/100</span>
        </div>

        <div class="score-grid score-grid-four coach-reveal" ${coachRevealStyle(0)}>
          ${[
            ["Vocab", scores.vocabulary || 0],
            ["Structure", scores.structure || 0],
            ["Clarity", scores.clarity || 0],
            ["Depth", scores.depth || 0],
          ]
            .map(
              ([label, value]) => `
                <article class="status-pill">
                  <span class="status-label">${escapeHtml(label)}</span>
                  <strong class="status-value">${Number(value) || 0}/10</strong>
                </article>
              `
            )
            .join("")}
        </div>

        <section class="simple-feedback-section coach-reveal" ${coachRevealStyle(1)}>
          <h4>Main issue</h4>
          <p>${escapeHtml(cleanUiText(feedback.main_issue) || "Make your answer clearer and more specific.")}</p>
        </section>

        ${!retryRequired && didWell.length
          ? `
              <section class="simple-feedback-section coach-reveal" ${coachRevealStyle(2)}>
                <h4>What you did well</h4>
                <ul class="compact-list">
                  ${didWell.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
              </section>
            `
          : ""}

        ${
          retryRequired
            ? `
              <section class="simple-feedback-section coach-reveal" ${coachRevealStyle(2)}>
                <h4>Try again</h4>
                <ul class="compact-list">
                  ${
                    fixThis.length
                      ? fixThis.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
                      : `<li>Mention the main subject.</li><li>Add one visible detail.</li>`
                  }
                </ul>
              </section>
            `
            : ""
        }

        ${!retryRequired ? `<section class="simple-feedback-section coach-reveal" ${coachRevealStyle(3)}>
          <h4>Fix this to improve</h4>
          <ul class="compact-list">
            ${
              fixThis.length
                ? fixThis.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
                : `<li>Add clearer details and one useful phrase.</li>`
            }
          </ul>
        </section>` : ""}

        ${!retryRequired ? renderReusableLanguageFeedback({
          phraseUsage,
          used: phraseUsageUsed,
          suggested: phraseUsageSuggested,
          partial: phraseUsagePartial,
          misused: phraseUsageMisused,
          revealIndex: 4,
        }) : ""}

        ${!retryRequired ? (
          missingDetails.length
            ? `
              <section class="simple-feedback-section coach-reveal" ${coachRevealStyle(5)}>
                <h4>Missing details</h4>
                <ul class="compact-list">
                  ${missingDetails.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
                </ul>
              </section>
            `
            : `
              <section class="simple-feedback-section coach-reveal" ${coachRevealStyle(5)}>
                <h4>Missing details</h4>
                <p>No major visible detail is missing. Now focus on stronger language.</p>
              </section>
            `
        ) : ""}

        ${!retryRequired ? renderInlineUpgradeSection(learnerText, alternatives, 6) : ""}

        ${!retryRequired ? `<section class="improved-version-box coach-reveal" ${coachRevealStyle(7)}>
          <h4>Improved version</h4>
          <p>${highlightSessionPhrases(betterVersion, session)}</p>
        </section>` : ""}

        <button id="feedbackPrimaryButton" class="primary-button journey-primary-button coach-reveal" ${coachRevealStyle(8)} type="button">
          ${escapeHtml(feedback.cta_label || (retryRequired ? "Try Again" : "Improve My Answer"))}
        </button>
      </section>
    </div>
  `;

  document.getElementById("feedbackPrimaryButton").addEventListener("click", () => {
    renderSessionStep(retryRequired ? "write" : "improve");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  animateNumber("feedbackScoreValue", totalScore);
}

function coachRevealStyle(index) {
  return `style="--reveal-delay: ${Math.min(index * 70, 560)}ms"`;
}

function renderInlineUpgradeSection(learnerText, alternatives, revealIndex = 0) {
  const upgrades = buildInlineUpgrades(learnerText, alternatives).slice(0, 3);
  if (!upgrades.length) {
    return "";
  }

  return `
    <section class="simple-feedback-section inline-upgrade-section coach-reveal" ${coachRevealStyle(revealIndex)}>
      <h4>Improve your sentence</h4>
      <p class="inline-upgrade-text">${renderInlineUpgradeText(learnerText, upgrades)}</p>
    </section>
  `;
}

function buildInlineUpgrades(learnerText, alternatives) {
  const text = String(learnerText || "").trim();
  if (!text) {
    return [];
  }
  const seen = new Set();
  return (alternatives || [])
    .map((item) => ({
      oldText: cleanUiText(item?.instead_of),
      newText: cleanUiText(item?.use),
    }))
    .filter((item) => item.oldText && item.newText)
    .filter((item) => !/^(simple wording|general word|short sentence|basic wording|instead)$/i.test(item.oldText))
    .filter((item) => text.toLowerCase().includes(item.oldText.toLowerCase()))
    .filter((item) => {
      const key = normalizeClientText(item.oldText);
      if (!key || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .sort((a, b) => b.oldText.length - a.oldText.length);
}

function renderInlineUpgradeText(learnerText, upgrades) {
  const excerpt = sentenceForInlineUpgrades(learnerText, upgrades);
  if (!excerpt) {
    return "";
  }
  const matches = [];
  const lowerExcerpt = excerpt.toLowerCase();
  upgrades.forEach((upgrade) => {
    const index = lowerExcerpt.indexOf(upgrade.oldText.toLowerCase());
    if (index === -1) {
      return;
    }
    const end = index + upgrade.oldText.length;
    if (matches.some((match) => index < match.end && end > match.start)) {
      return;
    }
    matches.push({ ...upgrade, start: index, end });
  });
  if (!matches.length) {
    return escapeHtml(excerpt);
  }
  matches.sort((a, b) => a.start - b.start);

  let html = "";
  let cursor = 0;
  matches.forEach((match) => {
    html += escapeHtml(excerpt.slice(cursor, match.start));
    html += `<span class="inline-upgrade-swap"><del>${escapeHtml(
      excerpt.slice(match.start, match.end)
    )}</del><span class="inline-upgrade-arrow">→</span><strong>${escapeHtml(
      match.newText
    )}</strong></span>`;
    cursor = match.end;
  });
  html += escapeHtml(excerpt.slice(cursor));
  return html;
}

function sentenceForInlineUpgrades(learnerText, upgrades) {
  const text = String(learnerText || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  const sentences = text.match(/[^.!?]+[.!?]?/g) || [text];
  const matchedSentence = sentences.find((sentence) =>
    upgrades.some((upgrade) => sentence.toLowerCase().includes(upgrade.oldText.toLowerCase()))
  );
  return (matchedSentence || sentences[0] || text).trim();
}

function renderReusableLanguageFeedback({ phraseUsage, used, suggested, partial, misused, revealIndex = 0 }) {
  const tryPhrases = suggested.slice(0, 2);
  const hasAnyUsage = used.length || partial.length || misused.length;
  return `
    <section class="simple-feedback-section phrase-usage-section coach-reveal" ${coachRevealStyle(revealIndex)}>
      <h4>Reusable language</h4>
      <p>${escapeHtml(
        cleanUiText(phraseUsage.message) ||
          (hasAnyUsage
            ? "Good: you are trying to use learned language. Now make it more precise."
            : "You did not use any learned phrases yet.")
      )}</p>
      <div class="language-feedback-grid">
        <div>
          <span class="field-label">Used well</span>
          <div class="mini-suggestion-row">
            ${
              used.length
                ? used.map((item) => `<span class="phrase-chip used">${escapeHtml(item)}</span>`).join("")
                : `<span class="muted">None yet</span>`
            }
          </div>
        </div>
        <div>
          <span class="field-label">Try next</span>
          <div class="mini-suggestion-row">
            ${
              tryPhrases.length
                ? tryPhrases.map((item) => `<span class="phrase-chip suggested">${escapeHtml(item)}</span>`).join("")
                : `<span class="muted">Add one phrase from the lesson if it fits.</span>`
            }
          </div>
        </div>
      </div>
      ${
        partial.length || misused.length
          ? `
            <ul class="compact-list phrase-note-list">
              ${partial
                .slice(0, 2)
                .map(
                  (item) =>
                    `<li>You used "${escapeHtml(item.attempt || "part of it")}". Try the full phrase "${escapeHtml(
                      item.phrase || ""
                    )}".</li>`
                )
                .join("")}
              ${misused
                .slice(0, 2)
                .map(
                  (item) =>
                    `<li>"${escapeHtml(item.phrase || "")}" needs adjustment: ${escapeHtml(
                      item.note || "Use it inside a complete sentence."
                    )}</li>`
                )
                .join("")}
            </ul>
          `
          : ""
      }
    </section>
  `;
}

function renderImproveStep(session) {
  const attempts = state.sessionFlow.attempts || [];
  const latestAttempt = attempts[attempts.length - 1] || null;
  const previousAttempt = attempts[attempts.length - 2] || null;
  const latestFeedback = latestAttempt?.feedback || state.sessionFlow.feedback || {};
  const latestText = latestAttempt?.text || state.sessionFlow.explanation || "";
  const rewriteDraft = latestText;
  const rewriteCount = Math.max(0, attempts.length - 1);
  const shouldSuggestQuiz = attempts.length >= 2;
  const latestScore = latestAttempt ? latestAttempt.score : feedbackTotalScore(latestFeedback);
  const previousScore = previousAttempt ? previousAttempt.score : null;
  const scoreDelta = previousScore === null ? 0 : latestScore - previousScore;
  const phraseSuggestions = buildImprovePhraseSuggestions(session, latestFeedback, latestText).slice(0, 3);
  const betterVersion = latestFeedback.better_version || "";

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell">
      ${renderStepProgress("improve")}
      <section class="focused-writing-card">
        <img class="focused-image-preview" src="${session.image_url}" alt="Image to describe">
        <div class="focused-copy">
          <p class="eyebrow">Step 4: Improve</p>
          <h3>Make your answer stronger</h3>
        </div>
        ${renderScoreProgress(attempts)}
        ${
          attempts.length > 1
            ? `
              <div class="improvement-comparison-box">
                <strong>${previousScore} → ${latestScore}</strong>
                <span>${scoreDelta >= 0 ? `+${scoreDelta} points` : `${scoreDelta} points`}</span>
              </div>
            `
            : ""
        }
        ${renderTargetedFeedback(latestFeedback, { scoreDelta, rewriteCount })}
        ${
          betterVersion
            ? `
              <section class="improved-version-box">
                <h4>Reference version</h4>
                <p>${highlightSessionPhrases(betterVersion, session)}</p>
              </section>
            `
            : ""
        }
        <div class="previous-answer-box">
          <span class="field-label">Previous answer</span>
          <p>${escapeHtml(latestText)}</p>
        </div>
        ${
          phraseSuggestions.length
            ? `
              <section class="phrase-reuse-panel">
                <span class="field-label">Try to include at least 1–2 of these phrases</span>
                <div class="mini-suggestion-row">
                  ${phraseSuggestions
                    .map(
                      (phrase, index) => `
                        <button class="phrase-chip phrase-insert-chip ${
                          !latestFeedback?.phrase_usage?.used?.length && index < 2 ? "priority" : ""
                        }" type="button" data-insert-phrase="${escapeHtml(phrase)}">
                          ${escapeHtml(phrase)}
                        </button>
                      `
                    )
                    .join("")}
                </div>
              </section>
            `
            : ""
        }
        <textarea
          id="learnerImproveInput"
          class="focused-writing-input"
          rows="10"
          placeholder="Improve your answer here..."
        >${escapeHtml(rewriteDraft)}</textarea>
        ${
          shouldSuggestQuiz
            ? `
              <div class="move-forward-box">
                <strong>You’ve improved a lot.</strong>
                <p>Want to move to quiz or keep refining?</p>
                <div class="journey-choice-row">
                  <button id="continueToQuizButton" class="primary-button" type="button">Continue to Quiz</button>
                  <button id="submitImproveButton" class="ghost-button" type="button">Keep Improving</button>
                </div>
              </div>
            `
            : `
              <button id="submitImproveButton" class="primary-button journey-primary-button" type="button">
                Submit Improved Version
              </button>
            `
        }
      </section>
    </div>
  `;

  document.getElementById("submitImproveButton")?.addEventListener("click", () => {
    const improvedText = document.getElementById("learnerImproveInput").value.trim();
    if (!improvedText) {
      showToast("Write your improved version first.", true);
      return;
    }
    requestImprovementFeedback(session, state.sessionFlow.explanation, improvedText);
  });
  document.getElementById("continueToQuizButton")?.addEventListener("click", () => {
    startPostImproveQuiz(session);
  });
  els.sessionDetailPanel.querySelectorAll("[data-insert-phrase]").forEach((button) => {
    button.addEventListener("click", () => {
      insertPhraseIntoImproveInput(button.dataset.insertPhrase || "");
      button.classList.add("selected");
    });
  });
  window.setTimeout(() => {
    document.getElementById("learnerImproveInput")?.focus();
  }, 50);
}

function buildWritingSuggestions(session) {
  const phrases = session.analysis.phrases || [];
  const patterns = session.analysis.sentence_patterns || [];
  return [
    ...phrases.slice(0, 2).map((item) => item.phrase),
    ...patterns.slice(0, 1).map((item) => item.pattern),
  ].filter(Boolean);
}

function buildImprovePhraseSuggestions(session, feedback, currentText) {
  const phrases = (session.analysis.phrases || [])
    .map((item) => item.phrase)
    .filter(Boolean);
  const used = new Set((feedback?.phrase_usage?.used || []).map((item) => normalizeClientText(item)));
  const suggested = feedback?.phrase_usage?.suggested || [];
  return [...suggested, ...phrases]
    .filter((phrase) => phrase && !used.has(normalizeClientText(phrase)))
    .filter((phrase, index, list) => list.findIndex((item) => normalizeClientText(item) === normalizeClientText(phrase)) === index)
    .filter((phrase) => !normalizeClientText(currentText).includes(normalizeClientText(phrase)))
    .slice(0, 5);
}

function insertPhraseIntoImproveInput(phrase) {
  const input = document.getElementById("learnerImproveInput");
  if (!input || !phrase) {
    return;
  }
  const value = input.value.trimEnd();
  const needsSpace = value && !/\s$/.test(input.value);
  input.value = `${value}${needsSpace ? " " : ""}${phrase}`;
  input.focus();
}

function highlightSessionPhrases(text, session) {
  const phrases = (session.analysis.phrases || [])
    .map((item) => item.phrase)
    .filter((phrase) => phrase && phrase.trim().split(/\s+/).length >= 2)
    .sort((a, b) => b.length - a.length)
    .slice(0, 12);
  if (!phrases.length) {
    return escapeHtml(text);
  }

  const rawText = String(text || "");
  const spans = [];
  const lowered = rawText.toLowerCase();
  phrases.forEach((phrase) => {
    const needle = phrase.toLowerCase();
    let index = lowered.indexOf(needle);
    while (index !== -1) {
      const end = index + phrase.length;
      const overlaps = spans.some(([start, stop]) => index < stop && end > start);
      if (!overlaps) {
        spans.push([index, end, rawText.slice(index, end)]);
      }
      index = lowered.indexOf(needle, end);
    }
  });
  if (!spans.length) {
    return escapeHtml(rawText);
  }
  spans.sort((a, b) => a[0] - b[0]);
  let cursor = 0;
  let html = "";
  spans.forEach(([start, end, phrase]) => {
    html += escapeHtml(rawText.slice(cursor, start));
    html += `<mark class="inline-phrase-highlight">${escapeHtml(phrase)}</mark>`;
    cursor = end;
  });
  html += escapeHtml(rawText.slice(cursor));
  return html;
}

function normalizeClientText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function cleanUiText(value) {
  if (value && typeof value === "object") {
    for (const key of ["text", "phrase", "value", "message", "detail"]) {
      if (value[key]) {
        return cleanUiText(value[key]);
      }
    }
    return "";
  }
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  if (
    (text.startsWith("{") && text.endsWith("}")) ||
    (text.startsWith("[") && text.endsWith("]")) ||
    /\b(attempt|phrase|note|usedWell|tryNext|mainIssue)\s*[:=]/i.test(text) ||
    /^(null|undefined|\[object Object\])$/i.test(text)
  ) {
    return "";
  }
  return text;
}

function cleanUiList(values, limit = 3) {
  const items = Array.isArray(values) ? values : [];
  const seen = new Set();
  const cleaned = [];
  items.forEach((value) => {
    const text = cleanUiText(value);
    const key = normalizeClientText(text);
    if (!text || !key || seen.has(key)) {
      return;
    }
    seen.add(key);
    cleaned.push(text);
  });
  return cleaned.slice(0, limit);
}

function cleanPhraseIssueList(values, includeAttempt) {
  const items = Array.isArray(values) ? values : [];
  return items
    .map((item) => ({
      phrase: cleanUiText(item?.phrase),
      note: cleanUiText(item?.note),
      attempt: includeAttempt ? cleanUiText(item?.attempt) : "",
    }))
    .filter((item) => item.phrase)
    .slice(0, 3);
}

function renderScoreProgress(attempts) {
  if (!attempts.length) {
    return "";
  }
  return `
    <div class="score-progress-strip" aria-label="Score progression">
      ${attempts
        .map(
          (attempt, index) => `
            <span class="score-progress-pill ${index === attempts.length - 1 ? "active" : ""}">
              ${index === 0 ? "First" : `Improve ${index}`} · ${attempt.score}
            </span>
          `
        )
        .join('<span class="score-progress-arrow">→</span>')}
    </div>
  `;
}

function renderTargetedFeedback(feedback, { scoreDelta = 0, rewriteCount = 0 } = {}) {
  const improvements = Array.isArray(feedback?.improvements) ? feedback.improvements : [];
  const weakPoints = Array.isArray(feedback?.weak_points) ? feedback.weak_points : [];
  const didWell = Array.isArray(feedback?.what_did_well) ? feedback.what_did_well : [];
  const missingDetails = Array.isArray(feedback?.missing_details) ? feedback.missing_details : [];
  const messages = [];

  if (rewriteCount > 0) {
    messages.push(
      scoreDelta > 0
        ? `Good improvement: your score increased by ${scoreDelta} point${pluralize(scoreDelta)}.`
        : "This version is not clearly stronger yet. Focus on one specific improvement."
    );
  }

  if (didWell[0]) {
    messages.push(didWell[0]);
  }
  if (missingDetails[0]) {
    messages.push(`Still missing: ${missingDetails[0]}`);
  }
  if (improvements[0]) {
    messages.push(improvements[0]);
  }
  if (messages.length < 3 && weakPoints[0]) {
    messages.push(`Still missing: ${weakPoints[0]}`);
  }
  if (messages.length < 2 && improvements[1]) {
    messages.push(improvements[1]);
  }

  return `
    <section class="targeted-feedback-box">
      <h4>Latest guidance</h4>
      <ul class="compact-list">
        ${(messages.length ? messages : ["Add one clearer detail and improve sentence structure."])
          .slice(0, 3)
          .map((item) => `<li>${escapeHtml(item)}</li>`)
          .join("")}
      </ul>
    </section>
  `;
}

function renderAiThinkingState(title, steps = []) {
  const safeSteps = steps.length ? steps : ["Reading the image", "Finding useful language", "Preparing the next step"];
  return `
    <div class="journey-shell focused-step-shell step-transition-in">
      <section class="ai-thinking-card" aria-live="polite">
        <div class="thinking-orb" aria-hidden="true"></div>
        <div>
          <p class="eyebrow">AI Coach</p>
          <h3>${escapeHtml(title)}</h3>
        </div>
        <div class="thinking-dots" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>
        <div class="thinking-step-list">
          ${safeSteps
            .map(
              (step, index) => `
                <div class="thinking-step" style="--reveal-delay: ${index * 80}ms">
                  <span></span>
                  <p>${escapeHtml(step)}</p>
                </div>
              `
            )
            .join("")}
        </div>
        <div class="skeleton-stack" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </section>
    </div>
  `;
}

function showSessionThinkingState(title, steps) {
  els.sessionWorkspace.classList.remove("hidden");
  els.sessionWorkspace.classList.add("focused-session-layout");
  els.sessionWorkspace.classList.remove("has-session-library");
  els.sessionDetailPanel.classList.remove("hidden");
  els.sessionLibrarySection.classList.add("hidden");
  els.sessionDetailPanel.innerHTML = renderAiThinkingState(title, steps);
}

function feedbackTotalScore(feedback) {
  if (Number.isFinite(Number(feedback?.score))) {
    return Math.max(1, Math.min(100, Math.round(Number(feedback.score))));
  }
  const scores = feedback?.scores || {};
  const values = ["vocabulary", "structure", "clarity", "depth"].map((key) =>
    Math.max(0, Math.min(10, Number(scores[key]) || 0))
  );
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.round(average * 10);
}

async function fetchSessions() {
  if (!state.user) return;
  try {
    const data = await api("/api/sessions");
    state.sessions = data.sessions || [];
    state.visibleSessionCount = Math.min(SESSION_CHUNK_SIZE, state.sessions.length);
    renderSessionLibrary();
    renderDashboardContent();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadSession(sessionId) {
  try {
    const data = await api(`/api/sessions/${sessionId}`);
    renderSession(data.session);
    renderSessionLibrary();
    renderDashboardContent();
  } catch (error) {
    showToast(error.message, true);
  }
}

function resetUploadPreview() {
  if (state.uploadPreviewUrl) {
    URL.revokeObjectURL(state.uploadPreviewUrl);
  }
  state.uploadPreviewUrl = "";
  els.imagePreview.src = "";
  els.imagePreviewShell.classList.add("hidden");
  els.uploadPlaceholder.classList.remove("hidden");
  els.fileNameLabel.textContent = "JPG, PNG, WEBP, or GIF up to 8 MB";
}

function onFileChange() {
  const file = els.imageInput.files[0];
  resetUploadPreview();
  if (!file) {
    els.analyzeButton.disabled = true;
    return;
  }

  state.uploadPreviewUrl = URL.createObjectURL(file);
  els.imagePreview.src = state.uploadPreviewUrl;
  els.imagePreviewShell.classList.remove("hidden");
  els.uploadPlaceholder.classList.add("hidden");
  els.fileNameLabel.textContent = file.name;
  els.analyzeButton.disabled = !state.user;
}

function openNewSessionComposer() {
  state.learnView = "compose";
  closeLanguageModal();
  resetUploadPreview();
  els.analyzeForm.reset();
  els.analyzeButton.disabled = true;
  renderLearnPlaceholder();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function onSignup(event) {
  event.preventDefault();
  const form = new FormData(els.signupForm);
  const payload = {
    full_name: form.get("full_name"),
    phone: form.get("phone"),
    email: form.get("email"),
    password: form.get("password"),
    assessment: Object.fromEntries(
      state.questions.map((question) => [question.id, form.get(question.id)])
    ),
  };

  setButtonBusy(els.signupButton, true, "Creating...");
  try {
    const data = await api("/api/auth/signup", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    showVerificationStep(data.email);
    showToast("Account created. Check your email for the OTP.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setButtonBusy(els.signupButton, false, "Create account");
  }
}

async function onLogin(event) {
  event.preventDefault();
  const form = new FormData(els.loginForm);

  setButtonBusy(els.loginButton, true, "Logging in...");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
      }),
    });
    applyUserState(data.user, data.stats, data.progress);
    await Promise.all([
      fetchSessions(),
      refreshQuizDashboard(),
      fetchReviewDashboard(),
      fetchProgressDashboard(),
      fetchChallenge(),
    ]);
    startQuizPolling();
    showToast("Welcome back.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setButtonBusy(els.loginButton, false, "Log in");
  }
}

async function onVerifyOtp(event) {
  event.preventDefault();
  const form = new FormData(els.verifyForm);
  try {
    const data = await api("/api/auth/verify-otp", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        email: form.get("email"),
        otp: form.get("otp"),
      }),
    });
    applyUserState(data.user, data.stats, data.progress);
    await Promise.all([
      fetchSessions(),
      refreshQuizDashboard(),
      fetchReviewDashboard(),
      fetchProgressDashboard(),
      fetchChallenge(),
    ]);
    startQuizPolling();
    showToast("Your account is verified. You can start learning now.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function onResendOtp() {
  try {
    await api("/api/auth/resend-otp", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        email: els.verificationEmailInput.value || state.pendingVerificationEmail,
      }),
    });
    showToast("A new OTP has been sent.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function onAnalyze(event) {
  event.preventDefault();
  if (!state.user) {
    showToast("Please log in first.", true);
    return;
  }

  const imageFile = els.imageInput.files[0];
  if (!imageFile) {
    showToast("Choose an image before generating an explanation.", true);
    return;
  }

  const formData = new FormData();
  formData.append("image", imageFile);

  setButtonBusy(els.analyzeButton, true, "Generating...");
  showSessionThinkingState("Generating your lesson...", [
    "Analyzing the image",
    "Finding reusable phrases",
    "Preparing sentence structures",
  ]);
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      body: formData,
    });
    const session = data.session;
    state.currentSession = session;
    state.currentSessionId = session.id;
    state.quizDashboard = data.quiz || state.quizDashboard;
    state.challenge = data.challenge || state.challenge;
    state.progress = data.progress || state.progress;
    state.stats = data.stats || state.stats;
    state.sessions = [
      {
        id: session.id,
        title: session.title,
        image_name: session.image_name,
        difficulty_band: session.difficulty_band,
        difficulty_label: session.difficulty_label,
        source_mode: session.source_mode,
        mastery_percent: session.mastery_percent,
        created_at: session.created_at,
      },
      ...state.sessions.filter((item) => item.id !== session.id),
    ];
    state.visibleSessionCount = Math.min(
      Math.max(state.visibleSessionCount + 1, SESSION_CHUNK_SIZE),
      state.sessions.length
    );

    renderProgressHeader();
    renderQuizButton();
    renderSession(session);
    renderSessionLibrary();
    renderDashboardContent();
    resetUploadPreview();
    els.analyzeForm.reset();
    els.analyzeButton.disabled = true;
    await Promise.all([fetchReviewDashboard(), fetchProgressDashboard(), fetchChallenge()]);
    startQuizPolling();
    showToast("Session ready. Write your explanation to begin.");
  } catch (error) {
    showToast(error.message, true);
    if (state.currentSession) {
      renderSession(state.currentSession);
    } else {
      state.learnView = "compose";
      renderLearnPlaceholder();
    }
  } finally {
    setButtonBusy(els.analyzeButton, false, "Generate Explanation");
  }
}

async function submitExplanationFeedback(session) {
  const input = document.getElementById("learnerExplanationInput");
  const button = document.getElementById("submitWritingButton");
  const explanation = input?.value?.trim() || "";

  if (!explanation) {
    showToast("Write your explanation first.", true);
    return;
  }

  setButtonBusy(button, true, "Checking...");
  showSessionThinkingState("Analyzing your writing...", [
    "Checking clarity and detail",
    "Finding reusable phrases",
    "Preparing feedback",
  ]);
  try {
    const data = await api(`/api/sessions/${session.id}/feedback`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ explanation }),
    });
    state.progress = data.progress || state.progress;
    state.stats = data.stats || state.stats;
    renderProgressHeader();
    renderDashboardContent();
    const feedback = data.feedback || {};
    renderSessionStep("feedback", {
      explanation,
      feedback,
      attempts: [
        {
          text: explanation,
          feedback,
          score: feedbackTotalScore(feedback),
        },
      ],
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    showToast(error.message, true);
    renderSessionStep("write", { explanation });
  } finally {
    setButtonBusy(button, false, "Submit");
  }
}

async function requestImprovementFeedback(session, explanation, improvedText) {
  const button = document.getElementById("submitImproveButton");
  setButtonBusy(button, true, "Checking...");
  showSessionThinkingState("Reviewing your improved answer...", [
    "Comparing your rewrite",
    "Checking phrase use",
    "Updating your score",
  ]);
  try {
    const data = await api(`/api/sessions/${session.id}/feedback`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ explanation, rewrite: improvedText }),
    });
    state.progress = data.progress || state.progress;
    state.stats = data.stats || state.stats;
    renderProgressHeader();
    renderDashboardContent();
    const feedback = data.feedback || {};
    const attempts = [
      ...(state.sessionFlow.attempts || []),
      {
        text: improvedText,
        feedback,
        score: feedbackTotalScore(feedback),
      },
    ];
    renderSessionStep("improve", {
      attempts,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    showToast(error.message, true);
    renderSessionStep("improve");
  } finally {
    setButtonBusy(button, false, "Submit Improved Version");
  }
}

async function startPostImproveQuiz(session) {
  const button = document.getElementById("continueToQuizButton");
  const attempts = state.sessionFlow.attempts || [];
  const firstAttempt = attempts[0] || {};
  const latestAttempt = attempts[attempts.length - 1] || {};
  setButtonBusy(button, true, "Building quiz...");
  els.quizModal.classList.remove("hidden");
  els.quizModalLabel.textContent = "Post-Improve Quiz";
  els.quizModalTitle.textContent = "Building targeted questions";
  els.quizContent.innerHTML = renderAiThinkingState("Creating your quiz...", [
    "Using your image explanation",
    "Checking reusable phrases",
    "Turning feedback into questions",
  ]);
  try {
    const data = await api(`/api/sessions/${session.id}/post-improve-quiz`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        explanation: state.sessionFlow.explanation || firstAttempt.text || "",
        learner_text: firstAttempt.text || state.sessionFlow.explanation || "",
        improved_text: latestAttempt.text || "",
        feedback: latestAttempt.feedback || state.sessionFlow.feedback || {},
      }),
    });
    state.quizDashboard = data.dashboard || state.quizDashboard;
    state.currentQuizRun = data.run;
    renderQuizButton();
    renderQuizRun(data.run);
  } catch (error) {
    showToast(error.message, true);
    closeQuizModal();
  } finally {
    setButtonBusy(button, false, "Continue to Quiz");
  }
}

function startQuizPolling() {
  stopQuizPolling();
  state.quizTimer = window.setInterval(async () => {
    if (!state.user || document.hidden || !els.quizModal.classList.contains("hidden")) {
      return;
    }
    await Promise.all([
      refreshQuizDashboard({ silent: true, nudge: true }),
      fetchChallenge({ silent: true }),
      fetchReviewDashboard({ silent: true }),
      fetchProgressDashboard({ silent: true }),
    ]);
  }, state.settings.review_prompt_interval_seconds * 1000);
}

function stopQuizPolling() {
  if (state.quizTimer) {
    window.clearInterval(state.quizTimer);
    state.quizTimer = null;
  }
}

async function refreshQuizDashboard({ silent = false, nudge = false } = {}) {
  if (!state.user) {
    state.quizDashboard = null;
    renderQuizButton();
    return null;
  }

  try {
    const data = await api("/api/quiz/dashboard");
    state.quizDashboard = data.dashboard || null;
    state.challenge = data.challenge || state.challenge;
    renderQuizButton();
    renderDashboardContent();

    if (nudge) {
      maybeShowQuizReminder(data.dashboard);
    }
    return data.dashboard;
  } catch (error) {
    if (!silent) {
      showToast(error.message, true);
    }
    return null;
  }
}

async function fetchReviewDashboard({ silent = false } = {}) {
  if (!state.user) {
    state.review = null;
    renderDashboardContent();
    return null;
  }

  try {
    const data = await api("/api/review/dashboard");
    state.review = data.review || null;
    if (data.progress) {
      state.progress = data.progress;
      renderProgressHeader();
    }
    renderDashboardContent();
    return data.review;
  } catch (error) {
    if (!silent) {
      showToast(error.message, true);
    }
    return null;
  }
}

async function fetchProgressDashboard({ silent = false } = {}) {
  if (!state.user) {
    state.progress = null;
    renderProgressHeader();
    renderDashboardContent();
    return null;
  }

  try {
    const data = await api("/api/progress/dashboard");
    state.progress = data.progress || null;
    state.stats = data.stats || state.stats;
    renderProgressHeader();
    renderDashboardContent();
    return data.progress;
  } catch (error) {
    if (!silent) {
      showToast(error.message, true);
    }
    return null;
  }
}

async function fetchChallenge({ silent = false } = {}) {
  if (!state.user) {
    state.challenge = null;
    renderDashboardContent();
    return null;
  }

  try {
    const data = await api("/api/challenge/today");
    state.challenge = data.challenge || null;
    if (data.progress) {
      state.progress = data.progress;
      renderProgressHeader();
    }
    renderDashboardContent();
    return data.challenge;
  } catch (error) {
    if (!silent) {
      showToast(error.message, true);
    }
    return null;
  }
}

function maybeShowQuizReminder(dashboard) {
  if (!dashboard) {
    return;
  }

  const reminderKey = [
    dashboard.active_run ? `run:${dashboard.active_run.id}` : "run:none",
    `due:${dashboard.due_count}`,
    `cooldown:${dashboard.cooldown_active ? "yes" : "no"}`,
  ].join("|");

  if (reminderKey === state.lastQuizReminderKey) {
    return;
  }

  state.lastQuizReminderKey = reminderKey;

  if (dashboard.active_run) {
    showToast("Your quiz is waiting for you.");
    return;
  }

  if (dashboard.can_start && dashboard.due_count > 0) {
    showToast(
      `Quiz ready: ${dashboard.available_question_count} question${pluralize(
        dashboard.available_question_count
      )} waiting.`
    );
  }
}

function openDashboardModal() {
  renderDashboardContent();
  els.dashboardModal.classList.remove("hidden");
}

function closeDashboardModal() {
  els.dashboardModal.classList.add("hidden");
}

function renderDashboardContent() {
  if (!state.user) {
    els.dashboardContent.innerHTML = `
      <div class="empty-copy">
        Sign in to see your progress, due review, and daily challenge.
      </div>
    `;
    return;
  }

  const progress = state.progress || {
    xp_points: 0,
    streak_days: 0,
    learner_level: 1,
    words_learned: 0,
    phrases_mastered: 0,
    combo_streak: 0,
    best_combo: 0,
    overall_accuracy_percent: 0,
    overall_mastery_percent: 0,
    recent_runs: [],
    weekly_summary: { accuracy_percent: 0, improvement_percent: 0 },
  };
  const review = state.review || { due_count: 0, weak_items: 0, items: [] };
  const challenge = state.challenge || null;
  const recentSessions = state.sessions.slice(0, 3);
  const recentRuns = Array.isArray(progress.recent_runs) ? progress.recent_runs.slice(0, 4) : [];

  els.dashboardContent.innerHTML = `
    <div class="dashboard-stack">
      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Profile</p>
            <h4>${escapeHtml(state.user.full_name)}</h4>
          </div>
          <button id="logoutButton" class="text-button" type="button">Log out</button>
        </div>
        <div class="dashboard-stat-grid">
          <article class="status-pill">
            <span class="status-label">XP</span>
            <strong class="status-value">${progress.xp_points || 0}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Streak</span>
            <strong class="status-value">${progress.streak_days || 0}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Level</span>
            <strong class="status-value">${progress.learner_level || 1}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Words</span>
            <strong class="status-value">${progress.words_learned || 0}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Accuracy</span>
            <strong class="status-value">${progress.overall_accuracy_percent || 0}%</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Weak Items</span>
            <strong class="status-value">${progress.weak_items || 0}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Combo</span>
            <strong class="status-value">${progress.combo_streak || 0}</strong>
          </article>
          <article class="status-pill">
            <span class="status-label">Mastery</span>
            <strong class="status-value">${progress.overall_mastery_percent || 0}%</strong>
          </article>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Quick Access</p>
            <h4>Review and challenge</h4>
          </div>
        </div>
        <div class="dashboard-action-grid">
          <button class="dashboard-action-card" type="button" data-dashboard-action="review" ${
            !review.due_count ? "disabled" : ""
          }>
            <span class="mini-pill">Review</span>
            <strong>${review.due_count || 0} due</strong>
            <span class="muted">${review.weak_items || 0} weak area${pluralize(review.weak_items || 0)}</span>
          </button>
          <button class="dashboard-action-card" type="button" data-dashboard-action="challenge" ${
            !challenge?.can_start ? "disabled" : ""
          }>
            <span class="mini-pill">Challenge</span>
            <strong>${challenge?.total_questions || 0} questions</strong>
            <span class="muted">${
              challenge
                ? challenge.status === "completed"
                  ? `Completed ${challenge.correct_count}/${challenge.total_questions}`
                  : "Today's 5-minute challenge"
                : "Unlock with more lessons"
            }</span>
          </button>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Today’s Review</p>
            <h4>Due now</h4>
          </div>
        </div>
        ${
          review.items?.length
            ? `
            <div class="review-preview-grid">
              ${review.items
                .map(
                  (item) => `
                    <article class="review-preview-card">
                      <div class="session-row">
                        <strong>${escapeHtml(item.session_title || "Lesson review")}</strong>
                        <span class="mini-pill">${item.is_weak ? "Weak" : `${item.mastery_percent || 0}%`}</span>
                      </div>
                      <p>${escapeHtml(item.prompt)}</p>
                      ${
                        item.context_note
                          ? `<p class="muted">${escapeHtml(item.context_note)}</p>`
                          : ""
                      }
                    </article>
                  `
                )
                .join("")}
            </div>
          `
            : `<div class="empty-copy">No review items are due right now.</div>`
        }
      </section>

      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">History</p>
            <h4>Recent activity</h4>
          </div>
        </div>
        ${
          recentRuns.length
            ? `
            <div class="review-preview-grid">
              ${recentRuns
                .map(
                  (run) => `
                    <article class="review-preview-card">
                      <strong>${escapeHtml(run.source_label || prettyQuizType(run.run_mode))}</strong>
                      <p>${run.correct_count}/${run.total_questions} correct</p>
                      <p class="muted">${escapeHtml(formatDate(run.completed_at))}</p>
                    </article>
                  `
                )
                .join("")}
            </div>
          `
            : `<div class="empty-copy">Complete a quiz or challenge to start building history.</div>`
        }
        ${
          recentSessions.length
            ? `
            <div class="review-preview-grid">
              ${recentSessions
                .map(
                  (session) => `
                    <article class="review-preview-card">
                      <strong>${escapeHtml(session.title)}</strong>
                      <p>Mastery ${Math.round(session.mastery_percent || 0)}%</p>
                      <p class="muted">${escapeHtml(formatDate(session.created_at))}</p>
                    </article>
                  `
                )
                .join("")}
            </div>
          `
            : ""
        }
      </section>
    </div>
  `;

  const logoutButton = document.getElementById("logoutButton");
  if (logoutButton) {
    logoutButton.addEventListener("click", onLogout);
  }

  els.dashboardContent.querySelectorAll("[data-dashboard-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.dashboardAction;
      closeDashboardModal();
      if (action === "review") {
        openReviewModal();
        return;
      }
      if (action === "challenge") {
        openQuizModal({ mode: "daily_challenge" });
      }
    });
  });
}

function renderLearnMode() {
  const showSession = state.learnView === "session" && Boolean(state.currentSession);
  const showCompose = !showSession;

  els.learnIntro.classList.toggle("hidden", !showCompose);
  els.composePanel.classList.toggle("hidden", !showCompose);
  els.sessionWorkspace.classList.toggle("hidden", !showSession);
  els.newSessionButton.classList.toggle("hidden", !state.user);
  els.quizLauncherButton.classList.toggle("hidden", showSession);
}

function renderSessionLibrary() {
  teardownSessionObserver();

  if (els.sessionWorkspace.classList.contains("focused-session-layout")) {
    els.sessionLibrarySection.classList.add("hidden");
    els.sessionWorkspace.classList.remove("has-session-library");
    return;
  }

  if (!state.user || !state.sessions.length || !state.currentSession) {
    els.sessionLibrarySection.classList.add("hidden");
    els.sessionWorkspace.classList.remove("has-session-library");
    els.sessionList.innerHTML = "";
    els.sessionLoadSentinel.classList.add("hidden");
    return;
  }

  const visibleSessions = state.sessions.slice(0, state.visibleSessionCount || SESSION_CHUNK_SIZE);
  els.sessionLibrarySection.classList.remove("hidden");
  els.sessionWorkspace.classList.add("has-session-library");
  els.sessionList.innerHTML = visibleSessions
    .map(
      (session) => `
        <button
          class="session-item learn-session-item ${state.currentSessionId === session.id ? "active" : ""}"
          type="button"
          data-session-id="${session.id}"
        >
          <div class="session-row">
            <h4>${escapeHtml(session.title)}</h4>
            <span class="session-tag">${escapeHtml(session.source_mode === "demo" ? "demo" : "live")}</span>
          </div>
          <p class="session-meta">
            ${escapeHtml(formatDate(session.created_at))} · Mastery ${Math.round(
              session.mastery_percent || 0
            )}%
          </p>
        </button>
      `
    )
    .join("");

  els.sessionList.appendChild(els.sessionLoadSentinel);

  els.sessionList.querySelectorAll("[data-session-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await loadSession(Number(button.dataset.sessionId));
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  const hasMoreSessions = state.visibleSessionCount < state.sessions.length;
  els.sessionLoadSentinel.classList.toggle("hidden", !hasMoreSessions);

  if (hasMoreSessions) {
    sessionListObserver = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        state.visibleSessionCount = Math.min(
          state.visibleSessionCount + SESSION_CHUNK_SIZE,
          state.sessions.length
        );
        renderSessionLibrary();
      },
      { root: els.sessionList, rootMargin: "140px 0px" }
    );
    sessionListObserver.observe(els.sessionLoadSentinel);
  }
}

function teardownSessionObserver() {
  if (!sessionListObserver) {
    return;
  }
  sessionListObserver.disconnect();
  sessionListObserver = null;
}

async function onLogout() {
  try {
    await api("/api/auth/logout", {
      method: "POST",
    });
  } catch (error) {
    showToast(error.message, true);
  } finally {
    closeDashboardModal();
    closeQuizModal();
    closeLanguageModal();
    clearUserState();
    switchAuthTab("signup");
  }
}

async function openReviewModal() {
  state.currentReviewSession = null;
  els.quizModal.classList.remove("hidden");
  els.quizModalLabel.textContent = "Today’s Review";
  els.quizModalTitle.textContent = "Preparing due items";
  els.quizContent.innerHTML = `<div class="feedback-box">Loading your review cards...</div>`;
  await startReviewSession();
}

async function startReviewSession() {
  try {
    const data = await api("/api/review/queue?mode=auto&limit=7");
    state.review = data.review || state.review;
    state.stats = data.stats || state.stats;
    renderDashboardContent();
    renderQuizButton();

    const cards = Array.isArray(data.cards) ? data.cards : [];
    if (!cards.length) {
      renderReviewUnavailable("No review items are due right now.");
      return;
    }

    state.currentReviewSession = {
      cards,
      index: 0,
      answeredCount: 0,
      correctCount: 0,
      wrongCount: 0,
    };
    renderReviewCard();
  } catch (error) {
    renderReviewUnavailable(error.message || "Unable to load the review queue.");
  }
}

async function openQuizModal(options = { mode: "mixed" }) {
  state.currentReviewSession = null;
  state.currentQuizLaunch = options;
  els.quizModal.classList.remove("hidden");
  els.quizModalLabel.textContent = options.mode === "session" ? "Quick Challenge" : "Quiz Mode";
  els.quizModalTitle.textContent =
    options.mode === "session" ? "Preparing your lesson quiz" : "Preparing your next round";
  els.quizContent.innerHTML = renderAiThinkingState("Building your quiz...", [
    "Choosing the best practice items",
    "Balancing review and new language",
    "Preparing questions",
  ]);
  await startOrResumeQuiz();
}

function closeQuizModal() {
  state.currentQuizRun = null;
  state.currentReviewSession = null;
  state.quizQuestionStartedAt = null;
  els.quizModal.classList.add("hidden");
}

function openLanguageModal({ item, kind, session }) {
  const term =
    kind === "vocabulary" ? item.word : kind === "pattern" ? item.pattern : item.phrase;
  const label =
    kind === "vocabulary"
      ? item.part_of_speech || "word"
      : kind === "pattern"
        ? "sentence structure"
      : item.collocation_type || "phrase";
  const examples = buildLanguageExamples(item);

  els.languageModalLabel.textContent =
    kind === "vocabulary"
      ? "Word Practice"
      : kind === "pattern"
        ? "Structure Practice"
        : "Phrase Practice";
  els.languageModalTitle.textContent = term;
  els.languageModalContent.innerHTML = `
    <div class="language-modal-stack">
      <div class="language-modal-summary">
        <span class="mini-pill">${escapeHtml(label)}</span>
        <p>${escapeHtml(item.meaning_simple || item.usage_note || "Useful reusable language from this lesson.")}</p>
      </div>
      <div class="language-example-panel">
        <h4>More examples</h4>
        <div class="language-example-list">
          ${
            examples.length
              ? examples
                  .map(
                    (example, index) => `
                <article class="language-example-card">
                  <span class="language-example-index">${index + 1}</span>
                  <p>${escapeHtml(example)}</p>
                </article>
              `
                  )
                  .join("")
              : `<article class="language-example-card"><p>No saved examples are available for this item yet.</p></article>`
          }
        </div>
      </div>
    </div>
  `;
  els.languageModal.classList.remove("hidden");
}

function closeLanguageModal() {
  els.languageModal.classList.add("hidden");
}

function buildLanguageExamples(item) {
  const examples = [];
  const seen = new Set();

  const push = (value) => {
    const text = String(value || "").trim();
    if (!text) {
      return;
    }
    const key = text.toLowerCase().replace(/\s+/g, " ");
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    examples.push(text);
  };

  const aiExamples = Array.isArray(item.examples) ? item.examples : [];
  aiExamples.forEach(push);
  push(item.example);

  return examples;
}

async function startOrResumeQuiz() {
  try {
    const data = await api("/api/quiz/start", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(state.currentQuizLaunch || { mode: "mixed" }),
    });
    state.quizDashboard = data.dashboard || state.quizDashboard;
    state.challenge = data.challenge || state.challenge;
    renderQuizButton();
    renderDashboardContent();

    if (!data.run) {
      renderQuizUnavailable(data.message || "Quiz is unavailable right now.");
      return;
    }

    state.currentQuizRun = data.run;
    renderQuizRun(data.run);
  } catch (error) {
    renderQuizUnavailable(error.message || "Unable to open the quiz right now.");
  }
}

function renderQuizUnavailable(message) {
  els.quizModalLabel.textContent = "Quiz Mode";
  els.quizModalTitle.textContent = "Not ready yet";
  els.quizContent.innerHTML = `
    <div class="feedback-box">
      <strong>${escapeHtml(message)}</strong>
    </div>
  `;
}

function renderReviewUnavailable(message) {
  els.quizModalLabel.textContent = "Today’s Review";
  els.quizModalTitle.textContent = "Not ready yet";
  els.quizContent.innerHTML = `
    <div class="feedback-box">
      <strong>${escapeHtml(message)}</strong>
    </div>
  `;
}

function renderReviewCard() {
  const reviewSession = state.currentReviewSession;
  const card = reviewSession?.cards?.[reviewSession.index];
  if (!reviewSession || !card) {
    renderReviewSummary();
    return;
  }

  state.quizQuestionStartedAt = Date.now();
  state.quizConfidence = 2;

  const progressPercent = Math.max(
    8,
    Math.round((reviewSession.index / reviewSession.cards.length) * 100)
  );

  els.quizModalLabel.textContent = "Today’s Review";
  els.quizModalTitle.textContent = `Card ${reviewSession.index + 1} of ${reviewSession.cards.length}`;
  els.quizContent.innerHTML = `
    <div class="quiz-flow quiz-question-enter">
      <div class="quiz-progress-row">
        <div>
          <p class="eyebrow">Progress</p>
          <strong>${reviewSession.answeredCount} answered · ${
            reviewSession.cards.length - reviewSession.answeredCount
          } left</strong>
        </div>
        <div class="mini-pill">${reviewSession.correctCount} right / ${reviewSession.wrongCount} wrong</div>
      </div>
      <div class="quiz-progress-track">
        <span class="quiz-progress-bar" style="width: ${progressPercent}%"></span>
      </div>
      <div class="quiz-type-row">
        <span class="mini-pill">${card.is_weak ? "Weak item" : "Review"}</span>
        <span class="mini-pill">Mastery ${card.mastery_percent || 0}%</span>
      </div>
      <p class="review-question">${escapeHtml(card.prompt)}</p>
      ${
        card.context_note
          ? `<div class="tip-box">Hint: ${escapeHtml(card.context_note)}</div>`
          : ""
      }
      <div class="confidence-row">
        <span class="field-label">Confidence</span>
        <div class="confidence-options">
          <button class="confidence-chip" type="button" data-confidence="1">Not sure</button>
          <button class="confidence-chip active" type="button" data-confidence="2">Okay</button>
          <button class="confidence-chip" type="button" data-confidence="3">Sure</button>
        </div>
      </div>
      <div class="answer-options">
        ${card.options
          .map(
            (option, index) => `
              <button class="answer-button quiz-answer-button" type="button" data-review-option-index="${index}">
                ${escapeHtml(option)}
              </button>
            `
          )
          .join("")}
      </div>
    </div>
  `;

  bindConfidenceButtons();
  els.quizContent.querySelectorAll("[data-review-option-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const option = card.options[Number(button.dataset.reviewOptionIndex)];
      submitReviewAnswer(option);
    });
  });
}

function renderQuizRun(run) {
  state.currentQuizRun = run;

  if (!run || run.status === "completed" || !run.question) {
    renderQuizSummary(run);
    return;
  }

  const question = run.question;
  state.quizQuestionStartedAt = Date.now();
  state.quizConfidence = 2;

  const progressPercent = Math.max(
    8,
    Math.round(((question.question_index - 1) / run.total_questions) * 100)
  );

  els.quizModalLabel.textContent = run.source_label || (run.answered_count > 0 ? "Resume Quiz" : "Quiz Mode");
  els.quizModalTitle.textContent = `Question ${question.question_index} of ${question.total_questions}`;
  els.quizContent.innerHTML = `
    <div class="quiz-flow">
      <div class="quiz-progress-track">
        <span class="quiz-progress-bar" style="width: ${progressPercent}%"></span>
      </div>
      <div class="quiz-top-stats">
        <span>Progress <strong>${question.question_index}/${question.total_questions}</strong></span>
        <span>XP <strong>${state.progress?.xp_points || 0}</strong></span>
        <span>Combo <strong>x${state.progress?.combo_streak || 0}</strong></span>
        <span>Best <strong>x${state.progress?.best_combo || 0}</strong></span>
      </div>
      <section class="quiz-question-card quiz-type-${escapeHtml(question.quiz_type)}">
        <div class="quiz-type-row">
          <span class="mini-pill">${escapeHtml(prettyQuizType(question.quiz_type))}</span>
          <span class="mini-pill">${escapeHtml(prettyAnswerMode(question.answer_mode))}</span>
          ${
            question.related_reusable_phrase
              ? `<span class="mini-pill">Phrase: ${escapeHtml(question.related_reusable_phrase)}</span>`
              : ""
          }
          ${question.xp_value ? `<span class="mini-pill">${question.xp_value} XP</span>` : ""}
        </div>
        ${renderQuizTypeDetail(question)}
        <p class="review-question">${escapeHtml(question.prompt)}</p>
        ${
          question.context_note
            ? `<div class="tip-box">Hint: ${escapeHtml(question.context_note)}</div>`
            : ""
        }
        <div class="confidence-row">
          <span class="field-label">Confidence</span>
          <div class="confidence-options">
            <button class="confidence-chip" type="button" data-confidence="1">Not sure</button>
            <button class="confidence-chip active" type="button" data-confidence="2">Okay</button>
            <button class="confidence-chip" type="button" data-confidence="3">Sure</button>
          </div>
        </div>
        <div id="quizAnswerZone"></div>
      </section>
    </div>
  `;

  bindConfidenceButtons();

  const answerZone = document.getElementById("quizAnswerZone");
  if (question.answer_mode === "typing") {
    renderTypingAnswer(question, answerZone);
    return;
  }
  if (question.answer_mode === "reorder") {
    renderReorderAnswer(question, answerZone);
    return;
  }
  renderMultipleChoiceAnswer(question, answerZone);
}

function bindConfidenceButtons() {
  els.quizContent.querySelectorAll("[data-confidence]").forEach((button) => {
    button.addEventListener("click", () => {
      state.quizConfidence = Number(button.dataset.confidence);
      els.quizContent.querySelectorAll("[data-confidence]").forEach((chip) => {
        chip.classList.toggle("active", chip === button);
      });
    });
  });
}

function renderMultipleChoiceAnswer(question, container) {
  let selectedOption = "";
  const duel = question.quiz_type === "phrase_duel";
  const snap = question.quiz_type === "phrase_snap";
  container.innerHTML = `
    <div class="answer-options ${duel ? "phrase-duel-options" : snap ? "phrase-snap-options" : ""}">
      ${question.options
        .map(
          (option, index) => `
            <button class="answer-button quiz-answer-button ${
              duel ? "phrase-duel-card" : snap ? "phrase-snap-option" : ""
            }" type="button" data-option-index="${index}">
              ${escapeHtml(option)}
            </button>
          `
        )
        .join("")}
    </div>
    <div class="quiz-submit-bar">
      <button id="submitChoiceAnswer" class="primary-button quiz-submit-button" type="button" disabled>Submit answer</button>
    </div>
  `;

  container.querySelectorAll("[data-option-index]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedOption = question.options[Number(button.dataset.optionIndex)];
      container.querySelectorAll("[data-option-index]").forEach((item) => {
        item.classList.toggle("selected", item === button);
      });
      document.getElementById("submitChoiceAnswer").disabled = false;
    });
  });
  document.getElementById("submitChoiceAnswer").addEventListener("click", () => {
    if (!selectedOption) {
      showToast("Choose an answer first.", true);
      return;
    }
    submitQuizAnswer(selectedOption);
  });
}

function renderTypingAnswer(question, container) {
  const relatedPhrase = question.related_reusable_phrase || question.metadata?.related_reusable_phrase || "";
  const starterText = question.quiz_type === "fix_the_mistake" ? extractBrokenSentence(question.prompt) : "";
  container.innerHTML = `
    <div class="typing-answer-shell">
      ${
        question.quiz_type === "use_it_or_lose_it" && relatedPhrase
          ? `<div class="phrase-focus-chip">${escapeHtml(relatedPhrase)}</div>`
          : ""
      }
      <textarea id="typingAnswerInput" class="quiz-text-input" rows="4" placeholder="${escapeHtml(
        question.quiz_type === "fix_the_mistake" ? "Edit the sentence here..." : "Type your answer here..."
      )}">${escapeHtml(starterText)}</textarea>
      ${
        question.metadata?.keywords?.length
          ? `<p class="muted">Key ideas to aim for: ${escapeHtml(question.metadata.keywords.join(", "))}</p>`
          : ""
      }
      <div class="quiz-submit-bar">
        <button id="submitTypingAnswer" class="primary-button quiz-submit-button" type="button">Submit answer</button>
      </div>
    </div>
  `;
  document.getElementById("submitTypingAnswer").addEventListener("click", () => {
    const value = document.getElementById("typingAnswerInput").value.trim();
    if (!value) {
      showToast("Type an answer first.", true);
      return;
    }
    submitQuizAnswer(value);
  });
}

function renderReorderAnswer(question, container) {
  const metadata = question.metadata || {};
  let availableTokens = [...(metadata.tokens || [])];
  let builtTokens = [];

  const draw = () => {
    container.innerHTML = `
      <div class="reorder-shell">
        <div class="reorder-answer-line">
          ${
            builtTokens.length
              ? builtTokens
                  .map(
                    (token, index) => `
                      <button class="token-chip token-chip-filled" type="button" data-built-index="${index}">
                        ${escapeHtml(token)}
                      </button>
                    `
                  )
                  .join("")
              : `<span class="muted">Tap the words in order to build the sentence.</span>`
          }
        </div>
        <div class="reorder-token-bank">
          ${availableTokens
            .map(
              (token, index) => `
                <button class="token-chip" type="button" data-available-index="${index}">
                  ${escapeHtml(token)}
                </button>
              `
            )
            .join("")}
        </div>
        <div class="utility-meta-row">
          <button id="clearReorderAnswer" class="ghost-button inline-button" type="button">Clear</button>
          <button id="submitReorderAnswer" class="primary-button inline-button quiz-submit-button" type="button" ${
            builtTokens.length ? "" : "disabled"
          }>Submit answer</button>
        </div>
      </div>
    `;

    container.querySelectorAll("[data-available-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.availableIndex);
        builtTokens.push(availableTokens[index]);
        availableTokens = availableTokens.filter((_, tokenIndex) => tokenIndex !== index);
        draw();
      });
    });

    container.querySelectorAll("[data-built-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.builtIndex);
        availableTokens.push(builtTokens[index]);
        builtTokens = builtTokens.filter((_, tokenIndex) => tokenIndex !== index);
        draw();
      });
    });

    document.getElementById("clearReorderAnswer").addEventListener("click", () => {
      availableTokens = [...(metadata.tokens || [])];
      builtTokens = [];
      draw();
    });

    document.getElementById("submitReorderAnswer").addEventListener("click", () => {
      if (!builtTokens.length) {
        showToast("Build the sentence first.", true);
        return;
      }
      submitQuizAnswer(builtTokens.join(" "));
    });
  };

  draw();
}

async function submitQuizAnswer(selectedAnswer) {
    if (!state.currentQuizRun || !state.currentQuizRun.question) {
      return;
    }

  const buttons = els.quizContent.querySelectorAll("button");
  buttons.forEach((button) => {
    button.disabled = true;
  });

  const responseMs = state.quizQuestionStartedAt ? Date.now() - state.quizQuestionStartedAt : null;
  try {
    const data = await api("/api/quiz/answer", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        run_id: state.currentQuizRun.id,
        item_id: state.currentQuizRun.question.id,
        selected_answer: selectedAnswer,
        response_ms: responseMs,
        confidence: state.quizConfidence,
      }),
    });

    state.stats = data.stats || state.stats;
    state.progress = data.progress || state.progress;
    state.quizDashboard = data.dashboard || state.quizDashboard;
    state.challenge = data.challenge || state.challenge;
    const answeredQuestion = state.currentQuizRun.question;
    state.currentQuizRun = data.run;
    if (data.result?.phrase_mastery) {
      applyPhraseMasteryUpdate(data.result.phrase_mastery);
    }
    renderProgressHeader();
    renderQuizButton();
    renderDashboardContent();

    if (data.run && data.run.status === "completed") {
      renderQuizSummary(data.run, data.result);
      await Promise.all([fetchReviewDashboard({ silent: true }), fetchProgressDashboard({ silent: true })]);
      return;
    }

    const feedback = data.result?.feedback || {};
    els.quizModalLabel.textContent = data.result.result_type || (data.result.correct ? "Correct" : "Checked");
    els.quizModalTitle.textContent = `Answer ${data.result.question_index} checked`;
    const resultType = data.result.result_type || (data.result.correct ? "Correct" : "Incorrect");
    const almostCorrect = resultType === "Almost Correct";
    const xpBreakdown = data.result.xp_breakdown || {};
    const phraseMastery = data.result.phrase_mastery || null;
    const resultDetail = renderQuizResultDetail(data.result, answeredQuestion);
    els.quizContent.innerHTML = `
      <div class="quiz-feedback-card">
        <div class="quiz-result-card ${resultClassForType(resultType)} ${resultMotionClassForType(resultType)}">
          <span class="quiz-result-label">${escapeHtml(resultType)}</span>
          ${resultDetail}
          ${
            feedback.good
              ? `<p class="muted">${escapeHtml(feedback.good)}</p>`
              : ""
          }
          ${
            feedback.improve
              ? `<p class="muted">${escapeHtml(feedback.improve)}</p>`
              : ""
          }
          ${
            feedback.corrected_example
              ? `<p class="muted"><strong>Model answer:</strong> ${escapeHtml(feedback.corrected_example)}</p>`
              : ""
          }
          ${
            data.result.next_due_at
              ? `<p class="muted">Next review: ${escapeHtml(formatDate(data.result.next_due_at))}</p>`
              : ""
          }
          <div class="quiz-xp-panel">
            <div class="reward-stat-row">
              <span class="score-pop">Score <strong id="quizScoreValue">0%</strong></span>
              <span class="xp-pop">XP gained <strong id="quizXpGainedValue">0</strong></span>
              <span>Current XP <strong>${state.progress?.xp_points || 0}</strong></span>
              <span class="combo-pop">Combo <strong>x${data.result.combo_streak || 0}</strong></span>
              <span>Max combo <strong>x${data.result.best_combo || state.progress?.best_combo || 0}</strong></span>
            </div>
            <p class="muted">${formatXpBreakdown(xpBreakdown)}</p>
          </div>
          ${
            phraseMastery
              ? `
                <div class="quiz-xp-panel">
                  <span class="field-label">Phrase mastery</span>
                  <p><strong>${escapeHtml(phraseMastery.phrase)}</strong> — ${escapeHtml(phraseMastery.state)}</p>
                </div>
              `
              : ""
          }
        </div>
        <div class="quiz-submit-bar">
          <button id="nextQuizButton" class="primary-button quiz-submit-button" type="button">Next question</button>
        </div>
      </div>
    `;
    document.getElementById("nextQuizButton").addEventListener("click", () => {
      renderQuizRun(data.run);
    });
    animateNumber("quizXpGainedValue", data.result.xp_awarded || 0);
    animateNumber("quizScoreValue", Math.round((Number(data.result.score) || 0) * 100), { suffix: "%" });
    await Promise.all([fetchReviewDashboard({ silent: true }), fetchProgressDashboard({ silent: true })]);
  } catch (error) {
    showToast(error.message, true);
    renderQuizRun(state.currentQuizRun);
  }
}

async function submitReviewAnswer(selectedAnswer) {
  const reviewSession = state.currentReviewSession;
  const card = reviewSession?.cards?.[reviewSession.index];
  if (!reviewSession || !card) {
    return;
  }

  const buttons = els.quizContent.querySelectorAll("button");
  buttons.forEach((button) => {
    button.disabled = true;
  });

  const responseMs = state.quizQuestionStartedAt ? Date.now() - state.quizQuestionStartedAt : null;
  try {
    const data = await api("/api/review/answer", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        card_id: card.id,
        selected_answer: selectedAnswer,
        response_ms: responseMs,
        confidence: state.quizConfidence,
      }),
    });

    const correct = Boolean(data.result?.correct);
    reviewSession.answeredCount += 1;
    reviewSession.correctCount += correct ? 1 : 0;
    reviewSession.wrongCount += correct ? 0 : 1;
    reviewSession.index += 1;
    state.review = data.review || state.review;
    state.progress = data.progress || state.progress;
    state.stats = data.stats || state.stats;
    renderProgressHeader();
    renderDashboardContent();

    const feedback = data.result?.feedback || {};
    els.quizModalLabel.textContent = correct ? "Correct" : "Checked";
    els.quizModalTitle.textContent = data.result?.session_title || "Today’s Review";
    els.quizContent.innerHTML = `
      <div class="quiz-feedback-card">
        <div class="feedback-box ${correct ? "feedback-success" : ""}">
          <strong>${correct ? "Correct." : "Checked."}</strong>
          <p>The answer is: ${escapeHtml(data.result.correct_answer)}</p>
          ${
            feedback.good
              ? `<p class="muted">${escapeHtml(feedback.good)}</p>`
              : ""
          }
          ${
            feedback.improve
              ? `<p class="muted">${escapeHtml(feedback.improve)}</p>`
              : ""
          }
          ${
            data.result.next_due_at
              ? `<p class="muted">Next review: ${escapeHtml(formatDate(data.result.next_due_at))}</p>`
              : ""
          }
          <p class="muted">XP earned: ${data.result.xp_awarded || 0}${
            data.result.combo_bonus ? ` · Combo +${data.result.combo_bonus}` : ""
          }</p>
        </div>
        <button id="nextReviewButton" class="primary-button" type="button">${
          reviewSession.index >= reviewSession.cards.length ? "Finish review" : "Next card"
        }</button>
      </div>
    `;
    document.getElementById("nextReviewButton").addEventListener("click", () => {
      renderReviewCard();
    });
  } catch (error) {
    showToast(error.message, true);
    renderReviewCard();
  }
}

function renderReviewSummary() {
  const reviewSession = state.currentReviewSession;
  if (!reviewSession) {
    renderReviewUnavailable("Your review session is no longer available.");
    return;
  }

  els.quizModalLabel.textContent = "Today’s Review";
  els.quizModalTitle.textContent = "Review complete";
  els.quizContent.innerHTML = `
    <div class="quiz-summary-shell">
      <div class="quiz-summary-grid">
        <article class="status-pill">
          <span class="status-label">Correct</span>
          <strong class="status-value">${reviewSession.correctCount}</strong>
        </article>
        <article class="status-pill">
          <span class="status-label">Wrong</span>
          <strong class="status-value">${reviewSession.wrongCount}</strong>
        </article>
        <article class="status-pill">
          <span class="status-label">Reviewed</span>
          <strong class="status-value">${reviewSession.answeredCount}</strong>
        </article>
      </div>
      <button id="closeReviewSummaryButton" class="primary-button" type="button">Back to learn</button>
    </div>
  `;

  document.getElementById("closeReviewSummaryButton").addEventListener("click", closeQuizModal);
}

function renderQuizSummary(run, lastResult = null) {
  if (!run) {
    renderQuizUnavailable("This quiz run is no longer available.");
    return;
  }

  els.quizModalLabel.textContent =
    run.run_mode === "daily_challenge"
      ? "Challenge Complete"
      : run.run_mode === "post_improve"
      ? "Reward"
      : run.run_mode === "session"
      ? "Quick Challenge Complete"
      : "Quiz Complete";
  els.quizModalTitle.textContent = "Round finished";
  els.quizContent.innerHTML = `
    <div class="quiz-summary-shell">
      ${
        lastResult
          ? `
          <div class="feedback-box ${lastResult.correct ? "feedback-success" : ""}">
            <strong>${lastResult.correct ? "Final answer correct." : "Final answer checked."}</strong>
            <p>The answer is: ${escapeHtml(lastResult.correct_answer)}</p>
            <p class="muted">XP earned: ${lastResult.xp_awarded || 0}${
              lastResult.combo_bonus ? ` · Combo +${lastResult.combo_bonus}` : ""
            }${lastResult.daily_bonus ? ` · Challenge +${lastResult.daily_bonus}` : ""}</p>
          </div>
        `
          : ""
      }
      <div class="quiz-summary-grid">
        <article class="status-pill">
          <span class="status-label">Correct</span>
          <strong class="status-value">${run.summary.correct_count}</strong>
        </article>
        <article class="status-pill">
          <span class="status-label">Wrong</span>
          <strong class="status-value">${run.summary.wrong_count}</strong>
        </article>
        <article class="status-pill">
          <span class="status-label">Accuracy</span>
          <strong class="status-value">${run.summary.accuracy_percent}%</strong>
        </article>
      </div>
      <div class="feedback-box feedback-success reward-card">
        <strong>Rewards saved</strong>
        <div class="reward-stat-row">
          <span>XP <strong id="rewardXpValue">${state.progress?.xp_points || 0}</strong></span>
          <span>Streak <strong id="rewardStreakValue">${state.progress?.streak_days || 0}</strong></span>
          <span>Level <strong>${state.progress?.learner_level || 1}</strong></span>
        </div>
        <p class="muted">Saved phrases ${state.progress?.phrases_mastered || 0}</p>
      </div>
      <button id="closeQuizSummaryButton" class="primary-button" type="button">Back to learn</button>
    </div>
  `;

  document.getElementById("closeQuizSummaryButton").addEventListener("click", closeQuizModal);
  animateNumber("rewardXpValue", state.progress?.xp_points || 0);
  animateNumber("rewardStreakValue", state.progress?.streak_days || 0);
}

function setButtonBusy(button, busy, label) {
  if (!button) {
    return;
  }
  button.disabled = busy;
  button.textContent = label;
  button.classList.toggle("is-busy", Boolean(busy));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : null;

  if (!response.ok) {
    throw new Error(payload?.error || "Request failed.");
  }
  return payload;
}

function jsonHeaders() {
  return {
    "Content-Type": "application/json",
  };
}

function formatBand(value) {
  return String(value || "")
    .split(" ")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString();
  } catch (error) {
    return value;
  }
}

function pluralize(count) {
  return Number(count) === 1 ? "" : "s";
}

function prettyQuizType(value) {
  const mapping = {
    recognition: "Recognition",
    phrase_completion: "Phrase Completion",
    expression_training: "Expression Training",
    situation_understanding: "Situation",
    sentence_building: "Sentence Building",
    fill_blank: "Fill Blank",
    typing: "Typing",
    memory_recall: "Memory Recall",
    error_focus: "Error Focus",
    sentence_upgrade_battle: "Sentence Upgrade Battle",
    phrase_snap: "Phrase Snap",
    phrase_duel: "Phrase Duel",
    fix_the_mistake: "Fix the Mistake",
    use_it_or_lose_it: "Use It or Lose It",
  };
  return mapping[value] || formatBand(String(value || "").replaceAll("_", " "));
}

function prettyAnswerMode(value) {
  const mapping = {
    multiple_choice: "Multiple choice",
    typing: "Typing",
    reorder: "Sentence order",
  };
  return mapping[value] || formatBand(value);
}

function formatXpBreakdown(breakdown) {
  const parts = [];
  if (breakdown.base_xp) parts.push(`${formatBand(breakdown.difficulty || "base")} +${breakdown.base_xp}`);
  if (breakdown.first_try_bonus) parts.push(`First try +${breakdown.first_try_bonus}`);
  if (breakdown.phrase_bonus) parts.push(`Phrase +${breakdown.phrase_bonus}`);
  if (breakdown.fast_bonus) parts.push(`Fast +${breakdown.fast_bonus}`);
  if (breakdown.complete_all_types_bonus) parts.push(`All types +${breakdown.complete_all_types_bonus}`);
  if (breakdown.perfect_quiz_bonus) parts.push(`Perfect quiz +${breakdown.perfect_quiz_bonus}`);
  if (breakdown.weak_item_bonus) parts.push(`Weak item +${breakdown.weak_item_bonus}`);
  if (breakdown.combo_bonus) parts.push(`Combo +${breakdown.combo_bonus}`);
  if (breakdown.daily_bonus) parts.push(`Challenge +${breakdown.daily_bonus}`);
  return parts.length ? parts.join(" · ") : "No XP gained this time.";
}

function resultClassForType(resultType) {
  if (resultType === "Correct") return "result-correct";
  if (resultType === "Almost Correct") return "result-almost";
  return "result-incorrect";
}

function resultMotionClassForType(resultType) {
  if (prefersReducedMotion()) return "";
  if (resultType === "Correct") return "result-glow";
  if (resultType === "Incorrect") return "result-shake";
  return "result-soft-pop";
}

function renderQuizTypeDetail(question) {
  const phrase = question.related_reusable_phrase || question.metadata?.related_reusable_phrase || "";
  if (question.quiz_type === "sentence_upgrade_battle") {
    const weak = question.metadata?.weak_sentence || extractBrokenSentence(question.prompt);
    return weak
      ? `<div class="quote-card"><span class="field-label">Weak sentence</span><p>${escapeHtml(weak)}</p></div>`
      : "";
  }
  if (question.quiz_type === "fix_the_mistake") {
    const broken = extractBrokenSentence(question.prompt);
    return broken
      ? `<div class="broken-sentence-card"><span class="field-label">Broken sentence</span><p>${escapeHtml(broken)}</p></div>`
      : "";
  }
  if (question.quiz_type === "use_it_or_lose_it" && phrase) {
    return `<div class="phrase-focus-chip">${escapeHtml(phrase)}</div>`;
  }
  if (question.quiz_type === "phrase_snap") {
    return `<div class="quick-action-note">Fill the blank with the reusable phrase.</div>`;
  }
  return "";
}

function renderQuizResultDetail(result, question) {
  const quizType = result.quiz_type || question?.quiz_type || "";
  const selected = result.selected_answer || "";
  const correct = result.correct_answer || "";
  const metadata = result.metadata || question?.metadata || {};
  const phrase = result.phrase_mastery?.phrase || metadata.related_reusable_phrase || question?.related_reusable_phrase || "";

  if (quizType === "sentence_upgrade_battle") {
    const weak = metadata.weak_sentence || question?.metadata?.weak_sentence || "";
    return `
      <div class="before-after-grid">
        ${weak ? `<div><span class="field-label">Before</span><p>${escapeHtml(weak)}</p></div>` : ""}
        <div><span class="field-label">Your answer</span><p>${escapeHtml(selected)}</p></div>
        <div><span class="field-label">Stronger version</span><p>${escapeHtml(correct)}</p></div>
      </div>
    `;
  }
  if (quizType === "fix_the_mistake") {
    return `
      <div class="before-after-grid">
        <div><span class="field-label">Your fix</span><p>${highlightChangedWords(selected, correct)}</p></div>
        <div><span class="field-label">Corrected version</span><p>${highlightChangedWords(correct, selected)}</p></div>
      </div>
    `;
  }
  if (quizType === "use_it_or_lose_it") {
    return `
      <div class="before-after-grid">
        <div><span class="field-label">Your sentence</span><p>${highlightPhraseInText(selected, phrase)}</p></div>
        <div><span class="field-label">Model answer</span><p>${highlightPhraseInText(correct, phrase)}</p></div>
      </div>
    `;
  }
  if (quizType === "phrase_duel") {
    return `<p>Stronger phrase use: ${escapeHtml(correct)}</p>`;
  }
  return `<p>The answer is: ${escapeHtml(correct)}</p>`;
}

function extractBrokenSentence(prompt) {
  return String(prompt || "")
    .replace(/^Fix the Mistake:\s*/i, "")
    .replace(/^Sentence Upgrade Battle:\s*Rewrite this sentence stronger:\s*/i, "")
    .trim();
}

function highlightPhraseInText(text, phrase) {
  const raw = String(text || "");
  if (!phrase) return escapeHtml(raw);
  const index = raw.toLowerCase().indexOf(String(phrase).toLowerCase());
  if (index === -1) return escapeHtml(raw);
  return `${escapeHtml(raw.slice(0, index))}<mark class="inline-phrase-highlight">${escapeHtml(
    raw.slice(index, index + phrase.length)
  )}</mark>${escapeHtml(raw.slice(index + phrase.length))}`;
}

function highlightChangedWords(text, compareText) {
  const compareWords = new Set(normalizeClientText(compareText).split(" ").filter(Boolean));
  return String(text || "")
    .split(/(\s+)/)
    .map((part) => {
      if (/^\s+$/.test(part)) return escapeHtml(part);
      const key = normalizeClientText(part);
      if (key && !compareWords.has(key)) {
        return `<mark class="correction-highlight">${escapeHtml(part)}</mark>`;
      }
      return escapeHtml(part);
    })
    .join("");
}

function applyPhraseMasteryUpdate(phraseMastery) {
  const phrases = state.currentSession?.analysis?.phrases || [];
  const key = normalizeClientText(phraseMastery.phrase);
  phrases.forEach((item) => {
    if (normalizeClientText(item.phrase) === key) {
      item.mastery = phraseMastery.mastery;
      item.mastery_state = phraseMastery.state;
    }
  });
}

function showToast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  els.toast.style.background = isError ? "#8f321f" : "#1d4033";
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.classList.add("hidden");
  }, 3200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
