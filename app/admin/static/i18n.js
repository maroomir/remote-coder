(function (window) {
  // NOTE: English is the canonical text in the templates. This catalog overlays
  // Korean when window.__UI_LANG__ === "ko" (set server-side from ui_language).
  // t(key) localizes keyed strings; tv(value) localizes backend-supplied values
  // by reverse English lookup; apply() rewrites [data-i18n*] elements on load.
  var CATALOG = {
    // shared: navigation + page chrome
    "nav.aria": { en: "Page navigation", ko: "페이지 이동" },
    "nav.home": { en: "Admin home", ko: "관리 홈" },
    "nav.projects": { en: "Projects", ko: "프로젝트 등록" },
    "nav.advanced": { en: "Advanced settings", ko: "고급 설정" },
    "nav.logs": { en: "Server logs", ko: "서버 로그" },
    "nav.database": { en: "Data browser", ko: "데이터 조회" },
    "common.localOnly": { en: "Local only", ko: "로컬 전용" },
    "common.localhostNote": {
      en: "This page is only available from <strong>127.0.0.1</strong>.",
      ko: "이 페이지는 <strong>127.0.0.1</strong>에서만 열립니다.",
    },
    "common.summaryAria": { en: "Summary", ko: "요약" },

    // shared: small labels reused across pages
    "common.none": { en: "(none)", ko: "(없음)" },
    "common.all": { en: "All", ko: "전체" },
    "common.off": { en: "Off", ko: "끔" },
    "common.set": { en: "Set", ko: "설정됨" },
    "common.unset": { en: "Not set", ko: "미설정" },
    "common.notSet": { en: "(not set)", ko: "(설정 안 됨)" },
    "common.name": { en: "Name", ko: "이름" },
    "common.status": { en: "Status", ko: "상태" },
    "common.model": { en: "Model", ko: "모델" },
    "common.actions": { en: "Actions", ko: "동작" },
    "common.root": { en: "Root", ko: "루트" },
    "common.worktree": { en: "Worktree", ko: "워크트리" },
    "common.defaultModel": { en: "Default model", ko: "기본 모델" },
    "common.enabled": { en: "Enabled", ko: "활성" },
    "common.allowedChatIds": { en: "Allowed Chat IDs", ko: "허용 Chat ID" },
    "common.allowedUserIds": { en: "Allowed User IDs", ko: "허용 User ID" },
    "common.edit": { en: "Edit", ko: "편집" },
    "common.delete": { en: "Delete", ko: "삭제" },
    "common.search": { en: "Search", ko: "검색" },
    "common.prev": { en: "Prev", ko: "이전" },
    "common.next": { en: "Next", ko: "다음" },
    "common.close": { en: "Close", ko: "닫기" },
    "common.fallbackDefault": { en: "Fallback default", ko: "폴백 기본" },
    "common.secondsSuffix": { en: "s", ko: "초" },

    // summary cards (summary.js)
    "summary.registered": { en: "Registered projects", ko: "등록 프로젝트" },
    "summary.active": { en: "Active", ko: "활성" },
    "summary.jobTimeout": { en: "Job timeout", ko: "작업 타임아웃" },
    "summary.gitRemote": { en: "Git remote", ko: "Git 원격" },

    // page titles
    "title.admin": { en: "Remote AI Coder - Admin", ko: "Remote AI Coder - 관리" },
    "title.projects": { en: "Remote AI Coder - Projects", ko: "Remote AI Coder - 프로젝트 등록" },
    "title.advanced": { en: "Remote AI Coder - Advanced Settings", ko: "Remote AI Coder - 고급 설정" },
    "title.logs": { en: "Remote AI Coder - Server Logs", ko: "Remote AI Coder - 서버 로그" },
    "title.database": { en: "Remote AI Coder - Data Browser", ko: "Remote AI Coder - 데이터 조회" },

    // admin.html (hub)
    "admin.tagline": { en: "Local admin UI", ko: "로컬 관리 UI" },
    "admin.activeProjects": { en: "Active projects", ko: "활성 프로젝트" },
    "admin.manageLink": { en: "Manage", ko: "등록·편집" },
    "admin.activeLead": {
      en: "Only enabled projects are shown. Add, disable, or delete them on the Projects page.",
      ko: "활성화된 프로젝트만 표시합니다. 추가·비활성·삭제는 프로젝트 등록 화면에서 할 수 있습니다.",
    },
    "admin.configSummary": { en: "Configuration files", ko: "설정 파일" },
    "admin.configLead": {
      en: "Registry and advanced settings file paths. Project bots and allowlists live in the registry.",
      ko: "레지스트리와 고급 설정 파일 경로입니다. 봇·allowlist는 레지스트리에 저장됩니다.",
    },
    "admin.noActiveHtml": {
      en: 'No active projects. Add or enable one on the <a href="/projects" class="link-manage">Projects</a> page.',
      ko: '활성화된 프로젝트가 없습니다. <a href="/projects" class="link-manage">프로젝트 등록</a>에서 추가·활성화할 수 있습니다.',
    },
    "admin.projectsConfigFile": { en: "Projects config file", ko: "프로젝트 설정 파일" },
    "admin.advancedSettingsFile": { en: "Advanced settings file", ko: "고급 설정 파일" },
    "admin.gitRemoteName": { en: "Git remote name", ko: "Git 원격 이름" },
    "admin.codexSandbox": { en: "Codex sandbox", ko: "Codex 샌드박스" },
    "admin.webhookSecret": { en: "Webhook secret", ko: "Webhook 시크릿" },
    "admin.webhookHintLabel": { en: "Webhook guide", ko: "Webhook 안내" },

    "setup.title": { en: "First-time setup", ko: "최초 설정" },
    "setup.lead": {
      en: "No projects registered yet. Check the prerequisites below, then add your first project to bring a Telegram bot online.",
      ko: "아직 등록된 프로젝트가 없습니다. 아래 전제조건을 확인한 뒤 첫 프로젝트를 추가하면 Telegram 봇이 연결됩니다.",
    },
    "setup.prereqTitle": { en: "Prerequisites", ko: "전제조건" },
    "setup.ngrok": { en: "ngrok tunnel", ko: "ngrok 터널" },
    "setup.aiCli": { en: "AI CLI", ko: "AI CLI" },
    "setup.aiCliNone": {
      en: "None found (install at least one: claude / codex / gemini)",
      ko: "설치된 것 없음 (claude / codex / gemini 중 최소 1개 설치)",
    },
    "setup.checking": { en: "Checking…", ko: "확인 중…" },
    "setup.recheck": { en: "Re-check", ko: "다시 확인" },
    "setup.cta": { en: "Add your first project", ko: "첫 프로젝트 추가" },
    "setup.nextNote": {
      en: "Once a project is added while the server is running, its bot goes live automatically.",
      ko: "서버가 실행 중일 때 프로젝트를 추가하면 해당 봇이 자동으로 연결됩니다.",
    },

    // projects.html
    "projects.h1": { en: "Project registration", ko: "프로젝트 등록" },
    "projects.tagline": {
      en: "Each entry is bound to <strong>one Telegram bot</strong> and a fixed repository.",
      ko: "각 등록 항목은 <strong>하나의 Telegram 봇</strong>과 고정된 저장소에 연결됩니다.",
    },
    "projects.listHeading": { en: "Registered projects", ko: "등록 목록" },
    "projects.listLead": {
      en: "Add a project or pick the fallback default. Saving is applied immediately to the running server's <code>BotInstanceManager</code>.",
      ko: "프로젝트를 추가하거나 기본 폴백 프로젝트를 지정합니다. 저장 시 실행 중인 서버의 <code>BotInstanceManager</code>에 즉시 반영됩니다.",
    },
    "projects.colGitRoot": { en: "Git root", ko: "Git 루트" },
    "projects.formHeading": { en: "Add / edit", ko: "추가 / 수정" },
    "projects.addNew": { en: "Add new project", ko: "새 프로젝트 추가" },
    "projects.editingPrefix": { en: "Editing: ", ko: "편집 중: " },
    "projects.nameHint": {
      en: "Start with a letter or digit; <code>.</code> <code>_</code> <code>-</code> allowed",
      ko: "영문·숫자로 시작, <code>.</code> <code>_</code> <code>-</code> 허용",
    },
    "projects.gitRootPath": { en: "Git root path", ko: "Git 루트 경로" },
    "projects.gitRootHint": {
      en: "Absolute path. The directory must exist to save.",
      ko: "절대 경로. 디렉터리가 존재해야 저장됩니다.",
    },
    "projects.botToken": { en: "Bot token", ko: "봇 토큰" },
    "projects.botTokenHint": {
      en: "API token from Telegram BotFather after <code>/newbot</code>. The plaintext is stored only in the registry file; lists and APIs show a masked value.",
      ko: "Telegram의 BotFather에서 <code>/newbot</code> 후 받은 API 토큰. 평문은 레지스트리 파일에만 저장되며, 목록·API에는 마스킹된 값만 표시됩니다.",
    },
    "projects.chatIdsHint": {
      en: "Comma- or space-separated. At least one.",
      ko: "쉼표 또는 공백으로 구분. 최소 1개.",
    },
    "projects.optional": { en: "Optional fields", ko: "선택 항목" },
    "projects.webhookSecret": { en: "Webhook secret (optional)", ko: "웹훅 시크릿 (선택)" },
    "projects.webhookSecretHint": {
      en: "Telegram <code>secret_token</code>. Leave blank when editing to keep the existing value.",
      ko: "Telegram <code>secret_token</code>. 편집 시 비우면 기존 값 유지.",
    },
    "projects.allowedUserIdsOptional": { en: "Allowed User IDs (optional)", ko: "허용 User ID (선택)" },
    "projects.userIdsHint": {
      en: "Blank allows by chat ID only.",
      ko: "비우면 채팅 ID만으로 허용합니다.",
    },
    "projects.btnAdd": { en: "Add", ko: "추가" },
    "projects.btnSave": { en: "Save (PUT)", ko: "저장 (PUT)" },
    "projects.btnClear": { en: "Clear form", ko: "폼 비우기" },
    "projects.captionDefault": { en: "Registry fallback default: ", ko: "등록 폴백 기본값: " },
    "projects.emptyRow": {
      en: "No projects registered. Add one with the form below.",
      ko: "등록된 프로젝트가 없습니다. 아래 폼에서 추가하세요.",
    },
    "projects.badgeDefault": { en: "Default", ko: "기본" },
    "projects.badgeOn": { en: "Enabled", ko: "활성" },
    "projects.badgeOff": { en: "Disabled", ko: "비활성" },
    "projects.secretBadge": { en: "Secret", ko: "시크릿" },
    "projects.secretSetTitle": { en: "Webhook secret set", ko: "웹훅 시크릿 설정됨" },
    "projects.maskedTokenTitle": { en: "Masked bot token", ko: "마스킹된 봇 토큰" },
    "projects.btnMakeDefault": { en: "Make default", ko: "기본으로" },
    "projects.setDefaultOk": {
      en: 'Set default project to "{name}".',
      ko: '기본 프로젝트를 "{name}"(으)로 설정했습니다.',
    },
    "projects.confirmDelete": {
      en: 'Delete project "{name}"? This cannot be undone.',
      ko: '프로젝트 "{name}"을(를) 삭제할까요? 이 작업은 되돌릴 수 없습니다.',
    },
    "projects.deletedOk": { en: "Deleted.", ko: "삭제했습니다." },
    "projects.editInfo": {
      en: "Name cannot be changed. Leave the bot token and webhook secret blank to keep existing values.",
      ko: "이름은 변경할 수 없습니다. 봇 토큰·웹훅 시크릿은 비워 두면 기존 값이 유지됩니다.",
    },
    "projects.errChatIds": { en: "Enter at least one allowed Chat ID.", ko: "허용 Chat ID를 하나 이상 입력하세요." },
    "projects.errBotToken": { en: "Enter the bot token.", ko: "봇 토큰을 입력하세요." },
    "projects.updatedOk": { en: "Updated.", ko: "수정했습니다." },
    "projects.createdOk": { en: "Added.", ko: "추가했습니다." },

    // advanced.html
    "advanced.h1": { en: "Advanced Settings", ko: "고급 설정" },
    "advanced.tagline": {
      en: "Options that can affect repositories and conversation memory.",
      ko: "저장소와 대화 기억에 영향을 줄 수 있는 옵션입니다.",
    },
    "advanced.secTelegram": { en: "Telegram Notifications", ko: "Telegram 알림" },
    "advanced.secTelegramLead": {
      en: "Configure message display and server event notifications.",
      ko: "메시지 표시와 서버 이벤트 알림을 설정합니다.",
    },
    "advanced.uiLangLabel": { en: "Interface language", ko: "인터페이스 언어" },
    "advanced.uiLangHint": {
      en: "Default: English. Choose Korean here for the Telegram bot and this admin UI.",
      ko: "기본값: English. 여기서 한국어를 선택하면 Telegram 봇과 이 관리 UI에 적용됩니다.",
    },
    "advanced.statusLimitLabel": { en: "Recent jobs shown by /status", ko: "/status가 보여주는 최근 작업 수" },
    "advanced.statusLimitHint": {
      en: "Maximum number of recent jobs selectable with inline buttons in /status. Default: 10",
      ko: "/status에서 인라인 버튼으로 고를 수 있는 최근 작업 최대 개수. 기본값: 10",
    },
    "advanced.phStatus": { en: "Example: 10", ko: "예: 10" },
    "advanced.phTimeout": { en: "Example: 3600", ko: "예: 3600" },
    "advanced.phRows": { en: "Example: 5000", ko: "예: 5000" },
    "advanced.phBytes": { en: "Example: 10485760", ko: "예: 10485760" },
    "advanced.naturalConfirmLabel": {
      en: "Use inline buttons instead of <code>y</code>/<code>Y</code> for natural-language job confirmations",
      ko: "자연어 작업 확인에 <code>y</code>/<code>Y</code> 대신 인라인 버튼 사용",
    },
    "advanced.naturalConfirmHint": {
      en: "Default: off. When enabled, job confirmation messages show <strong>Yes</strong>/<strong>No</strong> buttons.",
      ko: "기본값: 꺼짐. 켜면 작업 확인 메시지에 <strong>Yes</strong>/<strong>No</strong> 버튼이 표시됩니다.",
    },
    "advanced.lifecycleLabel": {
      en: "Send Telegram notifications when the server starts or stops",
      ko: "서버 시작·중지 시 Telegram 알림 전송",
    },
    "advanced.lifecycleHint": {
      en: "Default: on. When disabled, restarts do not send server start/stop messages.",
      ko: "기본값: 켜짐. 끄면 재시작 시 서버 시작·중지 메시지를 보내지 않습니다.",
    },
    "advanced.secJob": { en: "Job Execution", ko: "작업 실행" },
    "advanced.secJobLead": { en: "Configure AI job execution limits.", ko: "AI 작업 실행 제한을 설정합니다." },
    "advanced.jobTimeoutLabel": {
      en: "AI job timeout (seconds)",
      ko: "AI 작업 타임아웃 (초)",
    },
    "advanced.jobTimeoutHint": {
      en: "If a Claude/Codex/Gemini runner does not finish within this time, the job fails. Default: 1800.",
      ko: "Claude/Codex/Gemini 러너가 이 시간 내에 끝나지 않으면 작업이 실패합니다. 기본값: 1800.",
    },
    "advanced.gitRemoteLabel": { en: "Git remote name", ko: "Git 원격 이름" },
    "advanced.gitRemoteHint": {
      en: "Remote used for push, /rebase, /pr, and /clear. Default: origin.",
      ko: "push, /rebase, /pr, /clear 에 사용하는 원격입니다. 기본값: origin.",
    },
    "advanced.keepWorktreeLabel": {
      en: "Keep worktrees after successful jobs",
      ko: "성공한 작업 후 worktree 유지",
    },
    "advanced.keepWorktreeHint": {
      en: "Default: on. When disabled, successful job worktrees are cleaned up automatically.",
      ko: "기본값: 켜짐. 끄면 성공한 작업의 worktree를 자동으로 정리합니다.",
    },
    "advanced.codexSandboxLabel": { en: "Codex sandbox mode", ko: "Codex 샌드박스 모드" },
    "advanced.codexSandboxHint": {
      en: "Codex exec --sandbox value. Default: workspace-write.",
      ko: "Codex exec --sandbox 값입니다. 기본값: workspace-write.",
    },
    "advanced.conversationRecentLabel": {
      en: "Recent conversation entries for ambiguous follow-ups",
      ko: "모호한 후속 요청에 붙이는 최근 대화 개수",
    },
    "advanced.conversationRecentHint": {
      en: "How many recent SQLite conversation rows to include when parsing ambiguous follow-ups. Default: 10.",
      ko: "모호한 후속 요청 파싱 시 포함할 최근 SQLite 대화 행 수입니다. 기본값: 10.",
    },
    "advanced.replySnippetMaxLabel": {
      en: "Reply/context snippet max length (characters)",
      ko: "Reply/맥락 스니펫 최대 길이(문자)",
    },
    "advanced.replySnippetMaxHint": {
      en: "Maximum characters per reply chain, job result, or fallback reply message included in AI instructions. Default: 3000. Range: 200–20000.",
      ko: "AI 지시문에 포함되는 reply 체인·Job 결과·fallback reply 메시지당 최대 문자 수입니다. 기본값: 3000. 범위: 200–20000.",
    },
    "advanced.secGit": { en: "Git Integration", ko: "Git 통합" },
    "advanced.secGitLead": {
      en: "These options can broadly affect repositories. Use them only when you understand the impact.",
      ko: "이 옵션들은 저장소에 광범위한 영향을 줄 수 있습니다. 영향을 이해한 경우에만 사용하세요.",
    },
    "advanced.startupPullLabel": {
      en: "Run <code>git pull</code> for registered active project repositories on server startup/restart",
      ko: "서버 시작·재시작 시 등록된 활성 프로젝트 저장소에 <code>git pull</code> 실행",
    },
    "advanced.startupPullHint": {
      en: "Default: off. Pulls from the remote based on each active project's checked-out branch. Network errors, conflicts, or local changes can fail; the server still starts.",
      ko: "기본값: 꺼짐. 각 활성 프로젝트의 체크아웃된 브랜치 기준으로 원격에서 pull합니다. 네트워크 오류·충돌·로컬 변경이 있으면 실패할 수 있으나 서버는 그대로 시작됩니다.",
    },
    "advanced.mergeMainLabel": {
      en: "Apply job results immediately to <code>main</code>/<code>master</code>, then push",
      ko: "작업 결과를 <code>main</code>/<code>master</code>에 즉시 반영한 뒤 push",
    },
    "advanced.mergeMainHint": {
      en: "When disabled, jobs only commit and push to their work branch. When enabled, successful jobs run an integration similar to <code>/rebase</code> (rebase -> main fast-forward merge -> push).",
      ko: "끄면 작업은 자신의 작업 브랜치에만 커밋·push합니다. 켜면 성공한 작업은 <code>/rebase</code>와 유사한 통합(rebase -> main fast-forward merge -> push)을 수행합니다.",
    },
    "advanced.deleteRebasedLabel": {
      en: "Delete the rebased branch locally and remotely after <code>/rebase</code>",
      ko: "<code>/rebase</code> 후 리베이스한 브랜치를 로컬·원격에서 삭제",
    },
    "advanced.deleteRebasedHint": {
      en: "Default: on. When disabled, <code>/rebase</code> only merges into main/master and pushes; the target branch remains.",
      ko: "기본값: 켜짐. 끄면 <code>/rebase</code>는 main/master에 병합·push만 하고 대상 브랜치는 남깁니다.",
    },
    "advanced.secMemory": { en: "Conversation Memory (SQLite)", ko: "대화 기억 (SQLite)" },
    "advanced.secMemoryLead": {
      en: "These options can broadly affect the conversation memory SQLite database. Enable only when needed.",
      ko: "이 옵션들은 대화 기억 SQLite 데이터베이스에 광범위한 영향을 줄 수 있습니다. 필요할 때만 켜세요.",
    },
    "advanced.memoryEnabledLabel": {
      en: "Limit SQLite conversation memory storage",
      ko: "SQLite 대화 기억 저장 제한",
    },
    "advanced.memoryEnabledHint": {
      en: "When enabled, old <code>conversation_entries</code> rows are deleted <strong>globally</strong>. Set at least one positive row-count or DB-size limit.",
      ko: "켜면 오래된 <code>conversation_entries</code> 행이 <strong>전역적으로</strong> 삭제됩니다. 행 수 또는 DB 크기 제한 중 최소 하나를 양수로 설정하세요.",
    },
    "advanced.maxRowsLabel": { en: "Maximum rows (blank disables)", ko: "최대 행 수 (비우면 비활성)" },
    "advanced.maxBytesLabel": { en: "Maximum DB size (bytes, blank disables)", ko: "최대 DB 크기 (바이트, 비우면 비활성)" },
    "advanced.btnSave": { en: "Save", ko: "저장" },
    "advanced.btnReload": { en: "Reload", ko: "다시 불러오기" },
    "advanced.loadedMsg": { en: "Summary and advanced settings loaded.", ko: "요약과 고급 설정을 불러왔습니다." },
    "advanced.savedMsg": { en: "Advanced settings saved.", ko: "고급 설정을 저장했습니다." },

    // logs.html
    "logs.h1": { en: "Server logs", ko: "서버 로그" },
    "logs.tagline": {
      en: "Recent logs collected by the <code>app</code> package logger. Auto-refresh shows them near real time.",
      ko: "<code>app</code> 패키지 로거에 쌓인 최근 로그입니다. 자동 새로고침으로 실시간에 가깝게 볼 수 있습니다.",
    },
    "logs.console": { en: "Console", ko: "콘솔" },
    "logs.lead": {
      en: "Level is a <strong>minimum</strong>. Search partially matches message and exception text. Click a badge to fill that filter.",
      ko: "레벨은 <strong>최소</strong> 기준입니다. 검색어는 메시지·예외 텍스트에 부분 일치합니다. 배지를 클릭하면 해당 필터가 채워집니다.",
    },
    "logs.level": { en: "Level", ko: "레벨" },
    "logs.levelAria": { en: "Minimum log level", ko: "최소 로그 레벨" },
    "logs.category": { en: "Category", ko: "카테고리" },
    "logs.categoryAria": { en: "Event category", ko: "이벤트 카테고리" },
    "logs.phChatId": { en: "e.g. 123", ko: "예: 123" },
    "logs.phUserId": { en: "e.g. 456", ko: "예: 456" },
    "logs.phJobId": { en: "e.g. job_…", ko: "예: job_…" },
    "logs.phProject": { en: "Project name", ko: "프로젝트 이름" },
    "logs.logger": { en: "Logger (partial match)", ko: "로거 (부분 일치)" },
    "logs.phLogger": { en: "e.g. app.telegram", ko: "예: app.telegram" },
    "logs.phSearch": { en: "Message/exception", ko: "메시지·예외" },
    "logs.refresh": { en: "Refresh (s)", ko: "새로고침(초)" },
    "logs.refreshAria": { en: "Auto-refresh interval", ko: "자동 새로고침 간격" },
    "logs.applyFilter": { en: "Apply filters", ko: "필터 적용" },
    "logs.clearView": { en: "Clear view", ko: "화면 비우기" },
    "logs.stickBottom": { en: "Scroll to bottom", ko: "맨 아래로 스크롤" },
    "logs.loadWaiting": { en: "Waiting to load", ko: "로드 대기" },
    "logs.shownLines": { en: "Lines shown: {n}", ko: "표시 줄 수: {n}" },

    // database.html
    "database.h1": { en: "Data browser", ko: "데이터 조회" },
    "database.tagline": {
      en: "Read-only view of the conversation memory SQLite. Arbitrary SQL is never run.",
      ko: "대화 기억 SQLite를 읽기 전용으로 조회합니다. 임의 SQL은 실행되지 않습니다.",
    },
    "database.tablesHeading": { en: "Tables", ko: "표" },
    "database.lead": {
      en: "Tables and sort columns are restricted to a server whitelist.",
      ko: "테이블과 정렬 컬럼은 서버 화이트리스트로만 허용됩니다.",
    },
    "database.table": { en: "Table", ko: "테이블" },
    "database.tableAria": { en: "Table", ko: "테이블" },
    "database.sort": { en: "Sort", ko: "정렬" },
    "database.sortAria": { en: "Sort column", ko: "정렬 컬럼" },
    "database.order": { en: "Order", ko: "순서" },
    "database.orderAria": { en: "Sort order", ko: "정렬 순서" },
    "database.desc": { en: "Descending", ko: "내림차순" },
    "database.asc": { en: "Ascending", ko: "오름차순" },
    "database.pageSize": { en: "Page size", ko: "페이지 크기" },
    "database.pageSizeAria": { en: "Page size", ko: "페이지 크기" },
    "database.projectAria": { en: "Project filter", ko: "프로젝트 필터" },
    "database.roleAria": { en: "Role filter", ko: "역할 필터" },
    "database.searchPartial": { en: "Search (partial match)", ko: "검색 (부분 일치)" },
    "database.btnLoad": { en: "Load", ko: "조회" },
    "database.csvTitle": {
      en: "Download CSV (current filters/sort, up to 50,000 rows)",
      ko: "CSV 다운로드 (현재 필터·정렬, 최대 5만행)",
    },
    "database.csvAria": { en: "Download CSV", ko: "CSV 다운로드" },
    "database.textContent": { en: "Text content", ko: "text 내용" },
    "database.dbPrefix": { en: "DB: {path}", ko: "DB: {path}" },
    "database.dbMissing": { en: "DB file missing: {path}", ko: "DB 파일 없음: {path}" },
    "database.noTableMeta": { en: "No registered table metadata.", ko: "등록된 테이블 메타가 없습니다." },
    "database.noRows": { en: "No rows.", ko: "행이 없습니다." },
    "database.viewDetail": { en: "View", ko: "상세보기" },
    "database.pagerSummary": {
      en: "Total {total} rows · showing {from}–{to} (limit {limit}, offset {offset})",
      ko: "총 {total}행 · 표시 {from}–{to} (limit {limit}, offset {offset})",
    },

    // backend-supplied values (resolved via tv())
    "db.label.conversation_entries": { en: "Conversation & job history", ko: "대화·작업 기록" },
    "db.label.message_branch_links": { en: "Message–branch links", ko: "메시지–브랜치 연결" },
    "settings.webhookHint": {
      en: "Each project (bot) has its own webhook_path and token_hash_prefix. The full URL is the public Base joined with webhook_path. While ./run.sh is running, registration/edits refresh it automatically. Manual registration: python scripts/set_webhook.py <Base URL>",
      ko: "각 프로젝트(봇)마다 webhook_path·token_hash_prefix가 다릅니다. 전체 URL은 공개 Base에 webhook_path를 이어붙입니다. ./run.sh 실행 중에는 등록·수정 시 자동 갱신됩니다. 수동 등록: python scripts/set_webhook.py <Base URL>",
    },
  };

  var REVERSE = {};
  for (var k in CATALOG) {
    if (Object.prototype.hasOwnProperty.call(CATALOG, k)) {
      REVERSE[CATALOG[k].en] = k;
    }
  }

  function resolve(key, lang) {
    var e = CATALOG[key];
    if (!e) return key;
    return e[lang] || e.en || key;
  }

  var i18n = {
    lang: window.__UI_LANG__ === "ko" ? "ko" : "en",
    t: function (key, vars) {
      var s = resolve(key, this.lang);
      if (vars) {
        for (var v in vars) {
          if (Object.prototype.hasOwnProperty.call(vars, v)) {
            s = s.split("{" + v + "}").join(String(vars[v]));
          }
        }
      }
      return s;
    },
    tv: function (value) {
      if (value == null) return value;
      var key = REVERSE[value];
      return key ? resolve(key, this.lang) : value;
    },
    apply: function (root) {
      if (this.lang === "en") return;
      var self = this;
      var scope = root || document;
      scope.querySelectorAll("[data-i18n]").forEach(function (el) {
        el.textContent = self.t(el.getAttribute("data-i18n"));
      });
      scope.querySelectorAll("[data-i18n-html]").forEach(function (el) {
        el.innerHTML = self.t(el.getAttribute("data-i18n-html"));
      });
      scope.querySelectorAll("[data-i18n-title]").forEach(function (el) {
        el.setAttribute("title", self.t(el.getAttribute("data-i18n-title")));
      });
      scope.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
        el.setAttribute("placeholder", self.t(el.getAttribute("data-i18n-placeholder")));
      });
      scope.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
        el.setAttribute("aria-label", self.t(el.getAttribute("data-i18n-aria-label")));
      });
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.documentElement.lang = i18n.lang;
    i18n.apply(document);
  });

  window.i18n = i18n;
})(window);
