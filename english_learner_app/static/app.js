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
    step: "write",
    explanation: "",
    feedback: null,
    attempts: [],
  };
  renderSessionStep("write");
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
  setFocusedSessionLayout(true);
  renderWriteStep(session);
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
  const steps = activeStep === "guided_write" || activeStep === "submit"
    ? [
        ["image", "Image"],
        ["guided_write", "Guided Write"],
        ["submit", "Submit"],
      ]
    : [
        ["image", "Image"],
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
  const prefix = options.prefix || "";
  if (!element) {
    return;
  }
  if (prefersReducedMotion()) {
    element.textContent = `${prefix}${target}${suffix}`;
    return;
  }
  const duration = 520;
  const startTime = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    element.textContent = `${prefix}${Math.round(target * eased)}${suffix}`;
    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  };
  requestAnimationFrame(tick);
}

function playTapAnimation(element) {
  if (!element || prefersReducedMotion()) {
    return;
  }
  element.classList.remove("tap-pop");
  void element.offsetWidth;
  element.classList.add("tap-pop");
  window.setTimeout(() => {
    element.classList.remove("tap-pop");
  }, 220);
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
  const hintGroups = buildWritingHintGroups(session);
  const starterOptions = getWritingStarters(session);
  const starterText = starterOptions[0] || "The image shows ";
  const draftText = state.sessionFlow.explanation || starterText;
  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell">
      ${renderStepProgress("guided_write")}
      <section class="focused-writing-card">
        <div class="focused-image-frame">
          <img class="focused-image-preview" src="${session.image_url}" alt="Image to describe">
        </div>
        <div class="focused-copy">
          <p class="eyebrow">Guided Write</p>
          <h3>Describe this in 1 sentence.</h3>
        </div>
        <div class="mini-suggestion-row sentence-starter-row" aria-label="Sentence starters">
          ${starterOptions
            .map(
              (starter, index) => `
                <button class="sentence-starter-button ${index === 0 ? "selected" : ""}" type="button" data-insert-starter="${escapeHtml(starter)}">
                  ${escapeHtml(starter.trim())}
                </button>
              `
            )
            .join("")}
        </div>
        <textarea
          id="learnerExplanationInput"
          class="focused-writing-input guided-writing-input"
          rows="4"
          maxlength="900"
          placeholder="${escapeHtml(starterText)}"
        >${escapeHtml(draftText)}</textarea>
        ${
          hintGroups.some((group) => group.items.length)
            ? `
              <section class="guided-hint-panel" aria-label="Writing hints">
                ${hintGroups
                  .filter((group) => group.items.length)
                  .map(
                    (group) => `
                      <div class="guided-hint-group">
                        <span class="field-label">${escapeHtml(group.label)}</span>
                        <div class="mini-suggestion-row">
                          ${group.items
                            .map(
                              (item) => `
                                <button class="guidance-pill hint-chip-button" type="button" data-insert-hint="${escapeHtml(item)}">
                                  ${escapeHtml(item)}
                                </button>
                              `
                            )
                            .join("")}
                        </div>
                      </div>
                    `
                  )
                  .join("")}
              </section>
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
  els.sessionDetailPanel.querySelectorAll("[data-insert-starter]").forEach((button) => {
    button.addEventListener("click", () => {
      replaceWritingStarter(button.dataset.insertStarter || "");
      playTapAnimation(button);
      els.sessionDetailPanel.querySelectorAll("[data-insert-starter]").forEach((item) => {
        item.classList.toggle("selected", item === button);
      });
    });
  });
  els.sessionDetailPanel.querySelectorAll("[data-insert-hint]").forEach((button) => {
    button.addEventListener("click", () => {
      insertWritingHint(button.dataset.insertHint || "");
      playTapAnimation(button);
      button.classList.add("selected");
    });
  });
  const writingInput = document.getElementById("learnerExplanationInput");
  writingInput?.addEventListener("input", limitWritingInput);
  if (writingInput) {
    const cursorPosition = writingInput.value.length;
    writingInput.setSelectionRange(cursorPosition, cursorPosition);
  }
  window.setTimeout(() => {
    writingInput?.focus();
  }, 50);
}

function getWritingStarters(session) {
  const analysis = session?.analysis || {};
  const aiStarters = Array.isArray(analysis.sentence_starters) ? analysis.sentence_starters : [];
  const defaults = [
    "The image shows ",
    "Here we see ",
    "This scene shows ",
    "In this picture, ",
    "The photo captures ",
    "At first glance, ",
  ];
  const blockedTerms = [
    ...(analysis.objects || []).map((item) => item?.name || item),
    ...(analysis.actions || []).map((item) => item?.verb || item?.phrase || item),
    analysis.environment,
    ...(analysis.environment_details || []),
  ]
    .map((item) => normalizeClientText(item))
    .filter((item) => item && item.length > 2);
  return uniqueWritingHints([...aiStarters, ...defaults])
    .map(normalizeSentenceStarter)
    .filter((starter) => starter && !starterMentionsImageContent(starter, blockedTerms))
    .slice(0, 4);
}

function getWritingStarter(session) {
  return getWritingStarters(session)[0] || "The image shows ";
}

function normalizeSentenceStarter(value) {
  let text = cleanUiText(value).replace(/…/g, "...").replace(/\s*\.\.\.\s*$/, " ").trimEnd();
  if (!text) {
    return "";
  }
  if (!/[\s,]$/.test(text)) {
    text += " ";
  }
  return text;
}

function starterMentionsImageContent(starter, blockedTerms) {
  const key = normalizeClientText(starter);
  return blockedTerms.some((term) => term && key.includes(term));
}

function buildWritingHintGroups(session) {
  const analysis = session.analysis || {};
  const objectHints = uniqueWritingHints(
    (analysis.objects || []).map((item) => item?.name || item)
  ).slice(0, 3);
  const actionHints = uniqueWritingHints(
    (analysis.actions || []).map((item) => item?.verb || actionPhraseToVerb(item?.phrase || item))
  ).slice(0, 2);
  const structureHints = uniqueWritingHints([
    ...buildStructureHints(analysis),
    ...((analysis.sentence_patterns || []).map((item) => item?.pattern || "")),
  ]).slice(0, 3);

  const groups = [
    { label: "Objects", items: objectHints },
    { label: "Actions", items: actionHints },
    { label: "Structures", items: structureHints },
  ];
  let total = groups.reduce((sum, group) => sum + group.items.length, 0);
  if (total > 8) {
    groups.forEach((group) => {
      group.items = group.items.slice(0, Math.max(1, 8 - (total - group.items.length)));
      total = groups.reduce((sum, nextGroup) => sum + nextGroup.items.length, 0);
    });
  }
  return groups;
}

function actionPhraseToVerb(value) {
  const text = cleanUiText(value);
  const ingWord = text.match(/\b[a-z][a-z-]*ing\b/i)?.[0];
  return ingWord || text.split(/\s+/).slice(0, 2).join(" ");
}

function buildStructureHints(analysis) {
  const details = [analysis.environment, ...(analysis.environment_details || [])];
  const hints = details
    .map((item) => structureHintFromDetail(item))
    .filter(Boolean);
  return [...hints, "in the background", "in the foreground"];
}

function structureHintFromDetail(value) {
  const text = cleanUiText(value).replace(/[.!?]+$/, "");
  if (!text) {
    return "";
  }
  const lower = text.toLowerCase();
  if (/^on\s|^in\s|^near\s|^under\s|^behind\s|^beside\s|^with\s/.test(lower)) {
    return text;
  }
  if (lower.includes("background")) {
    return "in the background";
  }
  if (lower.includes("foreground") || lower.includes("front")) {
    return "in the foreground";
  }
  if (/\bgrass|lawn|field|road|street|sidewalk|floor|ground|table|chair|bench\b/.test(lower)) {
    return `on the ${lastUsefulNoun(lower)}`;
  }
  if (/\broom|kitchen|park|yard|garden|cafe|shop|market|water|river|beach\b/.test(lower)) {
    return `in the ${lastUsefulNoun(lower)}`;
  }
  if (/\btree|car|building|window|bridge|wall\b/.test(lower)) {
    return `near the ${lastUsefulNoun(lower)}`;
  }
  return "";
}

function lastUsefulNoun(text) {
  const blocked = new Set(["front", "back", "bright", "busy", "open", "sunny", "foreground"]);
  const words = text
    .replace(/[^a-z\s-]/g, " ")
    .split(/\s+/)
    .filter((word) => word && !blocked.has(word));
  return words.at(-1) || text;
}

function buildWritingSuggestions(session) {
  return buildWritingHintGroups(session).flatMap((group) => group.items);
}

function renderFeedbackStep(session, feedback) {
  if (!feedback) {
    renderSessionStep("write");
    return;
  }

  const totalScore = feedbackTotalScore(feedback);
  const latestAttempt = (state.sessionFlow.attempts || []).at(-1) || null;
  const attemptCount = Math.max(1, (state.sessionFlow.attempts || []).length);
  const latestText = latestAttempt?.text || state.sessionFlow.explanation || "";
  const issue = buildFeedbackIssue(feedback, session);
  const positive = buildFeedbackPositiveLine(feedback, totalScore, issue.focusAreas);
  const inlineUpgrades = buildFeedbackInlineUpgrades(feedback, latestText, issue);

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell diagnosis-shell">
      ${renderStepProgress("submit")}
      <section class="feedback-screen-card fast-feedback-card diagnosis-card">
        <div class="score-hero progressive-score-hero diagnosis-score-card coach-reveal" ${coachRevealStyle(0)}>
          <span class="score-label">Attempt ${attemptCount}</span>
          <div class="diagnosis-score-line">
            <strong id="feedbackScoreValue" data-score="${totalScore}">0</strong>
            <span>/100</span>
          </div>
        </div>

        <section class="diagnosis-line-card diagnosis-good-card coach-reveal" ${coachRevealStyle(1)}>
          <p><span aria-hidden="true">✓</span> Good: ${escapeHtml(positive)}</p>
        </section>

        <section class="diagnosis-line-card diagnosis-issue-card coach-reveal" ${coachRevealStyle(2)}>
          <p><strong>Main issue:</strong> ${escapeHtml(issue.message)}</p>
        </section>

        <section class="simple-feedback-section diagnosis-focus-card coach-reveal" ${coachRevealStyle(3)}>
          <h4>Next focus</h4>
          <div class="focus-area-row">
            ${issue.focusAreas.map((item) => `<span class="focus-area-chip diagnosis-chip">${escapeHtml(item)}</span>`).join("")}
          </div>
        </section>

        ${renderInlineUpgradeSection(inlineUpgrades, 4)}

        <button id="feedbackPrimaryButton" class="primary-button journey-primary-button diagnosis-cta coach-reveal" ${coachRevealStyle(5)} type="button">
          Improve My Answer
        </button>
      </section>
    </div>
  `;

  document.getElementById("feedbackPrimaryButton").addEventListener("click", () => {
    renderSessionStep("improve");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  animateNumber("feedbackScoreValue", totalScore);
}

function coachRevealStyle(index) {
  return `style="--reveal-delay: ${Math.min(index * 70, 560)}ms"`;
}

function renderInlineUpgradeSection(upgrades, revealIndex = 0) {
  if (!upgrades.length) {
    return "";
  }

  return `
    <section class="simple-feedback-section inline-upgrade-section diagnosis-upgrade-card coach-reveal" ${coachRevealStyle(revealIndex)}>
      <h4>Improve your sentence</h4>
      <ul class="inline-upgrade-list">
        ${upgrades
          .map(
            (item) => `
              <li>
                ${
                  item.kind === "add"
                    ? `
                      <span class="inline-upgrade-swap inline-upgrade-add">
                        <span class="inline-upgrade-label">Add:</span>
                        <strong>${escapeHtml(item.newText)}</strong>
                      </span>
                    `
                    : `
                      <span class="inline-upgrade-swap">
                        <del>${escapeHtml(item.oldText)}</del>
                        <span class="inline-upgrade-arrow">→</span>
                        <strong>${escapeHtml(item.newText)}</strong>
                      </span>
                    `
                }
              </li>
            `
          )
          .join("")}
      </ul>
    </section>
  `;
}

function buildFeedbackPositiveLine(feedback, score, focusAreas = []) {
  const coveragePositive = positiveLineFromCoverage(feedback, focusAreas);
  if (coveragePositive) {
    return coveragePositive;
  }
  const focusKeys = focusAreas.map(normalizeClientText).filter(Boolean);
  const candidates = [
    ...cleanUiList(feedback?.what_did_well || [], 2),
    cleanUiText(feedback?.what_improved),
  ].filter((item) => !focusKeys.some((focus) => normalizeClientText(item).includes(focus)));
  const positive = candidates.map(firstSentence).map(shortCoachSentence).find(Boolean);
  if (positive) {
    return stripLeadingFeedbackLabel(positive);
  }
  return score >= 45 ? "you described the basic scene clearly" : "you started with your own observation";
}

function buildFeedbackIssue(feedback, session) {
  const missingTypes = missingFeedbackTypes(feedback);
  const focusAreas = focusAreasFromMissingTypes(missingTypes);
  const additions = buildAdditiveSuggestions(feedback, session, missingTypes);
  const coveredTypes = coveredFeedbackTypes(feedback);
  const describedBackground = coveredTypes.some((type) => ["background", "setting"].includes(type));

  if (missingTypes.includes("main_subject") && missingTypes.includes("main_action")) {
    return {
      message: describedBackground
        ? "you described the background but missed the main subject and action."
        : "missing the main subject and main action.",
      focusAreas: ["main subject", "main action"],
      additions,
    };
  }
  if (missingTypes.includes("main_subject")) {
    return {
      message: "you missed the main subject.",
      focusAreas: ["main subject"],
      additions,
    };
  }
  if (missingTypes.includes("main_action")) {
    return {
      message: "you missed the main action.",
      focusAreas: ["main action"],
      additions,
    };
  }
  if (missingTypes.includes("foreground")) {
    return {
      message: "your answer needs more coverage of the foreground.",
      focusAreas: ["foreground"],
      additions,
    };
  }
  if (missingTypes.includes("background") || missingTypes.includes("setting")) {
    return {
      message: "you need to add the setting or background.",
      focusAreas: ["background"],
      additions,
    };
  }
  if (missingTypes.includes("detail")) {
    return {
      message: "your description is too partial.",
      focusAreas: focusAreas.length ? focusAreas : ["visible detail"],
      additions,
    };
  }

  const state = getProgressiveCoverageState(feedback);
  if (!state.naturalOk || !state.notListOk) {
    return {
      message: "your sentence needs clearer wording.",
      focusAreas: ["wording"],
      additions: [],
    };
  }

  const direct = shortCoachSentence(firstSentence(cleanUiText(feedback?.main_issue)));
  if (direct && !/\bcovered\b/i.test(direct)) {
    const directFocus = cleanUiList(feedback?.focus_areas || [], 3);
    return {
      message: stripLeadingFeedbackLabel(direct),
      focusAreas: directFocus.length ? directFocus : ["wording"],
      additions: [],
    };
  }

  const fix = shortCoachSentence(firstSentence(cleanUiList(feedback?.fix_this_to_improve || feedback?.improvements || [], 1)[0]));
  return {
    message: stripLeadingFeedbackLabel(fix) || "add one clearer missing detail.",
    focusAreas: focusAreas.length ? focusAreas : ["visible detail"],
    additions,
  };
}

function buildFeedbackInlineUpgrades(feedback, learnerText, issue = null) {
  if (issue?.additions?.length) {
    return issue.additions.slice(0, 2).map((item) => ({
      kind: "add",
      newText: item,
    }));
  }
  const upgrades = Array.isArray(feedback?.word_phrase_upgrades)
    ? feedback.word_phrase_upgrades
    : Array.isArray(feedback?.alternatives)
    ? feedback.alternatives
    : [];
  const direct = buildInlineUpgrades(learnerText, upgrades).slice(0, 3);
  if (direct.length) {
    return direct;
  }
  const loose = upgrades
    .map((item) => ({
      oldText: cleanUiText(item?.instead_of || item?.old),
      newText: cleanUiText(item?.use || item?.new || item?.strong),
    }))
    .filter((item) => item.oldText && item.newText)
    .filter((item) => !/^(simple wording|general word|short sentence|basic wording|instead)$/i.test(item.oldText))
    .slice(0, 3);
  if (loose.length) {
    return loose;
  }
  return buildQuickInlineUpgrade(
    learnerText,
    upgrades,
    feedback?.better_version || feedback?.improvedVersion || "",
    cleanUiList(feedback?.fix_this_to_improve || feedback?.improvements || [], 1)[0] || ""
  ).slice(0, 1);
}

function stripLeadingFeedbackLabel(value) {
  return cleanUiText(value).replace(/^(good|main issue|issue|focus|next):\s*/i, "");
}

function shortCoachSentence(value) {
  const text = cleanUiText(value).replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  return text
    .replace(/\s+(?:so|because)\s+.*$/i, ".")
    .replace(/\s+and your score is.*$/i, ".")
    .replace(/\s+so your score is.*$/i, ".")
    .replace(/\s*Your score is capped.*$/i, "")
    .trim();
}

function positiveLineFromCoverage(feedback, focusAreas = []) {
  const covered = coveredFeedbackTypes(feedback);
  const focusKeys = new Set(focusAreas.map(normalizeClientText));
  const safeCovered = covered.filter((type) => !focusKeys.has(normalizeClientText(typeLabelForFeedbackType(type))));
  if (safeCovered.includes("background") || safeCovered.includes("setting")) {
    return "you described the background and setting clearly.";
  }
  if (safeCovered.includes("main_subject") && safeCovered.includes("main_action")) {
    return "you mentioned the main subject and action.";
  }
  if (safeCovered.includes("main_subject")) {
    return "you mentioned the main subject.";
  }
  if (safeCovered.includes("foreground") || safeCovered.includes("detail")) {
    return "you included a useful visible detail.";
  }
  return "";
}

function missingFeedbackTypes(feedback) {
  const coverage = feedback?.coverage || {};
  const parts = Array.isArray(coverage.imageParts) ? coverage.imageParts : [];
  const types = [];
  if (coverage.mainSubjectMentioned === false) types.push("main_subject");
  if (coverage.mainActionMentioned === false) types.push("main_action");
  parts.forEach((part) => {
    const type = normalizeCoverageType(part?.type || part?.name || part?.description);
    const status = String(part?.coverageStatus || "").toLowerCase();
    const missing = part?.covered === false || ["missing", "inaccurate"].includes(status);
    if (type && missing) {
      types.push(type);
    }
  });
  cleanUiList(feedback?.missing_details || coverage.missingMajorParts || [], 5).forEach((item) => {
    const type = normalizeCoverageType(item);
    if (type) types.push(type);
  });
  return uniqueWritingHints(types);
}

function coveredFeedbackTypes(feedback) {
  const parts = Array.isArray(feedback?.coverage?.imageParts) ? feedback.coverage.imageParts : [];
  return uniqueWritingHints(
    parts
      .filter(isCoveragePartCovered)
      .map((part) => normalizeCoverageType(part?.type || part?.name || part?.description))
      .filter(Boolean)
  );
}

function normalizeCoverageType(value) {
  const text = normalizeClientText(value);
  if (!text) return "";
  if (text.includes("main subject") || text.includes("person") || text.includes("people") || text.includes("subject")) return "main_subject";
  if (text.includes("main action") || text.includes("action") || text.includes("doing") || text.includes("mowing") || text.includes("riding")) return "main_action";
  if (text.includes("foreground") || text.includes("front")) return "foreground";
  if (text.includes("background")) return "background";
  if (text.includes("setting") || text.includes("environment") || text.includes("context")) return "setting";
  if (text.includes("object") || text.includes("detail")) return "detail";
  return "";
}

function focusAreasFromMissingTypes(types) {
  const labels = types.map(typeLabelForFeedbackType).filter(Boolean);
  return uniqueWritingHints(labels).slice(0, 3);
}

function typeLabelForFeedbackType(type) {
  const labels = {
    main_subject: "main subject",
    main_action: "main action",
    foreground: "foreground",
    background: "background",
    setting: "background",
    detail: "visible detail",
  };
  return labels[type] || "";
}

function buildAdditiveSuggestions(feedback, session, missingTypes) {
  const suggestions = [];
  missingTypes.forEach((type) => {
    const part = findMissingCoveragePart(feedback, type);
    const fallback = additiveFallbackForType(type, session);
    const detail = cleanUiText(part?.description || part?.name || fallback);
    if (detail) {
      suggestions.push(detail);
    }
  });
  return uniqueWritingHints(suggestions).slice(0, 2);
}

function findMissingCoveragePart(feedback, normalizedType) {
  const parts = Array.isArray(feedback?.coverage?.imageParts) ? feedback.coverage.imageParts : [];
  return parts.find((part) => {
    const type = normalizeCoverageType(part?.type || part?.name || part?.description);
    const status = String(part?.coverageStatus || "").toLowerCase();
    return type === normalizedType && (part?.covered === false || ["missing", "inaccurate"].includes(status));
  });
}

function additiveFallbackForType(type, session) {
  const analysis = session?.analysis || {};
  if (type === "main_subject") {
    return cleanUiText((analysis.objects || [])[0]?.name || (analysis.objects || [])[0]) || "the main subject";
  }
  if (type === "main_action") {
    return cleanUiText((analysis.actions || [])[0]?.phrase || (analysis.actions || [])[0]?.verb || (analysis.actions || [])[0]) || "what the subject is doing";
  }
  if (type === "foreground") return "one foreground detail";
  if (type === "background" || type === "setting") return cleanUiText(analysis.environment) || "the background";
  return cleanUiText((analysis.environment_details || [])[0]) || "one visible detail";
}

function renderSpecificGuidance(guidance, revealIndex = 0, { showStructure = true } = {}) {
  const words = cleanUiList(guidance?.words || [], 7);
  const nouns = cleanUiList(guidance?.nouns || [], 5);
  const verbs = cleanUiList(guidance?.verbs || [], 4);
  const details = cleanUiList(guidance?.details || [], 5);
  const hintChips = uniqueWritingHints([...details, ...words]).slice(0, 8);
  const sentenceStarter = cleanUiText(guidance?.sentence_starter);
  if (!words.length && !nouns.length && !verbs.length && !details.length && !sentenceStarter) {
    return "";
  }
  return `
    <section class="simple-feedback-section exact-guidance-section coach-reveal" ${coachRevealStyle(revealIndex)}>
      <h4>Exact hints</h4>
      ${
        hintChips.length
          ? `
            <div>
              <span class="field-label">Try adding</span>
              <div class="exact-hint-row">
                ${hintChips.map((item) => `<span class="exact-hint-chip">${escapeHtml(item)}</span>`).join("")}
              </div>
            </div>
          `
          : ""
      }
      ${
        nouns.length || verbs.length
          ? `
            <div class="exact-hint-columns">
              ${
                nouns.length
                  ? `<div><span class="field-label">Nouns</span><p>${escapeHtml(nouns.join(", "))}</p></div>`
                  : ""
              }
              ${
                verbs.length
                  ? `<div><span class="field-label">Verbs</span><p>${escapeHtml(verbs.join(", "))}</p></div>`
                  : ""
              }
            </div>
          `
          : ""
      }
      ${
        showStructure && sentenceStarter
          ? `
            <div class="sentence-frame-box">
              <span class="field-label">Try this structure</span>
              <p>${escapeHtml(sentenceStarter)}</p>
            </div>
          `
          : ""
      }
    </section>
  `;
}

function renderDimensionTracker(items, revealIndex = 0) {
  const tracker = Array.isArray(items) ? items : [];
  if (!tracker.length) {
    return "";
  }
  return `
    <section class="simple-feedback-section dimension-tracker-section coach-reveal" ${coachRevealStyle(revealIndex)}>
      <h4>Image explanation built so far</h4>
      <div class="dimension-tracker-grid">
        ${tracker
          .map(
            (item) => `
              <span class="dimension-chip ${item.complete ? "complete" : ""}">
                <span>${item.complete ? "✓" : "○"}</span>
                ${escapeHtml(item.label || item.key || "")}
              </span>
            `
          )
          .join("")}
      </div>
    </section>
  `;
}

function buildProgressiveSuggestions(feedback, session) {
  const direct = cleanUiList(feedback?.actionable_suggestions || [], 2);
  if (direct.length) {
    return direct;
  }
  const challenge = cleanUiText(feedback?.specific_guidance?.next_challenge || feedback?.next_challenge);
  if (challenge) {
    return [challenge];
  }
  return buildGuidedNextSteps(feedback, session).slice(0, 2);
}

function articulationLevelFromScore(score) {
  if (score < 45) return "Basic";
  if (score < 60) return "Clear";
  if (score < 75) return "Descriptive";
  if (score < 88) return "Natural";
  return "Fluent";
}

function buildQuickInlineUpgrade(learnerText, alternatives, betterVersion = "", fallbackFix = "") {
  const directUpgrade = buildInlineUpgrades(learnerText, alternatives).slice(0, 1);
  if (directUpgrade.length) {
    return directUpgrade;
  }

  const original = firstSentence(learnerText);
  const improved = firstSentence(betterVersion);
  if (original && improved && normalizeClientText(original) !== normalizeClientText(improved)) {
    return [
      {
        oldText: original,
        newText: improved,
      },
    ];
  }
  const fix = firstSentence(fallbackFix);
  if (!original || !fix) {
    return [];
  }
  return [
    {
      oldText: original,
      newText: fix,
    },
  ];
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
    .map((item) => {
      const index = text.toLowerCase().indexOf(item.oldText.toLowerCase());
      if (index === -1) {
        return null;
      }
      return {
        ...item,
        oldText: text.slice(index, index + item.oldText.length),
      };
    })
    .filter(Boolean)
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

function firstSentence(value) {
  const text = cleanUiText(value);
  if (!text) {
    return "";
  }
  const match = text.match(/^[^.!?]+[.!?]?/);
  return (match ? match[0] : text).trim();
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
  const latestFeedback = latestAttempt?.feedback || state.sessionFlow.feedback || {};
  const latestText = latestAttempt?.text || state.sessionFlow.explanation || "";
  const rewriteDraft = latestText;
  const attemptNumber = attempts.length;
  const ready = isExplanationReady(latestFeedback);
  const showMoveOption = ready;
  const showEditor = !ready;
  const issue = buildFeedbackIssue(latestFeedback, session);
  const currentFocus = buildImproveCurrentFocus(issue);
  const hintGroups = buildImproveHintGroups(session, latestFeedback, issue, latestText);

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell">
      ${renderStepProgress("improve")}
      <section class="focused-writing-card improve-action-card">
        <div class="focused-image-frame">
          <img class="focused-image-preview" src="${session.image_url}" alt="Image to describe">
        </div>
        <div class="focused-copy">
          <p class="eyebrow">${ready ? "Ready for quiz" : `Refinement ${Math.max(1, attemptNumber)}`}</p>
          <h3>${ready ? "Excellent articulation. Let’s reinforce it." : "Improve your answer"}</h3>
        </div>
        ${showEditor ? renderImproveEditor({ rewriteDraft, currentFocus, hintGroups }) : ""}
        ${showEditor ? `
          <button id="submitImproveButton" class="primary-button journey-primary-button" type="button">
            Submit Improved Version
          </button>
        ` : ""}
        ${showMoveOption ? `
          <div class="move-forward-box">
            <strong>${ready ? "Ready for the quiz" : "You can keep building or move on"}</strong>
            <p class="muted">${
              ready
                ? "Your explanation covers the main image well enough to practice it."
                : "Keep refining the current focus before the quiz."
            }</p>
            <button id="continueToQuizButton" class="primary-button" type="button">Continue to Quiz</button>
          </div>
        ` : ""}
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
      playTapAnimation(button);
      button.classList.add("selected");
    });
  });
  window.setTimeout(() => {
    document.getElementById("learnerImproveInput")?.focus();
  }, 50);
}

