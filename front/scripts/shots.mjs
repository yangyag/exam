/**
 * 홈 화면 스크린샷 + 화면 점검 스크립트.
 *
 *   npm run shots                 # dev 서버(8091)가 없으면 자동 기동 → 캡처 → 종료
 *
 * 하는 일:
 *   1) 실제 DB 데이터로 홈을 캡처한다(모바일 375x812 · 데스크톱 1280x900) —
 *      콘솔 오류 0, 가로 잘림 0, 클릭 영역 44px 이상, 과목 5개·고유 문항 수를 확인한다.
 *   2) 상태 4종·확인 대화상자·백엔드 다운·로딩 화면은 브라우저에서 API 응답을 대체해 캡처한다.
 *      이때 시작하기/새로 구성이 보내는 본문도 검사한다. DB 는 건드리지 않는다(실제 요청 차단).
 *
 * SHOTS_DIR(기본 <저장소 루트>/tmp/shots) · SHOTS_BASE_URL(기본 http://localhost:8091) 로 바꿀 수 있다.
 */
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const frontDir = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const repoRoot = path.resolve(frontDir, '..')
const shotsDir = process.env.SHOTS_DIR ? path.resolve(process.env.SHOTS_DIR) : path.join(repoRoot, 'tmp', 'shots')
const baseUrl = process.env.SHOTS_BASE_URL || 'http://localhost:8091'
const apiOrigin = process.env.SHOTS_API_ORIGIN || 'http://127.0.0.1:8092'

const MOBILE = { width: 375, height: 812 }
const DESKTOP = { width: 1280, height: 900 }

// 실제 DB 기준값(중복 제거 고유 문항) — 1:176 2:194 3:194 4:199 5:181
const EXPECTED = [
  { name: '소프트웨어 설계', count: 176 },
  { name: '소프트웨어 개발', count: 194 },
  { name: '데이터베이스 구축', count: 194 },
  { name: '프로그래밍 언어 활용', count: 199 },
  { name: '정보시스템 구축 관리', count: 181 },
]

// 상태 4종을 한 화면에서 보기 위한 대체 응답(과목명·고유 문항 수는 실제 값 그대로)
const stubOverview = [
  {
    subjectCode: 1,
    subjectName: '소프트웨어 설계',
    uniqueQuestionCount: 176,
    status: 'first_pass',
    cycle: {
      id: 101,
      status: 'active',
      startedAt: '2026-09-11T00:10:00Z',
      endedAt: null,
      firstRound: { sessionId: 901, roundNo: 1, itemCount: 176, answered: 128, correct: 104 },
      currentRound: { sessionId: 901, roundNo: 1, itemCount: 176, answered: 128, correct: 104 },
    },
  },
  {
    subjectCode: 2,
    subjectName: '소프트웨어 개발',
    uniqueQuestionCount: 194,
    status: 'reviewing',
    cycle: {
      id: 102,
      status: 'active',
      startedAt: '2026-09-08T02:00:00Z',
      endedAt: null,
      firstRound: { sessionId: 902, roundNo: 1, itemCount: 194, answered: 194, correct: 182 },
      currentRound: { sessionId: 903, roundNo: 3, itemCount: 12, answered: 5, correct: 4 },
    },
  },
  {
    subjectCode: 3,
    subjectName: '데이터베이스 구축',
    uniqueQuestionCount: 194,
    status: 'completed',
    cycle: {
      id: 103,
      status: 'completed',
      startedAt: '2026-08-20T01:00:00Z',
      endedAt: '2026-09-02T11:30:00Z',
      firstRound: { sessionId: 904, roundNo: 1, itemCount: 194, answered: 194, correct: 176 },
      currentRound: null,
    },
  },
  {
    subjectCode: 4,
    subjectName: '프로그래밍 언어 활용',
    uniqueQuestionCount: 199,
    status: 'not_started',
    cycle: null,
  },
  {
    subjectCode: 5,
    subjectName: '정보시스템 구축 관리',
    uniqueQuestionCount: 181,
    status: 'not_started',
    cycle: null,
  },
]

const stubCycle = {
  id: 999,
  subjectCode: 2,
  subjectName: '소프트웨어 개발',
  status: 'active',
  startedAt: '2026-09-11T01:00:00Z',
  endedAt: null,
  rounds: [
    {
      sessionId: 12345,
      roundNo: 1,
      mode: 'subject',
      itemCount: 194,
      answered: 0,
      correct: 0,
      startedAt: '2026-09-11T01:00:00Z',
      finishedAt: null,
      endReason: null,
    },
  ],
}

