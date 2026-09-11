/**
 * 홈·연습 화면 스크린샷 + 화면 점검 스크립트.
 *
 *   npm run shots                 # dev 서버(8091)가 없으면 자동 기동 → 캡처 → 종료
 *
 * 하는 일:
 *   1) 실제 DB 데이터로 홈을 캡처한다(모바일 375x812 · 데스크톱 1280x900) —
 *      콘솔 오류 0, 가로 잘림 0, 클릭 영역 44px 이상, 과목 5개·고유 문항 수를 확인한다.
 *   2) 상태 4종·확인 대화상자·백엔드 다운·로딩 화면은 브라우저에서 API 응답을 대체해 캡처한다.
 *      이때 시작하기/새로 구성이 보내는 본문도 검사한다. DB 는 건드리지 않는다(실제 요청 차단).
 *   3) 연습 화면(문항·제출·해설·보기별 해설·라운드 종료·다음 라운드)과 충돌(409·중단) 안내도
 *      대체 응답으로 캡처한다 — 코드·지문·표·도식 네 종류를 지나가며, 보기 선택과 제출은
 *      키보드만으로 되는지 확인한다. 연습 픽스처는 실제 데이터셋 문항이다(scripts/practice-fixtures.mjs).
 *
 * SHOTS_DIR(기본 <저장소 루트>/tmp/shots) · SHOTS_BASE_URL(기본 http://localhost:8091) 로 바꿀 수 있다.
 */
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import {
  CODE_QUESTION,
  ROUND1_QUESTIONS,
  ROUND2_QUESTIONS,
  STUB_AT,
  TABLE_QUESTION,
  TEXT_QUESTION,
} from './practice-fixtures.mjs'

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