function renderImproveEditor({ rewriteDraft, currentFocus, hintGroups }) {
  return `
    <section class="improve-focus-card coach-reveal" ${coachRevealStyle(0)}>
      <span class="field-label">Current Focus</span>
      <p>${escapeHtml(currentFocus)}</p>
    </section>
    ${renderImproveHintsCard(hintGroups)}
    <textarea
      id="learnerImproveInput"
      class="focused-writing-input guided-writing-input"
      rows="6"
      maxlength="900"
      placeholder="Keep editing your explanation here..."
    >${escapeHtml(rewriteDraft)}</textarea>
  `;
}

function renderImproveHintsCard(groups) {
  const visibleGroups = groups.filter((group) => group.items.length);
  if (!visibleGroups.length) {
    return "";
  }
  return `
    <section class="improve-hints-card coach-reveal" ${coachRevealStyle(1)}>
      <h4>Hints</h4>
      <div class="improve-hint-grid">
        ${visibleGroups
          .map(
            (group) => `
              <div class="improve-hint-group">
                <span class="field-label">${escapeHtml(group.label)}</span>
                <div class="mini-suggestion-row">
                  ${group.items
                    .map(
                      (item) => `
                        <button class="phrase-chip phrase-insert-chip improve-hint-chip" type="button" data-insert-phrase="${escapeHtml(item)}">
                          ${escapeHtml(item)}
                        </button>
                      `
                    )
                    .join("")}
                </div>
              </div>
            `
          )
          .join("")}
      </div>
    </section>
  `;
}

