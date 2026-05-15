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
    max_upload_bytes: 25 * 1024 * 1024,
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
  uploadPreviewUrl: "",
  starterHintPopover: {
    activeHintId: null,
    popoverPosition: null,
  },
  sessionFlow: {
    step: "learn",
    explanation: "",
    feedback: null,
    attempts: [],
    initialStarterText: "",
    initialStarterTouched: false,
    initialImprovementCards: [],
    initialImprovementIndex: 0,
    initialImprovementDraft: "",
    initialAppliedImprovementIds: [],
    initialSkippedImprovementIds: [],
    initialLastAppliedImprovementId: "",
    articulationUpgrade: null,
    layerRewards: [],
    allLayersBonusAwarded: false,
  },
};

const els = {};
const SESSION_CHUNK_SIZE = 6;
const IMAGE_UPLOAD_TARGET_BYTES = 4 * 1024 * 1024;
const IMAGE_UPLOAD_MAX_DIMENSION = 1920;
const LEARNING_STAGES = Object.freeze({
  UPLOAD_IMAGE: "upload_image",
  INITIAL_ATTEMPT: "initial_attempt",
  FIRST_FEEDBACK: "first_feedback",
  REUSABLE_LANGUAGE: "reusable_language",
  MISSING_VISUAL_AREAS: "missing_visual_areas",
  COVERAGE_LAYERS: "coverage_layers",
  LAYER_SUCCESS: "layer_success",
  COVERAGE_COMPLETE: "coverage_complete",
  POLISH_STAGE: "polish_stage",
  FINAL_REVEAL: "final_reveal",
  QUIZ: "quiz",
});
let sessionListObserver = null;

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  initializeTheme();
  bindEvents();
  bootstrap();
});

function cacheElements() {
  const ids = [
    "xpValue",
    "streakValue",
    "newSessionButton",
    "uploadBackButton",
    "dashboardButton",
    "themeToggleButton",
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
    "uploadProcessingLabel",
    "analyzeButton",
    "takePhotoButton",
    "chooseGalleryButton",
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
  els.analyzeButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openImagePicker("gallery");
  });
  els.takePhotoButton.addEventListener("click", () => openImagePicker("camera"));
  els.chooseGalleryButton.addEventListener("click", () => openImagePicker("gallery"));
  els.uploadBackButton.addEventListener("click", openNewSessionComposer);
  els.newSessionButton.addEventListener("click", openNewSessionComposer);
  els.dashboardButton.addEventListener("click", openDashboardModal);
  els.themeToggleButton.addEventListener("click", toggleTheme);
  els.closeDashboardButton.addEventListener("click", closeDashboardModal);
  els.quizLauncherButton.addEventListener("click", () => openQuizModal({ mode: "mixed" }));
  els.closeQuizButton.addEventListener("click", closeQuizModal);
  els.closeLanguageModalButton.addEventListener("click", closeLanguageModal);
  els.sessionDetailPanel.addEventListener("click", onLanguageCardClick);
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.(".starter-hint-chip, .starter-hint-popover")) {
      closeStarterHintPopovers();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeStarterHintPopovers();
    }
  });
  window.addEventListener("resize", positionActiveStarterHintPopover, { passive: true });
  window.addEventListener("scroll", positionActiveStarterHintPopover, { passive: true });
}

function initializeTheme() {
  const storedTheme = safeLocalStorageGet("aiEnglishTheme");
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  applyTheme(storedTheme || (prefersDark ? "dark" : "light"), { persist: false });
}

function toggleTheme() {
  const nextTheme = document.body.classList.contains("dark-mode") ? "light" : "dark";
  applyTheme(nextTheme);
}

function applyTheme(theme, options = {}) {
  const dark = theme === "dark";
  document.documentElement.classList.toggle("dark-mode-preload", dark);
  document.body.classList.toggle("dark-mode", dark);
  if (els.themeToggleButton) {
    els.themeToggleButton.setAttribute("aria-pressed", String(dark));
    els.themeToggleButton.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    const icon = els.themeToggleButton.querySelector(".theme-toggle-icon");
    if (icon) {
      icon.textContent = dark ? "☀" : "☾";
    }
  }
  if (options.persist !== false) {
    safeLocalStorageSet("aiEnglishTheme", dark ? "dark" : "light");
  }
}

function safeLocalStorageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return "";
  }
}

function safeLocalStorageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    // Preference persistence is optional.
  }
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
  els.analyzeButton.disabled = false;
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
  state.sessionFlow = createInitialSessionFlow(session);
  renderSessionStep("write");
}

function createInitialSessionFlow(session = {}) {
  return {
    stage: normalizeLearningStage(session.learning_stage) || LEARNING_STAGES.INITIAL_ATTEMPT,
    step: "write",
    explanation: "",
    feedback: null,
    attempts: [],
    initialStarterText: "",
    initialStarterTouched: false,
    initialImprovementCards: [],
    initialImprovementIndex: 0,
    initialImprovementDraft: "",
    initialAppliedImprovementIds: [],
    initialSkippedImprovementIds: [],
    initialLastAppliedImprovementId: "",
    coverageLayers: null,
    coverageComplete: false,
    skippedCoverageLayers: [],
    polishUnlocked: false,
    articulationUpgrade: null,
    finalPolishedText: "",
    layerRewards: [],
    allLayersBonusAwarded: false,
    quizLaunchStarted: false,
  };
}

function normalizeLearningStage(stage) {
  const value = String(stage || "").trim();
  const aliases = {
    coverage_feedback: LEARNING_STAGES.FIRST_FEEDBACK,
    quiz_ready: LEARNING_STAGES.QUIZ,
    learn: LEARNING_STAGES.UPLOAD_IMAGE,
    image: LEARNING_STAGES.UPLOAD_IMAGE,
    guided_write: LEARNING_STAGES.INITIAL_ATTEMPT,
    write: LEARNING_STAGES.INITIAL_ATTEMPT,
    submit: LEARNING_STAGES.FIRST_FEEDBACK,
    feedback: LEARNING_STAGES.FIRST_FEEDBACK,
    improve: LEARNING_STAGES.COVERAGE_LAYERS,
    upgrade: LEARNING_STAGES.POLISH_STAGE,
    reward: LEARNING_STAGES.QUIZ,
  };
  const normalized = aliases[value] || value;
  return Object.values(LEARNING_STAGES).includes(normalized) ? normalized : "";
}

function renderSessionStep(step, updates = {}) {
  const session = state.currentSession;
  if (!session) {
    return;
  }
  const explicitStage = normalizeLearningStage(updates.stage || updates.learningStage);
  state.sessionFlow = {
    ...state.sessionFlow,
    ...updates,
    step,
  };
  state.sessionFlow.stage = explicitStage || inferLearningStage(step, state.sessionFlow, session);
  state.sessionFlow.learningStage = state.sessionFlow.stage;
  updateAppHeaderForStage(state.sessionFlow.stage);
  if (state.currentSession) {
    state.currentSession.learning_stage = state.sessionFlow.stage;
  }

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

function updateAppHeaderForStage(stage) {
  const normalized = normalizeLearningStage(stage) || LEARNING_STAGES.UPLOAD_IMAGE;
  const topbar = document.querySelector(".app-topbar");
  const label = document.querySelector(".upload-progress-head strong");
  const dots = [...document.querySelectorAll(".upload-progress-dots span")];
  const stepMap = {
    [LEARNING_STAGES.UPLOAD_IMAGE]: 1,
    [LEARNING_STAGES.INITIAL_ATTEMPT]: 1,
    [LEARNING_STAGES.FIRST_FEEDBACK]: 2,
    [LEARNING_STAGES.REUSABLE_LANGUAGE]: 2,
    [LEARNING_STAGES.MISSING_VISUAL_AREAS]: 2,
    [LEARNING_STAGES.COVERAGE_LAYERS]: 3,
    [LEARNING_STAGES.LAYER_SUCCESS]: 3,
    [LEARNING_STAGES.COVERAGE_COMPLETE]: 5,
    [LEARNING_STAGES.POLISH_STAGE]: 5,
    [LEARNING_STAGES.FINAL_REVEAL]: 5,
    [LEARNING_STAGES.QUIZ]: 5,
  };
  const stepNumber = stepMap[normalized] || 1;
  topbar?.classList.toggle("upload-app-header", true);
  if (label) {
    label.textContent = `Step ${stepNumber} of 5`;
  }
  dots.forEach((dot, index) => {
    dot.classList.toggle("active", index < stepNumber);
  });
}

function updateAppHeaderForCoverageFocus(current, total) {
  const topbar = document.querySelector(".app-topbar");
  const label = document.querySelector(".upload-progress-head strong");
  const dots = [...document.querySelectorAll(".upload-progress-dots span")];
  topbar?.classList.add("upload-app-header");
  if (label) {
    label.textContent = `Focus ${Math.max(1, current)} of ${Math.max(1, total)}`;
  }
  dots.forEach((dot, index) => {
    dot.classList.toggle("active", index < Math.max(1, current));
  });
}

function inferLearningStage(step, flow, session) {
  const current = normalizeLearningStage(flow?.stage);
  const upgrade = flow?.articulationUpgrade;
  if (flow?.quizLaunchStarted || current === LEARNING_STAGES.QUIZ) {
    return LEARNING_STAGES.QUIZ;
  }
  if (upgrade?.finalized || flow?.finalPolishedText || current === LEARNING_STAGES.FINAL_REVEAL) {
    return LEARNING_STAGES.FINAL_REVEAL;
  }
  if (current === LEARNING_STAGES.POLISH_STAGE) {
    return LEARNING_STAGES.POLISH_STAGE;
  }
  if (step === "write" || !(flow?.attempts || []).length) {
    return LEARNING_STAGES.INITIAL_ATTEMPT;
  }
  if (step === "feedback") {
    return current || LEARNING_STAGES.FIRST_FEEDBACK;
  }
  const latestAttempt = (flow?.attempts || []).at(-1) || {};
  const latestFeedback = latestAttempt.feedback || flow?.feedback || {};
  const layerState = buildCoverageLayerState(latestFeedback, session, latestAttempt.text || flow?.explanation || "");
  if (layerState.complete) {
    return LEARNING_STAGES.COVERAGE_COMPLETE;
  }
  return LEARNING_STAGES.COVERAGE_LAYERS;
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
    ["upload_image", "Image"],
    ["initial_attempt", "Attempt"],
    ["first_feedback", "Feedback"],
    ["reusable_language", "Language"],
    ["missing_visual_areas", "Missing"],
    ["coverage_layers", "Layers"],
    ["layer_success", "Success"],
    ["coverage_complete", "Covered"],
    ["polish_stage", "Polish"],
    ["final_reveal", "Final"],
    ["quiz", "Quiz"],
  ];
  const activeStage = normalizeLearningStage(activeStep) || normalizeLearningStage(state.sessionFlow?.stage) || LEARNING_STAGES.INITIAL_ATTEMPT;
  const stageAliases = {
    image: LEARNING_STAGES.UPLOAD_IMAGE,
    guided_write: LEARNING_STAGES.INITIAL_ATTEMPT,
    write: LEARNING_STAGES.INITIAL_ATTEMPT,
    submit: LEARNING_STAGES.FIRST_FEEDBACK,
    feedback: LEARNING_STAGES.FIRST_FEEDBACK,
    improve: LEARNING_STAGES.COVERAGE_LAYERS,
    coverage_complete: LEARNING_STAGES.COVERAGE_COMPLETE,
    upgrade: LEARNING_STAGES.POLISH_STAGE,
    quiz: LEARNING_STAGES.QUIZ,
    reward: LEARNING_STAGES.QUIZ,
  };
  const activeKey = stageAliases[activeStage] || activeStage;
  const activeIndex = steps.findIndex(([key]) => key === activeStep);
  const stageIndex = steps.findIndex(([key]) => key === activeKey);
  const progressIndex = stageIndex >= 0 ? stageIndex : Math.max(0, activeIndex);

  return `
    <nav class="journey-steps" aria-label="Learning progress">
      ${steps
        .map(
          ([key, label], index) => `
            <span class="journey-step ${
              index < progressIndex ? "complete" : index === progressIndex ? "active" : ""
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
  const starterHints = getStarterIdeaHints(session);
  const draft = prepareInitialAttemptDraft(state.sessionFlow, session);
  const draftText = draft.text;
  const starterClass = draft.isStarter ? " starter-prefill" : "";
  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell initial-attempt-shell">
      ${renderStepProgress(LEARNING_STAGES.INITIAL_ATTEMPT)}
      <section class="focused-writing-card initial-attempt-card">
        <div class="focused-copy">
          <h3>Describe this image in 1-2 sentences.</h3>
          <p class="muted initial-attempt-helper">Start simple. You can improve it later.</p>
        </div>
        <div class="focused-image-frame">
          <img class="focused-image-preview" src="${session.image_url}" alt="Image to describe">
        </div>
        <section class="starter-ideas-panel">
          <div class="starter-ideas-heading">
            <span class="starter-ideas-icon" aria-hidden="true">✦</span>
            <div>
              <h4>Starter ideas</h4>
              <p>Tap a hint to get started.</p>
            </div>
          </div>
          ${
            starterHints.length
              ? `
                <div class="mini-suggestion-row sentence-starter-row" aria-label="Starter ideas">
                  ${starterHints.map((hint, index) => renderStarterHintChip(hint, index)).join("")}
                </div>
              `
              : `<p class="muted starter-ideas-empty">No starter hints available yet.</p>`
          }
        </section>
        <div class="writing-box-wrap">
        <textarea
          id="learnerExplanationInput"
          class="focused-writing-input guided-writing-input${starterClass}"
          rows="4"
          maxlength="250"
          placeholder="Write your description here..."
        >${escapeHtml(draftText)}</textarea>
          <div id="initialAttemptCount" class="character-count">${draftText.length}/250</div>
        </div>
        <button id="submitWritingButton" class="primary-button journey-primary-button" type="button">
          Submit
        </button>
      </section>
    </div>
  `;

  document.getElementById("submitWritingButton").addEventListener("click", () => {
    submitExplanationFeedback(session, { mode: "first" });
  });
  els.sessionDetailPanel.querySelectorAll("[data-insert-hint]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      closeStarterHintPopovers();
      insertWritingHint(button.dataset.insertHint || "");
      playTapAnimation(button);
      button.closest(".starter-hint-chip")?.classList.add("selected");
    });
  });
  bindStarterHintInfoButtons();
  const writingInput = document.getElementById("learnerExplanationInput");
  writingInput?.addEventListener("input", onInitialAttemptInput);
  if (writingInput) {
    const cursorPosition = writingInput.value.length;
    writingInput.setSelectionRange(cursorPosition, cursorPosition);
  }
  window.setTimeout(() => {
    writingInput?.focus();
  }, 50);
}

function renderStarterHintChip(hint, index = 0) {
  const displayLabel = cleanUiText(hint?.label);
  const insertionText = displayLabel;
  const meaning = cleanUiText(hint?.meaning);
  const example = cleanUiText(hint?.example);
  const hasInfo = Boolean(meaning && example);
  const showInfo = hasInfo && starterHintShouldShowInfo(hint, displayLabel);
  if (!displayLabel || !insertionText) return "";
  return `
    <span class="starter-hint-chip${showInfo ? " has-info" : ""}" data-starter-hint-chip="${index}">
      <button class="sentence-starter-button noun-chip-button starter-hint-main" type="button" data-insert-hint="${escapeHtml(insertionText)}">
        ${escapeHtml(displayLabel)}
      </button>
      ${showInfo ? `
        <button
          class="starter-hint-info-button"
          type="button"
          data-starter-hint-info="${index}"
          aria-label="About ${escapeHtml(displayLabel)}"
          aria-expanded="false"
        >i</button>
        <span class="starter-hint-popover" data-starter-hint-popover="${index}" role="dialog">
          <strong>${escapeHtml(displayLabel)}</strong>
          <span class="popover-label">Meaning</span>
          <em>${escapeHtml(starterHintCompactText(meaning, 22))}</em>
          <span class="popover-label">Example</span>
          <em>${escapeHtml(starterHintCompactText(example, 16))}</em>
        </span>
      ` : ""}
    </span>
  `;
}

function starterHintShouldShowInfo(hint = {}, label = "") {
  const text = normalizeClientText(label);
  if (!text) return false;
  const words = text.split(/\s+/).filter(Boolean);
  const commonWords = new Set([
    "tree", "trees", "road", "street", "car", "cars", "building", "buildings",
    "child", "children", "boy", "girl", "man", "woman", "person", "people",
    "shirt", "clothes", "curtain", "curtains", "wall", "window", "door",
    "bed", "couch", "chair", "table", "floor", "sky", "house", "room",
  ]);
  if (words.length === 1 && commonWords.has(text)) return false;
  if (words.length === 2 && words.every((word) => commonWords.has(word) || /^(young|small|big|brown|green|blue|red|white|black|light|dark|old|new)$/.test(word))) {
    return false;
  }
  const highValuePattern = /\b(climbing|lined|overhang|patches?|shade|shaded|partially|visible|covered|surrounded|hanging|leaning|standing|sitting|next to|in front of|behind|nearby|with|under|over|across|along|between)\b/;
  if (highValuePattern.test(text)) return true;
  if (words.length >= 3) return true;
  return ["phrase", "sentence_structure"].includes(String(hint?.type || hint?.kind || ""));
}

function starterHintCompactText(value, maxWords) {
  const text = cleanUiText(value);
  const words = text.split(/\s+/).filter(Boolean);
  return words.length > maxWords ? `${words.slice(0, maxWords).join(" ")}.` : text;
}

function bindStarterHintInfoButtons() {
  els.sessionDetailPanel.querySelectorAll("[data-starter-hint-info]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const chip = button.closest(".starter-hint-chip");
      if (!chip) return;
      const willOpen = !chip.classList.contains("active");
      closeStarterHintPopovers();
      if (willOpen) {
        chip.classList.add("active");
        button.setAttribute("aria-expanded", "true");
        state.starterHintPopover.activeHintId = button.dataset.starterHintInfo || "";
        const popover = chip.querySelector(".starter-hint-popover");
        const wrapper = starterHintPopoverWrapper(chip);
        if (popover && wrapper) {
          popover.classList.add("is-open");
          popover.dataset.activeOwner = state.starterHintPopover.activeHintId;
          wrapper.appendChild(popover);
        }
        window.requestAnimationFrame(() => positionStarterHintPopover(chip, button, popover, wrapper));
      }
    });
  });
}

function closeStarterHintPopovers() {
  document.querySelectorAll(".starter-hint-chip.active").forEach((chip) => {
    chip.classList.remove("active");
    delete chip.dataset.popoverPlacement;
    chip.querySelector("[data-starter-hint-info]")?.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".starter-hint-popover.is-open").forEach((popover) => {
    const owner = starterHintChipById(popover.dataset.activeOwner || popover.dataset.starterHintPopover || "");
    popover.classList.remove("is-open", "popover-below", "popover-above");
    delete popover.dataset.activeOwner;
    delete popover.dataset.popoverPlacement;
    popover.removeAttribute("style");
    if (owner) {
      owner.appendChild(popover);
    }
  });
  state.starterHintPopover.activeHintId = null;
  state.starterHintPopover.popoverPosition = null;
}

function positionActiveStarterHintPopover() {
  const active = document.querySelector(".starter-hint-chip.active");
  const anchor = active?.querySelector("[data-starter-hint-info]");
  const popover = active
    ? document.querySelector(`.starter-hint-popover.is-open[data-active-owner="${active.dataset.starterHintChip}"]`) || active.querySelector(".starter-hint-popover")
    : null;
  if (active) {
    positionStarterHintPopover(active, anchor, popover, starterHintPopoverWrapper(active));
  }
}

function positionStarterHintPopover(chip, anchorElement = null, popoverElement = null, wrapperElement = null) {
  const popover = popoverElement || chip?.querySelector(".starter-hint-popover");
  if (!chip || !popover || !chip.classList.contains("active")) return;
  const wrapper = wrapperElement || starterHintPopoverWrapper(chip);
  const anchor = anchorElement || chip.querySelector("[data-starter-hint-info]") || chip;
  const safe = 16;
  const gap = 8;
  const scrollX = window.scrollX || window.pageXOffset || 0;
  const scrollY = window.scrollY || window.pageYOffset || 0;
  const viewportWidth = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const viewportHeight = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
  const wrapperRect = wrapper.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  const wrapperPageLeft = wrapperRect.left + scrollX;
  const wrapperPageTop = wrapperRect.top + scrollY;
  const anchorPageLeft = anchorRect.left + scrollX;
  const anchorPageTop = anchorRect.top + scrollY;
  const localX = anchorPageLeft - wrapperPageLeft + anchorRect.width / 2;
  const localBelowY = anchorPageTop - wrapperPageTop + anchorRect.height;
  const localAboveY = anchorPageTop - wrapperPageTop;
  const visibleLeft = clamp(-wrapperRect.left + safe, safe, Math.max(safe, wrapperRect.width - safe));
  const visibleRight = clamp(viewportWidth - wrapperRect.left - safe, visibleLeft, Math.max(visibleLeft, wrapperRect.width - safe));
  const visibleTop = clamp(-wrapperRect.top + safe, safe, Math.max(safe, wrapperRect.height - safe));
  const visibleBottom = clamp(viewportHeight - wrapperRect.top - safe, visibleTop, Math.max(visibleTop, wrapperRect.height - safe));
  const visibleWidth = Math.max(120, visibleRight - visibleLeft);
  const visibleHeight = Math.max(80, visibleBottom - visibleTop);
  const width = Math.min(280, Math.max(120, visibleWidth));
  const maxPopoverHeight = visibleHeight;
  popover.style.width = `${width}px`;
  popover.style.maxHeight = `${maxPopoverHeight}px`;

  const popoverRect = popover.getBoundingClientRect();
  const height = Math.min(Math.ceil(popoverRect.height || 170), maxPopoverHeight);
  const spaceBelow = visibleBottom - localBelowY - gap;
  const spaceAbove = localAboveY - visibleTop - gap;
  const placement = spaceBelow < height && spaceAbove > spaceBelow ? "above" : "below";
  const leftInWrapper = clamp(localX - width / 2, visibleLeft, Math.max(visibleLeft, visibleRight - width));
  const preferredTop = placement === "below"
    ? localBelowY + gap
    : localAboveY - height - gap;
  const topInWrapper = clamp(preferredTop, visibleTop, Math.max(visibleTop, visibleBottom - height));
  const arrowLeft = clamp(localX - leftInWrapper, 18, width - 18);

  state.starterHintPopover.popoverPosition = { top: topInWrapper, left: leftInWrapper, placement };
  chip.dataset.popoverPlacement = placement;
  chip.classList.toggle("popover-below", placement === "below");
  chip.classList.toggle("popover-above", placement === "above");
  popover.dataset.popoverPlacement = placement;
  popover.classList.toggle("popover-below", placement === "below");
  popover.classList.toggle("popover-above", placement === "above");
  popover.style.left = `${leftInWrapper}px`;
  popover.style.top = `${topInWrapper}px`;
  popover.style.maxHeight = `${maxPopoverHeight}px`;
  popover.style.setProperty("--arrow-left", `${arrowLeft}px`);
  popover.style.setProperty("--arrow-top", "50%");
}

function starterHintPopoverWrapper(chip) {
  return chip?.closest(".journey-shell, .focused-step-shell, #sessionDetailPanel, .learn-page") || els.sessionDetailPanel || document.body;
}

function starterHintChipById(id) {
  return [...document.querySelectorAll(".starter-hint-chip")]
    .find((chip) => chip.dataset.starterHintChip === String(id));
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(value, max));
}

function prepareInitialAttemptDraft(flow = {}, session = {}) {
  const existing = flow.explanation || "";
  if (cleanUiText(existing)) {
    return { text: existing, isStarter: false };
  }
  if (flow.initialStarterTouched) {
    return { text: "", isStarter: false };
  }
  const starter = getWritingStarter(session);
  flow.initialStarterText = starter;
  flow.initialStarterTouched = false;
  return { text: starter, isStarter: true };
}

function getStarterIdeaHints(session) {
  const analysis = session?.analysis || {};
  const candidates = [];
  const context = starterHintImageContext(analysis);
  const addHint = (value, score = 50, kind = "phrase", insertValue = "", metadata = {}, category = "") => {
    const label = kind === "starter" ? sentenceStarterHintLabel(value) : starterIdeaLabel(value);
    if (!starterIdeaLooksUseful(label)) return;
    candidates.push({
      label,
      insert: label,
      kind,
      category: category || (kind === "starter" ? "starter" : starterHintCategory(label, metadata, context)),
      type: starterHintType(kind),
      meaning: cleanUiText(metadata.meaning || metadata.meaning_simple || metadata.description),
      example: cleanUiText(metadata.example),
      score,
    });
  };

  (analysis.starter_hints || analysis.starterHints || []).forEach((item) => {
    if (!item || typeof item !== "object") return;
    const kind = item.type === "sentence_structure" ? "starter" : item.type || "phrase";
    addHint(item.label, 115, kind, item.insert || item.label, item, item.category || "");
  });
  const aiStarterHints = uniqueStarterIdeas(candidates)
    .filter((item) => item.meaning && item.example)
    .slice(0, 3);
  if (aiStarterHints.length) {
    return aiStarterHints;
  }
  candidates.length = 0;

  (analysis.objects || []).forEach((item, index) => {
    const value = item?.name || item?.description || item;
    const importance = Number(item?.importance || 0);
    addHint(
      value,
      95 - index * 8 + importance * 8,
      "visual",
      "",
      {
        ...item,
        meaning: item?.description,
        example: starterHintGeneralExample(value),
      },
      importance >= 0.85 ? "main_subject" : "supporting_subject"
    );
  });
  (analysis.vocabulary || []).forEach((item) => {
    addHint(item?.word || item, 72, "word", "", item);
  });
  (analysis.phrases || []).forEach((item) => {
    addHint(item?.phrase || item, 68, "phrase", "", item);
  });

  return uniqueStarterIdeas(candidates)
    .filter((item) => item.meaning && item.example)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
}

function starterHintGeneralExample(label) {
  const text = cleanUiText(label);
  const key = normalizeClientText(text);
  if (!key) return "";
  if (/\bclimbing vines?\b/.test(key)) return "The wall is covered with climbing vines.";
  if (/\blined with\b/.test(key)) return "The street is lined with small trees.";
  if (/\broof overhang\b/.test(key)) return "The roof overhang gives some shade.";
  if (/\bpatches? of shade\b/.test(key)) return "Patches of shade cover the path.";
  if (/\bhanging\b/.test(key)) return `The ${text} are hanging near the door.`;
  if (/\bbehind\b/.test(key)) return `The lamp is ${text} the chair.`;
  if (/\bnext to\b/.test(key)) return `The bag is ${text} the table.`;
  if (/\bin front of\b/.test(key)) return `The bike is ${text} the shop.`;
  if (text.split(/\s+/).length >= 2) return `The old house has ${text} near the entrance.`;
  const article = /^[aeiou]/i.test(text) ? "an" : "a";
  return `There is ${article} ${text} near the window.`;
}

function selectMinimalStarterHints(candidates = []) {
  const ordered = candidates
    .filter((item) => item && item.label && item.category !== "starter")
    .sort((a, b) => b.score - a.score);
  const selected = [];
  const pick = (category) => {
    const item = ordered.find((candidate) =>
      candidate.category === category &&
      !selected.some((existing) => starterHintsTooSimilar(existing.label, candidate.label))
    );
    if (item) selected.push(item);
  };

  pick("main_subject");
  const mainOnly = selected.length === 1 && !ordered.some((item) => item.category === "supporting_subject" || item.category === "setting");
  if (mainOnly) return selected;
  pick("supporting_subject");

  if (!selected.length && ordered[0]) {
    selected.push(ordered[0]);
  }
  ordered.forEach((item) => {
    if (selected.length >= 3) return;
    if (item.score < 70 && selected.length >= 1) return;
    if (selected.some((existing) => starterHintsTooSimilar(existing.label, item.label))) return;
    selected.push(item);
  });
  return selected;
}

function starterHintCategory(label, metadata = {}, context = {}) {
  const explicit = cleanUiText(metadata.category);
  if (["main_subject", "supporting_subject", "setting"].includes(explicit)) return explicit;
  const text = normalizeClientText(label);
  const primary = normalizeClientText(context.primary);
  if (primary && text === primary) return "main_subject";
  if (/\b(room|street|road|surface|background|foreground|curtains|columns|building|bed|couch|floor|sky|wall|window|setting)\b/.test(text)) {
    return "setting";
  }
  return context.primary ? "supporting_subject" : "main_subject";
}

function starterHintsTooSimilar(a, b) {
  const first = normalizeClientText(a);
  const second = normalizeClientText(b);
  return Boolean(first && second && (first === second || first.includes(second) || second.includes(first)));
}

function starterHintType(kind = "phrase") {
  if (kind === "starter") return "sentence_structure";
  if (kind === "word") return "word";
  return "phrase";
}

function starterHintImageContext(analysis = {}) {
  const objects = (analysis.objects || []).map((item) => cleanUiText(item?.name || item)).filter(Boolean);
  const details = (analysis.environment_details || []).flatMap(nounChipsFromText).map(cleanUiText).filter(Boolean);
  const primary = objects.find((item) => !/\b(signboard|logo|text|caption|label)\b/i.test(item)) || objects[0] || "";
  const surface = [...objects, ...details].find((item) => /\b(bed|couch|sofa|chair|bench|surface|floor|ground|road|path)\b/i.test(item)) || "";
  const setting = cleanUiText(analysis.environment?.setting || analysis.environment || details[0] || "");
  return { primary, surface, setting, objects, details };
}

function starterIdeaLabel(value) {
  return cleanUiText(value)
    .replace(/[.!?]+$/g, "")
    .replace(/^(the|a|an)\s+/i, "")
    .trim();
}

function starterIdeaLooksUseful(value) {
  const text = cleanUiText(value);
  if (!text || text.length > 34) return false;
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length || words.length > 3) return false;
  if (/\b(signboard|caption|label|logo|number|text|tiny|small detail|blue sky|cloudy sky)\b/i.test(text)) return false;
  if (/\b(that|which|because|while|although)\b/i.test(text)) return false;
  return true;
}

function uniqueStarterIdeas(candidates = []) {
  const seen = new Set();
  const result = [];
  candidates.forEach((item) => {
    const key = normalizeClientText(item.label);
    if (!key || seen.has(key)) return;
    if ([...seen].some((existing) => key.includes(existing) || existing.includes(key))) return;
    seen.add(key);
    result.push(item);
  });
  return result;
}

function sentenceStarterHintLabel(starter) {
  const text = normalizeSentenceStarter(starter).trim();
  if (!text) return "";
  return text.replace(/[,.]?\s*$/g, "...").replace(/\s+\.\.\.$/, "...");
}

function nounChipsFromText(value) {
  return cleanUiText(value)
    .replace(/[.!?]+$/g, "")
    .split(/\s*,\s*|\s+and\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
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

  const initialFeedback = feedback.initial_attempt_feedback;
  if (initialFeedback) {
    renderInitialAttemptFeedbackStep(session, feedback, initialFeedback);
    return;
  }

  const totalScore = feedbackTotalScore(feedback);
  const latestAttempt = (state.sessionFlow.attempts || []).at(-1) || null;
  const attemptCount = Math.max(1, (state.sessionFlow.attempts || []).length);
  const latestText = latestAttempt?.text || state.sessionFlow.explanation || "";
  const issue = buildFeedbackIssue(feedback, session);
  const positive = buildFeedbackPositiveLine(feedback, totalScore, issue.focusAreas);

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

        <button id="feedbackPrimaryButton" class="primary-button journey-primary-button diagnosis-cta coach-reveal" ${coachRevealStyle(4)} type="button">
          Continue Building Layers
        </button>
      </section>
    </div>
  `;

  document.getElementById("feedbackPrimaryButton").addEventListener("click", () => {
    renderSessionStep("improve", { stage: LEARNING_STAGES.COVERAGE_LAYERS });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  animateNumber("feedbackScoreValue", totalScore);
}

function renderInitialAttemptFeedbackStep(session, feedback, initialFeedback) {
  const latestAttempt = (state.sessionFlow.attempts || []).at(-1) || {};
  const originalAttempt = latestAttempt.text || state.sessionFlow.explanation || "";
  const upgrades = state.sessionFlow.initialImprovementCards?.length
    ? state.sessionFlow.initialImprovementCards
    : buildInitialImprovementCards(originalAttempt, initialFeedback, feedback);
  state.sessionFlow.initialImprovementCards = upgrades;
  state.sessionFlow.initialImprovementDraft = state.sessionFlow.initialImprovementDraft || originalAttempt;
  state.sessionFlow.initialAppliedImprovementIds = state.sessionFlow.initialAppliedImprovementIds || [];
  state.sessionFlow.initialSkippedImprovementIds = state.sessionFlow.initialSkippedImprovementIds || [];
  const draft = state.sessionFlow.initialImprovementDraft || originalAttempt;
  const completed = initialEnhancementComplete(upgrades);
  const message = cleanUiText(initialFeedback.message) || "Nice work — your sentence is clear enough to continue.";
  const handledCount = initialEnhancementHandledIds().size;
  const totalChoices = upgrades.length;

  els.sessionDetailPanel.innerHTML = `
    <div class="ai-enhancement-backdrop ai-enhancement-screen">
      <section class="ai-enhancement-modal coach-reveal" ${coachRevealStyle(0)} aria-labelledby="aiEnhancementTitle">
        <div class="ai-enhancement-status" aria-label="Learning progress">
          <button class="ai-enhancement-back-button" type="button" aria-label="Back to writing">
            <span aria-hidden="true">←</span>
          </button>
          <div class="ai-enhancement-progress">
            <strong>Step 2 of 5</strong>
            ${renderAiEnhancementDots()}
          </div>
          <div class="ai-enhancement-stats">
            <span aria-label="Streak">🔥 ${escapeHtml(String(state.progress?.streak_days || state.user?.streak_days || 4))}</span>
            <i aria-hidden="true"></i>
            <span>XP ${escapeHtml(String(state.progress?.xp_points || 860))}</span>
          </div>
        </div>

        <div class="ai-enhancement-image-frame">
          <img src="${escapeHtml(session.image_url || "")}" alt="Image being described">
        </div>

        <header class="ai-modal-header">
          <span class="ai-enhancement-kicker"><span aria-hidden="true">✣</span> AI enhancement</span>
          <h3 id="aiEnhancementTitle">Let’s polish your description</h3>
          <p>${upgrades.length ? "Tap the highlighted parts to see how we can improve them." : "Your description is already clear enough to continue."}</p>
        </header>

        <section class="ai-sentence-section initial-sentence-card initial-inline-sentence-card">
          <p id="initialEnhancementSentence">${renderInitialEnhancementSentence(draft, upgrades)}</p>
        </section>

        ${
          completed
            ? renderInitialImprovementCompleteState(message, draft, upgrades.length)
            : `<p class="ai-enhancement-tip"><span aria-hidden="true">💡</span> ${handledCount ? "Tap other highlights to continue improving." : "Choose Apply or Skip for each useful highlight."}</p>`
        }

        ${completed ? `
        <section class="ai-preview-card initial-final-preview">
          <h4><span aria-hidden="true">✣</span> Preview</h4>
          <p id="initialImprovementPreview">${renderInitialEnhancementSentence(draft, upgrades, { previewOnly: true })}</p>
          <div class="ai-preview-legend">
            <span><i></i> Your words</span>
            <span><i></i> Upgraded words</span>
          </div>
        </section>
        ` : `<p id="initialImprovementPreview" class="hidden">${escapeHtml(draft)}</p>`}

        <button id="feedbackPrimaryButton" class="primary-button journey-primary-button ai-complete-button" type="button" ${!completed ? "disabled" : ""}>
          Continue <span aria-hidden="true">›</span>
        </button>
        ${!completed && totalChoices ? `<small class="ai-complete-lock">${handledCount}/${totalChoices} choices handled</small>` : ""}
      </section>
    </div>
  `;

  els.sessionDetailPanel.querySelector(".ai-enhancement-back-button")?.addEventListener("click", () => {
    renderWriteStep(session);
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  document.getElementById("feedbackPrimaryButton").addEventListener("click", () => {
    state.sessionFlow.explanation = cleanUiText(document.getElementById("initialImprovementPreview")?.textContent) || draft || state.sessionFlow.explanation;
    renderSessionStep("improve", { stage: LEARNING_STAGES.COVERAGE_LAYERS });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  bindInitialEnhancementInteractions(session, feedback, initialFeedback);
  if (state.sessionFlow.initialLastAppliedImprovementId) {
    const id = state.sessionFlow.initialLastAppliedImprovementId;
    state.sessionFlow.initialLastAppliedImprovementId = "";
    window.setTimeout(() => {
      const target = [...els.sessionDetailPanel.querySelectorAll("[data-initial-enhancement-applied]")]
        .find((item) => item.dataset.initialEnhancementApplied === id);
      showInitialModalXpPulse(target || document.getElementById("initialEnhancementSentence"), 5);
    }, 40);
  }
}

function renderAiEnhancementDots() {
  return `
    <div class="ai-enhancement-dots" aria-hidden="true">
      ${Array.from({ length: 5 }, (_, index) => `<span class="${index < 2 ? "active" : ""}"></span>`).join("")}
    </div>
  `;
}

function renderInitialImprovementCompleteState(message, draft = "", upgradeCount = 0) {
  return `
    <section class="initial-improvement-done coach-reveal" ${coachRevealStyle(1)}>
      <span aria-hidden="true">✓</span>
      <div>
        <h4>${upgradeCount ? "All choices handled" : "No major upgrade needed"}</h4>
        <p>${escapeHtml(upgradeCount ? "Here is your polished sentence." : message)}</p>
      </div>
    </section>
  `;
}

function initialEnhancementHandledIds() {
  return new Set([
    ...(state.sessionFlow.initialAppliedImprovementIds || []),
    ...(state.sessionFlow.initialSkippedImprovementIds || []),
  ]);
}

function initialEnhancementComplete(upgrades = []) {
  if (!upgrades.length) return true;
  const handled = initialEnhancementHandledIds();
  return upgrades.every((item) => handled.has(item.id));
}

function renderInitialEnhancementSentence(text, upgrades = [], options = {}) {
  const raw = String(text || "");
  if (!raw) return "";
  const handled = initialEnhancementHandledIds();
  const applied = new Set(state.sessionFlow.initialAppliedImprovementIds || []);
  const spans = [];
  const lowered = raw.toLowerCase();
  upgrades.forEach((item) => {
    const isApplied = applied.has(item.id);
    const isHandled = handled.has(item.id);
    if (isHandled && !isApplied) return;
    const phrase = isApplied ? item.suggestedText : item.currentText;
    const start = lowered.indexOf(String(phrase || "").toLowerCase());
    if (start < 0) return;
    const end = start + phrase.length;
    if (spans.some((span) => start < span.end && end > span.start)) return;
    spans.push({ start, end, item, isApplied, isHandled });
  });
  spans.sort((a, b) => a.start - b.start);
  let cursor = 0;
  let markup = "";
  spans.forEach((span) => {
    markup += escapeHtml(raw.slice(cursor, span.start));
    const phrase = raw.slice(span.start, span.end);
    if (span.isApplied || options.previewOnly) {
      markup += span.isApplied
        ? `<mark class="initial-modal-upgraded initial-modal-just-applied" data-initial-enhancement-applied="${escapeHtml(span.item.id)}">${escapeHtml(phrase)}</mark>`
        : escapeHtml(phrase);
    } else {
      markup += `
        <span class="initial-modal-weak" role="button" tabindex="0" data-initial-modal-upgrade="${escapeHtml(span.item.id)}" aria-expanded="false">
          ${escapeHtml(phrase)}
          ${renderInitialEnhancementPopover(span.item)}
        </span>
      `;
    }
    cursor = span.end;
  });
  markup += escapeHtml(raw.slice(cursor));
  return markup;
}

function renderInitialEnhancementPopover(item) {
  return `
    <span class="initial-modal-popover" role="dialog">
      <small>Suggested upgrade</small>
      <strong>${escapeHtml(item.suggestedText)}</strong>
      <span class="popover-label">Why</span>
      <em>${escapeHtml(item.whyItHelps)}</em>
      <span class="popover-label">Example</span>
      <em>${escapeHtml(item.example)}</em>
      <span class="initial-modal-actions">
        <button class="initial-modal-skip" type="button" data-skip-initial-improvement="${escapeHtml(item.id)}">Skip</button>
        <button class="initial-modal-apply" type="button" data-apply-initial-improvement="${escapeHtml(item.id)}">Apply (+5 XP)</button>
      </span>
    </span>
  `;
}

function bindInitialEnhancementInteractions(session, feedback, initialFeedback) {
  els.sessionDetailPanel.querySelectorAll("[data-initial-modal-upgrade]").forEach((target) => {
    target.addEventListener("click", (event) => {
      if (event.target.closest("[data-apply-initial-improvement], [data-skip-initial-improvement], [data-dismiss-initial-modal]")) return;
      toggleInitialModalPopover(target);
    });
    target.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggleInitialModalPopover(target);
    });
  });
  els.sessionDetailPanel.querySelectorAll(".initial-modal-popover").forEach((popover) => {
    popover.addEventListener("click", (event) => {
      event.stopPropagation();
    });
  });
  els.sessionDetailPanel.querySelectorAll("[data-apply-initial-improvement]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      applyInitialImprovement(button.dataset.applyInitialImprovement || "", session, feedback, initialFeedback);
    });
  });
  els.sessionDetailPanel.querySelectorAll("[data-skip-initial-improvement]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      skipInitialImprovement(button.dataset.skipInitialImprovement || "", session, feedback, initialFeedback);
    });
  });
  els.sessionDetailPanel.querySelectorAll("[data-dismiss-initial-modal]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const target = button.closest("[data-initial-modal-upgrade]");
      target?.classList.remove("active");
      target?.setAttribute("aria-expanded", "false");
    });
  });
  window.addEventListener("resize", positionActiveInitialModalPopover, { passive: true });
}