/** 현재 포커스가 대화상자 안인지 밖인지 + 어떤 요소인지 — 포커스 트랩 점검용 */
function focusSpot(page) {
  return page.evaluate(() => {
    const active = document.activeElement
    const inside = Boolean(active?.closest('[data-testid="confirm-dialog"]'))
    const label = (active?.textContent || active?.tagName || '').trim().replace(/\s+/g, ' ').slice(0, 14)
    return `${inside ? 'in' : 'out'}:${label}`
  })
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
  if (await page.locator('[data-testid="subject-card"]').count() !== 5) {
    fail(`[모바일] 과목 카드가 5개가 아닙니다: ${await page.locator('[data-testid="subject-card"]').count()}`)
  }
  // 라벨과 숫자를 함께 본다 — 부분 문자열만 보면 라벨이 틀린 숫자를 보여도 통과한다(리뷰 P2-4)
  for (const [index, expected] of EXPECTED.entries()) {
    const card = page.locator('[data-testid="subject-card"]').nth(index)
    const where = `[모바일] ${index + 1}번 카드`
    const text = (await card.innerText()).replace(/\s+/g, ' ')
    if (!text.includes(expected.name)) fail(`${where}에 과목명이 없습니다: ${expected.name}`)

    const unique = (await card.locator('[data-testid="card-unique"]').innerText()).replace(/\s+/g, ' ')
    const uniqueMatch = unique.match(/^고유 문항 (\d+)개/)
    if (!uniqueMatch) fail(`${where}의 고유 문항 줄이 '고유 문항 N개' 형식이 아닙니다: ${unique}`)
    else if (Number(uniqueMatch[1]) !== expected.count) fail(`${where}의 고유 문항이 ${uniqueMatch[1]}개 입니다(기대 ${expected.count}개)`)

    // 표시는 '0 / 176' 이지만 DOM 텍스트는 '0/ 176' 이라 공백을 지우고 비교한다
    const progress = (await card.locator('[data-testid="card-progress"]').innerText()).replace(/\s+/g, '')
    if (progress !== `0/${expected.count}`) fail(`${where}의 진행도가 '0 / ${expected.count}' 가 아닙니다: ${progress}`)

    const correct = (await card.locator('[data-testid="card-correct"]').innerText()).trim()
    if (correct !== '0') fail(`${where}의 정답 수가 '0' 이 아닙니다: ${correct}`)
  }
  const header = await page.locator('header').first().innerText()
  const totalUnique = EXPECTED.reduce((sum, item) => sum + item.count, 0)
  if (!header.includes(`과목별 고유 문항 합계 ${totalUnique}개`)) {
    fail(`[모바일] 헤더에 '과목별 고유 문항 합계 ${totalUnique}개' 기준 표기가 없습니다: ${header.replace(/\s+/g, ' ')}`)
  }

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
    if (pathname.startsWith('/api/sessions/')) {
      // 연습 화면이 슬롯 문항을 따로 부른다 — 세션 상세와 같은 모양으로 답하지 않게 나눈다
      if (/\/items\/\d+$/.test(pathname)) {
        return route.fulfill(json({ ...CODE_QUESTION.item, seq: 1, choiceNo: null, isCorrect: null, answeredAt: null, result: null }))
      }
      return route.fulfill(json(stubSession))
    }
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

  // 정답 패널이 어느 풀이의 정답 수인지 화면 문구만으로 읽히는지(리뷰 P2-2)
  const completedCorrectLabel = (await completedCard.locator('[data-testid="card-correct-label"]').innerText()).trim()
  const completedCorrect = (await completedCard.locator('[data-testid="card-correct"]').innerText()).trim()
  const completedDetail = (await completedCard.locator('[data-testid="card-detail"]').innerText()).replace(/\s+/g, ' ')
  if (completedCorrectLabel === '1차 정답' && completedCorrect === '176' && /^1차\(전체\) 풀이 정답 176\/194/.test(completedDetail)) {
    pass(`완료 카드 정답 표기: ${completedCorrectLabel} ${completedCorrect} · ${completedDetail}`)
  } else {
    fail(`완료 카드 정답 표기가 예상과 다릅니다: 라벨=${completedCorrectLabel} 값=${completedCorrect} 보조줄=${completedDetail}`)
  }

  const reviewingCorrectLabel = (await page.locator('[data-testid="subject-card"]').nth(1)
    .locator('[data-testid="card-correct-label"]').innerText()).trim()
  if (reviewingCorrectLabel === '복습 정답') pass(`오답 복습 카드 정답 패널 라벨: ${reviewingCorrectLabel}`)
  else fail(`복습 카드 정답 패널 라벨이 '복습 정답' 이 아닙니다: ${reviewingCorrectLabel}`)

  await completedCard.getByRole('button', { name: '새로 구성' }).click()
  await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 10000 })
  const completedDialog = await page.getByTestId('confirm-dialog').innerText()
  if (completedDialog.includes('새 사이클을 시작합니다')) pass('완료 카드 확인 대화상자 문구 확인')
  else fail(`완료 카드 대화상자 문구가 다릅니다: ${completedDialog.replace(/\s+/g, ' ')}`)

  // 포커스 트랩 — 열린 동안 Tab·Shift+Tab 이 대화상자 밖으로 나가면 안 된다(리뷰 P2-3)
  const trapSpots = []
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Tab')
    trapSpots.push(await focusSpot(page))
  }
  await page.keyboard.press('Shift+Tab')
  trapSpots.push(await focusSpot(page))
  if (trapSpots.every((spot) => spot.startsWith('in:'))) {
    pass(`대화상자 포커스 트랩(Tab 5회 + Shift+Tab): ${trapSpots.join(' → ')}`)
  } else {
    fail(`Tab 이 대화상자를 벗어났습니다: ${trapSpots.join(' → ')}`)
  }

  // Esc 로도 닫히는지(키보드 조작) + 닫으면 트리거 버튼으로 포커스 복귀
  await page.keyboard.press('Escape')
  await page.waitForSelector('[data-testid="confirm-dialog"]', { state: 'detached', timeout: 5000 })
    .then(() => pass('확인 대화상자 Esc 닫기 동작'))
    .catch(() => fail('Esc 로 확인 대화상자가 닫히지 않았습니다'))
  const afterClose = await focusSpot(page)
  if (afterClose.startsWith('out:') && afterClose.includes('새로 구성')) {
    pass(`대화상자를 닫은 뒤 포커스 복귀: ${afterClose}`)
  } else {
    fail(`닫힌 뒤 포커스가 트리거 버튼으로 돌아오지 않았습니다: ${afterClose}`)
  }

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
  await page.waitForSelector('[data-testid="practice-item"]', { timeout: 30000 }).catch(() => fail('라운드 화면에 문항이 뜨지 않았습니다'))
  await sleep(300)
  await save(page, 'session-practice-simulated-desktop-1280x900.png')

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

  // 연습 화면도 같은 안내 문구를 쓰는지
  await page.goto(`${baseUrl}/sessions/1`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="practice-error"]', { timeout: 60000 })
  const practiceText = await page.getByTestId('practice-error').innerText()
  if (practiceText.includes('백엔드 서버에 연결할 수 없습니다') && practiceText.includes('uvicorn')) {
    pass('연습 화면도 백엔드 다운 안내 문구와 기동 명령 표시')
  } else {
    fail(`연습 화면 백엔드 다운 안내가 부족합니다: ${practiceText.replace(/\s+/g, ' ')}`)
  }
  await sleep(200)
  await save(page, 'practice-backend-down-simulated-desktop-1280x900.png')
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