function buildImproveCurrentFocus(issue) {
  const focus = normalizeClientText(issue?.focusAreas?.[0] || issue?.message || "");
  if (focus.includes("main subject")) return "Describe the main subject";
  if (focus.includes("main action")) return "Describe the action";
  if (focus.includes("background")) return "Add background detail";
  if (focus.includes("foreground")) return "Improve positioning";
  if (focus.includes("visible detail") || focus.includes("object")) return "Mention important objects";
  if (focus.includes("setting") || focus.includes("environment")) return "Explain the environment";
  if (focus.includes("mood") || focus.includes("atmosphere")) return "Add atmosphere";
  if (focus.includes("wording") || focus.includes("vocabulary")) return "Use stronger vocabulary";
  return "Make the description more complete";
}

function buildImproveHintGroups(session, feedback, issue, currentText) {
  const analysis = session?.analysis || {};
  const guidance = feedback?.specific_guidance || {};
  const focus = normalizeClientText(issue?.focusAreas?.join(" ") || issue?.message || "");
  const objectHints = cleanReusableHints([
    ...((analysis.objects || []).map((item) => item?.name || item)),
    ...cleanUiList(guidance.nouns || [], 5),
    ...(issue?.additions || []),
  ], "noun");
  const actionHints = cleanReusableHints([
    ...((analysis.actions || []).map((item) => item?.verb || actionPhraseToVerb(item?.phrase || item))),
    ...((analysis.actions || []).map((item) => item?.phrase || "")),
    ...cleanUiList(guidance.verbs || [], 5),
  ], "verb");
  const adjectiveHints = cleanReusableHints([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(guidance.words || [], 5),
  ], "adjective").filter((item) => !objectHints.some((noun) => normalizeClientText(noun).includes(normalizeClientText(item))));
  const phraseHints = cleanReusableHints([
    ...cleanUiList(guidance.details || [], 5),
    ...cleanUiList(guidance.words || [], 5),
    ...buildImprovePhraseSuggestions(session, feedback, currentText),
    ...buildStructureHints(analysis),
  ], "phrase");
  const structures = cleanSentenceFrames([
    cleanUiText(guidance.sentence_starter),
    ...cleanUiList(feedback?.reusable_sentence_structures || [], 2),
    ...((analysis.sentence_patterns || []).map((item) => item?.pattern || "")),
    defaultImproveStructureForFocus(focus),
  ]);

  const nounLimit = focus.includes("subject") || focus.includes("object") ? 5 : 3;
  const verbLimit = focus.includes("action") || focus.includes("happening") ? 5 : 3;
  const phraseLimit = focus.includes("background") || focus.includes("foreground") ? 4 : 3;
  const structureLimit = focus.includes("wording") || focus.includes("vocabulary") ? 2 : 1;
  const adjectiveLimit = focus.includes("wording") || focus.includes("vocabulary") || focus.includes("atmosphere") ? 4 : 2;

  return [
    { label: "Nouns", items: objectHints.slice(0, nounLimit) },
    { label: "Verbs", items: actionHints.slice(0, verbLimit) },
    { label: "Adjectives", items: adjectiveHints.slice(0, adjectiveLimit) },
    { label: "Useful phrases", items: phraseHints.slice(0, phraseLimit) },
    { label: "Structures", items: structures.slice(0, structureLimit) },
  ];
}