const stubSession = {
  id: 12345,
  mode: 'subject',
  examId: null,
  subjectCode: 2,
  cycleId: 999,
  roundNo: 1,
  endReason: null,
  startedAt: '2026-09-11T01:00:00Z',
  finishedAt: null,
  answered: 0,
  correct: 0,
  itemCount: 194,
  answeredCount: 0,
  nextSeq: 1,
  items: [{ seq: 1, questionId: '2026-1-001', choiceNo: null, isCorrect: null }],
}

const problems = []
const captures = []

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function fail(message) {
  problems.push(message)
  console.error(`  x ${message}`)
}

function pass(message) {
  console.log(`  v ${message}`)
}

async function isServerUp(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(3000) })
    return response.status < 500
  } catch {
    return false
  }
}

async function startDevServer() {
  console.log(`dev 서버(${baseUrl})가 없어 기동합니다…`)
  const child = spawn('npm', ['run', 'dev'], {
    cwd: frontDir,
    stdio: 'ignore',
    shell: process.platform === 'win32',
    env: { ...process.env, NUXT_TELEMETRY_DISABLED: '1' },
  })
  const deadline = Date.now() + 180000
  while (Date.now() < deadline) {
    if (await isServerUp(baseUrl)) {
      console.log('dev 서버 준비 완료')
      return child
    }
    await sleep(1000)
  }
  stopDevServer(child)
  throw new Error('dev 서버가 3분 안에 뜨지 않았습니다')
}

function stopDevServer(child) {
  if (!child || child.exitCode !== null) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }
}

function watchConsole(page) {
  const errors = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  return errors
}

async function save(page, name) {
  const file = path.join(shotsDir, name)
  await page.screenshot({ path: file, fullPage: true })
  captures.push({ file, bytes: statSync(file).size })
  console.log(`  → ${file}`)
}

/** 가로 잘림·클릭 영역(44px)·카드 개수를 브라우저에서 직접 잰다 */
async function auditLayout(page, label) {
  const result = await page.evaluate(() => {
    const found = []
    const doc = document.documentElement
    if (doc.scrollWidth > window.innerWidth + 1) {
      found.push(`가로 스크롤: scrollWidth ${doc.scrollWidth} > viewport ${window.innerWidth}`)
    }
    const targets = Array.from(document.querySelectorAll('[data-tap]')).filter(
      (el) => !el.disabled && el.offsetParent !== null,
    )
    const small = []
    for (const el of targets) {
      const rect = el.getBoundingClientRect()
      if (rect.height < 43.5 || rect.width < 43.5) {
        small.push(`${Math.round(rect.width)}x${Math.round(rect.height)} "${(el.textContent || '').trim().slice(0, 16)}"`)
      }
    }
    if (small.length) found.push(`클릭 영역 44px 미만: ${small.join(', ')}`)
    return { found, tapCount: targets.length, cards: document.querySelectorAll('[data-testid="subject-card"]').length }
  })
  if (result.found.length) {
    for (const item of result.found) fail(`[${label}] ${item}`)
  } else {
    pass(`[${label}] 가로 잘림 없음 · 클릭 영역 ${result.tapCount}개 모두 44px 이상`)
  }
  return result
}

/** 실제 데이터 컷 — 콘솔 오류 0 과 값 일치까지 확인한다 */
async function captureRealData(browser) {
  console.log('\n[1] 실제 DB 데이터 홈')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const page = await context.newPage()
  const errors = watchConsole(page)

  await page.setViewportSize(MOBILE)
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="subject-card"]', { timeout: 90000 })
  await sleep(400)

  const beforeDataChecks = problems.length
  const texts = await page.locator('[data-testid="subject-card"]').allInnerTexts()
  if (texts.length !== 5) fail(`[모바일] 과목 카드가 5개가 아닙니다: ${texts.length}`)
  EXPECTED.forEach((expected, index) => {
    const text = (texts[index] ?? '').replace(/\s+/g, ' ')
    if (!text.includes(expected.name)) fail(`[모바일] ${index + 1}번 카드에 과목명이 없습니다: ${expected.name}`)
    if (!text.includes(String(expected.count))) fail(`[모바일] ${index + 1}번 카드에 고유 문항 수가 없습니다: ${expected.count}`)
  })
  const header = await page.locator('header').first().innerText()
  if (!header.includes('고유 문항 944개')) fail(`[모바일] 헤더에 총 고유 문항(944)이 없습니다: ${header.replace(/\s+/g, ' ')}`)

  await save(page, 'home-mobile-375x812.png')
  await auditLayout(page, '모바일 375')

  await page.setViewportSize(DESKTOP)
  await sleep(400)
  await save(page, 'home-desktop-1280x900.png')
  await auditLayout(page, '데스크톱 1280')

  if (problems.length === beforeDataChecks) {
    pass('실제 데이터로 과목 5개·고유 문항 176/194/194/199/181 렌더링 확인')
  }
  if (errors.length === 0) pass('브라우저 콘솔 오류 0')
  else for (const message of errors) fail(`[실제 데이터] ${message}`)

  await context.close()
}

