// API 오류를 화면에 보여줄 형태로 바꾼다.
// 백엔드·DB 가 꺼져 있으면 그 사실을 알리고 기동 명령을 안내한다(back/README.md).
export type ApiErrorInfo = {
  title: string
  detail: string
  /** HTTP 상태 코드(서버에 닿지 못하면 0) — 404·409 분기에 쓴다 */
  status: number
  /** 사용자가 그대로 실행할 수 있는 명령(있을 때만) */
  command?: string
}

function pickStatus(error: unknown): number {
  if (typeof error === 'object' && error !== null) {
    const err = error as { statusCode?: unknown, response?: { status?: unknown } }
    const code = err.statusCode ?? err.response?.status
    if (typeof code === 'number') return code
  }
  return 0
}

function pickDetail(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const err = error as { data?: { detail?: unknown }, message?: unknown }
    if (typeof err.data?.detail === 'string') return err.data.detail
    if (typeof err.message === 'string') return err.message
  }
  return ''
}

export function describeApiError(error: unknown, base: string): ApiErrorInfo {
  const status = pickStatus(error)
  const detail = pickDetail(error)
  // 서버에 닿지 못한 요청은 Nuxt 가 500 으로 감싸므로 메시지로도 판별한다
  const networkFailure = status === 0
    || /fetch failed|Failed to fetch|no response|ECONNREFUSED|ERR_CONNECTION/i.test(detail)

  if (networkFailure) {
    return {
      title: '백엔드 서버에 연결할 수 없습니다',
      detail: `API 서버(${base})가 응답하지 않습니다. 서버를 켠 뒤 다시 시도해 주세요.`,
      status,
      command: 'cd back && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8092',
    }
  }

  if (status === 503) {
    return {
      title: '백엔드가 DB 에 연결하지 못했습니다',
      detail: 'API 서버는 살아 있지만 PostgreSQL 에 붙지 못했습니다(HTTP 503). DB 상태를 확인해 주세요.',
      status,
      command: 'docker start postgres',
    }
  }

  if (status === 404) {
    return {
      title: '찾을 수 없습니다 (HTTP 404)',
      detail: detail || '없는 세션이거나 없는 문항입니다. 홈에서 다시 시작해 주세요.',
      status,
    }
  }

  return {
    title: `데이터를 불러오지 못했습니다 (HTTP ${status})`,
    detail: detail || '알 수 없는 오류입니다.',
    status,
  }
}