function defaultImproveStructureForFocus(focus) {
  if (focus.includes("action") || focus.includes("happening")) {
    return "The person is ___";
  }
  if (focus.includes("background")) {
    return "In the background, there are ___";
  }
  if (focus.includes("subject")) {
    return "The main subject is ___";
  }
  return "The scene shows ___";
}

function buildImproveStructureSuggestion(feedback, guidance = {}) {
  return (
    cleanUiText(guidance?.sentence_starter) ||
    cleanUiList(feedback?.reusable_sentence_structures || [], 1)[0] ||
    "In the foreground, there is ..., while the background shows ..."
  );
}

function simplifyHintChip(value) {
  return cleanUiText(value)
    .replace(/^(mention|add|use|try|include)\s+(this\s+)?/i, "")
    .replace(/^(the\s+)?(main\s+)?(subject|action|setting|context):\s*/i, "")
    .replace(/[.!?]+$/, "");
}

function cleanReusableHints(values, kind = "phrase") {
  return uniqueWritingHints(values.flatMap((value) => reusableHintChunks(value, kind)));
}

function reusableHintChunks(value, kind) {
  const text = simplifyHintChip(value)
    .replace(/^there (is|are)\s+/i, "")
    .replace(/^a\s+|^an\s+|^the\s+/i, "")
    .trim();
  if (!text) {
    return [];
  }
  if (kind === "phrase") {
    const positioning = extractPositioningPhrases(text);
    if (positioning.length) {
      return positioning;
    }
  }
  const chunks = text
    .split(/\s*(?:,|;|\band\b|\bwhile\b|\bwith\b)\s*/i)
    .map((item) => item.trim())
    .filter(Boolean);
  return chunks
    .map((item) => item.replace(/^a\s+|^an\s+|^the\s+/i, "").replace(/[.!?]+$/g, "").trim())
    .filter((item) => isReusableHint(item, kind));
}