function applyInitialImprovement(id, session, feedback, initialFeedback) {
  const cards = state.sessionFlow.initialImprovementCards || [];
  const card = cards.find((item) => item.id === id);
  if (!card) return;
  state.sessionFlow.initialImprovementDraft = applyInitialImprovementToText(state.sessionFlow.initialImprovementDraft || "", card);
  state.sessionFlow.initialAppliedImprovementIds = uniqueWritingHints([...(state.sessionFlow.initialAppliedImprovementIds || []), id]);
  state.sessionFlow.initialLastAppliedImprovementId = id;
  awardLocalXp(5);
  renderInitialAttemptFeedbackStep(session, feedback, initialFeedback);
}

function skipInitialImprovement(id, session, feedback, initialFeedback) {
  state.sessionFlow.initialSkippedImprovementIds = uniqueWritingHints([...(state.sessionFlow.initialSkippedImprovementIds || []), id]);
  renderInitialAttemptFeedbackStep(session, feedback, initialFeedback);
}

function buildInitialImprovementCards(originalAttempt = "", initialFeedback = {}, feedback = {}) {
  const original = cleanUiText(originalAttempt);
  if (!original) return [];
  const rawCards = Array.isArray(initialFeedback.improvements)
    ? initialFeedback.improvements
    : Array.isArray(initialFeedback.improvement_cards)
      ? initialFeedback.improvement_cards
      : [];
  const cards = rawCards
    .map((item, index) => normalizeInitialImprovementCard(item, original, index))
    .filter(Boolean);
  const occupied = [];
  return cards.filter((card) => {
    const range = initialImprovementCardRange(original, card);
    if (!range) return false;
    if (occupied.some((item) => range.start < item.end && range.end > item.start)) return false;
    occupied.push(range);
    return true;
  }).slice(0, 3);
}

function normalizeInitialImprovementCard(item, original, index = 0) {
  if (!item || typeof item !== "object") return null;
  const category = normalizeInitialImprovementCategory(item.category);
  const title = cleanUiText(item.title) || initialImprovementCategoryTitle(category);
  const rawCurrent = cleanUiText(item.currentText || item.targetText || item.oldText || item.old);
  const currentText = findTextOccurrence(original, rawCurrent) || rawCurrent;
  const suggestedText = cleanUiText(item.suggestedText || item.replacementText || item.newText || item.suggested || item.rewrite || item.new);
  const whyItHelps = cleanUiText(item.whyItHelps || item.why || item.reason);
  const example = cleanUiText(item.example);
  const xpReward = [10, 5].includes(Number(item.xpReward)) ? Number(item.xpReward) : 5;
  if (!suggestedText || normalizeClientText(suggestedText) === normalizeClientText(currentText)) return null;
  if (!currentText || !whyItHelps || !example) return null;
  const card = {
    id: cleanUiText(item.id) || `${category}-${index + 1}`,
    category,
    title,
    currentText,
    suggestedText,
    whyItHelps,
    example,
    xpReward,
  };
  const preview = applyInitialImprovementToText(original, card);
  if (!initialImprovementPreviewLooksSafe(preview, original, card)) return null;
  return card;
}

function applyInitialImprovementToText(text, card) {
  const source = cleanUiText(text);
  if (!source || !card?.suggestedText) return source;
  const current = findTextOccurrence(source, card.currentText);
  if (current) {
    return replaceFirstTextOccurrence(source, current, card.suggestedText);
  }
  return card.suggestedText;
}

function initialImprovementCardRange(text, card) {
  const source = String(text || "").toLowerCase();
  const target = String(card?.currentText || "").toLowerCase();
  if (!source || !target) return null;
  const start = source.indexOf(target);
  return start >= 0 ? { start, end: start + target.length } : null;
}

function initialImprovementPreviewLooksSafe(preview, original, card) {
  const text = cleanUiText(preview);
  if (!text || normalizeClientText(text) === normalizeClientText(original)) return false;
  if (hasAdjacentRepeatedWords(text)) return false;
  if (text.split(/\s+/).length > Math.max(28, original.split(/\s+/).length + 12)) return false;
  const currentWords = normalizeClientText(card.currentText).split(/\s+/).filter((word) => word.length > 2);
  const suggestedWords = normalizeClientText(card.suggestedText);
  const preservesSomeMeaning = currentWords.length === 0 || currentWords.some((word) => suggestedWords.includes(word));
  if (!preservesSomeMeaning && card.currentText !== original) return false;
  return true;
}

function normalizeInitialImprovementCategory(category) {
  const value = String(category || "").trim();
  return [
    "subject_clarity",
    "sentence_flow",
    "natural_phrasing",
    "grammar_fix",
    "visual_clarity",
  ].includes(value) ? value : "natural_phrasing";
}

function initialImprovementCategoryTitle(category) {
  return {
    subject_clarity: "Clearer subject",
    sentence_flow: "Better sentence flow",
    natural_phrasing: "More natural phrasing",
    grammar_fix: "Cleaner grammar",
    visual_clarity: "Clearer image meaning",
  }[category] || "Useful improvement";
}

function buildContextAwareUpgrade(original, oldText, newText, options = {}) {
  const source = cleanUiText(original);
  const replacement = cleanUiText(newText);
  if (!source || !replacement) return null;
  const structuralTarget = options.allowStructuralRetarget === false ? "" : structuralStarterTarget(source, replacement);
  const target = findTextOccurrence(source, structuralTarget || oldText);
  if (!target || normalizeClientText(target) === normalizeClientText(replacement)) return null;
  const finalPreview = replaceFirstTextOccurrence(source, target, replacement);
  if (!upgradeFinalPreviewLooksSafe(source, target, replacement, finalPreview)) return null;
  return { oldText: target, newText: replacement, finalPreview };
}

function structuralStarterTarget(source, replacement) {
  if (!/^(?:the|this)\s+(?:image|scene|picture)\s+(?:shows|includes|has)\b/i.test(replacement)) {
    return "";
  }
  const patterns = [
    /\bIn (?:the|this) (?:image|scene|picture),? there (?:is|are)\b/i,
    /\bThere (?:is|are)\b/i,
    /\b(?:The|This) (?:image|scene|picture) (?:has|includes)\b/i,
  ];
  for (const pattern of patterns) {
    const match = String(source || "").match(pattern);
    if (match) return match[0];
  }
  return "";
}

function upgradeFinalPreviewLooksSafe(original, target, replacement, finalPreview) {
  const source = String(original || "");
  const preview = String(finalPreview || "");
  if (!source || !target || !replacement || !preview || preview === source) return false;
  if (!source.toLowerCase().includes(String(target).toLowerCase())) return false;
  if (/\bIn\s+(?:The|This)\s+(?:image|scene|picture)\s+(?:shows|includes|has)\b/.test(preview)) return false;
  if (/\b(?:image|scene|picture)\s+(?:shows|includes|has)\s+(?:image|scene|picture)\b/i.test(preview)) return false;
  if (hasAdjacentRepeatedWords(preview)) return false;

  const start = source.toLowerCase().indexOf(String(target).toLowerCase());
  const before = source.slice(0, start);
  const previousWord = (before.match(/\b([a-z]+)\s*$/i) || [])[1] || "";
  const replacementAddsClause = /\b(?:shows?|includes?|has|have|is|are|was|were|can see)\b/i.test(replacement);
  const targetHasClause = /\b(?:there\s+(?:is|are)|shows?|includes?|has|have|is|are|was|were|can see)\b/i.test(target);
  if (replacementAddsClause && !targetHasClause && /\b(?:in|on|at|of|with|behind|beside|near)\b/i.test(previousWord)) {
    return false;
  }
  if (replacementAddsClause && !targetHasClause && target.split(/\s+/).filter(Boolean).length <= 2 && start > 0) {
    return false;
  }
  return true;
}

function hasAdjacentRepeatedWords(text) {
  const words = String(text || "").toLowerCase().match(/\b[a-z]+\b/g) || [];
  return words.some((word, index) => index > 0 && word === words[index - 1]);
}

function toggleInitialModalPopover(target) {
  const active = target.classList.contains("active");
  els.sessionDetailPanel.querySelectorAll(".initial-modal-weak.active").forEach((item) => {
    item.classList.remove("active");
    item.setAttribute("aria-expanded", "false");
  });
  if (!active) {
    target.classList.add("active");
    target.setAttribute("aria-expanded", "true");
    window.requestAnimationFrame(() => positionInitialModalPopover(target));
  }
}

function positionActiveInitialModalPopover() {
  const active = els.sessionDetailPanel?.querySelector(".initial-modal-weak.active");
  if (active) {
    positionInitialModalPopover(active);
  }
}

function positionInitialModalPopover(target) {
  const popover = target?.querySelector(".initial-modal-popover");
  if (!target || !popover || !target.classList.contains("active")) return;
  const safe = 12;
  const gap = 12;
  const viewportWidth = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const viewportHeight = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
  const modalRect = target.closest(".ai-enhancement-modal")?.getBoundingClientRect();
  const availableWidth = modalRect
    ? Math.min(viewportWidth - safe * 2, modalRect.width - safe * 2)
    : viewportWidth - safe * 2;
  const width = Math.min(512, Math.max(248, availableWidth));
  popover.style.width = `${width}px`;

  const targetRect = target.getBoundingClientRect();
  let popoverRect = popover.getBoundingClientRect();
  const height = Math.min(popoverRect.height, Math.max(180, viewportHeight - safe * 2));
  const spaceAbove = targetRect.top - safe;
  const spaceBelow = viewportHeight - targetRect.bottom - safe;
  const openBelow = spaceAbove < height + gap && spaceBelow > spaceAbove;
  let top = openBelow ? targetRect.bottom + gap : targetRect.top - height - gap;
  top = Math.max(safe, Math.min(top, viewportHeight - height - safe));

  const center = targetRect.left + targetRect.width / 2;
  let left = center - width / 2;
  if (modalRect) {
    left = Math.max(modalRect.left + safe, Math.min(left, modalRect.right - width - safe));
  }
  left = Math.max(safe, Math.min(left, viewportWidth - width - safe));
  const arrowLeft = Math.max(18, Math.min(width - 18, center - left));

  target.classList.toggle("popover-below", openBelow);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
  popover.style.maxHeight = `${Math.max(160, viewportHeight - safe * 2)}px`;
  popover.style.setProperty("--arrow-left", `${arrowLeft}px`);
}

function showInitialModalXpPulse(anchor, xp = 5) {
  const pulse = document.createElement("span");
  pulse.className = "initial-modal-xp-pulse";
  pulse.textContent = `+${xp} XP`;
  (anchor || document.getElementById("initialEnhancementSentence"))?.appendChild(pulse);
  window.setTimeout(() => pulse.remove(), 900);
}

