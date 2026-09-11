/**
 * 홈·연습·회차·모의고사 화면 스크린샷 + 화면 점검 스크립트.
 *
 *   npm run shots                 # dev 서버(8091)가 없으면 자동 기동 → 캡처 → 종료
 *
 * 하는 일:
 *   1) 실제 DB 데이터로 홈과 회차 선택 화면을 캡처한다(모바일 375x812 · 데스크톱 1280x900) —
 *      콘솔 오류 0, 가로 잘림 0, 클릭 영역 44px 이상, 과목 5개·고유 문항 수·회차 13행을 확인한다.
 *   2) 상태 4종·확인 대화상자·백엔드 다운·로딩 화면은 브라우저에서 API 응답을 대체해 캡처한다.
 *      이때 시작하기/새로 구성이 보내는 본문도 검사한다. DB 는 건드리지 않는다(실제 요청 차단).
 *   3) 연습 화면(문항·제출·해설·보기별 해설·라운드 종료·다음 라운드)과 충돌(409·중단) 안내도
 *      대체 응답으로 캡처한다 — 코드·지문·표·도식 네 종류를 지나가며, 보기 선택과 제출은
 *      키보드만으로 되는지 확인한다. 연습 픽스처는 실제 데이터셋 문항이다(scripts/practice-fixtures.mjs).
 *   4) 회차별 연습·모의고사 — 회차 선택(13행·이어풀기·409 대화상자), 모의고사 풀이(정답·해설 미노출,
 *      선택 즉시 저장, 번호 그리드 100칸, 미응답 강조 제출 확인), 결과(요약·과목별 점수·문항 그리드·
 *      해설 재조회)를 대체 응답으로 캡처하고 키보드만으로 보기 선택·문항 이동이 되는지 확인한다.
 *      픽스처는 scripts/exam-fixtures.mjs(실 DB 응답에서 옮긴 회차 13행 + 실제 데이터셋 문항).
 *
 * SHOTS_DIR(기본 <저장소 루트>/tmp/shots) · SHOTS_BASE_URL(기본 http://localhost:8091) 로 바꿀 수 있다.
 */
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import {
  EXAM_DETAIL,
  EXAM_LIST,
  examItem,
  examResult,
  examSession,
  initialExamChoices,
  openSessionList,
} from './exam-fixtures.mjs'
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

async function save(page, name, { fullPage = true } = {}) {
  // sticky 헤더가 문서 중간에 찍히지 않게 항상 맨 위에서 캡처한다
  await page.evaluate(() => window.scrollTo(0, 0))
  await sleep(150)
  const file = path.join(shotsDir, name)
  await page.screenshot({ path: file, fullPage })
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

  // 회차 선택 화면도 실 데이터로 한 번 — 13회차 목록·문항 수가 그대로 나오는지(DB 무변경: 조회만)
  await page.goto(`${baseUrl}/exams`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-row-2026-1"]', { timeout: 60000 })
  await sleep(300)
  const beforeExamsChecks = problems.length
  const rowCount = await page.locator('[data-testid^="exam-row-"]:not([data-testid^="exam-row-title-"])').count()
  if (rowCount === EXAM_LIST.length) pass(`실제 데이터로 회차 ${rowCount}행 렌더링 확인`)
  else fail(`회차 행 수가 ${rowCount}개입니다(기대 ${EXAM_LIST.length}개)`)
  for (const exam of EXAM_LIST) {
    const row = page.locator(`[data-testid="exam-row-${exam.id}"]`)
    if (await row.count() === 0) {
      fail(`회차 ${exam.id} 행이 없습니다`)
      continue
    }
    const text = (await row.innerText()).replace(/\s+/g, ' ')
    if (!text.includes(exam.title)) fail(`회차 ${exam.id} 행에 제목이 없습니다: ${text.slice(0, 60)}`)
    if (!text.includes(`${exam.questionCount}문항`)) fail(`회차 ${exam.id} 행에 문항 수가 없습니다: ${text.slice(0, 60)}`)
  }
  await save(page, 'exams-real-desktop-1280x900.png')
  await auditLayout(page, '회차 선택 실제 데이터 1280')
  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'exams-real-mobile-375x812.png')
  await auditLayout(page, '회차 선택 실제 데이터 375')
  if (problems.length === beforeExamsChecks) pass('실제 데이터 회차 목록 13행·제목·문항 수 확인')
  await page.setViewportSize(DESKTOP)

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
    // 홈의 회차 자리 — 회차 13행과 열린 세션 목록(모의고사 화면 캡처와 같은 고정 데이터)
    if (pathname === '/api/exams') return route.fulfill(json(EXAM_LIST))
    if (pathname === '/api/sessions' && request.method() === 'GET') return route.fulfill(json(openSessionList()))
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
  if (progressLine.includes('프로그래밍 언어 활용') && progressLine.includes('문항 1 / 4')) pass(`[연습] 진행 표시(데스크톱 한 줄): ${progressLine}`)
  else fail(`[연습] 데스크톱 진행 표시가 다릅니다: ${progressLine}`)
  await save(page, 'practice-question-code-desktop-1280x900.png')
  await auditLayout(page, '연습 문항 데스크톱 1280')

  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'practice-question-code-mobile-375x812.png')
  await auditLayout(page, '연습 문항 모바일 375')
  // 좁은 화면에서 진행 표시가 잘리지 않는지(리뷰 P2-1) — 헤더 컷도 따로 남긴다
  const mobileHeader = await page.evaluate(() => {
    const progress = document.querySelector('[data-testid="practice-progress-mobile"]')
    const context = document.querySelector('[data-testid="practice-context-mobile"]')
    return {
      progressText: (progress?.textContent || '').trim(),
      progressWidth: progress?.clientWidth ?? 0,
      progressScroll: progress?.scrollWidth ?? 0,
      contextText: (context?.textContent || '').trim(),
      contextWidth: context?.clientWidth ?? 0,
      headerScroll: document.querySelector('header')?.scrollWidth ?? 0,
    }
  })
  if (/^문항 \d+ \/ \d+$/.test(mobileHeader.progressText) && mobileHeader.progressScroll <= mobileHeader.progressWidth + 1) {
    pass(`[연습] 모바일 375 헤더 진행 표시 잘림 없음: "${mobileHeader.progressText}" (client ${mobileHeader.progressWidth} / scroll ${mobileHeader.progressScroll})`)
  } else {
    fail(`[연습] 모바일 헤더 진행 표시가 잘리거나 없습니다: ${JSON.stringify(mobileHeader)}`)
  }
  if (mobileHeader.contextText && mobileHeader.contextWidth > 0) pass(`[연습] 모바일 과목·라운드 줄 표시: "${mobileHeader.contextText.slice(0, 30)}"`)
  else fail(`[연습] 모바일 과목·라운드 줄이 없습니다: ${JSON.stringify(mobileHeader)}`)
  if (mobileHeader.headerScroll <= MOBILE.width) pass(`[연습] 모바일 헤더 가로 넘침 없음(${mobileHeader.headerScroll} ≤ ${MOBILE.width})`)
  else fail(`[연습] 모바일 헤더가 가로로 넘칩니다: ${mobileHeader.headerScroll}`)
  await save(page, 'practice-mobile-header-375x812.png', { fullPage: false })
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