function extractPositioningPhrases(value) {
  const text = cleanUiText(value).toLowerCase();
  const matches = text.match(/\b(?:in|on|near|along|beside|behind|around|across|through|under|next to)\s+(?:the\s+)?[a-z]+(?:\s+[a-z]+){0,3}/g) || [];
  return matches
    .map((item) => item.trim())
    .filter((item) => isReusableHint(item, "phrase"));
}

function isReusableHint(value, kind) {
  const text = cleanUiText(value);
  const words = text.split(/\s+/).filter(Boolean);
  if (!text || words.length > 6) {
    return false;
  }
  if (/[.!?]/.test(text) || /\b(the image|the scene|this picture|there is|there are)\b/i.test(text)) {
    return false;
  }
  if (kind === "verb" && words.length > 4) {
    return false;
  }
  if (kind === "adjective" && (words.length > 2 || /\b(in|on|near|along|with|the)\b/i.test(text))) {
    return false;
  }
  return true;
}

function cleanSentenceFrames(values) {
  return uniqueWritingHints(values.map(normalizeSentenceFrame).filter(Boolean));
}

function normalizeSentenceFrame(value) {
  const text = cleanUiText(value).replace(/[.!?]+$/g, "").trim();
  if (!text) {
    return "";
  }
  if (!/_{2,}|\.{3}|\[[^\]]+\]/.test(text)) {
    return "";
  }
  const frame = text.replace(/\.{3}|\[[^\]]+\]/g, "___");
  const words = frame.split(/\s+/).filter(Boolean);
  if (words.length > 10 || !frame.includes("___")) {
    return "";
  }
  return frame;
}

function uniqueWritingHints(values) {
  const seen = new Set();
  const blocked = new Set(["image", "photo", "picture", "thing", "something"]);
  const hints = [];
  values.forEach((value) => {
    const text = cleanUiText(value).replace(/[.!?]+$/, "");
    const key = normalizeClientText(text);
    if (!text || !key || blocked.has(key) || seen.has(key)) {
      return;
    }
    seen.add(key);
    hints.push(text);
  });
  return hints;
}

function insertWritingHint(hint) {
  const input = document.getElementById("learnerExplanationInput");
  const text = cleanUiText(hint);
  if (!input || !text) {
    return;
  }
  if (normalizeClientText(input.value).startsWith(normalizeClientText(text))) {
    input.focus();
    return;
  }
  const value = input.value.trimEnd();
  const needsSpace = value && !/[\s-]$/.test(input.value);
  input.value = `${value}${needsSpace ? " " : ""}${text}`;
  limitWritingInput({ target: input });
  input.focus();
}

function replaceWritingStarter(starter) {
  const input = document.getElementById("learnerExplanationInput");
  const text = normalizeSentenceStarter(starter);
  if (!input || !text) {
    return;
  }
  const knownStarters = getWritingStarters(state.currentSession || {})
    .map((item) => normalizeClientText(item))
    .filter(Boolean);
  const currentValue = input.value || "";
  const currentKey = normalizeClientText(currentValue);
  const currentStarter = knownStarters.find((item) => currentKey.startsWith(item));
  if (!currentStarter) {
    insertWritingHint(text);
    return;
  }
  const rawStarter = getWritingStarters(state.currentSession || {}).find(
    (item) => normalizeClientText(item) === currentStarter
  );
  input.value = `${text}${currentValue.slice((rawStarter || "").length).trimStart()}`;
  input.focus();
}