function joinReadableList(items = []) {
  const clean = cleanUiList(items, 5);
  if (!clean.length) return "";
  if (clean.length === 1) return clean[0];
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(", ")}, and ${clean.at(-1)}`;
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
  const latestText = attempts.length <= 1 && state.sessionFlow.initialImprovementDraft
    ? state.sessionFlow.initialImprovementDraft
    : latestAttempt?.text || state.sessionFlow.explanation || "";
  const rewriteDraft = evolvingParagraphText(latestText, latestFeedback);
  const attemptNumber = attempts.length;
  const coverageLayers = buildCoverageLayerState(latestFeedback, session, latestText);
  state.sessionFlow.coverageLayers = coverageLayers;
  state.sessionFlow.coverageComplete = Boolean(coverageLayers.complete);
  state.sessionFlow.polishUnlocked = Boolean(coverageLayers.complete);
  const upgradeSuggestions = buildArticulationUpgradeSuggestions(session, latestFeedback, latestText);
  const upgradeState = normalizeArticulationUpgradeState(
    state.sessionFlow.articulationUpgrade,
    latestText,
    upgradeSuggestions
  );
  state.sessionFlow.articulationUpgrade = upgradeState;
  const coverageAcknowledged = Boolean(state.sessionFlow.coverageCompleteAcknowledged);
  const showCoverageComplete = coverageLayers.complete && !coverageAcknowledged && !upgradeState.finalized;
  const showUpgrade = coverageLayers.complete && coverageAcknowledged && !upgradeState.finalized;
  const showMoveOption = coverageLayers.complete && upgradeState.finalized;
  const showEditor = !coverageLayers.complete;
  const ready = showMoveOption;
  const issue = coverageLayers.currentLayer
    ? buildLayerFeedbackIssue(coverageLayers.currentLayer, latestFeedback, session)
    : buildFeedbackIssue(latestFeedback, session);
  const escalation = buildImproveEscalationContext(session, attempts, issue, coverageLayers.currentLayer);
  const currentFocus = coverageLayers.currentLayer
    ? buildLayerCurrentFocus(coverageLayers.currentLayer, session, escalation)
    : buildImproveCurrentFocus(issue, session, escalation);
  const hintGroups = buildImproveHintGroups(session, latestFeedback, issue, latestText, escalation);
  const stage = showMoveOption
    ? LEARNING_STAGES.FINAL_REVEAL
    : showUpgrade
      ? LEARNING_STAGES.POLISH_STAGE
      : coverageLayers.complete
        ? LEARNING_STAGES.COVERAGE_COMPLETE
        : state.sessionFlow.stage === LEARNING_STAGES.LAYER_SUCCESS
          ? LEARNING_STAGES.LAYER_SUCCESS
        : LEARNING_STAGES.COVERAGE_LAYERS;
  const currentLayerNumber = coverageLayers.currentIndex >= 0 ? coverageLayers.currentIndex + 1 : Math.max(1, attemptNumber);
  const layerTotal = Math.max(coverageLayers.layers?.length || 0, currentLayerNumber);
  const headerEyebrow = showMoveOption
    ? "Final reveal"
    : showUpgrade
      ? "Polish stage"
      : stage === LEARNING_STAGES.LAYER_SUCCESS
        ? "Layer success"
      : `Focus ${currentLayerNumber} of ${layerTotal}`;
  const headerTitle = showMoveOption
    ? "Look how far it improved"
    : showUpgrade
      ? "Upgrade your articulation"
      : shortFocusPreview(coverageLayers.currentLayer) || "Explore one visual area";
  const headerSupport = showUpgrade
    ? "Scene covered. Now choose the wording upgrades you like."
    : "";
  state.sessionFlow.stage = stage;
  if (state.currentSession) {
    state.currentSession.learning_stage = stage;
  }
  if (showEditor) {
    updateAppHeaderForCoverageFocus(currentLayerNumber, layerTotal);
  } else {
    updateAppHeaderForStage(stage);
  }

  els.sessionDetailPanel.innerHTML = `
    <div class="journey-shell focused-step-shell ${showEditor || showCoverageComplete ? "coverage-layer-shell" : ""}">
      ${showEditor || showCoverageComplete ? "" : renderStepProgress(stage)}
      <section class="focused-writing-card improve-action-card ${showEditor ? "coverage-layer-card" : ""}">
        ${showEditor ? renderImproveEditor({ rewriteDraft, currentFocus, hintGroups, articulation: coverageLayers, escalation, session, latestText, latestFeedback }) : ""}
        ${showCoverageComplete ? renderCoverageCompleteStage(latestFeedback, session, coverageLayers) : ""}
        ${showUpgrade ? renderArticulationUpgradeStage(upgradeState, upgradeSuggestions) : ""}
        ${showMoveOption && upgradeState.finalized ? renderFinalPolishedReveal(upgradeState, upgradeSuggestions, latestFeedback, session) : ""}
        ${showEditor ? `
          <button id="submitImproveButton" class="primary-button journey-primary-button" type="button">
            ${(escalation.level || 1) > 1 ? "Try Again" : "Add This Detail"}
          </button>
        ` : ""}
      </section>
    </div>
  `;

  document.getElementById("submitImproveButton")?.addEventListener("click", async () => {
    const detailText = document.getElementById("learnerImproveInput").value.trim();
    if (!detailText) {
      showToast("Add one detail first.", true);
      return;
    }
    const baseText = cleanUiText(document.getElementById("evolvingParagraph")?.textContent || rewriteDraft);
    const improvedText = mergeParagraphDetail(baseText, detailText);
    const preview = document.getElementById("liveMergePreview");
    preview?.classList.add("merge-insert-glow");
    showCoverageLayerSuccess(coverageLayers.currentLayer);
    await new Promise((resolve) => window.setTimeout(resolve, 420));
    requestImprovementFeedback(session, state.sessionFlow.explanation, improvedText);
  });
  document.getElementById("upgradeMyArticulationButton")?.addEventListener("click", () => {
    state.sessionFlow.coverageCompleteAcknowledged = true;
    renderImproveStep(session);
  });
  document.getElementById("moveToNextCoverageLayerButton")?.addEventListener("click", () => {
    moveToNextCoverageLayer();
  });
  document.getElementById("finishArticulationUpgradeButton")?.addEventListener("click", () => {
    finalizeArticulationUpgrade(upgradeState, upgradeSuggestions);
  });
  els.sessionDetailPanel.querySelectorAll("[data-apply-upgrade]").forEach((button) => {
    button.addEventListener("click", () => {
      applyArticulationUpgrade(button.dataset.applyUpgrade || "", upgradeSuggestions);
      playTapAnimation(button);
    });
  });
  els.sessionDetailPanel.querySelectorAll("[data-skip-upgrade]").forEach((button) => {
    button.addEventListener("click", () => {
      skipArticulationUpgrade(button.dataset.skipUpgrade || "", upgradeSuggestions);
      playTapAnimation(button);
    });
  });
  document.getElementById("articulationUpgradeInput")?.addEventListener("input", (event) => {
    const upgradeState = state.sessionFlow.articulationUpgrade;
    if (upgradeState) {
      upgradeState.answer = event.target.value;
      upgradeState.justApplied = false;
    }
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
  els.sessionDetailPanel.querySelectorAll("[data-stuck-upgrade-old]").forEach((button) => {
    button.addEventListener("click", () => {
      applyStuckLayerUpgrade(button.dataset.stuckUpgradeOld || "", button.dataset.stuckUpgradeNew || "");
      playTapAnimation(button);
      button.classList.add("selected");
    });
  });
  els.sessionDetailPanel.querySelectorAll(".inline-upgrade-target").forEach((target) => {
    target.addEventListener("click", (event) => {
      if (event.target.closest(".inline-upgrade-popover")) {
        return;
      }
      event.preventDefault();
      openInlineUpgradePopover(target);
    });
    target.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      openInlineUpgradePopover(target);
    });
  });
  window.setTimeout(() => {
    const detailInput = document.getElementById("learnerImproveInput");
    detailInput?.focus();
    detailInput?.addEventListener("input", () => updateLiveMergePreview(rewriteDraft));
    document.getElementById("editEvolvingParagraphButton")?.addEventListener("click", () => {
      enableEvolvingParagraphEdit(rewriteDraft);
    });
    positionInlineUpgradePopovers();
  }, 50);
}

function openInlineUpgradePopover(target) {
  els.sessionDetailPanel.querySelectorAll(".inline-upgrade-target.active").forEach((item) => {
    if (item !== target) {
      item.classList.remove("active", "show-below", "align-left", "align-right");
      item.setAttribute("aria-expanded", "false");
    }
  });
  target.classList.toggle("active");
  target.setAttribute("aria-expanded", target.classList.contains("active") ? "true" : "false");
  if (target.classList.contains("active")) {
    positionInlineUpgradePopover(target);
    window.setTimeout(() => {
      document.addEventListener("click", closeInlineUpgradePopoverOnOutside, { once: true });
    }, 0);
  }
}

function closeInlineUpgradePopoverOnOutside(event) {
  if (event.target.closest?.(".inline-upgrade-target")) {
    document.addEventListener("click", closeInlineUpgradePopoverOnOutside, { once: true });
    return;
  }
  els.sessionDetailPanel?.querySelectorAll(".inline-upgrade-target.active").forEach((item) => {
    item.classList.remove("active", "show-below", "align-left", "align-right");
    item.setAttribute("aria-expanded", "false");
  });
}

function positionInlineUpgradePopovers() {
  els.sessionDetailPanel.querySelectorAll(".inline-upgrade-target.active").forEach(positionInlineUpgradePopover);
}

function positionInlineUpgradePopover(target) {
  const popover = target.querySelector(".inline-upgrade-popover");
  const container = target.closest(".inline-upgrade-answer");
  if (!popover || !container) return;
  target.classList.remove("show-below", "align-left", "align-right");
  let rect = popover.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  if (rect.top < containerRect.top + 6 || rect.top < 8) {
    target.classList.add("show-below");
    rect = popover.getBoundingClientRect();
  }
  if (rect.left < containerRect.left + 6 || rect.left < 8) {
    target.classList.add("align-left");
  } else if (rect.right > containerRect.right - 6 || rect.right > window.innerWidth - 8) {
    target.classList.add("align-right");
  }
}

function renderImproveEditor({ rewriteDraft, currentFocus, hintGroups, articulation, escalation = {}, session = {}, latestText = "", latestFeedback = {} }) {
  const focus = buildLayerFocusDisplay(articulation?.currentLayer, currentFocus, escalation);
  const supportActive = (escalation.level || 1) > 1;
  const hints = supportActive
    ? progressiveSupportHints(hintGroups, escalation, currentFocus).slice(0, 6)
    : focusedMiniHints(hintGroups).slice(0, 6);
  const nextLayer = nextCoverageLayer(articulation);
  const originalAttempt = (state.sessionFlow.attempts || [])[0]?.text || state.sessionFlow.explanation || latestText || "";
  return `
    ${renderTinyCoverageProgress(articulation)}
    <details class="original-attempt-collapse coach-reveal" ${coachRevealStyle(0)}>
      <summary>
        <span aria-hidden="true">♙</span>
        <strong>Your original attempt</strong>
      </summary>
      <p>${escapeHtml(originalAttempt)}</p>
    </details>

    ${supportActive ? renderProgressiveSupportBanner(escalation, currentFocus) : ""}

    <section class="evolving-paragraph-section coach-reveal" ${coachRevealStyle(supportActive ? 2 : 1)}>
      <div class="coverage-section-head">
        <h3>Your evolving description</h3>
        <span aria-hidden="true">🔊</span>
      </div>
      <div id="evolvingParagraph" class="evolving-paragraph-card" tabindex="0">
        ${renderEvolvingParagraphMarkup(rewriteDraft, latestFeedback, session)}
      </div>
      <button id="editEvolvingParagraphButton" class="edit-paragraph-button" type="button">✎ Edit paragraph</button>
    </section>

    <section class="single-focus-card coach-reveal" ${coachRevealStyle(2)}>
      <div class="single-focus-icon" aria-hidden="true">${escapeHtml(focusVisualIcon(articulation?.currentLayer, focus.title))}</div>
      <div>
        <span>Current focus</span>
        <h4>${escapeHtml(cleanFocusTitle(focus.title))}</h4>
        <p>${escapeHtml(progressiveSupportHelper(focus, escalation, currentFocus) || "Add one more clear detail.")}</p>
        ${nextLayer ? `<small>Next: ${escapeHtml(shortFocusPreview(nextLayer))}</small>` : ""}
      </div>
      <span class="single-focus-arrow" aria-hidden="true">›</span>
    </section>

    ${hints.length ? `
      <div class="coverage-mini-hints coach-reveal" ${coachRevealStyle(3)}>
        ${hints.map((hint) => `<button class="phrase-chip phrase-insert-chip improve-hint-chip" type="button" data-insert-phrase="${escapeHtml(hint)}">${escapeHtml(hint)}</button>`).join("")}
      </div>
    ` : ""}

    <section class="continuation-input-section coach-reveal" ${coachRevealStyle(4)}>
      <h4>Continue your description</h4>
      <div class="continuation-input-wrap">
        <textarea
          id="learnerImproveInput"
          class="continuation-input"
          rows="2"
          maxlength="260"
          placeholder="Add one more detail..."
        ></textarea>
        <span class="continuation-mic" aria-hidden="true">🎙</span>
      </div>
    </section>

    <section class="live-merge-section coach-reveal" ${coachRevealStyle(5)}>
      <h4><span aria-hidden="true">◉</span> Live preview</h4>
      <div id="liveMergePreview" class="live-merge-card">
        ${renderEvolvingParagraphMarkup(rewriteDraft, latestFeedback, session)}
      </div>
    </section>
  `;
}

function renderProgressiveSupportBanner(escalation = {}, currentFocus = "") {
  const level = escalation.level || 1;
  const message = cleanUiText(escalation.message) || progressiveSupportTone(level, currentFocus);
  return `
    <section class="progressive-support-banner coach-reveal" ${coachRevealStyle(1)}>
      <span aria-hidden="true">✦</span>
      <div>
        <strong>Let's make this easier.</strong>
        <p>${escapeHtml(message)}</p>
      </div>
    </section>
  `;
}

function progressiveSupportTone(level, currentFocus = "") {
  const focus = cleanUiText(currentFocus);
  if (level >= 5) return focus || "Try one short supported sentence.";
  if (level >= 4) return "Use the sentence frame and fill in the blanks.";
  if (level >= 3) return "Choose one option that matches what you see.";
  return focus || "Look closely at one visible clue.";
}

function progressiveSupportHelper(focus = {}, escalation = {}, currentFocus = "") {
  const level = escalation.level || 1;
  const guidance = cleanUiText(currentFocus);
  if (level >= 2 && guidance) {
    return guidance.replace(/^👀\s*/u, "Look closely: ");
  }
  return focus.microPrompt || focus.support || "";
}

function progressiveSupportHints(hintGroups = [], escalation = {}, currentFocus = "") {
  const level = escalation.level || 1;
  const focus = cleanUiText(currentFocus);
  const baseHints = focusedMiniHints(hintGroups);
  const promptHints = [];
  if (level >= 3 && focus.includes(":")) {
    promptHints.push(...focus.split(":").slice(1).join(":").replace(/[?.]/g, "").split(/,|\bor\b/));
  }
  if (level >= 4 && focus.includes("___")) {
    promptHints.unshift(focus);
  }
  if (level >= 5 && /^try mentioning/i.test(focus)) {
    promptHints.unshift(focus.replace(/^try mentioning that\s+/i, "").replace(/^try mentioning\s+/i, ""));
  }
  return uniqueWritingHints([...promptHints, ...baseHints])
    .map((item) => cleanUiText(item))
    .filter((item) => item && item.length <= 90)
    .slice(0, 6);
}

function evolvingParagraphText(latestText, latestFeedback = {}) {
  return cleanUiText(
    latestFeedback?.initial_attempt_feedback?.covered_enhancement
    || latestFeedback?.better_version
    || latestText
  );
}

function mergeParagraphDetail(base, detail) {
  const cleanBase = cleanUiText(base).replace(/\s+$/g, "");
  const cleanDetail = cleanUiText(detail);
  if (!cleanBase) return ensureSentencePunctuation(cleanDetail);
  if (!cleanDetail) return ensureSentencePunctuation(cleanBase);
  const separator = /[.!?]$/.test(cleanBase) ? " " : ". ";
  return `${cleanBase}${separator}${ensureSentencePunctuation(cleanDetail)}`.trim();
}

function ensureSentencePunctuation(value) {
  const text = cleanUiText(value);
  return text && !/[.!?]$/.test(text) ? `${text}.` : text;
}

function renderEvolvingParagraphMarkup(text, feedback = {}, session = {}) {
  const raw = cleanUiText(text);
  const highlightTerms = uniqueWritingHints([
    ...cleanUiList(feedback?.initial_attempt_feedback?.reusable_language?.phrases || [], 5),
    ...cleanUiList(feedback?.initial_attempt_feedback?.reusable_language?.collocations || [], 5),
    ...cleanUiList(feedback?.initial_attempt_feedback?.reusable_language?.positioning_language || [], 4),
    ...((session?.analysis?.phrases || []).map((item) => item?.phrase || item)),
  ]).filter((item) => item && raw.toLowerCase().includes(item.toLowerCase()));
  return highlightTextTerms(raw, highlightTerms.slice(0, 5), "evolving-ai-highlight");
}

function highlightTextTerms(text, terms, className) {
  const raw = String(text || "");
  if (!raw || !terms?.length) return escapeHtml(raw);
  const spans = [];
  const lowered = raw.toLowerCase();
  terms
    .slice()
    .sort((a, b) => b.length - a.length)
    .forEach((term) => {
      const needle = String(term || "").toLowerCase();
      const start = lowered.indexOf(needle);
      if (start < 0) return;
      const end = start + needle.length;
      if (spans.some((span) => start < span.end && end > span.start)) return;
      spans.push({ start, end });
    });
  spans.sort((a, b) => a.start - b.start);
  let cursor = 0;
  let html = "";
  spans.forEach((span) => {
    html += escapeHtml(raw.slice(cursor, span.start));
    html += `<mark class="${className}">${escapeHtml(raw.slice(span.start, span.end))}</mark>`;
    cursor = span.end;
  });
  html += escapeHtml(raw.slice(cursor));
  return html;
}

function focusedMiniHints(hintGroups = []) {
  return uniqueWritingHints(
    simplifyHintGroups(hintGroups)
      .flatMap((group) => group.items || [])
      .filter((item) => cleanUiText(item).split(/\s+/).length <= 6)
  ).slice(0, 6);
}

function nextCoverageLayer(articulation) {
  const layers = articulation?.layers || [];
  const currentIndex = Number(articulation?.currentIndex ?? -1);
  return layers.find((layer, index) => index > currentIndex && !layer.completed) || null;
}

function renderTinyCoverageProgress(articulation) {
  const total = Math.max(1, articulation?.layers?.length || 1);
  const current = Math.max(1, (articulation?.currentIndex || 0) + 1);
  return `
    <div class="tiny-coverage-progress">
      <span>Focus ${current} of ${total}</span>
      <div>
        ${Array.from({ length: Math.min(total, 6) }, (_, index) => `<i class="${index + 1 === current ? "active" : index + 1 < current ? "done" : ""}"></i>`).join("")}
      </div>
    </div>
  `;
}

function cleanFocusTitle(title) {
  return cleanUiText(title)
    .replace(/^[^\w]+/, "")
    .replace(/\?$/g, "")
    .replace(/^(Add detail about|Add more detail about|Describe|Explain the appearance of)\s+/i, "")
    || "One clear detail";
}

function focusVisualIcon(layer, title = "") {
  const text = normalizeClientText(`${layer?.category || ""} ${layer?.visualFocus || ""} ${layer?.label || ""} ${title}`);
  if (/\b(building|apartment|residential|architecture)\b/.test(text)) return "🏢";
  if (/\b(tree|plant|greenery|leaf|branches)\b/.test(text)) return "🌿";
  if (/\b(light|shadow|shade|sun)\b/.test(text)) return "☀️";
  if (/\b(road|street|vehicle|car|motorcycle)\b/.test(text)) return "🛣️";
  return "✦";
}

function updateLiveMergePreview(baseText) {
  const preview = document.getElementById("liveMergePreview");
  const input = document.getElementById("learnerImproveInput");
  if (!preview || !input) return;
  const editableBase = cleanUiText(document.getElementById("evolvingParagraph")?.textContent || baseText);
  const merged = mergeParagraphDetail(editableBase, input.value);
  const highlightTerms = [...document.querySelectorAll("#evolvingParagraph mark")]
    .map((item) => cleanUiText(item.textContent))
    .filter(Boolean);
  preview.innerHTML = highlightTextTerms(merged, highlightTerms, "evolving-ai-highlight");
}

function enableEvolvingParagraphEdit(originalText) {
  const paragraph = document.getElementById("evolvingParagraph");
  if (!paragraph) return;
  paragraph.setAttribute("contenteditable", "true");
  paragraph.classList.add("editable");
  paragraph.addEventListener("input", () => updateLiveMergePreview(originalText));
  paragraph.focus();
  const range = document.createRange();
  range.selectNodeContents(paragraph);
  range.collapse(false);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function showCoverageLayerSuccess(layer) {
  const label = cleanFocusTitle(shortFocusPreview(layer) || layer?.label || "Detail");
  showToast(`✓ ${label} added`);
  awardLocalXp(10);
}

function renderCoverageCompleteStage(feedback = {}, session = {}, coverageLayers = {}) {
  const items = coverageCompleteChecklistItems(feedback, session, coverageLayers);
  return `
    <section class="coverage-complete-stage coach-reveal" ${coachRevealStyle(0)}>
      <div class="coverage-success-hero">
        <div class="success-sparkles" aria-hidden="true">
          <i></i><i></i><i></i><i></i><i></i><i></i>
        </div>
        <div class="success-checkmark" aria-hidden="true">✓</div>
        <h3><span aria-hidden="true">✓</span> Scene covered</h3>
        <p>You described the important parts of the image.</p>
      </div>

      <section class="coverage-checklist-card">
        <h4>What you covered</h4>
        <div class="coverage-checklist-items">
          ${items.map((item) => `
            <div class="coverage-check-item">
              <span class="coverage-check-icon" aria-hidden="true">${escapeHtml(item.icon)}</span>
              <strong>${escapeHtml(item.label)}</strong>
              <span class="coverage-check-done" aria-hidden="true">✓</span>
            </div>
          `).join("")}
        </div>
      </section>

      <section class="coverage-transition-card">
        <span aria-hidden="true">✦</span>
        <p>Great job! Now let's make it <strong>sound more natural.</strong></p>
      </section>

      <button id="upgradeMyArticulationButton" class="primary-button journey-primary-button coverage-complete-cta" type="button">
        ✦ Upgrade My Articulation
      </button>
    </section>
  `;
}

function coverageCompleteChecklistItems(feedback = {}, session = {}, coverageLayers = {}) {
  const coverageParts = Array.isArray(feedback?.coverage?.imageParts) ? feedback.coverage.imageParts : [];
  const partLabels = coverageParts
    .filter((part) => isCoveragePartCovered(part) || coverageLayers?.complete)
    .map((part) => cleanUiText(part?.name || part?.description || part?.type || ""))
    .filter(Boolean);
  const analysis = session?.analysis || {};
  const fallbackLabels = [
    ...((analysis.objects || []).map((item) => cleanUiText(item?.name || item))),
    analysis.environment,
    ...(analysis.environment_details || []),
    primaryAtmosphereHint(analysis),
  ].filter(Boolean);
  const labels = uniqueWritingHints([...partLabels, ...fallbackLabels])
    .map(coverageChecklistLabel)
    .filter(Boolean);
  const preferred = prioritizeCoverageChecklist(labels);
  return preferred.slice(0, 5).map((label) => ({
    label,
    icon: coverageChecklistIcon(label),
  }));
}

function coverageChecklistLabel(value) {
  const text = normalizeClientText(value);
  if (!text) return "";
  if (/\b(building|apartment|house|architecture|residential)\b/.test(text)) return "Buildings";
  if (/\b(tree|greenery|plant|leaf|leaves|branches|bush)\b/.test(text)) return "Greenery";
  if (/\b(road|street|lane|path|sidewalk)\b/.test(text)) return "Road";
  if (/\b(atmosphere|mood|shade|shadow|sunlight|light|peaceful|busy|quiet|calm)\b/.test(text)) return "Atmosphere";
  if (/\b(background|setting|environment|place|area)\b/.test(text)) return "Setting";
  if (/\b(vehicle|car|motorcycle|bike|traffic)\b/.test(text)) return "Vehicles";
  if (/\b(person|people|man|woman|child)\b/.test(text)) return "People";
  if (/\b(composition|foreground|background|position|layout)\b/.test(text)) return "Composition";
  return titleCaseWords(cleanUiText(value).split(/\s+/).slice(0, 3).join(" "));
}

function titleCaseWords(value) {
  return cleanUiText(value).replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function prioritizeCoverageChecklist(labels = []) {
  const unique = uniqueWritingHints(labels);
  const order = ["Buildings", "Greenery", "Road", "Atmosphere", "Setting", "Vehicles", "People", "Composition"];
  return [
    ...order.filter((item) => unique.includes(item)),
    ...unique.filter((item) => !order.includes(item)),
  ];
}

function coverageChecklistIcon(label = "") {
  const text = normalizeClientText(label);
  if (text.includes("building")) return "🏢";
  if (text.includes("greenery") || text.includes("tree")) return "🌳";
  if (text.includes("road") || text.includes("street")) return "🛣️";
  if (text.includes("atmosphere") || text.includes("light")) return "☁️";
  if (text.includes("vehicle")) return "🚗";
  if (text.includes("people")) return "👤";
  if (text.includes("composition")) return "◐";
  return "✓";
}

function renderMoveForwardLayerOption(coverageLayers, escalation = {}) {
  const layer = coverageLayers?.currentLayer;
  if (!layer || !escalation.canMoveForward) {
    return "";
  }
  const remaining = (coverageLayers.layers || []).filter((item) => !item.completed);
  const hasNext = remaining.length > 1;
  return `
    <section class="layer-support-message move-layer-message coach-reveal" ${coachRevealStyle(1)}>
      <span>${escapeHtml(escalation.moveForwardMessage || "Good effort. You can keep trying this focus or move to the next visual area.")}</span>
      <button id="moveToNextCoverageLayerButton" class="text-button" type="button">
        ${hasNext ? "Move to next visual area" : "Continue to polish"}
      </button>
    </section>
  `;
}

function renderStuckLayerUpgrade(upgrade) {
  if (!upgrade) return "";
  return `
    <section class="layer-upgrade-nudge coach-reveal" ${coachRevealStyle(2)}>
      <span class="field-label">Try a quick upgrade</span>
      <div class="layer-upgrade-row">
        <span class="layer-upgrade-before">${escapeHtml(upgrade.oldText)}</span>
        <span aria-hidden="true">→</span>
        <button class="phrase-chip phrase-insert-chip improve-hint-chip" type="button" data-stuck-upgrade-old="${escapeHtml(upgrade.oldText)}" data-stuck-upgrade-new="${escapeHtml(upgrade.newText)}">
          ${escapeHtml(upgrade.newText)}
        </button>
      </div>
    </section>
  `;
}

function renderLayerSupportMessage(escalation = {}) {
  const message = cleanUiText(escalation.message);
  if (!message || (escalation.level || 1) <= 1) {
    return "";
  }
  return `<div class="layer-support-message">${escapeHtml(message)}</div>`;
}

function moveToNextCoverageLayer() {
  const layer = state.sessionFlow.coverageLayers?.currentLayer;
  if (!layer) {
    return;
  }
  state.sessionFlow.skippedCoverageLayers = uniqueWritingHints([
    ...(state.sessionFlow.skippedCoverageLayers || []),
    layer.key,
  ]);
  showToast("Good effort — moving to the next visual area.");
  renderSessionStep("improve", { stage: LEARNING_STAGES.COVERAGE_LAYERS });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderArticulationUpgradeStage(upgradeState, suggestions) {
  const answer = upgradeState.answer || upgradeState.original || "";
  const handled = new Set([...(upgradeState.applied || []), ...(upgradeState.skipped || [])]);
  const activeSuggestions = suggestions.filter((item) => !handled.has(item.id)).slice(0, 5);
  const annotated = buildInlineUpgradeMarkup(answer, activeSuggestions, upgradeState.lastAppliedNewText || "");
  const originalAttempt = (state.sessionFlow.attempts || [])[0]?.text || upgradeState.original || "";
  const upgradeTags = richnessUpgradeTypes(activeSuggestions.length ? activeSuggestions : suggestions).slice(0, 5);
  return `
    <section class="articulation-polish-stage coach-reveal" ${coachRevealStyle(0)}>
      <details class="original-attempt-collapse polish-original-attempt">
        <summary>
          <span aria-hidden="true">♙</span>
          <strong>Your original attempt</strong>
        </summary>
        <p>${escapeHtml(originalAttempt)}</p>
      </details>

      <div class="polish-stage-heading">
        <div>
          <h3>Upgrade your articulation</h3>
          <p>Tap highlighted phrases to improve your description.</p>
        </div>
        <span aria-hidden="true">✦</span>
      </div>

      <section class="articulation-upgrade-card richness-upgrade-card">
        <div class="coverage-section-head polish-paragraph-head">
          <h4>Your evolving description</h4>
          <span aria-hidden="true">🔊</span>
        </div>
        <div class="inline-upgrade-answer ${upgradeState.justApplied ? "replacement-flash" : ""}" aria-live="polite">
          ${annotated.markup || escapeHtml(answer)}
        </div>

        <div class="polish-focus-panel">
          <div class="single-focus-icon" aria-hidden="true">🪄</div>
          <div>
            <strong>Polish focus</strong>
            <p>We'll improve flow, word choice and clarity.</p>
          </div>
        </div>

        ${upgradeTags.length ? `
          <div class="polish-upgrade-tags" aria-label="What we'll improve">
            ${upgradeTags.map((tag) => `<span>${escapeHtml(polishTagIcon(tag))} ${escapeHtml(tag)}</span>`).join("")}
          </div>
        ` : ""}

        ${
          annotated.count
            ? `<p class="muted inline-upgrade-help">${annotated.count} optional upgrade${pluralize(annotated.count)}. Apply only the ones you want.</p>`
            : `<p class="polish-complete-note"><span aria-hidden="true">✓</span> You handled the available upgrades. Ready for the reveal.</p>`
        }
      </section>

      <button id="finishArticulationUpgradeButton" class="primary-button journey-primary-button" type="button">
        ✦ Reveal Polished Version
      </button>
    </section>
  `;
}

function richnessUpgradeTypes(suggestions = []) {
  const labels = {
    visual_quality: "Visual quality",
    atmosphere: "Atmosphere",
    sentence_flow: "Sentence flow",
    vocabulary: "Stronger vocabulary",
    verb: "Better verbs",
    positioning: "Positioning",
  };
  return uniqueWritingHints((suggestions || []).map((item) => labels[item.type] || upgradeTypeLabel(item.type))).slice(0, 5);
}

function polishTagIcon(label = "") {
  const text = normalizeClientText(label);
  if (text.includes("visual")) return "🌿";
  if (text.includes("atmosphere")) return "✨";
  if (text.includes("position")) return "📍";
  if (text.includes("sentence") || text.includes("flow")) return "🧠";
  if (text.includes("vocabulary")) return "🎨";
  return "✦";
}

function buildInlineUpgradeMarkup(answer, suggestions, appliedText = "") {
  const text = String(answer || "");
  if (!text) {
    return { markup: "", count: 0 };
  }
  const targets = nonOverlappingUpgradeTargets(text, suggestions);
  const appliedTarget = buildAppliedUpgradeTarget(text, appliedText, targets);
  const allTargets = [...targets, ...(appliedTarget ? [appliedTarget] : [])].sort((a, b) => a.start - b.start);
  if (!allTargets.length) return { markup: escapeHtml(text), count: 0 };

  let cursor = 0;
  const pieces = [];
  allTargets.forEach((target) => {
    if (target.applied) {
      pieces.push(escapeHtml(text.slice(cursor, target.start)));
      pieces.push(`<mark class="inline-upgrade-applied">${escapeHtml(text.slice(target.start, target.end))}</mark>`);
      cursor = target.end;
      return;
    }
    const item = target.item;
    pieces.push(escapeHtml(text.slice(cursor, target.start)));
    pieces.push(`
      <span
        class="inline-upgrade-target"
        data-upgrade-id="${escapeHtml(item.id)}"
        role="button"
        tabindex="0"
        aria-haspopup="dialog"
        aria-expanded="false"
        aria-label="Show upgrade for ${escapeHtml(text.slice(target.start, target.end))}"
      >
        <span class="inline-upgrade-popover">
          <strong>${escapeHtml(item.newText)}</strong>
          <small>${escapeHtml(upgradeTypeReason(item.type))}</small>
          <button class="inline-upgrade-choice" type="button" data-apply-upgrade="${escapeHtml(item.id)}">Apply</button>
          <button class="inline-upgrade-dismiss" type="button" data-skip-upgrade="${escapeHtml(item.id)}" aria-label="Dismiss upgrade">×</button>
        </span>
        <span class="inline-upgrade-original">${escapeHtml(text.slice(target.start, target.end))}</span>
      </span>
    `);
    cursor = target.end;
  });
  pieces.push(escapeHtml(text.slice(cursor)));
  return {
    markup: pieces.join(""),
    count: targets.length,
  };
}

function buildAppliedUpgradeTarget(text, appliedText, activeTargets = []) {
  const phrase = cleanUiText(appliedText);
  if (!phrase) return null;
  const start = text.toLowerCase().indexOf(phrase.toLowerCase());
  if (start < 0) return null;
  const end = start + phrase.length;
  if (activeTargets.some((target) => start < target.end && end > target.start)) return null;
  return { start, end, applied: true };
}

function nonOverlappingUpgradeTargets(answer, suggestions) {
  const source = String(answer || "");
  const sourceKey = source.toLowerCase();
  const occupied = [];
  return (suggestions || [])
    .map((item) => {
      const oldText = cleanUiText(item.oldText);
      if (!oldText) {
        return null;
      }
      const start = sourceKey.indexOf(oldText.toLowerCase());
      if (start < 0) {
        return null;
      }
      const end = start + oldText.length;
      return { item, start, end, length: oldText.length };
    })
    .filter(Boolean)
    .sort((a, b) => a.start - b.start || a.length - b.length)
    .filter((target) => {
      const overlaps = occupied.some((range) => target.start < range.end && target.end > range.start);
      if (overlaps) {
        return false;
      }
      occupied.push({ start: target.start, end: target.end });
      return true;
    })
    .slice(0, 5);
}

function renderFinalPolishedReveal(upgradeState, suggestions = [], feedback = {}, session = {}) {
  const firstAttempt = (state.sessionFlow.attempts || [])[0]?.text || upgradeState.original || "";
  const finalAnswer = upgradeState.answer || upgradeState.original || firstAttempt;
  const learnedLanguage = finalRevealReusableLanguage(upgradeState, suggestions, feedback, session);
  const reward = finalRevealRewardSummary(upgradeState, learnedLanguage, feedback, session, finalAnswer);
  return `
    <section class="final-reveal-stage coach-reveal" ${coachRevealStyle(0)}>
      <div class="final-reveal-hero">
        <div class="success-sparkles final-sparkles" aria-hidden="true">
          <i></i><i></i><i></i><i></i><i></i><i></i>
        </div>
        <div class="final-flame-badge" aria-hidden="true">🔥</div>
        <h3>🔥 Your description evolved</h3>
        <p>You turned a simple start into a clear, natural description.</p>
      </div>

      <div class="final-comparison-stack">
        <section class="final-before-card">
          <span class="final-section-pill">Before</span>
          <div>
            <small>Your first attempt</small>
            <p>${escapeHtml(firstAttempt)}</p>
          </div>
          <span class="final-card-icon" aria-hidden="true">♙</span>
        </section>

        <div class="final-down-arrow" aria-hidden="true">↓</div>

        <section class="final-after-card">
          <div class="final-after-head">
            <span class="final-section-pill after">After ✦</span>
            <span class="final-card-icon" aria-hidden="true">🔊</span>
          </div>
          <small>Your final description</small>
          <p>${highlightTextTerms(finalAnswer, learnedLanguage, "final-learned-highlight")}</p>
          ${
            learnedLanguage.length
              ? `
                <div class="final-language-box">
                  <span aria-hidden="true">📖</span>
                  <div>
                    <strong>Reusable language you learned</strong>
                    <div class="mini-suggestion-row">
                      ${learnedLanguage.map((item) => `<span class="phrase-chip suggested">${escapeHtml(item)}</span>`).join("")}
                    </div>
                  </div>
                </div>
              `
              : ""
          }
        </section>
      </div>

      <section class="final-reward-summary" aria-label="Reward summary">
        <div>
          <span aria-hidden="true">✦</span>
          <strong>+${reward.xp} XP</strong>
          <small>Earned</small>
        </div>
        <div>
          <span aria-hidden="true">🎯</span>
          <strong>${reward.focuses}</strong>
          <small>Focuses Completed</small>
        </div>
        <div>
          <span aria-hidden="true">💬</span>
          <strong>${reward.phrases}</strong>
          <small>Phrases Learned</small>
        </div>
      </section>

      <button id="continueToQuizButton" class="primary-button journey-primary-button final-quiz-cta" type="button">
        ✦ Continue to Quiz
      </button>
    </section>
  `;
}

function finalRevealRewardSummary(upgradeState = {}, learnedLanguage = [], feedback = {}, session = {}, finalAnswer = "") {
  const focusCount = finalRevealFocusCount(feedback, session, finalAnswer);
  const phraseCount = learnedLanguage.length;
  const coverageXp = Math.max(0, focusCount * 10 + (state.sessionFlow.allLayersBonusAwarded ? 20 : 0));
  const polishXp = Number(upgradeState.xp || 0);
  return {
    xp: Math.max(polishXp + coverageXp, polishXp, 0),
    focuses: focusCount,
    phrases: phraseCount,
  };
}

function finalRevealFocusCount(feedback = {}, session = {}, finalAnswer = "") {
  const coverageParts = Array.isArray(feedback?.coverage?.imageParts) ? feedback.coverage.imageParts : [];
  const coveredParts = coverageParts.filter((part) => isCoveragePartCovered(part)).length;
  const rewardedLayers = (state.sessionFlow.layerRewards || []).length;
  const checklist = coverageCompleteChecklistItems(feedback, session, { complete: true }).length;
  const sentenceCount = cleanUiText(finalAnswer).split(/[.!?]+/).filter((item) => item.trim()).length;
  return Math.max(coveredParts, rewardedLayers, checklist, Math.min(5, sentenceCount));
}

function finalRevealReusableLanguage(upgradeState = {}, suggestions = [], feedback = {}, session = {}) {
  const applied = new Set(upgradeState.applied || []);
  const appliedLanguage = (suggestions || [])
    .filter((item) => applied.has(item.id))
    .map((item) => item.newText);
  const analysis = session?.analysis || {};
  const initialReusable = feedback?.initial_attempt_feedback?.reusable_language || {};
  return uniqueWritingHints([
    ...appliedLanguage,
    ...cleanUiList(feedback?.phrase_usage?.used || [], 3),
    ...cleanUiList(feedback?.phrase_usage?.suggested || [], 3),
    ...cleanUiList(initialReusable.phrases || [], 3),
    ...cleanUiList(initialReusable.collocations || [], 3),
    ...cleanUiList(initialReusable.positioning_language || [], 2),
    ...((analysis.phrases || []).map((item) => item?.phrase || item)),
    ...((analysis.reusable_language || []).map((item) => item?.text || item?.phrase || item)),
  ])
    .map(cleanUiText)
    .filter((item) => item && item.split(/\s+/).length <= 7)
    .slice(0, 3);
}

function renderArticulationProgress(articulation) {
  const layers = articulation?.layers || [];
  if (!layers.length) {
    return "";
  }
  const total = layers.length;
  const current = Math.max(0, articulation.currentIndex);
  const activeIndex = current >= 0 ? current : total - 1;
  const currentLayer = layers[activeIndex];
  return `
    <section class="articulation-progress-card coach-reveal" ${coachRevealStyle(0)}>
      <div class="articulation-progress-topline">
        <span>Focus ${Math.min(activeIndex + 1, total)} of ${total}</span>
        <div class="articulation-dot-row" aria-label="Articulation progress">
          ${layers
            .map(
              (layer, index) => `
                <span
                  class="articulation-dot ${layer.completed ? "complete" : index === activeIndex ? "current" : ""}"
                  aria-label="${layer.completed ? "Completed" : index === activeIndex ? "Current focus" : "Upcoming focus"}"
                ></span>
              `
            )
            .join("")}
        </div>
      </div>
      <p class="articulation-current-focus">${escapeHtml(shortFocusPreview(currentLayer))}</p>
    </section>
  `;
}

function renderCoverageLayerProgress(coverageLayers) {
  return renderArticulationProgress(coverageLayers);
}

function buildLayerFocusDisplay(layer, currentFocus, escalation = {}) {
  const title = conciseLayerFocusTitle(layer, currentFocus);
  const guidance = cleanUiText(currentFocus);
  const defaultSupport = supportingLineForLayer(layer);
  return {
    title: `${focusIconForLayer(layer, title)} ${title}`.trim(),
    support: !layer?.dynamic && guidance && normalizeClientText(guidance) !== normalizeClientText(title) && guidance.length <= 110
      ? guidance
      : defaultSupport,
    microPrompt: cleanUiText(layerExpansionPrompt(layer, escalation)) || "Add one clear visual detail.",
  };
}

function focusIconForLayer(layer, title = "") {
  const text = normalizeClientText(`${layer?.category || ""} ${layer?.visualFocus || ""} ${layer?.label || ""} ${title}`);
  if (/\b(flower|petal|blossom)\b/.test(text)) return "🌸";
  if (/\b(tree|trees|greenery|plants|bushes|shrubs|leaves)\b/.test(text)) return "🌿";
  if (/\b(light|lighting|sun|sunlight|shadow|reflection)\b/.test(text)) return "☀️";
  if (/\b(car|vehicle|vehicles|road|traffic|street)\b/.test(text)) return "🚗";
  if (/\b(apartment|architecture|unfinished|construction|structure|building|buildings)\b/.test(text)) return "🏢";
  if (/\b(room|building|roadside|city|street|environment|area)\b/.test(text)) return "🏙";
  if (/\b(texture|fabric|surface)\b/.test(text)) return "🔎";
  return "";
}

function conciseLayerFocusTitle(layer, fallback = "") {
  const category = layer?.category || "";
  const focus = cleanUiText(layer?.visualFocus || layer?.label || fallback)
    .replace(/^describe\s+/i, "")
    .replace(/[.!?]+$/g, "");
  const normalized = normalizeClientText(focus);
  if (category === "lighting" || /\b(light|lighting|sunlight|shadow|reflection)\b/.test(normalized)) {
    return "What stands out about the lighting?";
  }
  if (/\b(flower|petal|blossom)\b/.test(normalized)) {
    return "Explain the flower's appearance";
  }
  if (/\b(tree|trees|shrub|shrubs|leaf|leaves|greenery|plants|bushes)\b/.test(normalized)) {
    return "Add more detail about the greenery";
  }
  if (/\b(car|cars|vehicle|vehicles|bus|road|traffic)\b/.test(normalized)) {
    return category === "environment" ? "Describe the surroundings near the road" : "What stands out about the vehicles?";
  }
  if (/\b(apartment|building|buildings|unfinished|structure|construction|architecture)\b/.test(normalized)) {
    return "Describe the buildings in the background";
  }
  if (/\b(room|desk|window|curtain|wall|floor|table)\b/.test(normalized)) {
    return "Describe how this area looks";
  }
  if (["atmosphere", "condition"].includes(category)) {
    return category === "condition" ? "What condition do you notice?" : "What feeling does the scene create?";
  }
  if (category === "positioning") {
    return "Where does this detail appear?";
  }
  if (category === "texture") {
    return focus ? `What texture do you notice in ${stripLeadingArticle(focus)}?` : "What texture do you notice?";
  }
  if (category === "contrast") {
    return "What stands out visually?";
  }
  if (category === "composition") {
    return "What catches your eye first?";
  }
  if (["movement", "interaction"].includes(category)) {
    return focus ? `What is happening around ${stripLeadingArticle(focus)}?` : "What is happening in this part?";
  }
  if (category === "appearance") {
    return focus ? `Explain the appearance of ${stripLeadingArticle(focus)}` : "Explain the appearance";
  }
  if (category === "environment") {
    return focus ? `Describe the surroundings near ${stripLeadingArticle(focus)}` : "Describe the surroundings nearby";
  }
  return focus ? `Add detail about ${stripLeadingArticle(focus)}` : "Add one clear visual detail";
}

function supportingLineForLayer(layer) {
  const category = layer?.category || "";
  if (category === "positioning") return "Where is it in the scene?";
  if (category === "lighting") return "Describe what the light changes or highlights.";
  if (category === "texture") return "Use a simple texture word if you can.";
  if (category === "contrast") return "Look for what feels different or noticeable.";
  if (category === "composition") return "Say what your eyes notice first.";
  if (["movement", "interaction"].includes(category)) return "Add one clear action or relationship.";
  if (["atmosphere", "condition"].includes(category)) return "Use one simple clue from the image.";
  if (category === "appearance") return "Add color, shape, texture, or size.";
  return "What makes this part of the scene noticeable?";
}

function shortFocusPreview(layer) {
  return conciseLayerFocusTitle(layer).replace(/^(Describe|Add|Add more detail about|What stands out about|Explain|Explain the appearance of)\s+/i, "").replace(/\?$/g, "");
}

function stripLeadingArticle(value) {
  return cleanUiText(value).replace(/^(the|a|an)\s+/i, "");
}

function renderImproveHintsCard(groups) {
  const visibleGroups = simplifyHintGroups(groups);
  if (!visibleGroups.length) {
    return "";
  }
  return `
    <section class="improve-hints-card coach-reveal" ${coachRevealStyle(1)}>
      <h4>Focused hints</h4>
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