/**
 * 회차 선택·모의고사 전용 대체 API — DB 에 아무것도 쓰지 않는다.
 * 실제 API 처럼 제출 전 조회에는 정답·해설을 넣지 않고, 선택 저장은 {seq, choiceNo, answeredAt} 만 돌려준다.
 *  7201 모의고사 진행 중(12문항 선택 · 88문항 미응답) → 제출 → 결과
 *  7203 중단된 모의고사 · 7204 모의고사가 아닌 세션(연습) · 9999 없는 세션
 */
async function stubExamApi(context, { conflictOnStart = false, submitted = false, submitError = null } = {}) {
  const choices = initialExamChoices()
  let isSubmitted = submitted
  const puts = []
  const posts = []
  const sessionId = 7201

  const json = (data, status = 200) => ({
    status,
    headers: { 'content-type': 'application/json', 'access-control-allow-origin': '*' },
    body: JSON.stringify(data),
  })

  await context.route(`${apiOrigin}/**`, async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    // 도식 이미지는 실제 백엔드에서 그대로 받는다(파일 서빙 확인)
    if (pathname.startsWith('/figures/')) return route.continue()

    if (pathname === '/api/exams') return route.fulfill(json(EXAM_LIST))
    if (pathname === `/api/exams/${EXAM_DETAIL.id}`) return route.fulfill(json(EXAM_DETAIL))
    if (pathname.startsWith('/api/exams/')) {
      return route.fulfill(json({ detail: `회차 ${pathname.slice('/api/exams/'.length)} 를 찾을 수 없습니다` }, 404))
    }
    // 홈의 과목 요약 — 회차 진입점이 과목 카드와 함께 보이는지 확인하기 위해 필요하다
    if (pathname === '/api/subject-cycles/overview') return route.fulfill(json(stubOverview))

    if (pathname === '/api/sessions' && request.method() === 'GET') return route.fulfill(json(openSessionList()))
    if (pathname === '/api/sessions' && request.method() === 'POST') {
      const body = request.postDataJSON()
      posts.push(body)
      const openExists = (body.mode === 'exam' && body.examId === '2026-1')
        || (body.mode === 'exam_practice' && body.examId === '2024-1')
      if (conflictOnStart && openExists && !body.replaceActive) {
        return route.fulfill(json({
          detail: `이미 진행 중인 ${body.mode} 세션이 있습니다. replaceActive=true 로 새로 구성하세요`,
        }, 409))
      }
      return route.fulfill(json({
        id: body.mode === 'exam' ? sessionId : 7202,
        mode: body.mode,
        examId: body.examId,
        subjectCode: null,
        cycleId: null,
        roundNo: null,
        endReason: null,
        startedAt: STUB_AT,
        finishedAt: null,
        answered: 0,
        correct: 0,
      }, 201))
    }

    const submitMatch = pathname.match(/^\/api\/sessions\/(\d+)\/submit$/)
    if (submitMatch && request.method() === 'POST') {
      const id = Number(submitMatch[1])
      if (id === 7204) {
        return route.fulfill(json({
          detail: 'POST /api/sessions/{id}/submit 은 모의고사(mode=exam) 전용입니다. '
            + '연습은 마지막 문항에서 자동 종료되고 random 세션은 /finish 를 쓰세요',
        }, 400))
      }
      if (id === 7203) {
        return route.fulfill(json({ detail: '중단된 모의고사입니다. 새로 구성한 세션에서 계속하세요' }, 409))
      }
      if (id !== sessionId) return route.fulfill(json({ detail: `세션 ${id} 를 찾을 수 없습니다` }, 404))
      if (submitError) return route.fulfill(json(submitError.body, submitError.status))
      // 재제출도 같은 결과(서버가 멱등) — 두 번째부터는 기록이 늘지 않는다
      isSubmitted = true
      return route.fulfill(json(examResult(choices, id)))
    }

    const answerMatch = pathname.match(/^\/api\/sessions\/(\d+)\/items\/(\d+)\/answer$/)
    if (answerMatch && request.method() === 'PUT') {
      const seq = Number(answerMatch[2])
      const body = request.postDataJSON()
      puts.push({ session: Number(answerMatch[1]), seq, ...body })
      if (isSubmitted) {
        return route.fulfill(json({ detail: '이미 제출된 모의고사입니다. 결과는 세션 조회로 확인하세요' }, 409))
      }
      if (body.choiceNo === null || body.choiceNo === undefined) delete choices[seq]
      else choices[seq] = body.choiceNo
      return route.fulfill(json({
        seq,
        choiceNo: body.choiceNo ?? null,
        answeredAt: body.choiceNo === null ? null : STUB_AT,
      }))
    }

    const itemMatch = pathname.match(/^\/api\/sessions\/(\d+)\/items\/(\d+)$/)
    if (itemMatch) {
      const id = Number(itemMatch[1])
      const seq = Number(itemMatch[2])
      if (id === 7204) return route.fulfill(json(examItem(seq, null)))
      // 7202(회차별 연습)는 연습 화면이 여는 세션 — 채점 없는 문항을 그대로 준다
      if (id === 7202) return route.fulfill(json(examItem(seq, choices[seq] ?? null)))
      if (id === 7203) return route.fulfill(json({ detail: '중단된 모의고사입니다. 새로 구성한 세션에서 계속하세요' }, 409))
      if (id !== sessionId) return route.fulfill(json({ detail: `세션 ${id} 에 ${seq}번 문항이 없습니다` }, 404))
      return route.fulfill(json(examItem(seq, choices[seq] ?? null, { revealed: isSubmitted })))
    }

    const sessionMatch = pathname.match(/^\/api\/sessions\/(\d+)$/)
    if (sessionMatch) {
      const id = Number(sessionMatch[1])
      if (id === sessionId) return route.fulfill(json(examSession(choices, { submitted: isSubmitted })))
      if (id === 7202) {
        return route.fulfill(json({ ...examSession(choices, { id: 7202 }), mode: 'exam_practice', examId: '2024-1' }))
      }
      if (id === 7203) {
        return route.fulfill(json({
          ...examSession(choices, { id: 7203 }),
          endReason: 'abandoned',
          finishedAt: STUB_AT,
          nextSeq: null,
        }))
      }
      if (id === 7204) {
        return route.fulfill(json({ ...examSession(choices, { id: 7204 }), mode: 'subject', examId: null, subjectCode: 4, cycleId: 9001, roundNo: 1 }))
      }
      return route.fulfill(json({ detail: `세션 ${id} 를 찾을 수 없습니다` }, 404))
    }

    return route.fulfill(json({ detail: `stub 모의고사: 정의되지 않은 경로 ${pathname}` }, 404))
  })

  return { puts, posts }
}