function limitWritingInput(event) {
  const input = event.target;
  const sentences = String(input.value || "").match(/[^.!?]+[.!?]*/g) || [];
  if (sentences.length <= 6) {
    return;
  }
  input.value = sentences.slice(0, 6).join("").trimStart();
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

function buildImproveHints(feedback) {
  const upgrades = Array.isArray(feedback?.word_phrase_upgrades)
    ? feedback.word_phrase_upgrades
    : Array.isArray(feedback?.alternatives)
    ? feedback.alternatives
    : [];
  const upgradeHints = upgrades
    .map((item) => cleanUiText(item?.use || item?.new || item?.strong))
    .filter(Boolean);
  const phraseHints = cleanUiList(feedback?.phrase_usage?.suggested || [], 2);
  return uniqueWritingHints([...upgradeHints, ...phraseHints]).slice(0, 2);
}

function buildImproveSuggestionItems(feedback) {
  const fixes = cleanUiList(feedback?.fix_this_to_improve || feedback?.improvements || [], 3);
  const missing = cleanUiList(feedback?.missing_details || [], 2).map(
    (item) => `Add ${item}.`
  );
  return uniqueWritingHints([...fixes, ...missing])
    .map(firstSentence)
    .filter(Boolean)
    .slice(0, 2);
}

function isExplanationReady(feedback) {
  if (!feedback) {
    return false;
  }
  if (typeof feedback.is_ready === "boolean") {
    return feedback.is_ready;
  }
  if (typeof feedback?.readiness?.ready === "boolean") {
    return feedback.readiness.ready;
  }
  const state = getProgressiveCoverageState(feedback);
  const coverage = feedback.coverage || {};
  const coveragePercent = Number(coverage.coveragePercent || coverage.coverageScore || 0);
  const score = feedbackTotalScore(feedback);
  return (
    state.subjectOk &&
    state.actionOk &&
    state.settingOk &&
    state.detailCount >= 2 &&
    state.naturalOk &&
    state.notListOk &&
    coveragePercent >= 70 &&
    score >= 65
  );
}

function getProgressiveCoverageState(feedback) {
  const coverage = feedback?.coverage || {};
  const readinessCriteria = feedback?.readiness?.criteria || {};
  const imageParts = Array.isArray(coverage.imageParts) ? coverage.imageParts : [];
  const missing = cleanUiList(feedback?.missing_details || coverage.missingMajorParts || [], 6)
    .filter((item) => !/no major visual detail/i.test(item));
  const coveredParts = imageParts.filter((part) => isCoveragePartCovered(part));
  const detailCount = coveredParts.filter((part) => {
    const type = String(part.type || "").toLowerCase();
    return ["important", "object", "foreground", "detail"].some((key) => type.includes(key));
  }).length;
  const settingCovered = coveredParts.some((part) => /setting|background|environment|context/.test(String(part.type || "").toLowerCase()));
  const language = feedback?.language_quality || {};
  const score = feedbackTotalScore(feedback);
  return {
    missing,
    imageParts,
    subjectOk: Boolean(readinessCriteria.mainSubject ?? (coverage.mainSubjectMentioned !== false)),
    actionOk: Boolean(readinessCriteria.mainAction ?? (coverage.mainActionMentioned !== false)),
    settingOk: Boolean(readinessCriteria.settingBackground ?? (settingCovered || !missing.some((item) => /setting|background|environment|context/i.test(item)))),
    detailCount,
    naturalOk: Boolean(readinessCriteria.naturalEnglish ?? (Number(language.naturalness || language.score || 0) >= 55 || score >= 65)),
    notListOk: Boolean(readinessCriteria.notAWordList ?? !looksLikeWordListFeedback(feedback)),
  };
}

function isCoveragePartCovered(part) {
  const status = String(part?.coverageStatus || "").toLowerCase();
  return part?.covered === true || status === "covered" || status === "partially_covered";
}

function looksLikeWordListFeedback(feedback) {
  const issueText = cleanUiText([
    feedback?.main_issue,
    ...(feedback?.fix_this_to_improve || []),
    ...(feedback?.next_step_instructions || []),
  ].join(" "));
  return /\blist of words\b|\bcomplete sentence\b|\bsentence structure\b/i.test(issueText);
}

function buildGuidedNextSteps(feedback, session) {
  const state = getProgressiveCoverageState(feedback);
  const analysis = session?.analysis || {};
  const steps = [];
  if (!state.subjectOk || !state.actionOk) {
    if (!state.subjectOk) steps.push(subjectStep(feedback, analysis));
    if (!state.actionOk) steps.push(actionStep(feedback, analysis));
    return cleanProgressiveSteps(steps);
  }
  if (!state.settingOk) {
    return cleanProgressiveSteps([
      settingStep(feedback, analysis),
      "Add it after the subject/action using a phrase like “in the background” or “on the grass.”",
    ]);
  }
  if (state.detailCount < 2) {
    return cleanProgressiveSteps([
      detailStep(feedback, analysis, 0),
      detailStep(feedback, analysis, 1),
    ]);
  }
  if (!state.naturalOk || !state.notListOk) {
    return cleanProgressiveSteps([
      wordingStep(feedback, analysis),
      structureStep(feedback),
    ]);
  }
  return cleanProgressiveSteps([
    wordingStep(feedback, analysis),
  ]);
}

function cleanProgressiveSteps(values) {
  return uniqueWritingHints(values)
    .map(firstSentence)
    .filter(Boolean)
    .slice(0, 2);
}

function subjectStep(feedback, analysis) {
  const part = findCoveragePart(feedback, "main_subject");
  const subject = cleanUiText(part?.name || part?.description || (analysis.objects || [])[0]?.name || (analysis.objects || [])[0]);
  return subject ? `Mention the main subject: ${subject}.` : "Mention the main person, animal, or object in the image.";
}

function actionStep(feedback, analysis) {
  const part = findCoveragePart(feedback, "main_action");
  const action = cleanUiText(part?.name || part?.description || (analysis.actions || [])[0]?.phrase || (analysis.actions || [])[0]?.verb || (analysis.actions || [])[0]);
  return action ? `Add the main action: ${action}.` : "Add what the main subject is doing.";
}

function settingStep(feedback, analysis) {
  const part = findCoveragePart(feedback, "setting") || findCoveragePart(feedback, "background");
  const setting = cleanUiText(part?.description || part?.name || analysis.environment || (analysis.environment_details || [])[0]);
  return setting ? `Mention the setting/context: ${setting}.` : "Mention where the scene is happening.";
}

function detailStep(feedback, analysis, index = 0) {
  const parts = (feedback?.coverage?.imageParts || [])
    .filter((part) => {
      const type = String(part.type || "").toLowerCase();
      return !isCoveragePartCovered(part) && ["important", "object", "foreground", "detail"].some((key) => type.includes(key));
    });
  const analysisDetails = [
    ...(analysis.objects || []).map((item) => item?.name || item),
    ...(analysis.environment_details || []),
  ];
  const detail = cleanUiText(parts[index]?.description || parts[index]?.name || analysisDetails[index]);
  return detail ? `Add a visible detail: ${detail}.` : "Add one more visible detail from the image.";
}

function wordingStep(feedback, analysis) {
  const upgrade = buildImproveHints(feedback)[0]
    || cleanUiText((analysis.phrases || [])[0]?.phrase)
    || cleanUiText((analysis.vocabulary || [])[0]?.word);
  return upgrade ? `Upgrade the wording with “${upgrade}” if it fits.` : "Make the sentence sound natural and complete.";
}

function structureStep(feedback) {
  const structure = cleanUiList(feedback?.reusable_sentence_structures || [], 1)[0]
    || "The main subject is ..., while the background shows ...";
  return `Use this structure: ${structure}`;
}

function findCoveragePart(feedback, typeNeedle) {
  return (feedback?.coverage?.imageParts || []).find((part) => {
    const type = String(part.type || "").toLowerCase();
    return type.includes(typeNeedle.toLowerCase());
  });
}

function concreteObservationStep(detail) {
  const text = cleanUiText(detail);
  if (!text) return "";
  if (/^mention|^add|^describe/i.test(text)) return text;
  return `Mention this missing part: ${text}.`;
}

function concreteVocabularyStep(upgrade) {
  const text = cleanUiText(upgrade);
  if (!text) return "";
  if (/use\b/i.test(text)) return text;
  return `Try the phrase "${text}" if it fits the image.`;
}

function concreteStructureStep(structure) {
  const text = cleanUiText(structure);
  if (!text) return "";
  if (/^use/i.test(text)) return text;
  return `Use this structure: ${text}`;
}

function buildImproveChipItems(improveHints, phraseSuggestions) {
  return uniqueWritingHints([...improveHints, ...phraseSuggestions]).slice(0, 3);
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
          .slice(0, 2)
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
    showToast("Choose an image before starting guided writing.", true);
    return;
  }

  const formData = new FormData();
  formData.append("image", imageFile);

  setButtonBusy(els.analyzeButton, true, "Preparing...");
  showSessionThinkingState("Preparing guided writing...", [
    "Analyzing the image",
    "Finding visible objects",
    "Preparing beginner hints",
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
    showToast("Image ready. Write one sentence to begin.");
  } catch (error) {
    showToast(error.message, true);
    if (state.currentSession) {
      renderSession(state.currentSession);
    } else {
      state.learnView = "compose";
      renderLearnPlaceholder();
    }
  } finally {
    setButtonBusy(els.analyzeButton, false, "Start Guided Write");
  }
}

async function submitExplanationFeedback(session) {
  const input = document.getElementById("learnerExplanationInput");
  const button = document.getElementById("submitWritingButton");
  const explanation = input?.value?.trim() || "";

  if (
    !explanation ||
    normalizeClientText(explanation) === normalizeClientText(getWritingStarter(session))
  ) {
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
      body: JSON.stringify({ explanation, attempt_index: 1 }),
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
    "Comparing with the image reference",
    "Finding the next missing details",
    "Checking readiness for quiz",
  ]);
  try {
    const data = await api(`/api/sessions/${session.id}/feedback`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        explanation,
        rewrite: improvedText,
        attempt_index: (state.sessionFlow.attempts || []).length + 1,
      }),
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
      polishMode: false,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    showToast(error.message, true);
    renderSessionStep("improve");
  } finally {
    setButtonBusy(button, false, "Check Again");
  }
}