function simplifyHintGroups(groups = []) {
  const labelLimits = {
    nouns: 4,
    noun: 4,
    verbs: 3,
    verb: 3,
    details: 4,
    phrases: 4,
    "useful phrases": 5,
    positioning: 4,
    adjectives: 3,
    adjective: 3,
    structures: 3,
    "sentence frame": 1,
    "sentence frames": 3,
    "sentence structure": 3,
  };
  return groups.map((group) => {
    const label = cleanUiText(group.label || "");
    const key = normalizeClientText(label);
    const limit = labelLimits[key] || (key.includes("adjective") ? 2 : key.includes("structure") || key.includes("frame") ? 1 : 3);
    const items = uniqueWritingHints((group.items || []).map((item) => simplifyWritingHint(item, label)).filter(Boolean)).slice(0, limit);
    return { label: normalizeHintLabel(label), items };
  }).filter((group) => group.items.length).slice(0, 3);
}

function normalizeHintLabel(label) {
  const key = normalizeClientText(label);
  if (key.includes("noun")) return "Nouns";
  if (key.includes("verb")) return "Verbs";
  if (key.includes("adjective") || key.includes("choice")) return "Adjectives";
  if (key.includes("structure") || key.includes("frame")) return "Sentence frames";
  if (key.includes("position")) return "Phrases";
  return "Phrases";
}

function simplifyWritingHint(value, label = "") {
  let text = cleanUiText(value)
    .replace(/[.!?]+$/g, "")
    .replace(/^describe\s+/i, "")
    .replace(/^the image shows\s+/i, "")
    .replace(/^there (is|are)\s+/i, "")
    .replace(/\bcovering most of\b.*$/i, "")
    .trim();
  if (!text) return "";
  const key = normalizeClientText(label);
  if (key.includes("noun")) {
    text = nounLikeHint(text);
  } else if (key.includes("verb")) {
    text = verbLikeHint(text);
  } else if (key.includes("adjective") || key.includes("choice")) {
    text = adjectiveLikeHint(text);
  } else if (!key.includes("structure") && !key.includes("frame")) {
    text = phraseLikeHint(text);
  }
  const maxWords = key.includes("structure") || key.includes("frame") ? 12 : 5;
  return text.split(/\s+/).length <= maxWords ? text : "";
}

function nounLikeHint(value) {
  const text = cleanUiText(value);
  const matches = text.match(/\b(apartment buildings|unfinished structure|buildings|structure|construction|architecture|palm trees|trees|bushes|shrubs|greenery|vehicles|cars|road|street|wires|poles|desk|curtain|window|flower|petals|leaves|background|room)\b/gi);
  if (matches?.length) return matches[0].toLowerCase();
  return text.split(/\s+/).slice(0, 3).join(" ");
}

function verbLikeHint(value) {
  const text = normalizeClientText(value);
  const matches = text.match(/\b(stretch|stretching|line|lining|shade|shading|stand|standing|rise|rising|move|moving|pass|passing|parked|cover|covering|surround|surrounding)\b/g);
  return matches?.[0] || "";
}

function adjectiveLikeHint(value) {
  const text = normalizeClientText(value);
  const matches = text.match(/\b(dense|lush|green|bright|dark|soft|dusty|messy|clean|calm|busy|crowded|quiet|blurred|vivid|delicate|tangled|wooden|natural|unfinished|tall|distant|concrete|urban)\b/g);
  return matches?.[0] || "";
}

function phraseLikeHint(value) {
  const text = cleanUiText(value);
  const useful = text.match(/\b(branches stretching over the road|leaves creating shade|greenery along the roadside|trees lining the street|road surface|lane markings|along the roadside|parked motorcycle|moving car|roadside vehicle|tall buildings|concrete walls|apartment buildings in the background|bright daylight|shaded area|sunlight on the road|in the background|behind the greenery|above the road|covered with greenery|lined with trees|in the foreground|under the desk|near the window|beside the road|softly blurred|surrounded by leaves)\b/i);
  if (useful) return useful[0].toLowerCase();
  return text.split(/\s+/).slice(0, 4).join(" ");
}

function buildArticulationState(feedback, session, learnerText = "") {
  const coverage = getProgressiveCoverageState(feedback || {});
  const layers = articulationLayerDefinitions(feedback, session, learnerText).map((layer) => ({
    ...layer,
    completed: Boolean(layer.completed),
    current: false,
  }));
  const currentIndex = layers.findIndex((layer) => !layer.completed);
  if (currentIndex >= 0) {
    layers[currentIndex].current = true;
  }
  return {
    layers,
    currentIndex,
    currentLayer: currentIndex >= 0 ? layers[currentIndex] : null,
    complete: currentIndex === -1 && layers.length > 0,
    coverage,
    imageType: session?.analysis?.image_type || "dynamic",
  };
}

function buildCoverageLayerState(feedback, session, learnerText = "") {
  const coverage = getProgressiveCoverageState(feedback || {});
  const skipped = new Set(state?.sessionFlow?.skippedCoverageLayers || []);
  const allLayers = coverageLayerDefinitions(feedback, session, learnerText);
  const layers = allLayers.filter((layer) => !skipped.has(layer.key)).map((layer) => ({
    ...layer,
    completed: Boolean(layer.completed),
    current: false,
  }));
  const currentIndex = layers.findIndex((layer) => !layer.completed);
  if (currentIndex >= 0) {
    layers[currentIndex].current = true;
  }
  const gate = coverageCompletionGate(feedback, session);
  return {
    layers,
    currentIndex,
    currentLayer: currentIndex >= 0 ? layers[currentIndex] : null,
    complete: gate.complete && (currentIndex === -1 || layers.length === 0),
    coverage,
    gate,
    imageType: session?.analysis?.image_type || "dynamic",
  };
}

function coverageLayerDefinitions(feedback, session, learnerText = "") {
  const normalizedText = normalizeClientText(learnerText);
  const analysis = session?.analysis || {};
  const allTargets = analysisArticulationTargets(analysis);
  const missingAreas = missingVisualAreaLabels(feedback, session);
  if (!missingAreas.length) {
    return [];
  }
  const usedTargetKeys = new Set();
  return missingAreas.map((area, index) => {
    const matched = bestCoverageTargetForMissingArea(area, allTargets, usedTargetKeys);
    const target = matched || synthesizeCoverageTarget(area, index, analysis);
    usedTargetKeys.add(normalizeClientText(`${target.id} ${target.label} ${target.visualFocus}`));
    return {
      ...target,
      key: target.id || `coverage_${index + 1}_${cleanTargetId(area)}`,
      id: target.id || `coverage_${index + 1}_${cleanTargetId(area)}`,
      label: coverageLayerLabel(area, target),
      focusArea: target.visualFocus || area,
      visualFocus: target.visualFocus || area,
      prompt: coverageLayerPrompt(area, target),
      expansionPrompt: target.expansionPrompt || `Keep your answer and add one clear detail about ${area}.`,
      dynamic: true,
      coverageArea: area,
      completed: false,
    };
  }).slice(0, 6);
}