/** API 응답을 브라우저에서 대체 — DB 에 아무것도 쓰지 않는다 */
async function stubApi(context, { abort = false, holdOverview = false, overview = stubOverview } = {}) {
  let releaseOverview = null
  const gate = holdOverview ? new Promise((resolve) => { releaseOverview = resolve }) : null
  const posts = []

  const json = (data, status = 200) => ({
    status,
    headers: { 'content-type': 'application/json', 'access-control-allow-origin': '*' },
    body: JSON.stringify(data),
  })

  await context.route(`${apiOrigin}/**`, async (route) => {
    if (abort) return route.abort('connectionrefused')
    const request = route.request()
    const pathname = new URL(request.url()).pathname

    if (pathname === '/api/subject-cycles/overview') {
      if (gate) await gate
      return route.fulfill(json(overview))
    }
    if (pathname === '/api/subject-cycles' && request.method() === 'POST') {
      const body = request.postDataJSON()
      posts.push(body)
      // 5과목은 이미 진행 중인 사이클이 있는 상황을 흉내 낸다(409 경로 확인)
      if (body.subjectCode === 5) {
        return route.fulfill(json({ detail: '이미 진행 중인 사이클이 있습니다. 새로 구성하려면 replaceActive=true 로 보내세요' }, 409))
      }
      return route.fulfill(json({ ...stubCycle, subjectCode: body.subjectCode }, 201))
    }
    if (pathname.startsWith('/api/sessions/')) return route.fulfill(json(stubSession))
    return route.fulfill(json({ detail: 'stub: 정의되지 않은 경로' }, 404))
  })

  return { posts, releaseOverview }
}

/** 상태 4종·확인 대화상자·동작 본문 검사 */
async function captureStatesAndActions(browser) {
  console.log('\n[2] 상태 4종 · 확인 대화상자 · 동작 본문 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const { posts } = await stubApi(context)
  const page = await context.newPage()
  const errors = watchConsole(page)

  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="subject-card"]', { timeout: 90000 })
  await sleep(300)
  await save(page, 'states-simulated-desktop-1280x900.png')
  await auditLayout(page, '상태 4종 데스크톱')

  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'states-simulated-mobile-375x812.png')
  await auditLayout(page, '상태 4종 모바일')

  // 완료 상태 카드 — 주 동작은 새로 구성 하나(설계 5.1절). 대화상자는 중단 문구가 아니라 새 사이클 문구.
  const completedCard = page.locator('[data-testid="subject-card"]').nth(2)
  const completedButtons = (await completedCard.getByRole('button').allInnerTexts()).map((text) => text.trim())
  if (completedButtons.length === 1 && completedButtons[0] === '새로 구성') {
    pass('완료 상태 카드는 새로 구성 버튼 하나만 노출')
  } else {
    fail(`완료 상태 카드 버튼이 예상과 다릅니다: ${JSON.stringify(completedButtons)}`)
  }
  await completedCard.getByRole('button', { name: '새로 구성' }).click()
  await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 10000 })
  const completedDialog = await page.getByTestId('confirm-dialog').innerText()
  if (completedDialog.includes('새 사이클을 시작합니다')) pass('완료 카드 확인 대화상자 문구 확인')
  else fail(`완료 카드 대화상자 문구가 다릅니다: ${completedDialog.replace(/\s+/g, ' ')}`)
  // Esc 로도 닫히는지(키보드 조작)
  await page.keyboard.press('Escape')
  await page.waitForSelector('[data-testid="confirm-dialog"]', { state: 'detached', timeout: 5000 })
    .then(() => pass('확인 대화상자 Esc 닫기 동작'))
    .catch(() => fail('Esc 로 확인 대화상자가 닫히지 않았습니다'))

  // 새로 구성 → 확인 대화상자 → replaceActive=true 전송
  await page.setViewportSize(DESKTOP)
  const reviewingCard = page.locator('[data-testid="subject-card"]').nth(1)
  await reviewingCard.getByRole('button', { name: '새로 구성' }).click()
  await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 10000 })
  await sleep(200)
  await save(page, 'recreate-dialog-simulated-desktop-1280x900.png')
  await page.getByTestId('confirm-dialog').getByRole('button', { name: '새로 구성' }).click()

  const deadline = Date.now() + 15000
  while (posts.length < 1 && Date.now() < deadline) await sleep(100)
  const recreate = posts[0]
  if (recreate?.subjectCode === 2 && recreate?.replaceActive === true) {
    pass(`새로 구성 → POST /api/subject-cycles ${JSON.stringify(recreate)} (확인 대화상자 통과)`)
  } else {
    fail(`새로 구성 본문이 예상과 다릅니다: ${JSON.stringify(recreate)}`)
  }

  await page.waitForURL('**/sessions/**', { timeout: 15000 }).catch(() => fail('새로 구성 후 라운드 화면으로 이동하지 않았습니다'))
  await page.waitForSelector('h1', { timeout: 15000 }).catch(() => {})
  await sleep(300)
  await save(page, 'session-placeholder-simulated-desktop-1280x900.png')

  // 시작하기 → replaceActive=false 전송
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="subject-card"]', { timeout: 30000 })
  const notStartedCard = page.locator('[data-testid="subject-card"]').nth(3)
  await notStartedCard.getByRole('button', { name: '시작하기' }).click()
  const deadline2 = Date.now() + 15000
  while (posts.length < 2 && Date.now() < deadline2) await sleep(100)
  const start = posts[1]
  if (start?.subjectCode === 4 && start?.replaceActive === false) {
    pass(`시작하기 → POST /api/subject-cycles ${JSON.stringify(start)}`)
  } else {
    fail(`시작하기 본문이 예상과 다릅니다: ${JSON.stringify(start)}`)
  }

  // 409(이미 진행 중) — 오류 안내가 화면에 뜨는지
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="subject-card"]', { timeout: 30000 })
  await page.locator('[data-testid="subject-card"]').nth(4)
    .getByRole('button', { name: '시작하기' }).click()
  await page.waitForSelector('[data-testid="notice"]', { timeout: 15000 }).catch(() => {})
  const noticeText = await page.locator('[data-testid="notice"]').first().innerText().catch(() => '')
  if (noticeText.includes('이미 진행 중인 사이클')) pass(`409 안내 문구 표시: ${noticeText}`)
  else fail(`409 안내 문구가 없습니다: ${JSON.stringify(noticeText)}`)
  await sleep(200)
  await save(page, 'action-conflict-simulated-desktop-1280x900.png')

  await context.close()
  return errors
}