/**
 * 연습 화면 전용 대체 API — 세션·슬롯·제출 응답만 만든다(DB 무변경).
 * 실제 API 처럼 조회 응답에는 정답·해설을 넣지 않고, 채점 응답(PUT)에만 싣는다.
 *  7001 라운드1(코드·지문·표·도식 4문항) → 7002 오답 복습(표 1문항) → 사이클 완료
 *  7101 제출 충돌(첫 제출 응답 유실 → 다른 보기 재제출 409)
 *  7102 중단된 세션(안내 + 홈으로)
 */
async function stubPracticeApi(context, { conflict = false } = {}) {
  const sessions = {
    7001: { mode: 'subject', roundNo: 1, subjectCode: 4, questions: ROUND1_QUESTIONS, cycleId: 9001 },
    7002: { mode: 'review', roundNo: 2, subjectCode: 4, questions: ROUND2_QUESTIONS, cycleId: 9001 },
    7101: { mode: 'exam_practice', roundNo: null, subjectCode: null, questions: [CODE_QUESTION, TEXT_QUESTION], cycleId: null },
    7102: { mode: 'subject', roundNo: 1, subjectCode: 4, questions: ROUND1_QUESTIONS, cycleId: 9001, abandoned: true },
    7103: { mode: 'subject', roundNo: 1, subjectCode: 4, questions: [], cycleId: 9002 },
  }
  const graded = new Map()
  const puts = []
  let lostOnce = false

  const json = (data, status = 200) => ({
    status,
    headers: { 'content-type': 'application/json', 'access-control-allow-origin': '*' },
    body: JSON.stringify(data),
  })
  const questionAt = (id, seq) => sessions[id].questions[seq - 1]
  const isGraded = (id, seq) => graded.has(`${id}:${seq}`)
  const answeredOf = (id) => sessions[id].questions.filter((_, index) => isGraded(id, index + 1)).length
  const correctOf = (id) => sessions[id].questions.filter((_, index) => {
    const choiceNo = graded.get(`${id}:${index + 1}`)
    return choiceNo !== undefined && choiceNo === sessions[id].questions[index].answer
  }).length

  function gradeBody(entry, choiceNo) {
    const isCorrect = choiceNo === entry.answer
    return {
      questionId: entry.item.id,
      choiceNo,
      isCorrect,
      answer: entry.answer,
      explanation: entry.explanation,
      keyPoint: entry.keyPoint,
      choicesAnalysis: entry.choicesAnalysis,
      state: {
        questionId: entry.item.id,
        attemptCount: 1,
        correctCount: isCorrect ? 1 : 0,
        wrongCount: isCorrect ? 0 : 1,
        lastIsCorrect: isCorrect,
        lastChoiceNo: choiceNo,
        lastAnsweredAt: STUB_AT,
        streak: isCorrect ? 1 : 0,
        bookmarked: false,
        note: null,
        reviewDueOn: null,
        updatedAt: STUB_AT,
      },
    }
  }

  function itemBody(id, seq) {
    const entry = questionAt(id, seq)
    const choiceNo = graded.get(`${id}:${seq}`) ?? null
    return {
      ...entry.item,
      seq,
      choiceNo,
      isCorrect: choiceNo === null ? null : choiceNo === entry.answer,
      answeredAt: choiceNo === null ? null : STUB_AT,
      result: choiceNo === null ? null : gradeBody(entry, choiceNo),
    }
  }

  function sessionBody(id) {
    const meta = sessions[id]
    const count = meta.questions.length
    const answered = answeredOf(id)
    const finished = Boolean(meta.abandoned) || (count > 0 && answered === count)
    return {
      id: Number(id),
      mode: meta.mode,
      examId: null,
      subjectCode: meta.subjectCode,
      cycleId: meta.cycleId,
      roundNo: meta.roundNo,
      endReason: meta.abandoned ? 'abandoned' : null,
      startedAt: STUB_AT,
      finishedAt: finished ? STUB_AT : null,
      answered,
      correct: correctOf(id),
      itemCount: count,
      answeredCount: answered,
      nextSeq: finished || answered === count ? null : answered + 1,
      items: meta.questions.map((entry, index) => ({
        seq: index + 1,
        questionId: entry.item.id,
        choiceNo: graded.get(`${id}:${index + 1}`) ?? null,
        isCorrect: null,
      })),
      examResult: null,
    }
  }

  await context.route(`${apiOrigin}/**`, async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    // 도식 이미지는 실제 백엔드에서 그대로 받는다(파일 서빙 확인)
    if (pathname.startsWith('/figures/')) return route.continue()

    const answerMatch = pathname.match(/^\/api\/sessions\/(\d+)\/items\/(\d+)\/answer$/)
    if (answerMatch && request.method() === 'PUT') {
      const id = answerMatch[1]
      const seq = Number(answerMatch[2])
      const body = request.postDataJSON()
      puts.push({ session: Number(id), seq, ...body })
      const entry = questionAt(id, seq)
      if (conflict && id === '7101' && !lostOnce) {
        // 응답을 잃은 것처럼 끊는다 — 서버에는 기록이 남았다(재전송 멱등·409 확인용)
        lostOnce = true
        graded.set(`${id}:${seq}`, body.choiceNo)
        return route.abort('failed')
      }
      if (conflict && id === '7101' && isGraded(id, seq) && graded.get(`${id}:${seq}`) !== body.choiceNo) {
        return route.fulfill(json({ detail: '이미 채점된 문항입니다. 같은 보기만 다시 보낼 수 있습니다' }, 409))
      }
      graded.set(`${id}:${seq}`, body.choiceNo)
      const count = sessions[id].questions.length
      const answered = answeredOf(id)
      const finished = answered === count
      const result = {
        ...gradeBody(entry, body.choiceNo),
        session: { id: Number(id), itemCount: count, answeredCount: answered, nextSeq: finished ? null : answered + 1, finished },
        roundResult: null,
        cycle: null,
      }
      if (finished && id === '7001') {
        result.roundResult = { roundNo: 1, itemCount: count, correct: correctOf(id), wrong: count - correctOf(id) }
        result.cycle = { id: 9001, status: 'active', nextSessionId: 7002, nextRoundNo: 2, nextItemCount: ROUND2_QUESTIONS.length }
      }
      if (finished && id === '7002') {
        result.roundResult = { roundNo: 2, itemCount: count, correct: count, wrong: 0 }
        result.cycle = { id: 9001, status: 'completed', nextSessionId: null, nextRoundNo: null, nextItemCount: null }
      }
      return route.fulfill(json(result))
    }

    const itemMatch = pathname.match(/^\/api\/sessions\/(\d+)\/items\/(\d+)$/)
    if (itemMatch) return route.fulfill(json(itemBody(itemMatch[1], Number(itemMatch[2]))))

    const sessionMatch = pathname.match(/^\/api\/sessions\/(\d+)$/)
    if (sessionMatch && sessions[sessionMatch[1]]) return route.fulfill(json(sessionBody(sessionMatch[1])))

    return route.fulfill(json({ detail: `stub 연습: 정의되지 않은 경로 ${pathname}` }, 404))
  })

  return { puts, sessions }
}