function missingVisualAreaLabels(feedback = {}, session = {}) {
  const coverage = feedback.coverage || {};
  const flow = feedback.learning_flow || {};
  const initial = feedback.initial_attempt_feedback || {};
  const gate = coverageCompletionGate(feedback, session);
  if (gate.complete) {
    return [];
  }
  const currentLabels = [
    ...cleanUiList(flow.missing_visual_areas || [], 8),
    ...cleanUiList(feedback.missing_details || [], 8),
    ...cleanUiList(coverage.missingMajorParts || [], 8),
  ];
  (coverage.imageParts || []).forEach((part) => {
    if (!part || isCoveragePartCovered(part)) {
      return;
    }
    currentLabels.push(cleanUiText(part.name || part.description || part.type || ""));
  });
  const labels = currentLabels.length
    ? currentLabels
    : [
        ...cleanUiList(gate.missingFocuses || [], 8),
        ...cleanUiList(initial.missing_visual_areas || [], 8),
      ];
  return uniqueWritingHints(labels)
    .map((item) => item.replace(/_/g, " "))
    .filter((item) => !/no major visual detail/i.test(item))
    .slice(0, 6);
}

function coverageCompletionGate(feedback = {}, session = {}) {
  const coverage = feedback.coverage || {};
  const progressive = getProgressiveCoverageState(feedback);
  const analysis = session?.analysis || {};
  const coveragePercent = Number(coverage.coveragePercent || coverage.coverageScore || 0);
  const imageParts = Array.isArray(coverage.imageParts) ? coverage.imageParts : [];
  const coveredParts = imageParts.filter(isCoveragePartCovered);
  const relevant = relevantCoverageDimensions(analysis, feedback);
  const missingFocuses = [];
  const hasMainFocus = Boolean(progressive.subjectOk || coveredPartMatches(coveredParts, /main_subject|subject|main_object|person|object/));
  const actionRequired = relevant.action;
  const hasAction = !actionRequired || Boolean(progressive.actionOk || coveredPartMatches(coveredParts, /main_action|action|movement|interaction/));
  const hasSetting = Boolean(progressive.settingOk || coveredPartMatches(coveredParts, /setting|background|environment|context|place/));
  const detailCount = meaningfulDetailCount(coveredParts);
  const hasDetails = detailCount >= (relevant.detailHeavy ? 2 : 1);
  const hasAtmosphere = !relevant.atmosphere || Boolean(coveredPartMatches(coveredParts, /mood|atmosphere|condition|feeling/) || coveragePercent >= 82);
  const hasComposition = !relevant.composition || Boolean(coveredPartMatches(coveredParts, /composition|position|positioning|foreground|layout|lighting|shadow/) || coveragePercent >= 82);
  const naturalEnough = Boolean(progressive.notListOk && (progressive.naturalOk || coveragePercent >= 70));

  if (!hasMainFocus) missingFocuses.push("main visual focus");
  if (!hasAction) missingFocuses.push("main action");
  if (!hasSetting) missingFocuses.push("setting or background");
  if (!hasDetails) missingFocuses.push(relevant.detailHeavy ? "important objects and meaningful details" : "one meaningful visual detail");
  if (!hasAtmosphere) missingFocuses.push("atmosphere or condition");
  if (!hasComposition) missingFocuses.push("composition or positioning");
  if (!naturalEnough) missingFocuses.push("a clear connected sentence");

  const highPriorityMissing = missingFocuses.filter((item) => !/atmosphere|composition|connected sentence/i.test(item));
  const complete = (
    hasMainFocus &&
    hasAction &&
    hasSetting &&
    hasDetails &&
    hasAtmosphere &&
    hasComposition &&
    naturalEnough &&
    coveragePercent >= 68 &&
    highPriorityMissing.length === 0
  );

  return {
    complete,
    missingFocuses: uniqueWritingHints(missingFocuses).slice(0, 5),
    coveragePercent,
    hasMainFocus,
    hasAction,
    hasSetting,
    hasDetails,
    hasAtmosphere,
    hasComposition,
    naturalEnough,
  };
}

function relevantCoverageDimensions(analysis = {}, feedback = {}) {
  const targets = Array.isArray(analysis.articulation_targets) ? analysis.articulation_targets : [];
  const actions = Array.isArray(analysis.actions) ? analysis.actions : [];
  const details = [
    analysis.environment,
    ...(analysis.environment_details || []),
    ...(analysis.visual_zones || []).flatMap((zone) => [
      zone?.zone,
      ...(zone?.elements || []),
      ...(zone?.articulation_opportunities || []),
    ]),
    ...targets.flatMap((target) => [target?.category, target?.label, target?.visual_focus, target?.visualFocus]),
    ...cleanUiList(feedback?.missing_details || feedback?.coverage?.missingMajorParts || [], 6),
  ].map(normalizeClientText).join(" ");
  return {
    action: actions.some((item) => isMeaningfulActionPhrase(item?.phrase || item?.verb || item)),
    atmosphere: /\b(atmosphere|mood|feeling|condition|clean|messy|quiet|busy|calm|crowded|shaded|peaceful)\b/.test(details),
    composition: /\b(composition|position|positioning|foreground|background|lighting|shadow|sunlight|layout|near|behind|beside)\b/.test(details),
    detailHeavy: (analysis.objects || []).length >= 3 || (analysis.environment_details || []).length >= 2,
  };
}

function coveredPartMatches(coveredParts, pattern) {
  return coveredParts.some((part) => pattern.test(normalizeClientText(`${part.type || ""} ${part.name || ""} ${part.description || ""}`)));
}

function meaningfulDetailCount(coveredParts) {
  return coveredParts.filter((part) => {
    const text = normalizeClientText(`${part.type || ""} ${part.name || ""} ${part.description || ""}`);
    return /\b(important|object|foreground|detail|background|setting|environment|vehicle|building|tree|lighting|shadow|condition|atmosphere|composition|position)\b/.test(text);
  }).length;
}