async function startPostImproveQuiz(session) {
  if (state.sessionFlow.quizLaunchStarted) {
    return;
  }
  state.sessionFlow.quizLaunchStarted = true;
  const button = document.getElementById("continueToQuizButton");
  const attempts = state.sessionFlow.attempts || [];
  const firstAttempt = attempts[0] || {};
  const latestAttempt = attempts[attempts.length - 1] || {};
  const scoreImprovement = Math.max(0, (latestAttempt.score || 0) - (firstAttempt.score || 0));
  setButtonBusy(button, true, "Building quiz...");
  els.quizModal.classList.remove("hidden");
  els.quizModalLabel.textContent = "Micro Quiz";
  els.quizModalTitle.textContent = "Building 3 quick questions";
  els.quizContent.innerHTML = renderAiThinkingState("Creating your quiz...", [
    "Using your image explanation",
    "Checking feedback and hint words",
    "Making short reinforcement questions",
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
        score_improvement: scoreImprovement,
      }),
    });
    state.quizDashboard = data.dashboard || state.quizDashboard;
    state.currentQuizRun = data.run;
    renderQuizButton();
    renderQuizRun(data.run);
  } catch (error) {
    state.sessionFlow.quizLaunchStarted = false;
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
        Sign in to save XP, streaks, and recent image sessions.
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
  const recentSessions = state.sessions.slice(0, 3);

  els.dashboardContent.innerHTML = `
    <div class="dashboard-stack">
      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Progress</p>
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
            <span class="status-label">Combo</span>
            <strong class="status-value">${progress.best_combo || progress.combo_streak || 0}</strong>
          </article>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Quick Loop</p>
            <h4>One image, one sentence</h4>
          </div>
        </div>
        <div class="empty-copy compact-empty-copy">
          Upload an image, write one sentence, improve it once, then finish a 2-3 question micro quiz.
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">Recent</p>
            <h4>Image sessions</h4>
          </div>
        </div>
        ${
          recentSessions.length
            ? `
            <div class="review-preview-grid">
              ${recentSessions
                .map(
                  (session) => `
                    <article class="review-preview-card">
                      <strong>${escapeHtml(session.title)}</strong>
                      <p class="muted">${escapeHtml(formatDate(session.created_at))}</p>
                    </article>
                  `
                )
                .join("")}
            </div>
          `
            : `<div class="empty-copy">Your latest image sessions will appear here.</div>`
        }
      </section>
    </div>
  `;

  const logoutButton = document.getElementById("logoutButton");
  if (logoutButton) {
    logoutButton.addEventListener("click", onLogout);
  }
}

function renderLearnMode() {
  const showSession = state.learnView === "session" && Boolean(state.currentSession);
  const showCompose = !showSession;

  els.learnIntro.classList.toggle("hidden", !showCompose);
  els.composePanel.classList.toggle("hidden", !showCompose);
  els.sessionWorkspace.classList.toggle("hidden", !showSession);
  els.newSessionButton.classList.toggle("hidden", !state.user);
  els.quizLauncherButton.classList.add("hidden");
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
    <div class="quiz-flow quiz-question-enter">
      <div class="quiz-progress-track">
        <span class="quiz-progress-bar" style="width: ${progressPercent}%"></span>
      </div>
      <div class="quiz-top-stats">
        <span>Progress <strong>${question.question_index}/${question.total_questions}</strong></span>
        <span>Earned <strong>+${run.summary?.xp_earned || 0} XP</strong></span>
        <span>Combo <strong>${state.progress?.combo_streak >= 2 ? "🔥 " : ""}x${state.progress?.combo_streak || 0}</strong></span>
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
  if (question.answer_mode === "matching") {
    renderMatchingPairsAnswer(question, answerZone);
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
  const chooseBetter = question.quiz_type === "choose_better";
  const snap = question.quiz_type === "phrase_snap";
  container.innerHTML = `
    <div class="answer-options ${duel || chooseBetter ? "phrase-duel-options" : snap ? "phrase-snap-options" : ""}">
      ${question.options
        .map(
          (option, index) => `
            <button class="answer-button quiz-answer-button ${
              duel || chooseBetter ? "phrase-duel-card" : snap ? "phrase-snap-option" : ""
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
      playTapAnimation(button);
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
  const starterText = ["fix_the_mistake", "fix_the_sentence"].includes(question.quiz_type)
    ? extractBrokenSentence(question.prompt)
    : "";
  container.innerHTML = `
    <div class="typing-answer-shell">
      ${
        question.quiz_type === "use_it_or_lose_it" && relatedPhrase
          ? `<div class="phrase-focus-chip">${escapeHtml(relatedPhrase)}</div>`
          : ""
      }
      <textarea id="typingAnswerInput" class="quiz-text-input" rows="4" placeholder="${escapeHtml(
        ["fix_the_mistake", "fix_the_sentence"].includes(question.quiz_type) ? "Edit the sentence here..." : "Type your answer here..."
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

function renderMatchingPairsAnswer(question, container) {
  const pairs = Array.isArray(question.metadata?.pairs) ? question.metadata.pairs : [];
  const leftItems = pairs.map((pair) => String(pair.left || "").trim()).filter(Boolean);
  const rightItems = pairs
    .map((pair) => String(pair.right || "").trim())
    .filter(Boolean)
    .sort((a, b) => normalizeClientText(a).localeCompare(normalizeClientText(b)));
  const selected = {};
  let activeLeft = "";

  const draw = () => {
    const complete = leftItems.length > 0 && leftItems.every((item) => selected[item]);
    container.innerHTML = `
      <div class="matching-shell">
        <div class="matching-column">
          ${leftItems
            .map(
              (item) => `
                <button class="answer-button matching-card ${activeLeft === item ? "selected" : ""} ${selected[item] ? "matched" : ""}" type="button" data-match-left="${escapeHtml(item)}">
                  <span>${escapeHtml(item)}</span>
                  ${selected[item] ? `<strong>${escapeHtml(selected[item])}</strong>` : ""}
                </button>
              `
            )
            .join("")}
        </div>
        <div class="matching-column">
          ${rightItems
            .map(
              (item) => `
                <button class="answer-button matching-card ${Object.values(selected).includes(item) ? "matched" : ""}" type="button" data-match-right="${escapeHtml(item)}">
                  ${escapeHtml(item)}
                </button>
              `
            )
            .join("")}
        </div>
        <div class="quiz-submit-bar">
          <button id="submitMatchingAnswer" class="primary-button quiz-submit-button" type="button" ${complete ? "" : "disabled"}>Submit answer</button>
        </div>
      </div>
    `;

    container.querySelectorAll("[data-match-left]").forEach((button) => {
      button.addEventListener("click", () => {
        activeLeft = button.dataset.matchLeft || "";
        playTapAnimation(button);
        draw();
      });
    });
    container.querySelectorAll("[data-match-right]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!activeLeft) {
          showToast("Choose a word or phrase first.", true);
          return;
        }
        selected[activeLeft] = button.dataset.matchRight || "";
        activeLeft = "";
        playTapAnimation(button);
        draw();
      });
    });
    document.getElementById("submitMatchingAnswer")?.addEventListener("click", () => {
      const answer = leftItems.map((left) => `${left}=>${selected[left] || ""}`).join("||");
      submitQuizAnswer(answer);
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
    const resultType = data.result.result_type || (data.result.correct ? "Correct" : "Incorrect");
    const resultLabel = resultType === "Almost Correct" ? "Almost" : resultType === "Incorrect" ? "Wrong" : resultType;
    els.quizModalLabel.textContent = resultLabel;
    els.quizModalTitle.textContent = `Answer ${data.result.question_index} checked`;
    const comboBonus = data.result.combo_bonus || 0;
    const shortExplanation = quizShortExplanation(data.result, feedback);
    const comboStreak = data.result.combo_streak || 0;
    const xpBreakdown = data.result.xp_breakdown || {};
    els.quizContent.innerHTML = `
      <div class="quiz-feedback-card">
        <div class="quiz-result-card clean-result-card ${resultClassForType(resultType)} ${resultMotionClassForType(resultType)}">
          <span class="quiz-result-label">${escapeHtml(resultLabel)}</span>
          <div class="answer-reward-row">
            <span class="xp-pop">+<strong id="quizXpGainedValue">0</strong> XP</span>
            ${comboStreak >= 2 ? `<span class="combo-pop">🔥 Combo <strong>x${comboStreak}</strong></span>` : ""}
            ${comboBonus ? `<span class="combo-bonus-pop">Combo bonus +${comboBonus}</span>` : ""}
            ${xpBreakdown.fast_bonus ? `<span>Fast +${xpBreakdown.fast_bonus}</span>` : ""}
            ${xpBreakdown.perfect_quiz_bonus ? `<span>Perfect streak +${xpBreakdown.perfect_quiz_bonus}</span>` : ""}
          </div>
          ${renderAnsweredSnapshot(data.result, answeredQuestion)}
          <p class="result-explanation">${escapeHtml(shortExplanation)}</p>
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
    await Promise.all([fetchReviewDashboard({ silent: true }), fetchProgressDashboard({ silent: true })]);
  } catch (error) {
    showToast(error.message, true);
    renderQuizRun(state.currentQuizRun);
  }
}

