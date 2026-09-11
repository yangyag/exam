// 백엔드 OpenAPI 스키마에서 생성한 타입의 화면용 별칭.
// api.gen.ts 는 `npm run gen:types` 로 다시 만들기만 하고 직접 고치지 않는다.
import type { components } from './api.gen'

type Schemas = components['schemas']

export type Subject = Schemas['SubjectOut']
export type SubjectOverview = Schemas['SubjectOverviewOut']
export type SubjectStatus = SubjectOverview['status']
export type HomeCycle = Schemas['HomeCycleOut']
export type RoundSummary = Schemas['RoundSummaryOut']
export type SubjectCycle = Schemas['CycleOut']
export type CycleRound = Schemas['RoundOut']
export type SessionDetail = Schemas['SessionDetailOut']
export type SessionSummary = Schemas['SessionOut']
export type SessionMode = SessionDetail['mode']