/** 연습 화면 — 문항(코드·지문·표·도식) → 제출·해설 → 라운드 종료 → 오답 복습 라운드 */
async function capturePractice(browser) {
  console.log('\n[6] 연습 화면 — 문항·제출·해설·라운드 전환 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const { puts } = await stubPracticeApi(context)
  const page = await context.newPage()
  const errors = watchConsole(page)
  const before = problems.length

  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/sessions/7001`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="practice-item"]', { timeout: 90000 })
  await sleep(300)

  if (await page.locator('[data-testid="passage-code"]').count()) pass('[연습] 코드 지문 고정폭 렌더')
  else fail('[연습] 코드 지문(passage-code)이 없습니다')
  const progressLine = (await page.locator('[data-testid="practice-progress"]').innerText()).replace(/\s+/g, ' ')
  if (progressLine.includes('문항 1 / 4')) pass(`[연습] 진행 표시: ${progressLine}`)
  else fail(`[연습] 진행 표시가 다릅니다: ${progressLine}`)
  await save(page, 'practice-question-code-desktop-1280x900.png')
  await auditLayout(page, '연습 문항 데스크톱 1280')

  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'practice-question-code-mobile-375x812.png')
  await auditLayout(page, '연습 문항 모바일 375')
  await page.setViewportSize(DESKTOP)
  await sleep(200)

  // 키보드만으로 보기 선택(방향키) → 제출(Enter)
  let onRadio = false
  for (let i = 0; i < 12 && !onRadio; i++) {
    await page.keyboard.press('Tab')
    onRadio = await page.evaluate(() => document.activeElement?.getAttribute('type') === 'radio')
  }
  if (onRadio) pass('[연습] Tab 으로 보기(라디오) 포커스 진입')
  else fail('[연습] Tab 으로 보기에 포커스가 가지 않습니다')
  await page.keyboard.press('ArrowDown')
  const checkedValue = await page.evaluate(() => document.querySelector('input[name="practice-choice"]:checked')?.value ?? '')
  if (checkedValue === '2') pass('[연습] 방향키로 보기 2 선택')
  else fail(`[연습] 방향키 선택이 동작하지 않습니다: ${checkedValue}`)

  let onSubmit = false
  for (let i = 0; i < 8 && !onSubmit; i++) {
    await page.keyboard.press('Tab')
    onSubmit = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') === 'practice-submit')
  }
  if (onSubmit) pass('[연습] Tab 으로 제출 버튼 포커스')
  else fail('[연습] Tab 으로 제출 버튼에 포커스가 가지 않습니다')
  await page.keyboard.press('Enter')
  await page.waitForSelector('[data-testid="practice-result"]', { timeout: 30000 })

  const firstPut = puts.find((entry) => entry.session === 7001 && entry.seq === 1)
  const verdict = (await page.locator('[data-testid="practice-verdict"]').innerText()).trim()
  if (verdict.includes('정답') && firstPut?.choiceNo === 2 && Number.isFinite(firstPut?.elapsedMs)) {
    pass(`[연습] 키보드만으로 제출 → ${verdict} · PUT choiceNo=${firstPut.choiceNo} elapsedMs=${firstPut.elapsedMs}`)
  } else {
    fail(`[연습] 키보드 제출 결과가 예상과 다릅니다: ${verdict} / ${JSON.stringify(firstPut)}`)
  }
  await save(page, 'practice-graded-desktop-1280x900.png')
  await auditLayout(page, '연습 채점 데스크톱 1280')

  if (await page.locator('[data-testid="practice-analysis"]').count() === 0) pass('[연습] 보기별 해설 기본 접힘')
  else fail('[연습] 보기별 해설이 기본으로 펼쳐져 있습니다')
  await page.locator('[data-testid="practice-analysis-toggle"]').click()
  await page.waitForSelector('[data-testid="practice-analysis"]', { timeout: 10000 })
  const analysisRows = await page.locator('[data-testid="practice-analysis"] li').count()
  if (analysisRows === 4) pass('[연습] 보기별 해설 펼치기 → 4개 확인')
  else fail(`[연습] 보기별 해설 항목이 4개가 아닙니다: ${analysisRows}`)
  await save(page, 'practice-graded-analysis-desktop-1280x900.png')

  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'practice-graded-mobile-375x812.png')
  await auditLayout(page, '연습 채점 모바일 375')
  await page.setViewportSize(DESKTOP)

  // 지문(text) → 표 → 도식 순서로 지나간다
  await page.locator('[data-testid="practice-next"]').click()
  await page.waitForSelector('[data-testid="passage-text"]', { timeout: 30000 })
  pass('[연습] 지문(text) 렌더(문항 2 / 4)')
  await page.locator('[data-testid="practice-choice-1"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-result"]', { timeout: 30000 })

  await page.locator('[data-testid="practice-next"]').click()
  await page.waitForSelector('[data-testid="passage-table"]', { timeout: 30000 })
  await sleep(200)
  pass('[연습] 표 지문 렌더(문항 3 / 4)')
  await save(page, 'practice-question-table-desktop-1280x900.png')
  await page.locator('[data-testid="practice-choice-3"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-result"]', { timeout: 30000 })
  const wrongVerdict = (await page.locator('[data-testid="practice-verdict"]').innerText()).trim()
  if (wrongVerdict.includes('오답')) pass(`[연습] 오답 표시: ${wrongVerdict}`)
  else fail(`[연습] 오답 문항이 오답으로 표시되지 않았습니다: ${wrongVerdict}`)
  await save(page, 'practice-graded-wrong-desktop-1280x900.png')

  await page.locator('[data-testid="practice-next"]').click()
  await page.waitForSelector('[data-testid="practice-figure"]', { timeout: 30000 })
  // 이미지가 실제로 로드될 때까지 기다린다(요소만 생기고 아직 로딩 중일 수 있다)
  await page.waitForFunction(() => {
    const image = document.querySelector('[data-testid="practice-figure"]')
    return Boolean(image && image.complete && image.naturalWidth > 0)
  }, null, { timeout: 15000 }).catch(() => {})
  const imageOk = await page.evaluate(() => {
    const image = document.querySelector('[data-testid="practice-figure"]')
    return Boolean(image && image.complete && image.naturalWidth > 0)
  })
  const altText = await page.locator('[data-testid="practice-figure"]').getAttribute('alt')
  if (imageOk && altText) pass(`[연습] 도식 이미지 로드 + alt: ${altText.slice(0, 30)}…`)
  else fail(`[연습] 도식 이미지가 로드되지 않았습니다(alt=${altText})`)

  // 앞 문항의 채점 상태(정오답 색·해설 패널)가 남지 않아야 한다
  await sleep(400)
  const stale = await page.evaluate(() => ({
    tinted: Array.from(document.querySelectorAll('[data-testid^="practice-choice-"]'))
      .filter((el) => /emerald|red-/.test(el.className)).length,
    resultPanels: document.querySelectorAll('[data-testid="practice-result"]').length,
  }))
  if (stale.tinted === 0 && stale.resultPanels === 0) pass('[연습] 다음 문항에서 정오답 색·해설 패널이 초기화됨')
  else fail(`[연습] 앞 문항 채점 상태가 남았습니다: ${JSON.stringify(stale)}`)
  await save(page, 'practice-question-figure-desktop-1280x900.png')

  // 마지막 문항 제출 → 라운드 종료 요약
  await page.locator('[data-testid="practice-choice-2"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-round-end"]', { timeout: 30000 })
  const roundText = (await page.locator('[data-testid="practice-round-end"]').innerText()).replace(/\s+/g, ' ')
  if (/전체 4문항/.test(roundText) && /정답 3/.test(roundText) && /오답 1/.test(roundText)) {
    pass(`[연습] 라운드 종료 요약: ${roundText.slice(0, 46)}`)
  } else {
    fail(`[연습] 라운드 종료 요약이 예상과 다릅니다: ${roundText.slice(0, 90)}`)
  }
  await save(page, 'practice-round-end-desktop-1280x900.png')

  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'practice-round-end-mobile-375x812.png')
  await page.setViewportSize(DESKTOP)

  // 다음 라운드(오답 복습) 이어가기 → 사이클 완료
  await page.locator('[data-testid="practice-next-round"]').click()
  await page.waitForURL('**/sessions/7002', { timeout: 30000 })
  await page.waitForSelector('[data-testid="practice-item"]', { timeout: 30000 })
  const reviewLine = (await page.locator('[data-testid="practice-progress"]').innerText()).replace(/\s+/g, ' ')
  if (reviewLine.includes('문항 1 / 1') && reviewLine.includes('오답 복습')) pass(`[연습] 다음 라운드 진입: ${reviewLine}`)
  else fail(`[연습] 다음 라운드 화면이 예상과 다릅니다: ${reviewLine}`)
  await page.locator('[data-testid="practice-choice-1"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-cycle-completed"]', { timeout: 30000 })
  pass('[연습] 오답이 없어 사이클 완료 안내 표시')
  await save(page, 'practice-cycle-completed-desktop-1280x900.png')

  if (errors.length === 0) pass('[연습] 브라우저 콘솔 오류 0')
  else for (const message of errors) fail(`[연습] ${message}`)

  await context.close()
  return problems.length - before
}

/** 연습 제출 충돌(409·중단 세션) 안내 */
async function capturePracticeConflicts(browser) {
  console.log('\n[7] 연습 제출 충돌·중단 세션 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  await stubPracticeApi(context, { conflict: true })
  const page = await context.newPage()
  watchConsole(page)
  await page.setViewportSize(DESKTOP)

  await page.goto(`${baseUrl}/sessions/7101`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="practice-item"]', { timeout: 90000 })

  // 첫 제출은 응답을 잃는다 → 같은 보기 재전송 안내
  await page.locator('[data-testid="practice-choice-3"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-submit-error"]', { timeout: 30000 })
  const submitError = (await page.locator('[data-testid="practice-submit-error"]').innerText()).replace(/\s+/g, ' ')
  if (submitError.includes('같은 보기로 다시 보내면 기록이 늘지 않고')) pass('[연습] 응답 유실 → 제출 오류와 재전송 안내 표시')
  else fail(`[연습] 제출 오류 안내가 부족합니다: ${submitError.slice(0, 80)}`)
  await save(page, 'practice-submit-error-desktop-1280x900.png')

  // 다른 보기로 재제출 → 409 메시지를 그대로 보여주고 저장된 결과로 다음 진행
  await page.locator('[data-testid="practice-choice-4"]').click()
  await page.locator('[data-testid="practice-submit"]').click()
  await page.waitForSelector('[data-testid="practice-conflict"]', { timeout: 30000 })
  const conflictText = (await page.locator('[data-testid="practice-conflict"]').innerText()).trim()
  if (conflictText.includes('이미 채점된 문항입니다')) pass(`[연습] 409 메시지 그대로 표시: ${conflictText}`)
  else fail(`[연습] 409 메시지가 다릅니다: ${conflictText}`)
  await page.waitForSelector('[data-testid="practice-result"]', { timeout: 15000 })
  if (await page.locator('[data-testid="practice-next"]').count()) pass('[연습] 409 뒤에도 다음 문항으로 진행 가능')
  else fail('[연습] 409 뒤에 다음 문항 버튼이 없습니다')
  await save(page, 'practice-conflict-desktop-1280x900.png')

  // 중단된 세션 → 안내 + 홈으로
  await page.goto(`${baseUrl}/sessions/7102`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="practice-closed"]', { timeout: 60000 })
  const closedText = (await page.locator('[data-testid="practice-closed"]').innerText()).replace(/\s+/g, ' ')
  if (closedText.includes('중단된 라운드') && await page.getByRole('link', { name: '홈으로', exact: true }).count() === 1) {
    pass(`[연습] 중단 세션 안내 + 홈으로: ${closedText.slice(0, 46)}`)
  } else {
    fail(`[연습] 중단 세션 안내가 예상과 다릅니다: ${closedText.slice(0, 80)}`)
  }
  await save(page, 'practice-abandoned-desktop-1280x900.png')

  // 문항이 없는 라운드 → 빈 상태 안내
  await page.goto(`${baseUrl}/sessions/7103`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="practice-empty"]', { timeout: 60000 })
  pass(`[연습] 빈 라운드 안내: ${(await page.locator('[data-testid="practice-empty"]').innerText()).replace(/\s+/g, ' ').slice(0, 40)}`)
  await save(page, 'practice-empty-desktop-1280x900.png')

  // 없는 세션 → 404 안내 + 재시도·홈으로
  await page.goto(`${baseUrl}/sessions/9999`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="practice-error"]', { timeout: 60000 })
  const notFoundText = (await page.locator('[data-testid="practice-error"]').innerText()).replace(/\s+/g, ' ')
  if (notFoundText.includes('찾을 수 없습니다') && notFoundText.includes('다시 시도') && notFoundText.includes('홈으로')) {
    pass(`[연습] 404 안내: ${notFoundText.slice(0, 44)}`)
  } else {
    fail(`[연습] 404 안내가 예상과 다릅니다: ${notFoundText.slice(0, 90)}`)
  }
  await save(page, 'practice-404-desktop-1280x900.png')

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
    await capturePractice(browser)
    await capturePracticeConflicts(browser)
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
