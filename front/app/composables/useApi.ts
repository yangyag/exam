// 백엔드 API 주소 헬퍼.
// JSON 엔드포인트는 전부 /api 프리픽스, 도식 이미지는 /figures/... 로 온다(back/README.md).
export function useApi() {
  const config = useRuntimeConfig()
  const base = config.public.apiBase

  // 앞 슬래시를 하나로 맞춰 붙인다
  const url = (path: string) => `${base}${path.startsWith('/') ? path : `/${path}`}`

  return {
    base,
    url,
    /** 도식 이미지 경로(figure.imageUrl)는 서버 기준 상대경로라 오리진을 앞에 붙인다 */
    figureUrl: (imageUrl?: string | null) => (imageUrl ? url(imageUrl) : null),
  }
}