function bestCoverageTargetForMissingArea(area, targets, usedTargetKeys) {
  const areaKey = normalizeClientText(area);
  if (!areaKey) {
    return null;
  }
  const scored = targets
    .filter((target) => !usedTargetKeys.has(normalizeClientText(`${target.id} ${target.label} ${target.visualFocus}`)))
    .map((target) => ({
      target,
      score: coverageTargetMatchScore(areaKey, target),
    }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score);
  return scored[0]?.target || null;
}

function coverageTargetMatchScore(areaKey, target) {
  const targetKey = normalizeClientText([
    target.label,
    target.visualFocus,
    target.category,
    ...(target.hints || []),
    ...(target.evidence || []),
  ].join(" "));
  if (!targetKey) {
    return 0;
  }
  let score = 0;
  if (/\b(action|happening|movement|interaction)\b/.test(areaKey) && ["movement", "interaction"].includes(target.category)) {
    score += 10;
  }
  if (/\b(appearance|look|color|shape|texture)\b/.test(areaKey) && target.category === "appearance") {
    score += 8;
  }
  if (targetKey.includes(areaKey) || areaKey.includes(targetKey)) {
    score += 8;
  }
  const areaTokens = meaningfulCoverageTokens(areaKey);
  const targetTokens = new Set(meaningfulCoverageTokens(targetKey));
  areaTokens.forEach((token) => {
    if (targetTokens.has(token)) {
      score += 3;
    }
  });
  const areaCategory = normalizeTargetCategory(areaKey);
  if (areaCategory && areaCategory === target.category) {
    score += 2;
  }
  return score;
}

function meaningfulCoverageTokens(text) {
  const blocked = new Set(["main", "visual", "area", "detail", "important", "describe", "image", "scene", "the", "and", "with"]);
  return normalizeClientText(text)
    .split(/\s+/)
    .filter((token) => token.length >= 3 && !blocked.has(token));
}

function synthesizeCoverageTarget(area, index, analysis = {}) {
  const focus = cleanUiText(area) || `visual area ${index + 1}`;
  const category = normalizeTargetCategory(focus);
  const pack = focusLanguagePack({ visualFocus: focus, label: focus, category }, analysis);
  return {
    id: `coverage_${index + 1}_${cleanTargetId(focus)}`,
    label: coverageLayerLabel(focus, { category }),
    prompt: coverageLayerPrompt(focus, { category }),
    expansionPrompt: `Keep your answer and add one clear detail about ${focus}.`,
    category,
    visualFocus: focus,
    hints: cleanLayerHints([focus, ...pack.nouns, ...pack.phrases, ...pack.adjectives], 8),
    evidence: cleanLayerHints([focus, ...pack.phrases], 5),
    importance: 0.7,
  };
}

function coverageLayerLabel(area, target = {}) {
  const text = cleanUiText(area).replace(/^the\s+/i, "");
  const key = normalizeClientText(`${text} ${target.category || ""}`);
  if (/\b(tree|trees|greenery|plants|leaves|bushes|shrubs)\b/.test(key)) return "Add more detail about the greenery";
  if (/\b(vehicle|vehicles|car|cars|motorcycle|traffic)\b/.test(key)) return "Describe the vehicles near the road";
  if (/\b(building|buildings|apartment|structure|construction)\b/.test(key)) return "Describe the buildings in the background";
  if (/\b(light|lighting|shadow|shadows|sunlight|shaded)\b/.test(key)) return "Describe the lighting and shadows";
  if (/\b(atmosphere|mood|feeling|quiet|busy|calm)\b/.test(key)) return "Describe the atmosphere of the place";
  if (/\b(road|street|lane)\b/.test(key)) return "Describe the road area";
  return text ? `Add detail about ${text}` : "Add one missing visual area";
}

function coverageLayerPrompt(area, target = {}) {
  const label = coverageLayerLabel(area, target);
  if (label.endsWith("?")) return label;
  return `${label}.`;
}

function completedArticulationLayerKeys(feedback, session, learnerText = "") {
  return coverageLayerDefinitions(feedback, session, learnerText)
    .filter((layer) => layer.completed)
    .map((layer) => layer.key);
}

function awardNewLayerCompletionXp(session, feedback, learnerText = "") {
  const completed = completedArticulationLayerKeys(feedback, session, learnerText);
  const rewarded = new Set(state.sessionFlow.layerRewards || []);
  const newKeys = completed.filter((key) => !rewarded.has(key));
  if (!newKeys.length) {
    return;
  }
  state.sessionFlow.layerRewards = uniqueWritingHints([...rewarded, ...newKeys]);
  const points = newKeys.length * 10;
  awardLocalXp(points);
  showToast(`+${points} XP — ${newKeys.length === 1 ? "Layer completed" : "Layers completed"}`);

  const allKeys = coverageLayerDefinitions(feedback, session, learnerText).map((layer) => layer.key);
  const allComplete = allKeys.length > 0 && allKeys.every((key) => state.sessionFlow.layerRewards.includes(key));
  if (allComplete && !state.sessionFlow.allLayersBonusAwarded) {
    state.sessionFlow.allLayersBonusAwarded = true;
    awardLocalXp(20);
    showToast("+20 XP — All image layers covered");
  }
}

function articulationLayerDefinitions(feedback, session, learnerText = "") {
  const normalizedText = normalizeClientText(learnerText);
  const analysis = session?.analysis || {};
  const targets = analysisArticulationTargets(analysis);
  return targets.map((target, index) => ({
    key: target.id || `target_${index + 1}`,
    label: target.label || target.visualFocus || `Target ${index + 1}`,
    focusArea: target.visualFocus || target.label || target.category || "image detail",
    category: target.category || "detail",
    prompt: target.prompt,
    expansionPrompt: target.expansionPrompt,
    visualFocus: target.visualFocus,
    evidence: target.evidence,
    hints: target.hints,
    dynamic: true,
    completed: dynamicTargetCompleted(target, feedback, analysis, normalizedText),
  }));
}

function analysisArticulationTargets(analysis = {}) {
  const rawTargets = Array.isArray(analysis.articulation_targets) ? analysis.articulation_targets : [];
  const normalized = rawTargets.map((target, index) => normalizeClientArticulationTarget(target, index)).filter(Boolean);
  const targets = normalized.length >= 3 ? normalized : buildFallbackArticulationTargets(analysis, normalized);
  const seen = new Set();
  return targets.filter((target) => {
    const key = normalizeClientText(`${target.category} ${target.label} ${target.visualFocus}`);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 6);
}

function normalizeClientArticulationTarget(target, index = 0) {
  if (!target || typeof target !== "object") return null;
  const label = cleanUiText(target.label || target.title || target.visual_focus || target.focus || target.prompt);
  const prompt = cleanUiText(target.prompt || target.question || "");
  const visualFocus = cleanUiText(target.visual_focus || target.visualFocus || target.focus || label);
  const category = normalizeTargetCategory(target.category || label || prompt);
  if (!label && !prompt && !visualFocus) return null;
  if (isGenericTargetLabel(label, prompt)) return null;
  const hints = cleanLayerHints([...(target.hints || []), ...(target.words || [])], 6);
  const evidence = cleanLayerHints([...(target.evidence || []), ...(target.visual_evidence || [])], 4);
  return {
    id: cleanTargetId(target.id || `${category}_${index + 1}_${label || visualFocus}`),
    label: label || visualFocus || `Image detail ${index + 1}`,
    prompt: prompt || `Describe ${visualFocus || label}.`,
    expansionPrompt: cleanUiText(target.expansionPrompt || target.expansion_prompt || ""),
    category,
    visualFocus: visualFocus || label,
    hints,
    evidence,
    importance: Number(target.importance || 0.6),
  };
}

function buildFallbackArticulationTargets(analysis = {}, existing = []) {
  const targets = [...existing];
  const seen = new Set(targets.map((target) => normalizeClientText(`${target.category} ${target.label} ${target.visualFocus}`)));
  const add = (target) => {
    const normalized = normalizeClientArticulationTarget(target, targets.length);
    if (!normalized) return;
    const key = normalizeClientText(`${normalized.category} ${normalized.label} ${normalized.visualFocus}`);
    if (!key || seen.has(key) || targets.length >= 6) return;
    seen.add(key);
    targets.push(normalized);
  };

  const objects = (analysis.objects || [])
    .map((item) => ({
      name: cleanUiText(item?.name || item),
      description: cleanUiText(item?.description || ""),
      color: cleanUiText(item?.color || ""),
      position: cleanUiText(item?.position || ""),
      evidence: cleanLayerHints(item?.visual_evidence || item?.evidence || [], 3),
      importance: Number(item?.importance || 0.6),
    }))
    .filter((item) => item.name)
    .sort((a, b) => b.importance - a.importance);

  objects.slice(0, 3).forEach((object) => {
    add({
      label: `Add detail about ${object.name}`,
      prompt: `Add detail about ${object.name}.`,
      category: "appearance",
      visual_focus: object.name,
      evidence: [object.description, object.position, ...object.evidence],
      hints: [object.name, object.color, object.position, ...object.evidence],
      importance: object.importance,
    });
  });

  (analysis.actions || []).filter((item) => isMeaningfulActionPhrase(item?.phrase || item?.verb || item)).slice(0, 2).forEach((action) => {
    const phrase = cleanUiText(action?.phrase || action?.verb || action);
    const category = normalizeTargetCategory(phrase);
    add({
      label: `What stands out about ${phrase}?`,
      prompt: `What stands out about ${phrase}?`,
      category,
      visual_focus: phrase,
      evidence: [action?.visible_evidence, action?.description],
      hints: [phrase, action?.verb],
      importance: Number(action?.importance || 0.6),
    });
  });

  (analysis.visual_zones || []).forEach((zone) => {
    const zoneName = cleanUiText(zone?.zone || "").replace(/_/g, " ");
    const elements = cleanLayerHints(zone?.elements || [], 5);
    const opportunities = cleanLayerHints(zone?.articulation_opportunities || zone?.opportunities || [], 5);
    const focus = bestZoneFocus(zoneName, elements, opportunities);
    if (!focus) return;
    const category = normalizeTargetCategory(`${focus} ${opportunities.join(" ")} ${zoneName}`);
    add({
      label: zoneTargetLabel(focus, category, zoneName),
      prompt: zoneTargetLabel(focus, category, zoneName),
      category: category === "detail" ? "environment" : category,
      visual_focus: focus,
      evidence: [zoneName, ...elements, ...opportunities],
      hints: [focus, ...elements.slice(0, 2), ...opportunities.slice(0, 2)],
      importance: Number(zone?.importance || 0.55),
    });
  });

  (analysis.environment_details || []).slice(0, 4).forEach((detail) => {
    const text = cleanUiText(detail);
    if (!text) return;
    const category = conditionRelatedHint(text) ? "condition" : positioningRelatedHint(text) ? "positioning" : normalizeTargetCategory(text);
    add({
      label: `Add detail about ${text}`,
      prompt: `Add detail about ${text}.`,
      category,
      visual_focus: text,
      evidence: [analysis.environment, text],
      hints: [text, "nearby", "in the background"],
      importance: 0.55,
    });
  });

  const summary = cleanUiText(analysis.scene_summary_natural || analysis.native_explanation || analysis.scene_summary_simple);
  const moodHints = uniqueWritingHints([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...(analysis.environment_details || []),
  ]).filter(atmosphereRelatedHint).slice(0, 5);
  if (moodHints.length && atmosphereRelatedHint(summary)) {
    add({
      label: "Describe the feeling of the scene",
      prompt: "What feeling does the scene create?",
      category: "atmosphere",
      visual_focus: "the feeling of the scene",
      evidence: analysis.environment_details || [],
      hints: moodHints,
      importance: 0.45,
    });
  }

  if (targets.length < 3 && cleanUiText(analysis.environment)) {
    add({
      label: `Describe the area around ${cleanUiText(analysis.environment)}`,
      prompt: `Describe the area around ${cleanUiText(analysis.environment)}.`,
      category: "environment",
      visual_focus: cleanUiText(analysis.environment),
      evidence: analysis.environment_details || [],
      hints: [analysis.environment, "around it", "behind it"],
      importance: 0.5,
    });
  }
  return targets;
}

function bestZoneFocus(zoneName, elements = [], opportunities = []) {
  const candidates = [...elements, ...opportunities].map(cleanUiText).filter(Boolean);
  const priority = [
    /\b(apartment buildings?|buildings?|unfinished structure|construction|architecture)\b/i,
    /\b(wires?|poles?|skyline|upper|background)\b/i,
    /\b(lighting|sunlight|shadow|reflection)\b/i,
    /\b(contrast|behind|foreground|middle ground|background)\b/i,
  ];
  for (const pattern of priority) {
    const match = candidates.find((item) => pattern.test(item));
    if (match) return match;
  }
  if (/\bbackground|upper/.test(normalizeClientText(zoneName)) && candidates.length) return candidates[0];
  return candidates[0] || "";
}

function zoneTargetLabel(focus, category, zoneName) {
  const text = cleanUiText(focus);
  if (/\b(apartment|building|structure|construction|architecture)\b/i.test(text)) {
    return `Describe the ${text} in the background`;
  }
  if (category === "lighting") return `What stands out about the lighting near ${text}?`;
  if (["composition", "positioning", "contrast"].includes(category)) return `What stands out in the ${zoneName || "background"}?`;
  return `Add detail about ${text}`;
}

function normalizeTargetCategory(value) {
  const text = normalizeClientText(value);
  if (/\b(light|lighting|shadow|sun|bright)\b/.test(text)) return "lighting";
  if (/\b(texture|rough|smooth|fabric|surface)\b/.test(text)) return "texture";
  if (/\b(color|appearance|shape|surface|petal|fabric)\b/.test(text)) return "appearance";
  if (/\b(apartment|building|structure|construction|architecture)\b/.test(text)) return "environment";
  if (/\b(position|arrangement|foreground|background|near|behind|under|beside)\b/.test(text)) return "positioning";
  if (/\b(composition|layout|framing|center|focus|focused)\b/.test(text)) return "composition";
  if (/\b(contrast|stands out|against|different)\b/.test(text)) return "contrast";
  if (/\b(feeling|mood|atmosphere|calm|busy|messy|peaceful)\b/.test(text)) return "atmosphere";
  if (/\b(condition|dust|dirty|clean|clutter|maintained|worn)\b/.test(text)) return "condition";
  if (/\b(walking|running|driving|crowd|traffic|moving|movement)\b/.test(text)) return "movement";
  if (/\b(holding|using|carrying|talking|playing|interaction|together)\b/.test(text)) return "interaction";
  if (/\b(room|street|garden|background|surroundings|environment|area|place|desk|roadside)\b/.test(text)) return "environment";
  return "detail";
}

function isGenericTargetLabel(label, prompt) {
  const text = normalizeClientText(`${label} ${prompt}`).trim();
  return ["subject", "action", "environment", "details", "atmosphere", "describe the environment", "describe details", "describe the action"].includes(text);
}

function cleanTargetId(value) {
  return normalizeClientText(value).replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48) || "target";
}

function dynamicTargetCompleted(target, feedback, analysis, normalizedText) {
  if (!normalizedText) return false;
  const directTerms = dynamicTargetTerms(target).filter((term) => term.length >= 3);
  const directMatches = directTerms.filter((term) => normalizedText.includes(normalizeClientText(term))).length;
  if (directMatches >= (target.category === "appearance" ? 2 : 1)) return true;
  if (["movement", "interaction"].includes(target.category)) return isMeaningfulActionPhrase(normalizedText) && directMatches > 0;
  if (["appearance", "texture", "contrast"].includes(target.category) && hasAppearanceLayer(feedback, analysis, normalizedText)) return directMatches > 0;
  if (["positioning", "composition", "environment", "lighting"].includes(target.category) && hasCompositionLayer(feedback, analysis, normalizedText)) return directMatches > 0 || /\b(near|behind|under|beside|background|foreground|bright|light|shadow|roadside|room|street)\b/.test(normalizedText);
  if (["atmosphere", "condition"].includes(target.category)) return hasAtmosphereLayer(feedback, analysis, normalizedText) || conditionRelatedHint(normalizedText);
  return false;
}

function dynamicTargetTerms(target = {}) {
  return uniqueWritingHints([
    target.visualFocus,
    target.label,
    ...(target.hints || []),
    ...(target.evidence || []),
  ]).flatMap((item) => compactTargetTerms(item));
}

function compactTargetTerms(value) {
  const text = cleanUiText(value);
  if (!text) return [];
  const pieces = [text];
  text.split(/\s+/).forEach((word) => {
    if (word.length >= 4 && !COMMON_ARTICULATION_WORDS.has(normalizeClientText(word))) pieces.push(word);
  });
  return pieces;
}

const COMMON_ARTICULATION_WORDS = new Set(["describe", "image", "scene", "thing", "object", "area", "looks", "there", "nearby", "background"]);

function buildLayerFeedbackIssue(layer, feedback, session) {
  return {
    message: layer.prompt || layer.focusArea,
    focusAreas: [layer.focusArea],
    additions: layerAdditions(layer, feedback, session),
    target: layer,
  };
}

function layerAdditions(layer, feedback, session) {
  if (layer?.dynamic) {
    return uniqueWritingHints([
      ...(layer.hints || []),
      ...(layer.evidence || []),
      layer.visualFocus,
      layer.label,
    ]).slice(0, 6);
  }
  const analysis = session?.analysis || {};
  if (["subject", "main_object", "person"].includes(layer.key)) return [primarySubjectHint(analysis)].filter(Boolean);
  if (layer.key === "action") return [primaryActionPhrase(analysis)].filter(Boolean);
  if (["environment", "surroundings", "main_environment", "background"].includes(layer.key)) {
    return [primaryBackgroundHint(analysis) || cleanUiText(analysis.environment)].filter(Boolean);
  }
  if (["details", "objects"].includes(layer.key)) {
    return uniqueWritingHints([
      primaryObjectHint(analysis, 1),
      primaryObjectHint(analysis, 2),
      ...cleanUiList(feedback?.specific_guidance?.nouns || [], 3),
    ]).filter(Boolean);
  }
  if (layer.key === "appearance") return appearanceHintsForAnalysis(analysis, feedback).slice(0, 3);
  if (["composition", "layout"].includes(layer.key)) return compositionHintsForAnalysis(analysis, feedback).slice(0, 3);
  if (layer.key === "expression") return expressionHintsForAnalysis(analysis, feedback).slice(0, 3);
  if (["atmosphere", "mood"].includes(layer.key)) {
    return uniqueWritingHints([
      primaryAtmosphereHint(analysis),
      ...atmosphereChoiceWords(analysis),
      ...conditionHintWords(analysis),
    ]).filter(Boolean).slice(0, 5);
  }
  return [];
}

function buildLayerCurrentFocus(layer, session, escalation = {}) {
  if (layer?.dynamic) {
    return dynamicTargetPrompt(layer, session, escalation.level || 1);
  }
  const level = escalation.level || 1;
  const progressive = progressiveLayerPrompt(layer, session, level);
  if (progressive) {
    return progressive;
  }
  const text = {
    subject: "Describe the main subject",
    main_object: "Describe the main object",
    person: "Describe the person",
    action: "Explain what is happening",
    environment: "Add background details",
    main_environment: "Describe the main environment",
    surroundings: "Describe the surroundings",
    details: "Mention important objects",
    objects: "Mention important objects",
    appearance: "Add visual details",
    composition: "Explain the composition",
    layout: "Describe the layout",
    expression: "Describe the expression or posture",
    atmosphere: "Describe the atmosphere",
    mood: "Describe the mood",
  };
  return text[layer.key] || "Add one more layer";
}

function dynamicTargetPrompt(layer, session, level = 1) {
  const base = cleanUiText(layer.prompt || `Describe ${layer.visualFocus || layer.label}.`);
  if (level <= 1) return base;
  if (level === 2) return dynamicNoticePrompt(layer, session);
  if (level === 3) return dynamicContrastPrompt(layer, session);
  if (level === 4) return dynamicSentenceScaffold(layer, session);
  if (level >= 5) return directLayerHelp(layer, session);
  return base;
}

function dynamicNoticePrompt(layer, session) {
  const evidence = dynamicVisibleEvidence(layer, session);
  return evidence ? `👀 Notice ${evidence}.` : "👀 Notice one clear detail in this part of the image.";
}

function dynamicContrastPrompt(layer, session) {
  const choices = dynamicTargetChoices(layer, session).slice(0, 4);
  return choices.length
    ? `Does this part feel: ${choices.join(", ")}?`
    : "What kind of detail fits here: color, shape, position, or feeling?";
}

function dynamicSentenceScaffold(layer, session) {
  const focus = stripLeadingArticle(cleanUiText(layer.visualFocus || layer.label || "this area"));
  const evidence = dynamicVisibleEvidence(layer, session).replace(/^the\s+/i, "");
  if (["atmosphere", "condition", "environment"].includes(layer.category)) {
    return `The ${focus} looks ___ because of the ___.`;
  }
  if (layer.category === "lighting") {
    return `The light makes the ${focus} look ___.`;
  }
  if (layer.category === "positioning") {
    return `The ${focus} is ___ the ${evidence || "scene"}.`;
  }
  return `The ${focus} looks ___ and ___.`;
}

function directLayerHelp(layer, session) {
  const focus = stripLeadingArticle(cleanUiText(layer.visualFocus || layer.label || "this area"));
  const evidence = dynamicVisibleEvidence(layer, session);
  const phrase = cleanLayerHints([...(layer?.hints || []), evidence], 6).find((item) => item.split(/\s+/).length <= 7);
  if (phrase) {
    return `Try mentioning that ${phrase}.`;
  }
  if (layer.category === "lighting") {
    return `Try mentioning the light or shadows around ${focus}.`;
  }
  if (layer.category === "atmosphere") {
    return `Try mentioning how ${focus} makes the place feel.`;
  }
  return `Try adding one short detail about ${focus}.`;
}

function dynamicVisibleEvidence(layer, session) {
  return cleanLayerHints([
    ...(layer?.evidence || []),
    ...(layer?.hints || []),
    layer?.visualFocus,
    visibleEvidencePhrase(session?.analysis || {}),
  ], 6).find((item) => item.split(/\s+/).length <= 6) || "";
}

function dynamicTargetChoices(layer, session) {
  const category = layer?.category || "";
  if (category === "lighting") return ["bright", "soft", "shadowy", "warm"];
  if (category === "condition") return ["clean", "messy", "dusty", "well maintained"];
  if (category === "atmosphere") return atmosphereChoiceWords(session?.analysis || {});
  if (category === "environment") return ["peaceful", "crowded", "tropical", "busy"];
  if (category === "texture") return ["smooth", "rough", "soft", "delicate"];
  if (category === "contrast") return ["bright", "dark", "colorful", "noticeable"];
  return uniqueWritingHints([
    ...cleanLayerHints(layer?.hints || [], 4).map(adjectiveLikeHint).filter(Boolean),
    "clear",
    "noticeable",
    "detailed",
  ]);
}

function buildStuckLayerUpgrade(text, layer, escalation = {}) {
  if (!layer?.dynamic || (escalation.level || 1) < 5) return null;
  const source = cleanUiText(text);
  if (!source) return null;
  const category = layer.category || "";
  const upgrades = [
    ["nice", upgradePhraseForLayer(layer, "nice")],
    ["good", upgradePhraseForLayer(layer, "good")],
    ["bad", category === "condition" ? "messy and neglected" : "not very clear"],
    ["beautiful", category === "appearance" ? "bright and eye-catching" : "calm and attractive"],
    ["many", category === "environment" ? "a dense area of" : "several visible"],
    ["big", "large and noticeable"],
    ["small", "small but noticeable"],
  ];
  const found = upgrades.find(([oldText, newText]) => newText && newText !== oldText && new RegExp(`\\b${escapeRegExp(oldText)}\\b`, "i").test(source));
  if (!found) {
    const choices = dynamicTargetChoices(layer, {}).filter(Boolean);
    const focus = stripLeadingArticle(cleanUiText(layer.visualFocus || "this area"));
    return choices[0] ? { oldText: focus.split(/\s+/)[0] || "this", newText: `${choices[0]} ${focus}` } : null;
  }
  return { oldText: found[0], newText: found[1] };
}

function upgradePhraseForLayer(layer, word) {
  const category = layer?.category || "";
  if (category === "atmosphere") return word === "nice" ? "peaceful and inviting" : "calm and natural";
  if (category === "environment") return word === "nice" ? "peaceful and tropical" : "clear and well arranged";
  if (category === "lighting") return word === "nice" ? "soft and bright" : "naturally lit";
  if (category === "condition") return word === "nice" ? "clean and well maintained" : "neatly arranged";
  if (category === "texture") return word === "nice" ? "smooth and delicate" : "clear and textured";
  return word === "nice" ? "clear and noticeable" : "more detailed";
}

function applyStuckLayerUpgrade(oldText, newText) {
  const input = document.getElementById("learnerImproveInput");
  if (!input || !oldText || !newText) return;
  const current = input.value || "";
  if (new RegExp(`\\b${escapeRegExp(oldText)}\\b`, "i").test(current)) {
    input.value = current.replace(new RegExp(`\\b${escapeRegExp(oldText)}\\b`, "i"), newText);
  } else {
    input.value = `${current.trim()} ${newText}`.trim();
  }
  input.focus();
  showToast("+5 XP — wording upgraded");
  awardLocalXp(5);
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function progressiveLayerPrompt(layer, session, level = 1) {
  const key = normalizeLayerGuidanceKey(layer);
  const analysis = session?.analysis || {};
  const evidence = visibleEvidencePhrase(analysis);
  const object = primaryObjectHint(analysis, 0) || primarySubjectHint(analysis) || "the main object";
  const background = primaryBackgroundHint(analysis) || "the background";
  const prompts = {
    atmosphere: [
      "What feeling does the scene create?",
      "Does the area feel clean, messy, calm, crowded, or neglected?",
      evidence ? `Because of ${evidence}, the scene feels ___.` : "The scene feels ___.",
    ],
    composition: [
      "What stands out visually?",
      "What is closest to the camera or most noticeable?",
      `The object closest to the camera is ${object === "the main object" ? "___" : object}.`,
    ],
    interpretation: [
      "What does the scene suggest?",
      "Does the scene suggest daily life, work, relaxation, disorder, or maintenance?",
      evidence ? `Because of ${evidence}, the scene suggests ___.` : "The scene suggests ___.",
    ],
    condition: [
      "What condition is the place or object in?",
      "Does it look clean, messy, dusty, damaged, fresh, or well maintained?",
      evidence ? `Because of ${evidence}, it looks ___.` : "It looks ___.",
    ],
    positioning: [
      "Where is the important detail in the image?",
      "Is it in the foreground, background, center, beside something, or behind something?",
      `${object === "the main object" ? "The important detail" : object} is near ${background}.`,
    ],
  };
  const options = prompts[key];
  return options ? options[Math.min(Math.max(level, 1), 3) - 1] : "";
}

function layerExpansionPrompt(layer, escalation = {}) {
  if (layer?.dynamic) {
    return dynamicTargetExpansionPrompt(layer, escalation.level || 1);
  }
  const level = escalation.level || 1;
  const progressive = progressiveLayerExpansionPrompt(layer, level);
  if (progressive) {
    return progressive;
  }
  const text = {
    subject: "Start with who or what the image is mainly about.",
    main_object: "Name the object or natural feature clearly before adding details.",
    person: "Start with the person as the visual focus.",
    action: "Keep your sentence and add what is happening.",
    environment: "Expand the same answer with where it happens or what is behind it.",
    main_environment: "Describe the place or setting first.",
    surroundings: "Add what appears around the main object.",
    details: "Add one or two important visible details without starting over.",
    objects: "Add the visible objects that make the setting clearer.",
    appearance: "Add color, shape, size, texture, or other visual details.",
    composition: "Explain what is in focus or where the object appears.",
    layout: "Use position words to show how the scene is arranged.",
    expression: "Add face, body position, or posture language if it fits.",
    atmosphere: "Finish by adding the feeling or quality of the scene.",
    mood: "Finish with the feeling or expression the image gives.",
  };
  return text[layer?.key] || "Keep your answer and add one clear layer.";
}

function dynamicTargetExpansionPrompt(layer, level = 1) {
  if (layer.expansionPrompt) return layer.expansionPrompt;
  const focus = cleanUiText(layer.visualFocus || layer.label || "this part of the image");
  if (level >= 5) return directLayerHelp(layer, state.currentSession || {});
  if (level >= 3) return "Use the sentence frame and one hint word.";
  if (level >= 2) return `Choose one hint and add it to your description of ${focus}.`;
  return `Add one clear detail about ${focus}.`;
}

function progressiveLayerExpansionPrompt(layer, level = 1) {
  const key = normalizeLayerGuidanceKey(layer);
  if (!isAbstractLayerCategory(key)) {
    return "";
  }
  const prompts = {
    atmosphere: [
      "Use one simple feeling word.",
      "Choose a category, then add one adjective.",
      "Finish the sentence frame with one direct word.",
    ],
    composition: [
      "Name the most noticeable visual part.",
      "Look for what is closest, centered, or in focus.",
      "Use the frame to say exactly what stands out.",
    ],
    interpretation: [
      "Say what the image makes you think about.",
      "Choose a simple idea like work, daily life, disorder, or maintenance.",
      "Use the visible evidence to finish the sentence.",
    ],
    condition: [
      "Describe whether it looks clean, messy, fresh, or damaged.",
      "Choose a condition word from the hints.",
      "Use the evidence and finish the sentence.",
    ],
  };
  const options = prompts[key];
  return options ? options[Math.min(Math.max(level, 1), 3) - 1] : "";
}

function importantObjectCoverageCount(feedback, session, learnerText = "") {
  const text = normalizeClientText(learnerText);
  const objects = (session?.analysis?.objects || [])
    .map((item) => cleanUiText(item?.name || item))
    .filter(Boolean);
  const mentionedObjects = objects.filter((item) => text.includes(normalizeClientText(item))).length;
  const coveredParts = (feedback?.coverage?.imageParts || []).filter((part) => {
    const type = normalizeClientText(part?.type || "");
    return isCoveragePartCovered(part) && /\b(object|detail|foreground|important)\b/.test(type);
  }).length;
  return Math.max(mentionedObjects, coveredParts);
}

function classifyImproveImageType(analysis = {}) {
  const objects = (analysis.objects || []).map((item) => cleanUiText(item?.name || item)).filter(Boolean);
  const actions = (analysis.actions || []).map((item) => cleanUiText(item?.phrase || item?.verb || item)).filter(Boolean);
  const environment = cleanUiText(analysis.environment);
  const details = (analysis.environment_details || []).map(cleanUiText).filter(Boolean);
  const summary = cleanUiText(analysis.scene_summary_natural || analysis.natural_explanation || analysis.scene_summary_simple);
  const combined = normalizeClientText([...objects, ...actions, environment, ...details, summary].join(" "));
  const hasMeaningfulAction = actions.some(isMeaningfulActionPhrase);
  if (hasMeaningfulAction || /\b(traffic|sports?|game|cooking|machine|driving|walking|running|riding)\b/.test(combined)) {
    return "action";
  }
  const primary = normalizeClientText(objects[0] || "");
  const hasPerson = objects.some((item) => /\b(person|people|man|woman|child|boy|girl|face|selfie|portrait)\b/i.test(item));
  if (hasPerson && !hasMeaningfulAction) {
    return "portrait";
  }
  const objectFocus = /\b(flower|plant|leaf|tree|food|meal|dish|product|bottle|cup|book|phone|car|cat|dog|object|close up|closeup)\b/.test(combined);
  const environmentFocus = /\b(park|street|beach|city|garden|landscape|view|field|yard|room|river|mountain|forest|road|market)\b/.test(combined);
  if (objectFocus && (objects.length <= 3 || primary)) {
    return "object";
  }
  if (environmentFocus) {
    return "environment";
  }
  return objects.length <= 2 ? "object" : "environment";
}

function isMeaningfulActionPhrase(value) {
  const text = normalizeClientText(value);
  if (!text) return false;
  if (/\b(walking|running|riding|driving|cooking|using|holding|playing|mowing|crossing|working|cutting|eating|drinking|throwing|jumping|swimming|climbing)\b/.test(text)) {
    return true;
  }
  return !/\b(sitting|standing|posing|smiling|looking|facing|visible|appears?|shown)\b/.test(text) && /\b\w+ing\b/.test(text);
}

function mentionsPrimaryObject(analysis, normalizedText) {
  const primary = normalizeClientText(primarySubjectHint(analysis));
  return Boolean(primary && normalizedText.includes(primary));
}

function hasEnvironmentText(analysis, normalizedText) {
  return [analysis.environment, ...(analysis.environment_details || [])]
    .map((item) => normalizeClientText(item))
    .filter(Boolean)
    .some((item) => normalizedText.includes(item));
}

function hasAppearanceLayer(feedback, analysis, normalizedText) {
  const hints = appearanceHintsForAnalysis(analysis, feedback);
  const hasHint = hints.some((item) => normalizedText.includes(normalizeClientText(item)));
  return hasHint || /\b(red|pink|yellow|green|blue|white|black|bright|dark|soft|vivid|tall|small|large|round|thin|wide|fresh|smooth|rough|delicate|blurred)\b/.test(normalizedText);
}

function hasCompositionLayer(feedback, analysis, normalizedText) {
  const hints = compositionHintsForAnalysis(analysis, feedback);
  const hasHint = hints.some((item) => normalizedText.includes(normalizeClientText(item)));
  return hasHint || /\b(foreground|background|center|middle|focus|focused|blurred|near|beside|behind|around|surrounded|close up|close-up)\b/.test(normalizedText);
}

function hasExpressionLayer(feedback, analysis, normalizedText) {
  const hints = expressionHintsForAnalysis(analysis, feedback);
  const hasHint = hints.some((item) => normalizedText.includes(normalizeClientText(item)));
  return hasHint || /\b(smiling|serious|calm|relaxed|standing|sitting|looking|facing|posture|expression|pose)\b/.test(normalizedText);
}

function appearanceHintsForAnalysis(analysis = {}, feedback = {}) {
  return uniqueWritingHints([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(feedback?.specific_guidance?.words || [], 5),
    ...((analysis.objects || []).map((item) => item?.description || "")),
    ...(analysis.environment_details || []),
  ]).filter((item) => /\b(red|pink|yellow|green|blue|white|black|bright|dark|soft|vivid|tall|small|large|round|fresh|smooth|rough|delicate|petals?|leaves|leaf|grassy|blurred|well-kept)\b/i.test(item));
}

function compositionHintsForAnalysis(analysis = {}, feedback = {}) {
  return uniqueWritingHints([
    ...buildStructureHints(analysis),
    ...((analysis.phrases || []).map((item) => item?.phrase || item)),
    ...cleanUiList(feedback?.specific_guidance?.details || [], 5),
    "in focus",
    "in the foreground",
    "slightly blurred background",
    "near the center",
    "surrounded by leaves",
  ]).filter((item) => positioningRelatedHint(item) || /\b(focus|focused|blurred|center|surrounded)\b/i.test(item));
}

function expressionHintsForAnalysis(analysis = {}, feedback = {}) {
  return uniqueWritingHints([
    ...((analysis.actions || []).map((item) => item?.phrase || item?.verb || item)),
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(feedback?.specific_guidance?.words || [], 5),
    "smiling",
    "standing still",
    "relaxed posture",
    "calm expression",
  ]).filter((item) => /\b(smiling|serious|calm|relaxed|standing|sitting|looking|facing|posture|expression|pose)\b/i.test(item));
}

function hasAtmosphereLayer(feedback, analysis, normalizedText) {
  const words = [
    ...((analysis?.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    analysis?.environment,
    ...(analysis?.environment_details || []),
    ...cleanUiList(feedback?.specific_guidance?.words || [], 5),
  ].map(cleanUiText).filter(atmosphereRelatedHint);
  const textHasMood = words.some((word) => normalizedText.includes(normalizeClientText(word)));
  const language = feedback?.language_quality || {};
  const naturalScore = Number(language.naturalness || language.score || 0);
  return textHasMood || /\b(calm|peaceful|busy|quiet|bright|dark|sunny|lively|warm|clean|well kept|well-kept)\b/.test(normalizedText) || naturalScore >= 70;
}

function buildArticulationUpgradeSuggestions(session, feedback, learnerText) {
  const text = cleanUiText(learnerText);
  if (!text) {
    return [];
  }
  const analysis = session?.analysis || {};
  const suggestions = [];
  const push = (item) => {
    const normalized = normalizeUpgradeSuggestion(item, text);
    if (!normalized) return;
    if (suggestions.some((existing) => normalizeClientText(existing.oldText || existing.newText) === normalizeClientText(normalized.oldText || normalized.newText))) {
      return;
    }
    suggestions.push(normalized);
  };

  buildFeedbackInlineUpgrades(feedback || {}, text)
    .forEach((item) => push({ ...item, type: inferUpgradeType(item.oldText, item.newText) }));

  const objects = (analysis.objects || []).map((item) => cleanUiText(item?.name || item)).filter(Boolean);
  const details = (analysis.environment_details || []).map(cleanUiText).filter(Boolean);
  const vocabulary = [
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(feedback?.specific_guidance?.words || [], 5),
  ].map(cleanUiText).filter(Boolean);
  const action = primaryActionPhrase(analysis);
  const actionVerb = primaryActionVerb(analysis);
  const positioning = uniqueWritingHints([
    ...buildStructureHints(analysis),
    ...((analysis.phrases || []).map((item) => item?.phrase || item)),
    ...cleanUiList(feedback?.phrase_usage?.suggested || [], 3),
  ]).filter(positioningRelatedHint);
  const atmosphere = uniqueWritingHints([
    ...vocabulary,
    primaryAtmosphereHint(analysis),
    "peaceful atmosphere",
    "calm outdoor setting",
    "well-kept environment",
  ]).filter(atmosphereRelatedHint);
  const visualDetails = uniqueWritingHints([...objects, ...details, ...vocabulary]).filter(Boolean);
  const richNounUpgrade = (noun, fallback) => {
    const match = visualDetails.find((item) =>
      normalizeClientText(item).includes(normalizeClientText(noun)) &&
      normalizeClientText(item) !== normalizeClientText(noun)
    );
    return match || fallback;
  };

  [
    ["thing", visualDetails[0]],
    ["things", visualDetails.find((item) => !/\b(feeling|atmosphere|mood)\b/i.test(item))],
    ["place", analysis.environment || details[0]],
    ["people", objects.find((item) => /\b(two|three|group|person|people|man|woman|child)\b/i.test(item))],
    ["person", objects.find((item) => /\bman|woman|child|person\b/i.test(item))],
    ["trees", richNounUpgrade("trees", "tall palm trees")],
    ["tree", richNounUpgrade("tree", "tall tree")],
    ["grass", richNounUpgrade("grass", "green grass")],
    ["flower", richNounUpgrade("flower", "bright flower")],
    ["flowers", richNounUpgrade("flowers", "bright flowers")],
    ["building", richNounUpgrade("building", "tall building")],
    ["buildings", richNounUpgrade("buildings", "tall buildings")],
    ["road", richNounUpgrade("road", "busy road")],
    ["background", richNounUpgrade("background", "soft background")],
    ["nice", atmosphere[0]],
    ["good", atmosphere[0]],
    ["beautiful", atmosphere[0] || richNounUpgrade("scene", "vivid scene")],
    ["big", visualDetails.find((item) => /\b(tall|large|wide|broad)\b/i.test(item))],
    ["small", visualDetails.find((item) => /\b(small|narrow|tiny|compact)\b/i.test(item))],
  ].forEach(([oldText, newText]) => push({
    oldText,
    newText,
    type: atmosphereRelatedHint(newText)
      ? "atmosphere"
      : /\b(thing|things|place|people|person|tree|trees|grass|flower|flowers|building|buildings|road|background)\b/i.test(oldText)
        ? "vocabulary"
        : "visual_quality",
  }));

  [
    ["go", actionVerb || action],
    ["going", action],
    ["move", action],
    ["moving", action],
    ["walk", action && normalizeClientText(action) !== "walk" ? action : ""],
    ["look", "gaze"],
    ["hold", "grip"],
  ].forEach(([oldText, newText]) => push({ oldText, newText, type: "verb" }));

  const firstPosition = positioning.find((item) => !normalizeClientText(text).includes(normalizeClientText(item)));
  const positionTarget = findPositioningUpgradeTarget(text);
  if (firstPosition && positionTarget) {
    push({ oldText: positionTarget, newText: `${positionTarget} ${firstPosition}`, type: "positioning" });
  }
  if (!/\b(while|with|surrounded by|creating|adding to)\b/i.test(text)) {
    const flowTarget = firstSentence(text);
    const flow = text.includes(".") ? "with clearer details" : "while showing the setting";
    if (flowTarget && flowTarget.split(/\s+/).length <= 6) {
      push({ oldText: flowTarget, newText: `${flowTarget.replace(/[.!?]+$/g, "")} ${flow}.`, type: "sentence_flow" });
    }
  }
  [
    ["The image shows", "The scene shows"],
    ["There are", "In the scene, there are"],
    ["It has", "The scene includes"],
    ["There is", "The scene includes"],
  ].forEach(([oldText, newText]) => push({ oldText, newText, type: "sentence_flow" }));
  const firstMood = atmosphere.find((item) => !normalizeClientText(text).includes(normalizeClientText(item)));
  const moodTarget = findMoodUpgradeTarget(text);
  if (firstMood && moodTarget) {
    push({ oldText: moodTarget, newText: `${moodTarget} with a ${firstMood} feeling`, type: "atmosphere" });
  }

  const compositionTarget = findTextOccurrence(text, "background") || findTextOccurrence(text, "behind");
  const compositionPhrase = positioning.find((item) => /\b(foreground|background|behind|near|beside|along)\b/i.test(item));
  if (compositionTarget && compositionPhrase && !normalizeClientText(text).includes(normalizeClientText(compositionPhrase))) {
    push({ oldText: compositionTarget, newText: `${compositionTarget} ${compositionPhrase}`, type: "positioning" });
  }

  return selectPolishUpgradeSuggestions(suggestions, text).map((item, index) => ({
    ...item,
    id: `${item.type}-${index}-${normalizeClientText(item.oldText || item.newText).slice(0, 18)}`,
  }));
}

function selectPolishUpgradeSuggestions(suggestions = [], answer = "") {
  const source = String(answer || "");
  const selected = [];
  const usedRanges = [];
  const usedTypes = new Set();
  const seenOldText = new Set();
  const typePriority = {
    vocabulary: 1,
    verb: 2,
    positioning: 3,
    atmosphere: 4,
    sentence_flow: 5,
    visual_quality: 6,
  };
  const candidates = suggestions
    .map((item, index) => ({
      ...item,
      type: normalizePolishUpgradeType(item.type),
      originalIndex: index,
    }))
    .filter((item) => polishUpgradeTypeAllowed(item.type))
    .sort((a, b) => (typePriority[a.type] || 9) - (typePriority[b.type] || 9) || a.originalIndex - b.originalIndex);

  const trySelect = (item, requireNewType = false) => {
    if (selected.length >= 5) return;
    if (requireNewType && usedTypes.has(item.type)) return;
    const oldKey = normalizeClientText(item.oldText || "");
    if (!oldKey || seenOldText.has(oldKey)) return;
    const start = source.toLowerCase().indexOf(String(item.oldText || "").toLowerCase());
    if (start < 0) return;
    const end = start + String(item.oldText || "").length;
    if (usedRanges.some((range) => start < range.end && end > range.start)) return;
    selected.push(item);
    seenOldText.add(oldKey);
    usedTypes.add(item.type);
    usedRanges.push({ start, end });
  };

  candidates.forEach((item) => trySelect(item, true));
  candidates.forEach((item) => trySelect(item, false));

  return selected;
}

function normalizePolishUpgradeType(type) {
  const value = String(type || "").trim();
  if (value === "flow") return "sentence_flow";
  if (value === "composition") return "positioning";
  if (value === "impression") return "atmosphere";
  return value || "vocabulary";
}

function polishUpgradeTypeAllowed(type) {
  return ["vocabulary", "verb", "positioning", "atmosphere", "sentence_flow", "visual_quality"].includes(type);
}

function normalizeUpgradeSuggestion(item, text) {
  const oldText = cleanUiText(item?.targetText || item?.oldText || item?.old || item?.instead_of);
  const newText = cleanUiText(item?.replacementText || item?.newText || item?.new || item?.use || item?.strong);
  if (!newText || oldText === newText || normalizeClientText(oldText) === normalizeClientText(newText)) {
    return null;
  }
  if (oldText.split(/\s+/).filter(Boolean).length > 6 || newText.split(/\s+/).filter(Boolean).length > 7) {
    return null;
  }
  const safeUpgrade = buildContextAwareUpgrade(text, oldText, newText, { allowStructuralRetarget: false });
  if (!oldText || !safeUpgrade) {
    return null;
  }
  const type = item?.type || inferUpgradeType(oldText, newText);
  return {
    oldText: safeUpgrade.oldText,
    newText: safeUpgrade.newText,
    targetText: safeUpgrade.oldText,
    replacementText: safeUpgrade.newText,
    reason: cleanUiText(item?.reason || item?.why),
    example: cleanUiText(item?.example),
    finalPreview: safeUpgrade.finalPreview,
    type,
    xp: xpForUpgradeType(type),
  };
}

function findPositioningUpgradeTarget(text) {
  return findTextOccurrence(text, "behind it") ||
    findTextOccurrence(text, "background") ||
    findTextOccurrence(text, "plants") ||
    findTextOccurrence(text, "trees") ||
    findTextOccurrence(text, "around it");
}

function findMoodUpgradeTarget(text) {
  return findTextOccurrence(text, "looks nice") ||
    findTextOccurrence(text, "nice") ||
    findTextOccurrence(text, "good") ||
    findTextOccurrence(text, "beautiful") ||
    findTextOccurrence(text, "calm");
}

function inferUpgradeType(oldText, newText) {
  const combined = `${oldText || ""} ${newText || ""}`;
  if (/\b(foreground|background|composition|in focus|center|framed)\b/i.test(combined)) return "positioning";
  if (positioningRelatedHint(combined)) return "positioning";
  if (/\b(while|with|surrounded by|creating|adding to)\b/i.test(combined)) return "sentence_flow";
  if (atmosphereRelatedHint(combined)) return "atmosphere";
  if (/\b(appears|impression|suggests|creates)\b/i.test(combined)) return "atmosphere";
  if (/\b(tall|bright|soft|vivid|dense|lush|green|delicate|blurred|towering|trimmed)\b/i.test(combined)) return "visual_quality";
  if (actionRelatedHint(combined) || /\b(go|move|look|hold|gaze|grip)\b/i.test(combined)) return "verb";
  return "vocabulary";
}

function xpForUpgradeType(type) {
  return {
    vocabulary: 5,
    visual_quality: 5,
    verb: 5,
    positioning: 5,
    sentence_flow: 10,
    atmosphere: 10,
  }[type] || 5;
}

function upgradeTypeLabel(type) {
  return {
    vocabulary: "Stronger vocabulary",
    visual_quality: "Visual detail",
    verb: "Precise verb",
    positioning: "Positioning",
    sentence_flow: "Sentence flow",
    atmosphere: "Atmosphere",
  }[type] || "Upgrade";
}

function upgradeTypeReason(type) {
  return {
    vocabulary: "🎨 Rich vocabulary",
    visual_quality: "🌿 More vivid description",
    verb: "🧠 More precise action",
    positioning: "📍 Clearer placement",
    sentence_flow: "🧠 More natural phrasing",
    atmosphere: "✨ Stronger atmosphere",
  }[type] || "✨ More natural wording";
}

function polishRewardLabel(type) {
  return {
    vocabulary: "stronger wording",
    visual_quality: "more vivid detail",
    verb: "stronger verb",
    positioning: "clearer positioning",
    sentence_flow: "smoother flow",
    atmosphere: "richer atmosphere",
  }[type] || "wording upgraded";
}

function findTextOccurrence(text, phrase) {
  const source = String(text || "");
  const index = source.toLowerCase().indexOf(String(phrase || "").toLowerCase());
  return index >= 0 ? source.slice(index, index + String(phrase).length) : "";
}

function normalizeArticulationUpgradeState(existing, answer, suggestions) {
  const ids = suggestions.map((item) => item.id).join("|");
  if (!existing || normalizeClientText(existing.original) !== normalizeClientText(answer) || existing.suggestionKey !== ids) {
    return {
      original: answer,
      answer,
      suggestionKey: ids,
      applied: [],
      skipped: [],
      xp: 0,
      finalized: false,
      justApplied: false,
      lastAppliedNewText: "",
    };
  }
  return {
    original: existing.original || answer,
    answer: cleanUiText(existing.answer) || answer,
    suggestionKey: ids,
    applied: Array.isArray(existing.applied) ? existing.applied : [],
    skipped: Array.isArray(existing.skipped) ? existing.skipped : [],
    xp: Number(existing.xp || 0),
    finalized: Boolean(existing.finalized),
    multiBonusAwarded: Boolean(existing.multiBonusAwarded),
    justApplied: Boolean(existing.justApplied),
    lastAppliedNewText: cleanUiText(existing.lastAppliedNewText),
  };
}

function currentUpgradeAnswer() {
  return cleanUiText(document.getElementById("articulationUpgradeInput")?.value) || state.sessionFlow.articulationUpgrade?.answer || "";
}

function applyArticulationUpgrade(id, suggestions) {
  const upgrade = suggestions.find((item) => item.id === id);
  const upgradeState = state.sessionFlow.articulationUpgrade;
  if (!upgrade || !upgradeState || upgradeState.applied.includes(id)) {
    return;
  }
  const current = currentUpgradeAnswer();
  if (!findTextOccurrence(current, upgrade.oldText)) {
    upgradeState.answer = current;
    upgradeState.skipped = uniqueWritingHints([...upgradeState.skipped, id]);
    showToast("That wording changed, so this suggestion was dismissed.");
    renderSessionStep("improve", { articulationUpgrade: upgradeState });
    return;
  }
  const next = replaceFirstTextOccurrence(current, upgrade.oldText, upgrade.newText);
  upgradeState.answer = next;
  upgradeState.applied = uniqueWritingHints([...upgradeState.applied, id]);
  upgradeState.skipped = upgradeState.skipped.filter((item) => item !== id);
  upgradeState.xp += upgrade.xp;
  upgradeState.justApplied = true;
  upgradeState.lastAppliedNewText = upgrade.newText;
  awardLocalXp(upgrade.xp);
  showToast(`+${upgrade.xp} XP — ${polishRewardLabel(upgrade.type)}`);
  maybeAwardUpgradeBonus(upgradeState);
  renderSessionStep("improve", { articulationUpgrade: upgradeState });
}

function maybeAwardUpgradeBonus(upgradeState) {
  if ((upgradeState.applied || []).length >= 2 && !upgradeState.multiBonusAwarded) {
    upgradeState.xp += 10;
    upgradeState.multiBonusAwarded = true;
    awardLocalXp(10);
    showToast("+10 XP — Multiple articulation upgrades");
  }
}

function skipArticulationUpgrade(id, suggestions) {
  const upgradeState = state.sessionFlow.articulationUpgrade;
  if (!upgradeState || upgradeState.skipped.includes(id)) {
    return;
  }
  upgradeState.answer = currentUpgradeAnswer();
  upgradeState.skipped = uniqueWritingHints([...upgradeState.skipped, id]);
  upgradeState.justApplied = false;
  renderSessionStep("improve", { articulationUpgrade: upgradeState });
}

function finalizeArticulationUpgrade(upgradeState, suggestions) {
  const nextState = upgradeState || state.sessionFlow.articulationUpgrade;
  if (!nextState) return;
  if (!nextState.justApplied) {
    nextState.answer = currentUpgradeAnswer() || nextState.answer;
  }
  const remaining = suggestions.filter((item) => !nextState.applied.includes(item.id) && !nextState.skipped.includes(item.id));
  nextState.skipped = uniqueWritingHints([...nextState.skipped, ...remaining.map((item) => item.id)]);
  nextState.finalized = true;
  state.sessionFlow.stage = LEARNING_STAGES.FINAL_REVEAL;
  state.sessionFlow.finalPolishedText = nextState.answer || nextState.original || "";
  renderSessionStep("improve", { articulationUpgrade: nextState });
}

function allArticulationUpgradesHandled(upgradeState, suggestions) {
  const handled = new Set([...(upgradeState.applied || []), ...(upgradeState.skipped || [])]);
  return suggestions.every((item) => handled.has(item.id));
}

function replaceFirstTextOccurrence(text, oldText, newText) {
  const source = String(text || "");
  const index = source.toLowerCase().indexOf(String(oldText || "").toLowerCase());
  if (index === -1) {
    return source;
  }
  return `${source.slice(0, index)}${newText}${source.slice(index + oldText.length)}`;
}

function awardLocalXp(points) {
  const value = Number(points || 0);
  if (!value) return;
  state.progress = {
    ...(state.progress || {}),
    xp_points: Number(state.progress?.xp_points || 0) + value,
  };
  renderProgressHeader();
}

function buildImproveCurrentFocus(issue, session = {}, escalation = {}) {
  const focus = normalizeClientText(issue?.focusAreas?.[0] || issue?.message || "");
  const category = improveFocusCategory(focus);
  const level = escalation.level || 1;
  if (level >= 3) {
    const explicit = explicitImproveFocusText(category, session);
    if (explicit) return explicit;
  }
  if (level >= 2) {
    const guided = guidedImproveFocusText(category);
    if (guided) return guided;
  }
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

function buildImproveEscalationContext(session, attempts, issue, currentLayer = null) {
  const focusCategory = improveFocusCategory(normalizeClientText(issue?.focusAreas?.[0] || issue?.message || ""));
  const layerKey = currentLayer?.key || "";
  const layerCategory = currentLayer?.category || focusCategory;
  const abstractLayer = isAbstractLayerCategory(normalizeLayerGuidanceKey(currentLayer) || layerCategory);
  const recent = (attempts || []).map((attempt) => ({
    category: improveFocusCategory(normalizeClientText(buildFeedbackIssue(attempt.feedback || {}, session)?.focusAreas?.[0] || "")),
    currentLayerKey: buildCoverageLayerState(attempt.feedback || {}, session, attempt.text || "").currentLayer?.key || "",
    score: Number(attempt.score || feedbackTotalScore(attempt.feedback || {})) || 0,
  }));
  let repeatedFocusCount = 0;
  if (layerKey) {
    for (let index = recent.length - 1; index >= 0; index -= 1) {
      if (recent[index].currentLayerKey !== layerKey) break;
      repeatedFocusCount += 1;
    }
  } else {
    for (let index = recent.length - 1; index >= 0; index -= 1) {
      if (recent[index].category !== focusCategory) break;
      repeatedFocusCount += 1;
    }
  }
  const previous = recent[recent.length - 2];
  const latest = recent[recent.length - 1];
  const scoreDelta = latest && previous ? latest.score - previous.score : 0;
  const noMeaningfulImprovement = Boolean(previous && latest && scoreDelta < 5);
  let level = 1;
  if (currentLayer?.dynamic) {
    level = Math.min(5, Math.max(1, repeatedFocusCount || 1));
  } else if (abstractLayer && repeatedFocusCount >= 2) {
    level = 3;
  } else if (abstractLayer && repeatedFocusCount >= 1) {
    level = 2;
  } else if (repeatedFocusCount >= 3) {
    level = 3;
  } else if (repeatedFocusCount >= 2 || recent.length >= 2) {
    level = 2;
  }
  return {
    focusCategory,
    layerKey,
    layerCategory,
    level,
    repeatedFocusCount,
    noMeaningfulImprovement,
    canMoveForward: Boolean(currentLayer?.dynamic && repeatedFocusCount >= 5),
    moveForwardMessage: "Good effort. You can keep this detail simple and move to the next visual area.",
    message: supportiveLayerMessage(currentLayer, level, session),
  };
}

function guidedImproveFocusText(category) {
  const text = {
    subject: "Who is the image mainly focused on?",
    action: "What is the main subject doing?",
    background: "What can you see behind the main subject?",
    environment: "Where is this scene happening?",
    objects: "Which important object should you add?",
    positioning: "Where is the important detail in the image?",
    appearance: "What does the main object look like?",
    composition: "What is in focus or where is it placed?",
    expression: "What expression or posture do you notice?",
    atmosphere: "What feeling does the scene create?",
    vocabulary: "Which general word can become more exact?",
  };
  return text[category] || "";
}

function normalizeLayerGuidanceKey(layerOrCategory) {
  const text = normalizeClientText(
    typeof layerOrCategory === "string"
      ? layerOrCategory
      : [layerOrCategory?.key, layerOrCategory?.category, layerOrCategory?.focusArea].filter(Boolean).join(" ")
  );
  if (!text) return "";
  if (text.includes("atmosphere") || text.includes("mood")) return "atmosphere";
  if (text.includes("composition") || text.includes("layout") || text.includes("positioning") || text.includes("focus")) return "composition";
  if (text.includes("interpret") || text.includes("suggest")) return "interpretation";
  if (text.includes("condition") || text.includes("maintained") || text.includes("messy") || text.includes("clean")) return "condition";
  return text;
}

function isAbstractLayerCategory(value) {
  const key = normalizeLayerGuidanceKey(value);
  return ["atmosphere", "composition", "interpretation", "condition"].includes(key);
}

function supportiveLayerMessage(layer, level, session) {
  if ((level || 1) <= 1) {
    return "";
  }
  if (layer?.dynamic) {
    if (level >= 5) return "Try the short helper sentence, or move forward if you made a reasonable attempt.";
    if (level >= 4) return "Use the sentence frame to finish this focus.";
    if (level >= 3) return "Choose one word that best matches what you see.";
    return "Let's notice one visible clue first.";
  }
  const key = normalizeLayerGuidanceKey(layer);
  const evidence = visibleEvidencePhrase(session?.analysis || {});
  if (level >= 3) {
    const direct = {
      atmosphere: evidence ? `Look at ${evidence} — what feeling do they create?` : "Let's make this easier. Finish the sentence with one feeling word.",
      composition: "Let's make this easier. Look for the closest or most noticeable part.",
      interpretation: evidence ? `Look at ${evidence} — what does that suggest?` : "Let's make this easier. Choose one simple idea the scene suggests.",
      condition: evidence ? `Look at ${evidence} — what condition does that show?` : "Let's make this easier. Choose one condition word.",
    };
    return direct[key] || "Let's make this easier.";
  }
  const guided = {
    atmosphere: "Try thinking about the condition or feeling of the place.",
    composition: "Try looking for what your eyes notice first.",
    interpretation: "Try choosing the simple idea the scene suggests.",
    condition: "Try thinking about whether it looks clean, messy, fresh, or neglected.",
  };
  return guided[key] || "Let's make this easier.";
}

function explicitImproveFocusText(category, session) {
  const analysis = session?.analysis || {};
  const subject = primarySubjectHint(analysis);
  const action = primaryActionPhrase(analysis);
  const background = primaryBackgroundHint(analysis);
  const object = primaryObjectHint(analysis, 1);
  const mood = primaryAtmosphereHint(analysis);
  const appearance = appearanceHintsForAnalysis(analysis, {}).find(Boolean);
  const composition = compositionHintsForAnalysis(analysis, {}).find(Boolean);
  const expression = expressionHintsForAnalysis(analysis, {}).find(Boolean);
  const text = {
    subject: subject ? `Mention ${combineSubjectAction(subject, action)}` : "Mention the main person, animal, or object",
    action: action ? `Mention the action: ${action}` : "Mention what the main subject is doing",
    background: background ? `Add the background detail: ${background}` : "Add one background detail",
    environment: background ? `Say where it happens: ${background}` : "Say where the scene happens",
    objects: object ? `Mention the important object: ${object}` : "Mention one important visible object",
    positioning: object ? `Place ${object} in the scene` : "Say where the important detail is",
    appearance: appearance ? `Add the visual detail: ${appearance}` : "Add one visual detail",
    composition: composition ? `Add composition language: ${composition}` : "Say what is in focus or where it appears",
    expression: expression ? `Mention the expression or posture: ${expression}` : "Mention the person's expression or posture",
    atmosphere: mood ? `Describe the atmosphere as ${mood}` : "Describe the atmosphere clearly",
    vocabulary: mood ? `Use a stronger word like ${mood}` : "Replace one general word with a stronger word",
  };
  return text[category] || "";
}

function improveEscalatedHints(session, category, level) {
  if (level <= 1) {
    return { contextual: [], direct: [] };
  }
  const analysis = session?.analysis || {};
  const subject = primarySubjectHint(analysis);
  const action = primaryActionPhrase(analysis);
  const actionVerb = primaryActionVerb(analysis);
  const background = primaryBackgroundHint(analysis);
  const object = primaryObjectHint(analysis, 1);
  const mood = primaryAtmosphereHint(analysis);
  const appearance = appearanceHintsForAnalysis(analysis, {}).find(Boolean);
  const composition = compositionHintsForAnalysis(analysis, {}).find(Boolean);
  const expression = expressionHintsForAnalysis(analysis, {}).find(Boolean);
  const evidence = visibleEvidencePhrase(analysis);
  const conditionWords = conditionHintWords(analysis);
  const atmosphereWords = atmosphereChoiceWords(analysis);
  const contextual = {
    subject: [subject, combineSubjectAction(subject, actionVerb)],
    action: [actionVerb, action],
    background: [background, background ? `in the background` : ""],
    environment: [background, background ? `in the scene` : ""],
    objects: [object, primaryObjectHint(analysis, 2)],
    positioning: [object, object ? `near ${object}` : "", background],
    appearance: [appearance, primarySubjectHint(analysis)],
    composition: [
      composition,
      object,
      "closest to the camera",
      "most noticeable",
      "in the foreground",
    ],
    expression: [expression],
    atmosphere: [
      ...atmosphereWords,
      ...conditionWords,
      mood,
      mood ? `${mood} atmosphere` : "",
    ],
    interpretation: ["daily life", "work", "relaxation", "disorder", "maintenance"],
    condition: conditionWords,
    vocabulary: [mood],
  };
  const direct = {
    subject: [combineSubjectAction(subject, action)],
    action: [action],
    background: [background],
    environment: [background],
    objects: [object],
    positioning: [object && background ? `${object} near ${background}` : object],
    appearance: [appearance],
    composition: [
      composition,
      object && `The object closest to the camera is ${object}`,
    ],
    expression: [expression],
    atmosphere: [
      evidence ? `Because of ${evidence}, the scene feels ___` : "The scene feels ___",
      ...conditionWords.slice(0, 4),
    ],
    interpretation: [
      evidence ? `Because of ${evidence}, the scene suggests ___` : "The scene suggests ___",
      "disorder",
      "maintenance",
      "daily life",
    ],
    condition: [
      evidence ? `Because of ${evidence}, it looks ___` : "It looks ___",
      ...conditionWords.slice(0, 4),
    ],
    vocabulary: [mood],
  };
  return {
    contextual: cleanLayerHints(contextual[category] || [], level >= 3 ? 7 : 5),
    direct: cleanLayerHints(direct[category] || [], 5),
  };
}

function primarySubjectHint(analysis) {
  return cleanUiText((analysis.objects || [])[0]?.name || (analysis.objects || [])[0]);
}

function primaryObjectHint(analysis, index = 0) {
  return cleanUiText((analysis.objects || [])[index]?.name || (analysis.objects || [])[index]);
}

function primaryActionPhrase(analysis) {
  const action = (analysis.actions || [])[0];
  return cleanUiText(action?.phrase || action?.verb || action);
}

function primaryActionVerb(analysis) {
  const action = (analysis.actions || [])[0];
  return cleanUiText(action?.verb || actionPhraseToVerb(action?.phrase || action));
}

function primaryBackgroundHint(analysis) {
  return cleanReusableHints([
    ...(analysis.environment_details || []),
    analysis.environment,
  ], "noun").find((item) => !normalizeClientText(item).includes(normalizeClientText(primarySubjectHint(analysis)))) || "";
}

function primaryAtmosphereHint(analysis) {
  return cleanReusableHints([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    analysis.environment,
    ...(analysis.environment_details || []),
  ], "adjective").find(atmosphereRelatedHint) || "";
}

function visibleEvidencePhrase(analysis = {}) {
  const details = [
    ...(analysis.environment_details || []),
    ...((analysis.objects || []).map((item) => item?.description || item?.name || item)),
    analysis.environment,
  ].map(cleanUiText).filter(Boolean);
  const evidence = details.find((item) =>
    /\b(wire|dust|dirty|messy|clutter|broken|damaged|exposed|blurred|crowded|empty|clean|bright|dark|foreground|background|closest|center)\b/i.test(item)
  ) || details[0] || "";
  return simplifyEvidencePhrase(evidence);
}

function simplifyEvidencePhrase(value) {
  return cleanUiText(value)
    .replace(/^there (is|are)\s+/i, "")
    .replace(/^a\s+|^an\s+|^the\s+/i, "")
    .replace(/[.!?]+$/g, "")
    .split(/\s*(?:,|;|\band\b)\s*/i)
    .map((item) => item.trim())
    .find((item) => item.split(/\s+/).length <= 6) || "";
}

function atmosphereChoiceWords(analysis = {}) {
  return uniqueWritingHints([
    primaryAtmosphereHint(analysis),
    "calm",
    "messy",
    "peaceful",
    "crowded",
    "neglected",
    "busy",
  ]).filter(Boolean);
}

function conditionHintWords(analysis = {}) {
  const evidence = normalizeClientText(visibleEvidencePhrase(analysis));
  const defaults = ["clean", "messy", "dusty", "cluttered", "well maintained", "neglected"];
  if (/\b(wire|dust|dirty|messy|clutter|broken|damaged|exposed)\b/.test(evidence)) {
    return ["neglected", "messy", "cluttered", "dusty", "not well maintained"];
  }
  return defaults;
}

function abstractSentenceFrames(category, analysis = {}, level = 1) {
  const evidence = visibleEvidencePhrase(analysis);
  const object = primaryObjectHint(analysis, 0) || primarySubjectHint(analysis) || "The main object";
  const frames = {
    atmosphere: level >= 3
      ? [evidence ? `Because of ${evidence}, the scene feels ___` : "The scene feels ___"]
      : ["The scene feels ___"],
    composition: level >= 3
      ? [`${object} stands out because it is ___`, "The closest object is ___"]
      : ["___ stands out visually"],
    interpretation: level >= 3
      ? [evidence ? `Because of ${evidence}, the scene suggests ___` : "The scene suggests ___"]
      : ["The scene suggests ___"],
    condition: level >= 3
      ? [evidence ? `Because of ${evidence}, it looks ___` : "It looks ___"]
      : ["The place looks ___"],
  };
  return cleanLayerHints(frames[category] || [], 3);
}

function cleanLayerHints(values, limit = 5) {
  return uniqueWritingHints(values.map(cleanUiText))
    .filter(Boolean)
    .map((item) => item.replace(/[.!?]+$/g, ""))
    .filter((item) => item.split(/\s+/).filter(Boolean).length <= 9)
    .slice(0, limit);
}

function buildDynamicTargetHintGroups(target, analysis = {}, level = 1) {
  const focus = cleanUiText(target.visualFocus || target.label);
  const pack = focusLanguagePack(target, analysis);
  const baseHints = cleanLayerHints([...(target.hints || []), ...(target.evidence || []), focus], level >= 3 ? 8 : 5);
  const choices = dynamicTargetChoices(target, { analysis });
  const nouns = uniqueWritingHints(cleanLayerHints([
    ...pack.nouns,
    focus,
    ...baseHints.filter((item) => !atmosphereRelatedHint(item) && !positioningRelatedHint(item)),
  ], level >= 3 ? 8 : 7).map(nounLikeHint).filter(Boolean)).slice(0, 5);
  const verbs = uniqueWritingHints(cleanLayerHints([
    ...pack.verbs,
    ...baseHints,
  ], 8).map(verbLikeHint).filter(Boolean)).slice(0, 4);
  const phraseHints = uniqueWritingHints(cleanLayerHints([
    ...pack.phrases,
    ...baseHints.filter(positioningRelatedHint),
    ...(target.category === "positioning" ? ["in the foreground", "in the background", "near ___", "under ___"] : []),
    ...(target.category === "lighting" ? ["soft light", "bright reflection", "natural light"] : []),
    ...(level >= 2 ? target.evidence || [] : []),
  ], 10).map(phraseLikeHint).filter(Boolean)).filter(usefulFocusedPhrase).slice(0, 5);
  const adjectiveHints = uniqueWritingHints(cleanLayerHints([
    ...pack.adjectives,
    ...(level >= 3 ? choices : []),
    ...baseHints.filter((item) => atmosphereRelatedHint(item) || conditionRelatedHint(item)),
    ...(["appearance", "texture", "contrast"].includes(target.category) ? ["bright", "dark", "smooth", "rough", "delicate"] : []),
    ...(target.category === "condition" ? conditionHintWords(analysis) : []),
    ...(target.category === "atmosphere" ? atmosphereChoiceWords(analysis) : []),
  ], level >= 3 ? 8 : 7).map(adjectiveLikeHint).filter(Boolean)).slice(0, 4);
  const frames = uniqueWritingHints([
    ...pack.frames,
    dynamicTargetSentenceFrame(target, analysis, level),
  ].filter(Boolean)).slice(0, 3);
  const groups = level >= 4
    ? [
      { label: "Nouns", items: nouns },
      { label: "Verbs", items: verbs },
      { label: "Adjectives", items: adjectiveHints },
      { label: "Sentence frames", items: frames },
    ]
    : [
    { label: "Nouns", items: nouns },
    { label: "Verbs", items: verbs },
    { label: "Phrases", items: phraseHints },
    { label: "Adjectives", items: adjectiveHints },
    { label: "Sentence frames", items: frames },
    ];
  return groups.filter((group) => group.items.length);
}

function focusLanguagePack(target = {}, analysis = {}) {
  const text = normalizeClientText(`${target.visualFocus || ""} ${target.label || ""} ${target.category || ""} ${(target.evidence || []).join(" ")}`);
  const packs = {
    greenery: {
      nouns: ["tree branches", "leaves", "roadside plants", "shaded area", "greenery"],
      verbs: ["stretching", "lining", "creating shade"],
      adjectives: ["dense", "leafy", "overhanging", "shaded"],
      phrases: ["branches stretching over the road", "leaves creating shade", "greenery along the roadside", "trees lining the street"],
      frames: ["The trees ___ over the road.", "The greenery creates ___.", "Along the roadside, there are ___."],
    },
    road: {
      nouns: ["road surface", "lane markings", "asphalt", "pavement", "street"],
      verbs: ["runs", "curves", "stretches"],
      adjectives: ["narrow", "empty", "busy", "urban"],
      phrases: ["along the roadside", "on the road surface", "down the street", "beside the road"],
      frames: ["The road looks ___ because ___.", "The street ___ through the scene.", "Along the road, there are ___."],
    },
    vehicles: {
      nouns: ["roadside vehicle", "moving car", "parked motorcycle", "traffic", "vehicles"],
      verbs: ["parked", "moving", "passing", "standing"],
      adjectives: ["busy", "parked", "small", "nearby"],
      phrases: ["vehicles on the road", "traffic along the street", "parked near the roadside", "moving through the scene"],
      frames: ["The vehicles are ___ on the road.", "There is ___ near the roadside.", "The traffic makes the scene feel ___."],
    },
    buildings: {
      nouns: ["tall buildings", "apartment buildings", "balconies", "concrete walls", "urban structures"],
      verbs: ["rise", "stand", "appear"],
      adjectives: ["tall", "distant", "concrete", "unfinished", "urban"],
      phrases: ["apartment buildings in the background", "concrete walls behind the trees", "urban structures above the greenery", "an unfinished structure in the distance"],
      frames: ["In the background, there are ___.", "The buildings look ___ behind the greenery.", "The unfinished structure adds ___."],
    },
    atmosphere: {
      nouns: ["shaded street", "quiet area", "urban scene", "roadside environment"],
      verbs: ["creates", "feels", "suggests"],
      adjectives: ["quiet", "shaded", "narrow", "calm", "urban", "slightly worn", "peaceful"],
      phrases: ["a quiet urban feeling", "a shaded roadside scene", "a calm atmosphere", "a slightly worn look"],
      frames: ["The scene feels ___.", "The shaded area creates ___.", "Overall, the place feels ___."],
    },
    lighting: {
      nouns: ["bright daylight", "shadows", "shaded area", "sunlight", "contrast"],
      verbs: ["shines", "creates", "highlights"],
      adjectives: ["bright", "shaded", "soft", "sunny"],
      phrases: ["bright daylight", "shadows on the road", "sunlight through the trees", "contrast between light and shade"],
      frames: ["The light makes the scene look ___.", "The shadows create ___.", "Sunlight highlights ___."],
    },
  };
  if (/\b(greenery|tree|trees|branches|leaves|plants|bushes|shrubs)\b/.test(text)) return packs.greenery;
  if (/\b(road|street|lane|asphalt|pavement)\b/.test(text)) return packs.road;
  if (/\b(vehicle|vehicles|car|cars|motorcycle|rickshaw|traffic)\b/.test(text)) return packs.vehicles;
  if (/\b(building|buildings|apartment|balcony|concrete|structure|construction|urban)\b/.test(text)) return packs.buildings;
  if (/\b(atmosphere|mood|feeling|quiet|calm|peaceful)\b/.test(text)) return packs.atmosphere;
  if (/\b(light|lighting|daylight|shadow|sunlight|shaded)\b/.test(text)) return packs.lighting;
  return {
    nouns: cleanLayerHints([target.visualFocus, ...(target.hints || [])], 5),
    verbs: [],
    adjectives: cleanLayerHints([...(target.hints || []), ...(target.evidence || [])], 4).map(adjectiveLikeHint).filter(Boolean),
    phrases: cleanLayerHints([...(target.hints || []), ...(target.evidence || [])], 5).map(phraseLikeHint).filter(usefulFocusedPhrase),
    frames: [],
  };
}

function usefulFocusedPhrase(value) {
  const text = normalizeClientText(value);
  return Boolean(text && !["nearby", "near", "behind", "under", "in the background", "in the foreground"].includes(text));
}

function dynamicTargetSentenceFrame(target, analysis = {}, level = 1) {
  const focus = cleanUiText(target.visualFocus || target.label || "this detail").replace(/^describe\s+/i, "");
  if (target.category === "atmosphere") {
    const evidence = cleanUiText((target.evidence || [])[0]) || visibleEvidencePhrase(analysis);
    return level >= 3 && evidence ? `Because of ${evidence}, the scene feels ___` : "The scene feels ___";
  }
  if (target.category === "condition") {
    const evidence = cleanUiText((target.evidence || [])[0]) || visibleEvidencePhrase(analysis);
    return level >= 3 && evidence ? `Because of ${evidence}, it looks ___` : "It looks ___";
  }
  if (target.category === "positioning") return `${focus || "It"} is near ___`;
  if (target.category === "lighting") return `The light near ${focus || "it"} looks ___`;
  if (["movement", "interaction"].includes(target.category)) return `${focus || "This part"} is happening ___`;
  return `The ${focus || "detail"} looks ___`;
}

function combineSubjectAction(subject, action) {
  const cleanSubject = cleanUiText(subject);
  const cleanAction = cleanUiText(action);
  if (!cleanSubject) return cleanAction;
  if (!cleanAction) return cleanSubject;
  const actionKey = normalizeClientText(cleanAction);
  if (normalizeClientText(cleanSubject).includes(actionKey)) {
    return cleanSubject;
  }
  return `${cleanSubject} ${cleanAction}`;
}

function buildImproveHintGroups(session, feedback, issue, currentText, escalation = {}) {
  const analysis = session?.analysis || {};
  if (issue?.target?.dynamic) {
    return buildDynamicTargetHintGroups(issue.target, analysis, escalation.level || 1);
  }
  const guidance = feedback?.specific_guidance || {};
  const focus = normalizeClientText(issue?.focusAreas?.join(" ") || issue?.message || "");
  const focusCategory = improveFocusCategory(focus);
  const level = escalation.level || 1;
  const subjectHints = categorizedHintItems([
    cleanUiText((analysis.objects || [])[0]?.name || (analysis.objects || [])[0]),
    ...(issue?.additions || []),
  ], "noun", ["subject", "objects"]);
  const objectHints = categorizedHintItems([
    ...((analysis.objects || []).map((item) => item?.name || item)),
    ...cleanUiList(guidance.nouns || [], 5),
    ...(issue?.additions || []),
  ], "noun", ["objects", "subject"]);
  const actionHints = categorizedHintItems([
    ...((analysis.actions || []).map((item) => item?.verb || actionPhraseToVerb(item?.phrase || item))),
    ...((analysis.actions || []).map((item) => item?.phrase || "")),
    ...cleanUiList(guidance.verbs || [], 5),
  ], "verb", ["action", "subject"]);
  const environmentHints = categorizedHintItems([
    analysis.environment,
    ...(analysis.environment_details || []),
    ...cleanUiList(guidance.details || [], 5),
  ], "noun", ["background", "environment"]);
  const positioningHints = categorizedHintItems([
    ...buildStructureHints(analysis),
    ...cleanUiList(guidance.details || [], 5),
    ...buildImprovePhraseSuggestions(session, feedback, currentText),
  ], "phrase", ["background", "environment", "positioning"]);
  const atmosphereHints = categorizedHintItems([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(guidance.words || [], 5),
    analysis.environment,
    ...(analysis.environment_details || []),
    ...cleanUiList(guidance.details || [], 5),
  ], "adjective", ["atmosphere", "vocabulary"]).filter((item) => atmosphereRelatedHint(item.text));
  const appearanceHints = categorizedHintItems([
    ...appearanceHintsForAnalysis(analysis, feedback),
    ...cleanUiList(guidance.words || [], 5),
  ], "phrase", ["appearance", "vocabulary"]);
  const compositionHints = categorizedHintItems([
    ...compositionHintsForAnalysis(analysis, feedback),
    ...buildImprovePhraseSuggestions(session, feedback, currentText),
  ], "phrase", ["composition", "positioning"]);
  const expressionHints = categorizedHintItems([
    ...expressionHintsForAnalysis(analysis, feedback),
    ...cleanUiList(guidance.words || [], 5),
  ], "phrase", ["expression", "atmosphere"]);
  const vocabularyHints = categorizedHintItems([
    ...((analysis.vocabulary || []).map((item) => item?.word || item?.phrase || item)),
    ...cleanUiList(guidance.words || [], 5),
  ], "adjective", ["vocabulary"]).filter((item) => !hintListText(objectHints).some((noun) => normalizeClientText(noun).includes(normalizeClientText(item.text))));
  const structures = cleanSentenceFrames([
    cleanUiText(guidance.sentence_starter),
    ...cleanUiList(feedback?.reusable_sentence_structures || [], 2),
    ...((analysis.sentence_patterns || []).map((item) => item?.pattern || "")),
    defaultImproveStructureForFocus(focus),
  ]);
  const scoped = (items, category, limit) => hintListText(items.filter((item) => item.categories.includes(category))).slice(0, limit);
  const scopedPhrases = (category, limit) => scoped(positioningHints, category, limit).filter((item) => !unrelatedToImproveFocus(item, category));
  const atmosphereWords = scoped(atmosphereHints, "atmosphere", 8);
  const escalatedHints = improveEscalatedHints(session, focusCategory, level);
  const smallChunks = (items) => items.filter((item) => item.split(/\s+/).length <= 2);
  const leveled = (baseItems, category, limit) => {
    const extras = level >= 2 ? escalatedHints.contextual : [];
    const direct = level >= 3 ? escalatedHints.direct : [];
    return uniqueWritingHints([...direct, ...extras, ...baseItems])
      .filter((item) => !unrelatedToImproveFocus(item, category))
      .slice(0, limit);
  };

  const plans = {
    subject: [
      { label: "Nouns", items: leveled(scoped(subjectHints, "subject", 4).length ? scoped(subjectHints, "subject", 4) : scoped(objectHints, "subject", 4), "subject", level >= 3 ? 5 : 4) },
      { label: level >= 2 ? "Useful phrases" : "Verbs", items: leveled(level >= 2 ? scoped(actionHints, "subject", 3) : smallChunks(scoped(actionHints, "subject", 5)), "subject", level >= 2 ? 4 : 3) },
      { label: "Structures", items: focusStructures(structures, "subject").slice(0, 2) },
    ],
    action: [
      { label: level >= 2 ? "Action phrases" : "Verbs", items: leveled(level >= 2 ? scoped(actionHints, "action", 5) : smallChunks(scoped(actionHints, "action", 5)), "action", 5) },
      { label: "Structures", items: focusStructures(structures, "action").slice(0, 2) },
    ],
    background: [
      { label: "Nouns", items: leveled(scoped(environmentHints, "background", 5), "background", 5) },
      { label: "Positioning", items: leveled(scopedPhrases("background", 4), "background", 4) },
      { label: "Structures", items: focusStructures(structures, "background").slice(0, 2) },
    ],
    environment: [
      { label: "Nouns", items: leveled(scoped(environmentHints, "environment", 5), "environment", 5) },
      { label: "Positioning", items: leveled(scopedPhrases("environment", 4), "environment", 4) },
      { label: "Structures", items: focusStructures(structures, "background").slice(0, 1) },
    ],
    appearance: [
      { label: "Nouns", items: leveled(scoped(objectHints, "objects", 4), "objects", 4) },
      { label: "Adjectives", items: leveled(scoped(appearanceHints, "appearance", 5), "appearance", 5) },
      { label: "Structures", items: focusStructures(structures, "appearance").slice(0, 2) },
    ],
    objects: [
      { label: "Nouns", items: leveled(scoped(objectHints, "objects", 5), "objects", 5) },
      { label: "Positioning", items: leveled(scopedPhrases("positioning", 3), "positioning", 3) },
      { label: "Structures", items: focusStructures(structures, "object").slice(0, 2) },
    ],
    composition: [
      { label: level >= 2 ? "Look for" : "Composition phrases", items: leveled(scoped(compositionHints, "composition", 5), "composition", 5) },
      { label: "Nouns", items: uniqueWritingHints([...scoped(objectHints, "objects", 3), ...scoped(environmentHints, "environment", 3)]).slice(0, 3) },
      { label: "Sentence frame", items: level >= 3 ? abstractSentenceFrames("composition", analysis, level) : focusStructures(structures, "composition").slice(0, 2) },
    ],
    positioning: [
      { label: "Positioning", items: leveled(scopedPhrases("positioning", 5), "positioning", 5) },
      { label: "Nouns", items: uniqueWritingHints([...scoped(objectHints, "objects", 3), ...scoped(environmentHints, "environment", 3)]).slice(0, 3) },
      { label: "Structures", items: focusStructures(structures, "positioning").slice(0, 2) },
    ],
    expression: [
      { label: "Expression and posture", items: leveled(scoped(expressionHints, "expression", 5), "expression", 5) },
      { label: "Structures", items: focusStructures(structures, "expression").slice(0, 2) },
    ],
    atmosphere: [
      { label: level >= 2 ? "Choices" : "Adjectives", items: leveled(uniqueWritingHints([...atmosphereWords.filter((item) => item.split(/\s+/).length <= 2), ...conditionHintWords(analysis)]), "atmosphere", level >= 3 ? 6 : 5) },
      { label: level >= 3 ? "Visible evidence" : "Contrast", items: level >= 2 ? cleanLayerHints([visibleEvidencePhrase(analysis), "clean or messy", "calm or crowded", "fresh or neglected"], 4) : leveled(atmosphereWords.filter((item) => item.split(/\s+/).length > 2), "atmosphere", 3) },
      { label: "Sentence frame", items: abstractSentenceFrames("atmosphere", analysis, level) },
    ],
    interpretation: [
      { label: level >= 2 ? "Choices" : "Ideas", items: leveled(["daily life", "work", "relaxation", "disorder", "maintenance"], "interpretation", 5) },
      { label: "Visible evidence", items: cleanLayerHints([visibleEvidencePhrase(analysis), "messy details", "daily objects"], 3) },
      { label: "Sentence frame", items: abstractSentenceFrames("interpretation", analysis, level) },
    ],
    condition: [
      { label: level >= 2 ? "Choices" : "Adjectives", items: leveled(conditionHintWords(analysis), "condition", 6) },
      { label: "Visible evidence", items: cleanLayerHints([visibleEvidencePhrase(analysis), "dust", "exposed wires", "clutter"], 4) },
      { label: "Sentence frame", items: abstractSentenceFrames("condition", analysis, level) },
    ],
    vocabulary: [
      { label: "Adjectives", items: leveled(uniqueWritingHints([...scoped(vocabularyHints, "vocabulary", 5), ...scoped(atmosphereHints, "vocabulary", 5)]), "vocabulary", 5) },
      { label: "Structures", items: focusStructures(structures, "vocabulary").slice(0, 2) },
    ],
    complete: [
      { label: "Nouns", items: scoped(objectHints, "objects", 3) },
      { label: "Verbs", items: scoped(actionHints, "action", 3) },
      { label: "Structures", items: structures.slice(0, 1) },
    ],
  };
  return (plans[focusCategory] || plans.complete).filter((group) => group.items.length);
}

function categorizedHintItems(values, kind, categories) {
  return cleanReusableHints(values, kind).map((text) => ({
    text,
    categories: categoriesForHint(text, categories),
  }));
}

function categoriesForHint(value, baseCategories) {
  const categories = new Set(baseCategories);
  const text = normalizeClientText(value);
  if (/\b(background|behind|distant|sky|lawn|grass|trees|bushes|street|room|wall|field|yard)\b/.test(text)) {
    categories.add("background");
    categories.add("environment");
  }
  if (/\b(in|on|near|along|beside|behind|around|across|through|under|next to)\b/.test(text)) {
    categories.add("positioning");
  }
  if (actionRelatedHint(value)) {
    categories.add("action");
  }
  if (atmosphereRelatedHint(value)) {
    categories.add("atmosphere");
    categories.add("vocabulary");
  }
  return [...categories];
}

function hintListText(items) {
  return uniqueWritingHints(items.map((item) => item.text || item));
}

function unrelatedToImproveFocus(value, category) {
  if (/\b___\b/.test(value)) {
    return false;
  }
  if (["background", "environment", "positioning"].includes(category)) {
    return actionRelatedHint(value) && !positioningRelatedHint(value);
  }
  if (category === "atmosphere") {
    return !atmosphereRelatedHint(value);
  }
  return false;
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

function improveFocusCategory(focus) {
  if (focus.includes("main subject") || focus.includes("subject") || focus === "person") return "subject";
  if (focus.includes("main action") || focus.includes("action") || focus.includes("happening")) return "action";
  if (focus.includes("background")) return "background";
  if (focus.includes("setting") || focus.includes("environment") || focus.includes("surroundings")) return "environment";
  if (focus.includes("foreground") || focus.includes("position")) return "positioning";
  if (focus.includes("appearance") || focus.includes("visual")) return "appearance";
  if (focus.includes("composition") || focus.includes("layout") || focus.includes("focus")) return "composition";
  if (focus.includes("interpret") || focus.includes("suggest")) return "interpretation";
  if (focus.includes("condition") || focus.includes("maintained") || focus.includes("messy") || focus.includes("clean")) return "condition";
  if (focus.includes("expression") || focus.includes("posture")) return "expression";
  if (focus.includes("object") || focus.includes("visible detail")) return "objects";
  if (focus.includes("mood") || focus.includes("atmosphere")) return "atmosphere";
  if (focus.includes("wording") || focus.includes("vocabulary")) return "vocabulary";
  return "complete";
}

function focusStructures(structures, category) {
  const defaults = {
    subject: ["The main subject is ___"],
    action: ["The person is ___"],
    background: ["In the background, there are ___"],
    object: ["The scene includes ___"],
    positioning: ["___ is near ___"],
    appearance: ["The object appears ___"],
    composition: ["___ is in focus"],
    expression: ["The person looks ___"],
    atmosphere: ["The scene feels ___"],
    interpretation: ["The scene suggests ___"],
    condition: ["The place looks ___"],
    vocabulary: ["The scene looks ___"],
  };
  const keywords = {
    subject: /subject|person|main/i,
    action: /is ___|doing|action/i,
    background: /background|there are|behind/i,
    object: /includes|shows/i,
    positioning: /near|beside|behind|in the|on the/i,
    appearance: /appears|looks|has|bright|soft|color/i,
    composition: /focus|foreground|background|center|stands out/i,
    expression: /person|looks|posture|expression/i,
    atmosphere: /feels|looks/i,
    interpretation: /suggests|shows|because/i,
    condition: /looks|condition|maintained/i,
    vocabulary: /looks|appears|feels/i,
  };
  return uniqueWritingHints([
    ...structures.filter((item) => (keywords[category] || /___/).test(item)),
    ...(defaults[category] || ["The scene shows ___"]),
  ]);
}

function actionRelatedHint(value) {
  return /\b(ing|move|moving|walk|walking|ride|riding|hold|holding|look|looking|stand|standing|drive|driving|run|running)\b/i.test(value);
}

function positioningRelatedHint(value) {
  return /\b(in|on|near|along|beside|behind|around|across|through|under|next to|foreground|background)\b/i.test(value);
}

function atmosphereRelatedHint(value) {
  return /\b(quiet|busy|calm|bright|dark|peaceful|crowded|clean|messy|dusty|cluttered|neglected|maintained|well-kept|sunny|focused|lively|warm|serene|dramatic|inviting)\b/i.test(value);
}

function conditionRelatedHint(value) {
  return /\b(clean|messy|dusty|dirty|cluttered|neglected|maintained|well-kept|broken|damaged|worn|exposed|tidy|poorly maintained|not well maintained)\b/i.test(value);
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
  onInitialAttemptInput({ target: input });
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
  onInitialAttemptInput({ target: input });
  input.focus();
}

function onInitialAttemptInput(event) {
  const input = event.target;
  const starter = state.sessionFlow?.initialStarterText || "";
  if (state.sessionFlow) {
    state.sessionFlow.initialStarterTouched = true;
  }
  limitWritingInput(event);
  const value = input.value || "";
  const stillOnlyStarter = starter && normalizeClientText(value) === normalizeClientText(starter);
  input.classList.toggle("starter-prefill", Boolean(stillOnlyStarter));
}

function limitWritingInput(event) {
  const input = event.target;
  if (input.id === "learnerExplanationInput") {
    input.value = String(input.value || "").slice(0, 250);
    const count = document.getElementById("initialAttemptCount");
    if (count) {
      count.textContent = `${input.value.length}/250`;
    }
  }
  const sentences = String(input.value || "").match(/[^.!?]+[.!?]*/g) || [];
  if (sentences.length <= 2) {
    return;
  }
  input.value = sentences.slice(0, 2).join("").trimStart();
  const count = document.getElementById("initialAttemptCount");
  if (count) {
    count.textContent = `${input.value.length}/250`;
  }
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

function isExplanationReady(feedback, session = state.currentSession || {}) {
  if (!feedback) {
    return false;
  }
  return coverageCompletionGate(feedback, session).complete;
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
  input.dispatchEvent(new Event("input", { bubbles: true }));
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
  els.uploadProcessingLabel?.classList.add("hidden");
  els.fileNameLabel.textContent = "JPG, PNG up to 10MB";
}

function openImagePicker(mode = "gallery") {
  if (mode === "camera") {
    els.imageInput.setAttribute("capture", "environment");
  } else {
    els.imageInput.removeAttribute("capture");
  }
  els.imageInput.click();
}

async function onFileChange() {
  const file = els.imageInput.files[0];
  resetUploadPreview();
  if (!file) {
    els.analyzeButton.disabled = !state.user;
    return;
  }

  state.uploadPreviewUrl = URL.createObjectURL(file);
  els.imagePreview.src = state.uploadPreviewUrl;
  els.imagePreviewShell.classList.remove("hidden");
  els.uploadPlaceholder.classList.add("hidden");
  els.fileNameLabel.textContent = `${file.name} (${formatBytes(file.size)})`;
  els.analyzeButton.disabled = !state.user;
  if (!state.user) {
    showToast("Please log in first.", true);
    return;
  }
  await startImageAnalysis();
}

function openNewSessionComposer() {
  state.learnView = "compose";
  closeLanguageModal();
  resetUploadPreview();
  els.analyzeForm.reset();
  els.analyzeButton.disabled = !state.user;
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
  event?.preventDefault?.();
  await startImageAnalysis();
}

async function startImageAnalysis() {
  if (!state.user) {
    showToast("Please log in first.", true);
    return;
  }

  const imageFile = els.imageInput.files[0];
  if (!imageFile) {
    showToast("Choose an image before starting guided writing.", true);
    return;
  }

  els.uploadProcessingLabel?.classList.remove("hidden");
  setButtonBusy(els.analyzeButton, true, "Preparing...");
  showSessionThinkingState("Preparing guided writing...", [
    "Analyzing the image",
    "Finding visible objects",
    "Preparing beginner hints",
  ]);
  try {
    const uploadFile = await prepareImageForUpload(imageFile);
    if (uploadFile.size !== imageFile.size) {
      els.fileNameLabel.textContent = `${imageFile.name} (${formatBytes(imageFile.size)} -> ${formatBytes(uploadFile.size)})`;
    }
    const formData = new FormData();
    formData.append("image", uploadFile, uploadFile.name || imageFile.name);
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
    els.uploadProcessingLabel?.classList.add("hidden");
    setButtonBusy(els.analyzeButton, false, "Choose Image");
  }
}

async function prepareImageForUpload(file) {
  const maxBytes = Math.min(Number(state.settings.max_upload_bytes || 25 * 1024 * 1024), 10 * 1024 * 1024);
  if (!file.type.startsWith("image/")) {
    throw new Error("Please upload an image file.");
  }
  if (file.size <= Math.min(maxBytes, IMAGE_UPLOAD_TARGET_BYTES) || file.type === "image/gif") {
    if (file.size > maxBytes) {
      throw new Error(`That image is too large. Please choose an image under ${formatBytes(maxBytes)}.`);
    }
    return file;
  }

  try {
    const image = await loadImageForCompression(file);
    const scale = Math.min(1, IMAGE_UPLOAD_MAX_DIMENSION / Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height));
    const width = Math.max(1, Math.round((image.naturalWidth || image.width) * scale));
    const height = Math.max(1, Math.round((image.naturalHeight || image.height) * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    context.drawImage(image, 0, 0, width, height);

    const targetBytes = Math.min(maxBytes * 0.9, IMAGE_UPLOAD_TARGET_BYTES);
    let quality = 0.88;
    let blob = await canvasToBlob(canvas, "image/jpeg", quality);
    while (blob && blob.size > targetBytes && quality > 0.55) {
      quality -= 0.08;
      blob = await canvasToBlob(canvas, "image/jpeg", quality);
    }
    if (!blob || blob.size > maxBytes) {
      if (file.size <= maxBytes) return file;
      throw new Error(`That image is too large. Please choose an image under ${formatBytes(maxBytes)}.`);
    }
    const baseName = file.name.replace(/\.[^.]+$/, "") || "upload-image";
    return new File([blob], `${baseName}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
  } catch (error) {
    if (file.size <= maxBytes) {
      return file;
    }
    throw error;
  }
}

function loadImageForCompression(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("This image could not be prepared for upload."));
    };
    image.src = url;
  });
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => {
    canvas.toBlob(resolve, type, quality);
  });
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
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
  showSessionThinkingState("Finding ways to improve your wording...", [
    "Reading your sentence",
    "Looking for major wording upgrades",
    "Preparing your choices",
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
      stage: data.learning_stage || data.stage || feedback.learning_stage || LEARNING_STAGES.FIRST_FEEDBACK,
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
    awardNewLayerCompletionXp(session, feedback, explanation);
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
  showSessionThinkingState("Checking this layer...", [
    "Comparing with the image reference",
    "Finding the next missing details",
    "Checking whether the layer is covered",
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
    const previousFeedback = (state.sessionFlow.attempts || []).at(-1)?.feedback || state.sessionFlow.feedback || {};
    const serverStage = normalizeLearningStage(data.learning_stage || data.stage || feedback.learning_stage);
    const nextStage =
      serverStage === LEARNING_STAGES.COVERAGE_LAYERS && didCoverageImprove(previousFeedback, feedback)
        ? LEARNING_STAGES.LAYER_SUCCESS
        : serverStage || null;
    const attempts = [
      ...(state.sessionFlow.attempts || []),
      {
        text: improvedText,
        feedback,
        score: feedbackTotalScore(feedback),
      },
    ];
    renderSessionStep("improve", {
      stage: nextStage,
      attempts,
      polishMode: false,
    });
    awardNewLayerCompletionXp(session, feedback, improvedText);
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    showToast(error.message, true);
    renderSessionStep("improve");
  } finally {
    setButtonBusy(button, false, "Check Again");
  }
}

function didCoverageImprove(previousFeedback = {}, nextFeedback = {}) {
  const before = Number(previousFeedback?.coverage_engine?.score || previousFeedback?.coverage?.coveragePercent || previousFeedback?.coverage?.coverageScore || 0);
  const after = Number(nextFeedback?.coverage_engine?.score || nextFeedback?.coverage?.coveragePercent || nextFeedback?.coverage?.coverageScore || 0);
  if (after >= before + 8) {
    return true;
  }
  const beforeCovered = new Set(coveredFeedbackTypes(previousFeedback));
  return coveredFeedbackTypes(nextFeedback).some((type) => !beforeCovered.has(type));
}

async function startPostImproveQuiz(session) {
  if (state.sessionFlow.quizLaunchStarted) {
    return;
  }
  state.sessionFlow.quizLaunchStarted = true;
  state.sessionFlow.stage = LEARNING_STAGES.QUIZ;
  if (state.currentSession) {
    state.currentSession.learning_stage = LEARNING_STAGES.QUIZ;
  }
  const button = document.getElementById("continueToQuizButton");
  const attempts = state.sessionFlow.attempts || [];
  const firstAttempt = attempts[0] || {};
  const latestAttempt = attempts[attempts.length - 1] || {};
  const finalUpgrade = state.sessionFlow.articulationUpgrade;
  const finalImprovedText = finalUpgrade?.finalized
    ? finalUpgrade.answer || latestAttempt.text || ""
    : latestAttempt.text || "";
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
        improved_text: finalImprovedText,
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

  if (showCompose) {
    updateAppHeaderForStage(LEARNING_STAGES.UPLOAD_IMAGE);
  } else {
    document.querySelector(".app-topbar")?.classList.remove("upload-app-header");
  }
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
        <div id="quizAnswerZone"></div>
      </section>
    </div>
  `;

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
        confidence: 2,
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
        confidence: 2,
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
    if (response.status === 413) {
      throw new Error(`That image is too large. Please choose a smaller image or let the app compress it below ${formatBytes(state.settings.max_upload_bytes)}.`);
    }
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