/** 백엔드가 꺼져 있을 때의 안내 화면 */
async function captureBackendDown(browser) {
  console.log('\n[3] 백엔드 다운 안내 (요청 차단)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  await stubApi(context, { abort: true })
  const page = await context.newPage()
  watchConsole(page)
  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="home-error"]', { timeout: 60000 })
  const text = await page.getByTestId('home-error').innerText()
  if (text.includes('백엔드 서버에 연결할 수 없습니다') && text.includes('uvicorn')) {
    pass('백엔드 다운 시 안내 문구와 기동 명령 표시')
  } else {
    fail(`백엔드 다운 안내가 부족합니다: ${text.replace(/\s+/g, ' ')}`)
  }
  await sleep(200)
  await save(page, 'backend-down-simulated-desktop-1280x900.png')
  await context.close()
}

/** 로딩(스켈레톤) 화면 */
async function captureLoading(browser) {
  console.log('\n[4] 로딩 화면 (응답 지연)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const { releaseOverview } = await stubApi(context, { holdOverview: true })
  const page = await context.newPage()
  watchConsole(page)
  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="home-loading"]', { timeout: 30000 })
  await sleep(400)
  await save(page, 'loading-simulated-desktop-1280x900.png')
  pass('로딩 중 스켈레톤 카드 표시')
  releaseOverview?.()
  await context.close()
}

/** 빈 목록(과목 0행) 안내 화면 */
async function captureEmpty(browser) {
  console.log('\n[5] 빈 목록 안내 (과목 0행)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  await stubApi(context, { overview: [] })
  const page = await context.newPage()
  watchConsole(page)
  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="home-empty"]', { timeout: 60000 })
  pass('과목 0행일 때 빈 목록 안내 표시')
  await save(page, 'empty-simulated-desktop-1280x900.png')
  await context.close()
}

async function main() {
  mkdirSync(shotsDir, { recursive: true })

  if (!(await isServerUp(apiOrigin))) {
    console.error(`백엔드(${apiOrigin})가 응답하지 않습니다. 먼저 기동하세요:
  cd back && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8092`)
    process.exit(1)
  }

  const devServer = (await isServerUp(baseUrl)) ? null : await startDevServer()
  const browser = await chromium.launch()
  try {
    await captureRealData(browser)
    await captureStatesAndActions(browser)
    await captureBackendDown(browser)
    await captureLoading(browser)
    await captureEmpty(browser)
  } finally {
    await browser.close()
    stopDevServer(devServer)
  }

  console.log(`\n저장 위치: ${shotsDir}`)
  for (const { file, bytes } of captures) {
    console.log(`  ${path.basename(file)} (${Math.round(bytes / 1024)}KB)`)
  }

  if (problems.length) {
    console.error(`\n점검 실패 ${problems.length}건`)
    process.exit(1)
  }
  console.log('\n모든 점검 통과')
}

await main()