/** 그리드에서 상태별 원 개수 — 미응답/선택됨/정답/오답 표기가 맞는지 센다 */
async function gridStateCounts(page) {
  return page.evaluate(() => {
    const cells = Array.from(document.querySelectorAll('[data-testid^="exam-grid-"][data-state]'))
    const counts = { total: cells.length, unanswered: 0, chosen: 0, correct: 0, wrong: 0 }
    for (const cell of cells) {
      const state = cell.getAttribute('data-state')
      if (state in counts) counts[state] += 1
    }
    return counts
  })
}

/**
 * 브라우저가 4xx 응답을 자동으로 남기는 네트워크 로그('Failed to load resource').
 * 의도한 오류 경로(409·400·404)를 확인하는 컷에서만 걸러낸다 — JS 오류와는 다르다.
 */
function isExpectedResourceLog(message, statuses) {
  return message.includes('Failed to load resource') && statuses.some(code => message.includes(`status of ${code}`))
}

/** POST 본문이 count 건 이상 쌓일 때까지 기다린다 */
async function waitForPosts(posts, count, timeout = 15000) {
  const deadline = Date.now() + timeout
  while (posts.length < count && Date.now() < deadline) await sleep(100)
  return posts.length >= count
}

/** 회차 선택 화면 — 13회차 목록·진행 중 이어풀기·시작 본문·409 대화상자 */
async function captureExamsList(browser) {
  console.log('\n[8] 회차 선택 — 13회차·이어풀기·시작·409 대화상자 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const { posts } = await stubExamApi(context, { conflictOnStart: true })
  const page = await context.newPage()
  const errors = watchConsole(page)
  const before = problems.length

  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/exams`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="exam-row-2026-1"]', { timeout: 90000 })
  await sleep(300)

  const rows = await page.locator('[data-testid^="exam-row-"]:not([data-testid^="exam-row-title-"])').count()
  if (rows === EXAM_LIST.length) pass(`[회차] 13회차 목록(${rows}행) 표시`)
  else fail(`[회차] 회차 행 수가 ${rows}개입니다(기대 ${EXAM_LIST.length}개)`)

  // 진행 중 이어풀기 — 모의고사(7201)·회차 연습(7202)만, 끝난 세션(2023-3)은 없어야 한다
  const resumeExam = page.locator('[data-testid="exam-resume-2026-1-exam"]')
  const resumePractice = page.locator('[data-testid="exam-resume-2024-1-exam_practice"]')
  if (await resumeExam.count() === 1 && await resumePractice.count() === 1) {
    pass('[회차] 진행 중 세션에만 이어풀기 표시(모의고사 2026-1 · 회차 연습 2024-1)')
  } else {
    fail(`[회차] 이어풀기 표시가 예상과 다릅니다(모의고사 ${await resumeExam.count()} · 연습 ${await resumePractice.count()})`)
  }
  if (await page.locator('[data-testid="exam-open-2023-3-exam"]').count() === 0) {
    pass('[회차] 끝난 세션(2023-3)은 이어풀기로 나오지 않음')
  } else {
    fail('[회차] 제출이 끝난 세션이 이어풀기로 표시됩니다')
  }
  const resumeHref = await resumeExam.getAttribute('href')
  const practiceHref = await resumePractice.getAttribute('href')
  if (resumeHref === '/exam/7201' && practiceHref === '/sessions/7202') {
    pass(`[회차] 이어풀기 경로 — 모의고사 ${resumeHref} · 회차 연습 ${practiceHref}`)
  } else {
    fail(`[회차] 이어풀기 경로가 예상과 다릅니다: ${resumeHref} / ${practiceHref}`)
  }

  await save(page, 'exams-list-desktop-1280x900.png')
  await auditLayout(page, '회차 선택 데스크톱 1280')
  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'exams-list-mobile-375x812.png')
  await auditLayout(page, '회차 선택 모바일 375')
  await page.setViewportSize(DESKTOP)
  await sleep(200)

  // 홈에도 진행 중 회차 세션이 보이고 이어풀기가 모의고사/연습 화면으로 갈라지는지
  await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="home-exam-session"]', { timeout: 60000 })
  const homeCards = await page.locator('[data-testid="home-exam-session"]').count()
  const homeResumeExam = await page.locator('[data-testid="home-exam-resume-exam"]').getAttribute('href')
  const homeResumePractice = await page.locator('[data-testid="home-exam-resume-exam_practice"]').getAttribute('href')
  const homeCardText = (await page.locator('[data-testid="home-exam-sessions"]').innerText()).replace(/\s+/g, ' ')
  if (homeCards === 2 && homeResumeExam === '/exam/7201' && homeResumePractice === '/sessions/7202') {
    pass(`[회차] 홈 진행 중 카드 ${homeCards}개 — 모의고사 ${homeResumeExam} · 연습 ${homeResumePractice}`)
  } else {
    fail(`[회차] 홈 진행 중 표시가 예상과 다릅니다: 카드 ${homeCards} · ${homeResumeExam} / ${homeResumePractice}`)
  }
  if (homeCardText.includes('2026년 1회 정보처리기사 필기') && homeCardText.includes('12 / 100문항')) {
    pass(`[회차] 홈 카드에 회차 제목·진행도 표시: ${homeCardText.slice(0, 60)}`)
  } else {
    fail(`[회차] 홈 카드 문구가 예상과 다릅니다: ${homeCardText.slice(0, 90)}`)
  }
  await sleep(200)
  await save(page, 'home-exam-sessions-desktop-1280x900.png')
  await auditLayout(page, '홈 회차 진행 중 데스크톱 1280')
  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'home-exam-sessions-mobile-375x812.png')
  await auditLayout(page, '홈 회차 진행 중 모바일 375')
  await page.setViewportSize(DESKTOP)
  await sleep(200)
  await page.goto(`${baseUrl}/exams`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-row-2026-1"]', { timeout: 60000 })

  // 진행 중 세션이 없는 회차(2025-2)는 회차별 연습이 바로 시작된다 → POST 본문 확인 + 연습 화면 이동
  await page.locator('[data-testid="exam-practice-2025-2"]').click()
  await waitForPosts(posts, 1)
  const started = posts.at(-1)
  if (started?.mode === 'exam_practice' && started?.examId === '2025-2' && started?.replaceActive === false) {
    pass(`[회차] 회차별 연습 시작 → POST /api/sessions ${JSON.stringify(started)}`)
  } else {
    fail(`[회차] 회차별 연습 시작 본문이 예상과 다릅니다: ${JSON.stringify(started)}`)
  }
  await page.waitForURL('**/sessions/**', { timeout: 15000 })
    .then(() => pass('[회차] 회차별 연습은 기존 연습 화면(/sessions/{id})으로 이동'))
    .catch(() => fail('[회차] 회차별 연습 시작 뒤 연습 화면으로 이동하지 않았습니다'))

  // 진행 중인 모의고사(2026-1)를 다시 시작하면 409 → 확인 대화상자 → replaceActive=true
  await page.goto(`${baseUrl}/exams`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-row-2026-1"]', { timeout: 60000 })
  const beforeConflict = posts.length
  await page.locator('[data-testid="exam-mock-2026-1"]').click()
  await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 15000 })
  await waitForPosts(posts, beforeConflict + 1)
  const firstAttempt = posts.at(-1)
  if (firstAttempt?.mode === 'exam' && firstAttempt?.examId === '2026-1' && firstAttempt?.replaceActive === false) {
    pass(`[회차] 진행 중 세션은 replaceActive:false 로 먼저 시도 → 409`)
  } else {
    fail(`[회차] 첫 시도 본문이 예상과 다릅니다: ${JSON.stringify(firstAttempt)}`)
  }
  const dialogText = (await page.getByTestId('confirm-dialog').innerText()).replace(/\s+/g, ' ')
  if (dialogText.includes('2026년 1회 정보처리기사 필기') && dialogText.includes('중단하고 처음부터 새로 시작')) {
    pass(`[회차] 409 → 중단 확인 대화상자: ${dialogText.slice(0, 50)}`)
  } else {
    fail(`[회차] 409 대화상자 문구가 예상과 다릅니다: ${dialogText.slice(0, 90)}`)
  }
  await sleep(200)
  await save(page, 'exams-replace-dialog-desktop-1280x900.png')
  await page.getByTestId('confirm-dialog').getByRole('button', { name: '중단하고 새로 시작' }).click()
  await waitForPosts(posts, beforeConflict + 2)
  const replaced = posts.at(-1)
  if (replaced?.mode === 'exam' && replaced?.examId === '2026-1' && replaced?.replaceActive === true) {
    pass(`[회차] 중단하고 새로 시작 → POST /api/sessions ${JSON.stringify(replaced)}`)
  } else {
    fail(`[회차] 재시작 본문이 예상과 다릅니다: ${JSON.stringify(replaced)}`)
  }
  await page.waitForURL('**/exam/**', { timeout: 15000 })
    .then(() => pass('[회차] 모의고사 시작은 모의고사 화면(/exam/{id})으로 이동'))
    .catch(() => fail('[회차] 모의고사 시작 뒤 모의고사 화면으로 이동하지 않았습니다'))

  // 409 응답 자체는 브라우저가 네트워크 로그로 남긴다 — JS 오류만 문제로 본다
  const unexpectedErrors = errors.filter(message => !isExpectedResourceLog(message, [409]))
  if (unexpectedErrors.length === 0) pass(`[회차] 브라우저 콘솔 오류 0(의도한 409 네트워크 로그 ${errors.length - unexpectedErrors.length}건 제외)`)
  else for (const message of unexpectedErrors) fail(`[회차] ${message}`)

  await context.close()
  return problems.length - before
}

/** 모의고사 풀이 → 제출 확인 → 결과 → 문항 해설 재조회 */
async function captureExamTaking(browser) {
  console.log('\n[9] 모의고사 풀이·제출·결과 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  const { puts } = await stubExamApi(context)
  const page = await context.newPage()
  const errors = watchConsole(page)
  const before = problems.length

  await page.setViewportSize(DESKTOP)
  await page.goto(`${baseUrl}/exam/7201`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="exam-item"]', { timeout: 90000 })
  await sleep(400)

  // 제출 전에는 정답·해설이 화면에 없다(서버도 보내지 않는다)
  const leak = await page.evaluate(() => {
    const text = document.body.innerText
    return {
      explanation: text.includes('continue는 반복문 전체를 빠져나가는 break와 달리'),
      verdict: text.includes('정답입니다') || text.includes('오답입니다'),
      resultPanel: document.querySelectorAll('[data-testid="exam-explain-text"]').length,
      badges: Array.from(document.querySelectorAll('[data-testid^="exam-choice-"]'))
        .filter(el => /정답|내 답/.test(el.innerText)).length,
    }
  })
  if (!leak.explanation && !leak.verdict && leak.resultPanel === 0 && leak.badges === 0) {
    pass('[모의고사] 풀이 중 정답·해설 미노출(해설 문장·정오답 표기·해설 패널 없음)')
  } else {
    fail(`[모의고사] 풀이 중 정답·해설이 노출됩니다: ${JSON.stringify(leak)}`)
  }

  // 이어풀기 — 서버 nextSeq(13번, 선택 안 된 최소 seq)로 열린다
  const progress = (await page.locator('[data-testid="exam-progress"]').innerText()).replace(/\s+/g, ' ')
  const seqBadge = (await page.locator('[data-testid="exam-item-seq"]').innerText()).replace(/\s+/g, ' ')
  if (progress.includes('문항 13 / 100') && seqBadge === '13 / 100') {
    pass(`[모의고사] 이어풀기 위치 = 서버 nextSeq(13번): ${progress}`)
  } else {
    fail(`[모의고사] 이어풀기 위치가 예상과 다릅니다: ${progress} / ${seqBadge}`)
  }
  if (await page.locator('[data-testid="exam-resume"]').count() === 1) pass('[모의고사] 이어풀기 안내 표시')
  else fail('[모의고사] 이어풀기 안내가 없습니다')

  // 번호 그리드 — 미응답(빈 원) 88 · 선택됨(채운 원) 12
  const initialGrid = await gridStateCounts(page)
  if (initialGrid.total === 100 && initialGrid.chosen === 12 && initialGrid.unanswered === 88) {
    pass(`[모의고사] 번호 그리드 100칸 — 선택됨 ${initialGrid.chosen} · 미응답 ${initialGrid.unanswered}`)
  } else {
    fail(`[모의고사] 번호 그리드 상태가 예상과 다릅니다: ${JSON.stringify(initialGrid)}`)
  }
  const currentRing = await page.evaluate(() => document.querySelectorAll('[data-testid^="exam-grid-"][aria-current="true"]').length)
  if (currentRing === 1) pass('[모의고사] 지금 보는 문항 표시 1개')
  else fail(`[모의고사] 지금 보는 문항 표시가 ${currentRing}개입니다`)

  await save(page, 'exam-taking-desktop-1280x900.png')
  await auditLayout(page, '모의고사 풀이 데스크톱 1280')

  await page.setViewportSize(MOBILE)
  // 모바일 뷰포트로 새로 열면 번호 그리드가 기본 접힘이다(세로로 길어서) — 접힌 상태와 펼친 상태를 모두 남긴다
  await page.goto(`${baseUrl}/exam/7201`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-item"]', { timeout: 60000 })
  await sleep(300)
  if (await page.locator('#exam-grid').count() === 0) pass('[모의고사] 모바일 375 는 번호 그리드가 기본 접힘')
  else fail('[모의고사] 모바일에서 번호 그리드가 기본으로 펼쳐져 있습니다')
  await save(page, 'exam-taking-mobile-375x812.png')
  await auditLayout(page, '모의고사 풀이 모바일 375')
  await page.locator('[data-testid="exam-grid-toggle"]').click()
  await page.waitForSelector('#exam-grid', { timeout: 10000 })
  await sleep(200)
  await save(page, 'exam-grid-mobile-375x812.png')
  await auditLayout(page, '모의고사 그리드 모바일 375')
  const mobileGrid = await gridStateCounts(page)
  if (mobileGrid.chosen === 12 && mobileGrid.unanswered === 88) pass('[모의고사] 모바일 그리드도 선택/미응답 구분 유지')
  else fail(`[모의고사] 모바일 그리드 상태가 다릅니다: ${JSON.stringify(mobileGrid)}`)
  await page.setViewportSize(DESKTOP)
  // 데스크톱 기본값(그리드 펼침)으로 다시 열어 키보드 이동을 확인한다
  await page.goto(`${baseUrl}/exam/7201`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-item"]', { timeout: 60000 })
  await sleep(300)

  // 키보드만으로 문항 이동 — 그리드까지 Tab 으로 간 뒤 방향키로 옮긴다
  // (접기 토글도 exam-grid- 로 시작하므로 숫자까지 붙은 칸만 인정한다)
  let onGrid = false
  let focusedCell = ''
  for (let index = 0; index < 25 && !onGrid; index++) {
    await page.keyboard.press('Tab')
    focusedCell = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') || '')
    onGrid = /^exam-grid-\d+$/.test(focusedCell)
  }
  if (onGrid) pass(`[모의고사] Tab 으로 번호 그리드 포커스 진입(${focusedCell} — 탭 정지 1개)`)
  else fail(`[모의고사] Tab 으로 그리드에 포커스가 가지 않습니다(마지막 포커스 ${focusedCell})`)

  const putsBeforeMove = puts.length
  await page.keyboard.press('ArrowRight')
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-item-seq"]')?.textContent?.trim().startsWith('14 /'), null, { timeout: 15000 })
    .then(() => pass('[모의고사] 방향키로 14번 문항 이동(그리드 포커스 유지)'))
    .catch(() => fail('[모의고사] 방향키 문항 이동이 동작하지 않습니다'))
  await page.keyboard.press('ArrowLeft')
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-item-seq"]')?.textContent?.trim().startsWith('13 /'), null, { timeout: 15000 })
    .catch(() => fail('[모의고사] 방향키로 13번으로 돌아오지 못했습니다'))
  if (puts.length === putsBeforeMove) pass('[모의고사] 문항 이동은 저장 요청을 보내지 않음')
  else fail('[모의고사] 문항 이동만으로 PUT 이 나갔습니다')

  // 키보드만으로 보기 선택(방향키) → 즉시 저장
  let onRadio = false
  for (let index = 0; index < 25 && !onRadio; index++) {
    await page.keyboard.press('Tab')
    onRadio = await page.evaluate(() => document.activeElement?.getAttribute('type') === 'radio')
  }
  if (onRadio) pass('[모의고사] Tab 으로 보기(라디오) 포커스 진입')
  else fail('[모의고사] Tab 으로 보기에 포커스가 가지 않습니다')
  await page.keyboard.press('ArrowDown')
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-choice-2"] input')?.checked === true, null, { timeout: 15000 })
    .catch(() => fail('[모의고사] 방향키 보기 선택이 화면에 반영되지 않았습니다'))
  await page.waitForSelector('[data-testid="exam-save-status"]:has-text("보기를 저장했습니다")', { timeout: 15000 })
    .then(() => pass('[모의고사] 키보드로 고른 보기가 즉시 저장됨'))
    .catch(() => fail('[모의고사] 키보드 선택이 저장되지 않았습니다'))
  const keyboardPut = puts.find(entry => entry.seq === 13)
  if (keyboardPut?.choiceNo === 2 && !('elapsedMs' in keyboardPut)) {
    pass('[모의고사] 선택 저장 본문 = {choiceNo} 만(정답·시간 없음)')
  } else {
    fail(`[모의고사] 선택 저장 본문이 예상과 다릅니다: ${JSON.stringify(keyboardPut)}`)
  }
  const afterSelect = await gridStateCounts(page)
  if (afterSelect.chosen === 13 && afterSelect.unanswered === 87) pass('[모의고사] 선택 즉시 그리드·진행률 갱신(13 선택 · 87 미응답)')
  else fail(`[모의고사] 선택 반영이 예상과 다릅니다: ${JSON.stringify(afterSelect)}`)

  // 선택 해제 → choiceNo:null 저장, 그리드는 다시 미응답
  await page.locator('[data-testid="exam-clear"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-grid-13"]')?.getAttribute('data-state') === 'unanswered', null, { timeout: 15000 })
    .then(() => pass('[모의고사] 선택 해제 → 그리드가 미응답(빈 원)으로 복귀'))
    .catch(() => fail('[모의고사] 선택 해제가 그리드에 반영되지 않았습니다'))
  const clearPut = puts.filter(entry => entry.seq === 13).at(-1)
  if (clearPut && clearPut.choiceNo === null) pass('[모의고사] 선택 해제 본문 = {choiceNo:null}')
  else fail(`[모의고사] 선택 해제 본문이 예상과 다릅니다: ${JSON.stringify(clearPut)}`)

  // 이전·다음 버튼도 동작한다
  await page.locator('[data-testid="exam-next"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-item-seq"]')?.textContent?.trim().startsWith('14 /'), null, { timeout: 15000 })
    .then(() => pass('[모의고사] 다음 문항 버튼 이동'))
    .catch(() => fail('[모의고사] 다음 문항 버튼이 동작하지 않습니다'))
  await page.locator('[data-testid="exam-prev"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-item-seq"]')?.textContent?.trim().startsWith('13 /'), null, { timeout: 15000 })
    .catch(() => fail('[모의고사] 이전 문항 버튼이 동작하지 않습니다'))

  // 제출 확인 — 미응답 문항 수 강조
  const putsBeforeSubmit = puts.length
  await page.locator('[data-testid="exam-submit"]').click()
  await page.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 15000 })
  const submitDialog = (await page.getByTestId('confirm-dialog').innerText()).replace(/\s+/g, ' ')
  const unansweredLine = (await page.locator('[data-testid="submit-unanswered"]').innerText()).replace(/\s+/g, ' ')
  if (/미응답\s*88\s*문항/.test(unansweredLine)) pass(`[모의고사] 제출 확인 대화상자에 미응답 강조: ${unansweredLine}`)
  else fail(`[모의고사] 미응답 강조가 예상과 다릅니다: ${unansweredLine}`)
  await sleep(200)
  await save(page, 'exam-submit-dialog-desktop-1280x900.png')
  await page.setViewportSize(MOBILE)
  await sleep(200)
  await save(page, 'exam-submit-dialog-mobile-375x812.png')
  await auditLayout(page, '제출 확인 모바일 375')
  await page.setViewportSize(DESKTOP)
  await sleep(200)

  // 제출 → 같은 화면이 결과 화면으로 바뀐다
  await page.getByTestId('confirm-dialog').getByRole('button', { name: '제출하기' }).click()
  await page.waitForSelector('[data-testid="exam-result-summary"]', { timeout: 30000 })
  pass('[모의고사] 제출 뒤 결과 화면으로 전환')

  const verdict = (await page.locator('[data-testid="exam-result-verdict"]').innerText()).trim()
  const average = (await page.locator('[data-testid="exam-result-average"]').innerText()).trim()
  const answered = (await page.locator('[data-testid="exam-result-answered"]').innerText()).replace(/\s+/g, ' ')
  const correct = (await page.locator('[data-testid="exam-result-correct"]').innerText()).trim()
  const wrong = (await page.locator('[data-testid="exam-result-wrong"]').innerText()).trim()
  if (verdict === '합격 기준 미달' && average === '9' && answered === '12 / 88' && correct === '9' && wrong === '3') {
    pass(`[모의고사] 결과 요약 — ${verdict} · 평균 ${average}점 · 응답 ${answered} · 정답 ${correct} · 오답 ${wrong}(미응답 제외)`)
  } else {
    fail(`[모의고사] 결과 요약이 예상과 다릅니다: ${verdict} / ${average} / ${answered} / ${correct} / ${wrong}`)
  }

  const subject1 = (await page.locator('[data-testid="exam-subject-1"]').innerText()).replace(/\s+/g, ' ')
  const subject2 = (await page.locator('[data-testid="exam-subject-2"]').innerText()).replace(/\s+/g, ' ')
  if (subject1.includes('소프트웨어 설계') && subject1.includes('45점') && subject1.includes('40점 이상')
    && subject2.includes('40점 미만')) {
    pass(`[모의고사] 과목별 점수 40점 기준 — 1과목 ${subject1} / 2과목 ${subject2}`)
  } else {
    fail(`[모의고사] 과목별 점수 표시가 예상과 다릅니다: ${subject1} / ${subject2}`)
  }

  const resultGrid = await gridStateCounts(page)
  if (resultGrid.correct === 9 && resultGrid.wrong === 3 && resultGrid.unanswered === 88) {
    pass(`[모의고사] 결과 그리드 — 정답 ${resultGrid.correct} · 오답 ${resultGrid.wrong} · 미응답 ${resultGrid.unanswered}(오답과 구분)`)
  } else {
    fail(`[모의고사] 결과 그리드 상태가 예상과 다릅니다: ${JSON.stringify(resultGrid)}`)
  }

  await save(page, 'exam-result-desktop-1280x900.png')
  await auditLayout(page, '모의고사 결과 데스크톱 1280')
  await page.setViewportSize(MOBILE)
  await sleep(300)
  await save(page, 'exam-result-mobile-375x812.png')
  await auditLayout(page, '모의고사 결과 모바일 375')
  await page.setViewportSize(DESKTOP)
  await sleep(200)

  // 미응답 문항 해설 — 미응답으로 표시되고 정답·해설을 볼 수 있다
  await page.locator('[data-testid="exam-grid-13"]').click()
  await page.waitForSelector('[data-testid="exam-explain-text"]', { timeout: 30000 })
  const explainVerdict = (await page.locator('[data-testid="exam-explain-verdict"]').innerText()).trim()
  const explainText = (await page.locator('[data-testid="exam-explain-text"]').innerText()).replace(/\s+/g, ' ')
  const unansweredNote = await page.locator('[data-testid="exam-explain-unanswered"]').innerText().catch(() => '')
  if (explainVerdict === '미응답' && unansweredNote.includes('미응답') && explainText.includes('continue')) {
    pass(`[모의고사] 미응답 문항 해설 — ${explainVerdict} · ${explainText.slice(0, 40)}…`)
  } else {
    fail(`[모의고사] 미응답 문항 해설이 예상과 다릅니다: ${explainVerdict} / ${unansweredNote} / ${explainText.slice(0, 40)}`)
  }
  await save(page, 'exam-result-explain-unanswered-desktop-1280x900.png')

  // 정답·오답 문항도 구분해서 보여준다
  await page.locator('[data-testid="exam-grid-1"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-explain-verdict"]')?.textContent?.trim() === '정답입니다', null, { timeout: 15000 })
    .catch(() => fail('[모의고사] 정답 문항 해설 표시가 다릅니다'))
  await page.locator('[data-testid="exam-explain-analysis-toggle"]').click()
  await page.waitForSelector('[data-testid="exam-explain-analysis"]', { timeout: 10000 })
  const analysisRows = await page.locator('[data-testid="exam-explain-analysis"] li').count()
  if (analysisRows === 4) pass('[모의고사] 문항 해설에서 보기별 해설 4개 펼침')
  else fail(`[모의고사] 보기별 해설 항목이 4개가 아닙니다: ${analysisRows}`)
  await page.locator('[data-testid="exam-grid-10"]').click()
  await page.waitForFunction(() => document.querySelector('[data-testid="exam-explain-verdict"]')?.textContent?.trim() === '오답입니다', null, { timeout: 15000 })
    .then(() => pass('[모의고사] 오답 문항 해설 표시'))
    .catch(() => fail('[모의고사] 오답 문항 해설 표시가 다릅니다'))
  await save(page, 'exam-result-explain-desktop-1280x900.png')

  // 해설 조회는 원장을 늘리지 않는다 — 결과 화면에서 PUT·POST 가 더 나가지 않는다
  if (puts.length === putsBeforeSubmit) pass(`[모의고사] 해설 조회는 PUT 을 보내지 않음(제출 전 ${putsBeforeSubmit}건 그대로)`)
  else fail(`[모의고사] 결과 화면에서 PUT 이 ${puts.length - putsBeforeSubmit}건 더 나갔습니다`)

  if (errors.length === 0) pass('[모의고사] 브라우저 콘솔 오류 0')
  else for (const message of errors) fail(`[모의고사] ${message}`)

  await context.close()
  return problems.length - before
}

/** 풀이할 수 없는 모의고사 세션 안내 — 중단·비-exam·404·제출 충돌(409) */
async function captureExamClosed(browser) {
  console.log('\n[10] 모의고사 안내 화면 — 중단·비-exam·404·제출 409 (API 대체, DB 무변경)')
  const context = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  await stubExamApi(context)
  const page = await context.newPage()
  const consoleErrors = watchConsole(page)
  await page.setViewportSize(DESKTOP)

  // 중단된 모의고사
  await page.goto(`${baseUrl}/exam/7203`, { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.waitForSelector('[data-testid="exam-closed"]', { timeout: 60000 })
  const abandoned = (await page.locator('[data-testid="exam-closed"]').innerText()).replace(/\s+/g, ' ')
  if (abandoned.includes('중단된 모의고사') && abandoned.includes('회차 목록')) {
    pass(`[모의고사 안내] 중단된 세션: ${abandoned.slice(0, 46)}`)
  } else {
    fail(`[모의고사 안내] 중단 세션 문구가 예상과 다릅니다: ${abandoned.slice(0, 90)}`)
  }
  await save(page, 'exam-abandoned-desktop-1280x900.png')

  // 모의고사가 아닌 세션 → 연습 화면으로 안내
  await page.goto(`${baseUrl}/exam/7204`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-closed"]', { timeout: 60000 })
  const notExam = (await page.locator('[data-testid="exam-closed"]').innerText()).replace(/\s+/g, ' ')
  if (notExam.includes('모의고사가 아닙니다') && notExam.includes('전체 문항 풀이')) {
    pass(`[모의고사 안내] 비-exam 세션: ${notExam.slice(0, 46)}`)
  } else {
    fail(`[모의고사 안내] 비-exam 문구가 예상과 다릅니다: ${notExam.slice(0, 90)}`)
  }
  await save(page, 'exam-not-exam-desktop-1280x900.png')
  await page.locator('[data-testid="exam-closed"]').getByRole('link', { name: '연습 화면으로' }).click()
  await page.waitForURL('**/sessions/7204', { timeout: 15000 })
    .then(() => pass('[모의고사 안내] 비-exam 세션에서 연습 화면으로 이동'))
    .catch(() => fail('[모의고사 안내] 연습 화면 링크가 동작하지 않습니다'))

  // 없는 세션 → 404 안내
  await page.goto(`${baseUrl}/exam/9999`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="exam-error"]', { timeout: 60000 })
  const notFound = (await page.locator('[data-testid="exam-error"]').innerText()).replace(/\s+/g, ' ')
  if (notFound.includes('찾을 수 없습니다') && notFound.includes('다시 시도')) {
    pass(`[모의고사 안내] 404: ${notFound.slice(0, 44)}`)
  } else {
    fail(`[모의고사 안내] 404 문구가 예상과 다릅니다: ${notFound.slice(0, 90)}`)
  }
  await save(page, 'exam-404-desktop-1280x900.png')

  // 안내 화면으로 오는 4xx 는 의도한 경로다 — JS 오류만 문제로 본다
  const closedErrors = consoleErrors.filter(message => !isExpectedResourceLog(message, [400, 404, 409]))
  if (closedErrors.length === 0) pass('[모의고사 안내] 브라우저 콘솔 오류 0(의도한 4xx 네트워크 로그 제외)')
  else for (const message of closedErrors) fail(`[모의고사 안내] ${message}`)

  await context.close()

  // 제출이 409(중단) 인 경우 — 풀이 화면 대신 안내 화면으로
  const conflictContext = await browser.newContext({ locale: 'ko-KR', timezoneId: 'Asia/Seoul', deviceScaleFactor: 1, colorScheme: 'light' })
  await stubExamApi(conflictContext, {
    submitError: { status: 409, body: { detail: '중단된 모의고사입니다. 새로 구성한 세션에서 계속하세요' } },
  })
  const conflictPage = await conflictContext.newPage()
  watchConsole(conflictPage)
  await conflictPage.setViewportSize(DESKTOP)
  await conflictPage.goto(`${baseUrl}/exam/7201`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await conflictPage.waitForSelector('[data-testid="exam-item"]', { timeout: 60000 })
  await conflictPage.locator('[data-testid="exam-submit"]').click()
  await conflictPage.waitForSelector('[data-testid="confirm-dialog"]', { timeout: 15000 })
  await conflictPage.getByTestId('confirm-dialog').getByRole('button', { name: '제출하기' }).click()
  await conflictPage.waitForSelector('[data-testid="exam-closed"]', { timeout: 30000 })
  const submitConflict = (await conflictPage.locator('[data-testid="exam-closed"]').innerText()).replace(/\s+/g, ' ')
  if (submitConflict.includes('중단된 모의고사')) pass(`[모의고사 안내] 제출 409 → 안내 화면: ${submitConflict.slice(0, 46)}`)
  else fail(`[모의고사 안내] 제출 409 안내가 예상과 다릅니다: ${submitConflict.slice(0, 90)}`)
  await save(conflictPage, 'exam-submit-conflict-desktop-1280x900.png')
  await conflictContext.close()
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
    await captureExamsList(browser)
    await captureExamTaking(browser)
    await captureExamClosed(browser)
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