function renderAnsweredSnapshot(result, question) {
  const selected = cleanUiText(result?.selected_answer);
  const correct = cleanUiText(result?.correct_answer);
  if (!selected && !correct) {
    return "";
  }
  const isCorrect = Boolean(result?.correct);
  const label = question?.answer_mode === "matching"
    ? "Pairs"
    : question?.answer_mode === "reorder"
      ? "Sentence"
      : question?.answer_mode === "typing"
        ? "Answer"
        : "Choice";
  return `
    <div class="answered-snapshot ${isCorrect ? "is-correct" : "is-wrong"}">
      <div>
        <span class="field-label">Your ${escapeHtml(label)}</span>
        <p>${escapeHtml(formatSnapshotAnswer(selected))}</p>
      </div>
      ${
        !isCorrect && correct
          ? `
            <div>
              <span class="field-label">Correct</span>
              <p>${escapeHtml(formatSnapshotAnswer(correct))}</p>
            </div>
          `
          : ""
      }
    </div>
  `;
}

function formatSnapshotAnswer(value) {
  return cleanUiText(value).replaceAll("||", " · ").replaceAll("=>", " → ");
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

  const summary = run.summary || {};
  const totalXp = summary.xp_earned || 0;
  const maxCombo = summary.max_combo || 0;
  const correctAnswers = summary.correct_answers ?? summary.correct_count ?? 0;
  const answeredCount = summary.answered_count ?? run.total_questions ?? 0;
  const phrasesPracticed = uniqueWritingHints([
    ...(summary.phrases_practiced || []),
    summary.phrase_practiced,
    lastResult?.phrase_mastery?.phrase,
    lastResult?.metadata?.related_reusable_phrase,
  ]).slice(0, 3);
  const scoreImprovement = summary.score_improvement || lastResult?.metadata?.score_improvement || 0;
  const finalExplanation = lastResult
    ? quizShortExplanation(lastResult, lastResult.feedback || {})
    : "";
  const streakDays = state.progress?.streak_days || 0;
  els.quizModalLabel.textContent =
    run.run_mode === "daily_challenge"
      ? "Challenge Complete"
      : run.run_mode === "post_improve"
      ? "Reward"
      : run.run_mode === "session"
      ? "Quick Challenge Complete"
      : "Quiz Complete";
  els.quizModalTitle.textContent = "Nice work";
  els.quizContent.innerHTML = `
    <div class="quiz-summary-shell reward-screen">
      <div class="reward-hero-card">
        <span class="field-label">Total earned</span>
        <strong class="reward-xp-total">+<span id="rewardXpValue">0</span> XP</strong>
      </div>
      <div class="reward-stat-row reward-stat-grid">
        <span>Correct <strong>${correctAnswers}/${answeredCount}</strong></span>
        <span>🔥 Max Combo <strong id="rewardComboValue">x0</strong></span>
        ${phrasesPracticed.length ? `<span>🧠 Phrases <strong>${escapeHtml(phrasesPracticed.join(", "))}</strong></span>` : ""}
        ${summary.perfect_quiz ? `<span>Perfect streak <strong>+20 XP</strong></span>` : ""}
        ${scoreImprovement ? `<span>Score <strong>+${escapeHtml(scoreImprovement)} points</strong></span>` : ""}
        <span>Streak <strong>${streakDays ? `Day ${streakDays}` : "Started"}</strong></span>
      </div>
      ${finalExplanation ? `<p class="result-explanation">${escapeHtml(finalExplanation)}</p>` : ""}
      <button id="closeQuizSummaryButton" class="primary-button reward-next-button" type="button">Next Image</button>
    </div>
  `;

  document.getElementById("closeQuizSummaryButton").addEventListener("click", () => {
    closeQuizModal();
    openNewSessionComposer();
  });
  animateNumber("rewardXpValue", totalXp);
  animateNumber("rewardComboValue", maxCombo, { prefix: "x" });
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
    multiple_choice_comprehension: "Multiple Choice",
    matching_pairs: "Matching Pairs",
    sentence_reconstruction: "Sentence Reconstruction",
    recognition: "Recognition",
    phrase_completion: "Phrase Completion",
    expression_training: "Expression Training",
    situation_understanding: "Situation",
    sentence_building: "Sentence Building",
    fill_blank: "Fill in the Blank",
    typing: "Typing",
    memory_recall: "Memory Recall",
    error_focus: "Error Focus",
    sentence_upgrade_battle: "Sentence Upgrade Battle",
    phrase_snap: "Phrase Snap",
    choose_better: "Choose Better",
    phrase_duel: "Phrase Duel",
    fix_the_mistake: "Fix the Mistake",
    fix_the_sentence: "Fix the Sentence",
    use_it_or_lose_it: "Use the Word/Phrase",
  };
  return mapping[value] || formatBand(String(value || "").replaceAll("_", " "));
}

function prettyAnswerMode(value) {
  const mapping = {
    multiple_choice: "Multiple choice",
    matching: "Matching",
    typing: "Typing",
    reorder: "Sentence order",
  };
  return mapping[value] || formatBand(value);
}

function formatXpBreakdown(breakdown) {
  const base = Number(breakdown?.base_xp || 0);
  const firstTry = Number(breakdown?.first_try_bonus || 0);
  const fast = Number(breakdown?.fast_bonus || 0);
  const perfect = Number(breakdown?.perfect_quiz_bonus || 0);
  const combo = Number(breakdown?.combo_bonus || 0);
  if (!base && !firstTry && !fast && !perfect && !combo) return "No XP gained this time.";
  return [
    base ? `Answer +${base}` : "",
    firstTry ? `First try +${firstTry}` : "",
    fast ? `Fast +${fast}` : "",
    perfect ? `Perfect +${perfect}` : "",
    combo ? `Combo +${combo}` : "",
  ].filter(Boolean).join(" · ");
}

function quizShortExplanation(result, feedback) {
  if (feedback?.good) return feedback.good;
  if (feedback?.improve) return feedback.improve;
  if (result?.result_type === "Correct") return "That reinforces the image phrase.";
  if (result?.result_type === "Almost Correct") return "Close. Keep the meaning and make it smoother.";
  return "Review the image phrase, then try the next one.";
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
  if (["fix_the_mistake", "fix_the_sentence"].includes(question.quiz_type)) {
    const broken = extractBrokenSentence(question.prompt);
    return broken
      ? `<div class="broken-sentence-card"><span class="field-label">Broken sentence</span><p>${escapeHtml(broken)}</p></div>`
      : "";
  }
  if (question.quiz_type === "use_it_or_lose_it" && phrase) {
    return `<div class="phrase-focus-chip">${escapeHtml(phrase)}</div>`;
  }
  if (["phrase_snap", "fill_blank"].includes(question.quiz_type)) {
    return `<div class="quick-action-note">Fill the blank with the missing word.</div>`;
  }
  if (question.quiz_type === "multiple_choice_comprehension") {
    return `<div class="quick-action-note">Choose the answer from this image session.</div>`;
  }
  if (question.quiz_type === "matching_pairs") {
    return `<div class="quick-action-note">Tap a word, then tap its matching meaning.</div>`;
  }
  if (question.quiz_type === "sentence_reconstruction") {
    return `<div class="quick-action-note">Tap the words to rebuild the sentence.</div>`;
  }
  if (question.quiz_type === "choose_better") {
    return `<div class="quick-action-note">Pick the sentence that sounds clearer for this image.</div>`;
  }
  return "";
}

function renderQuizResultDetail(result, question) {
  const quizType = result.quiz_type || question?.quiz_type || "";
  const selected = result.selected_answer || "";
  const correct = result.correct_answer || "";
  const metadata = result.metadata || question?.metadata || {};
  const phrase = result.phrase_mastery?.phrase || metadata.related_reusable_phrase || question?.related_reusable_phrase || "";

  if (quizType === "choose_better") {
    return `
      <div class="before-after-grid">
        <div><span class="field-label">Your choice</span><p>${escapeHtml(selected)}</p></div>
        <div><span class="field-label">Better version</span><p>${escapeHtml(correct)}</p></div>
      </div>
    `;
  }
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
  if (["fix_the_mistake", "fix_the_sentence"].includes(quizType)) {
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
    .replace(/^Fix the Sentence:\s*/i, "")
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
