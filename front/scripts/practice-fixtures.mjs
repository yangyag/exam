/**
 * 연습 화면 스크린샷용 고정 데이터.
 *
 * 실제 데이터셋(data/questions/*)에서 그대로 가져왔고, 과목 4(프로그래밍 언어 활용) 사이클의
 * 라운드처럼 서로 다른 회차 문항을 섞어 놓았다 — 한 라운드가 코드·지문·표·도식 네 종류를 모두
 * 지나가게 하려는 것이다(화면 점검: 지문 렌더 3종 + 도식 이미지).
 *
 * `item` 은 조회 응답 형태(정답·해설 없음), `answer`·`explanation`·`choicesAnalysis` 는
 * 채점 응답에만 실리는 값이다 — shots.mjs 가 실제 API 처럼 나눠서 돌려준다(DB 는 쓰지 않는다).
 */

// 라운드 1 — 코드 → 지문 → 표 → 도식 순서
export const CODE_QUESTION = {
  item: {
    id: '2026-1-064',
    examId: '2026-1',
    number: 64,
    subjectCode: 4,
    subjectName: '프로그래밍 언어 활용',
    stem: '다음 C 언어 프로그램이 실행되었을 때의 결과는?',
    passage: '#include <stdio.h>\nmain( ) {\n    int sum = 0;\n    for (int i = 0; i <= 10; i++) {\n        if (i % 2 == 0)\n            continue;\n        sum = sum + i;\n    }\n    printf("%d", sum);\n}',
    passageKind: 'code',
    difficulty: 2,
    choices: [
      { no: 1, text: '20' },
      { no: 2, text: '25' },
      { no: 3, text: '30' },
      { no: 4, text: '55' },
    ],
    figure: { needed: false, kind: null, imageUrl: null, alt: null },
    tags: ['C 언어', 'continue', '반복문'],
    state: null,
  },
  answer: 2,
  explanation: 'for 문이 i를 0부터 10까지 증가시키면서 i % 2 == 0인 짝수일 때 continue를 만나 아래의 sum = sum + i를 건너뜁니다. 따라서 sum에는 홀수인 1, 3, 5, 7, 9만 누적되어 25가 출력됩니다. continue는 반복문 전체를 빠져나가는 break와 달리 해당 회차의 남은 문장만 건너뛰고 다음 반복으로 넘어가는 제어문입니다.',
  keyPoint: 'continue 문에 의한 반복 회차 건너뛰기',
  choicesAnalysis: [
    { no: 1, correct: false, why: '짝수를 더하거나 누적 범위를 잘못 계산한 값으로, 홀수의 합 25와 다릅니다.' },
    { no: 2, correct: true, why: '1 + 3 + 5 + 7 + 9 = 25가 출력되므로 정답입니다.' },
    { no: 3, correct: false, why: 'continue의 동작을 반영하지 못한 값으로 실제 출력값 25와 다릅니다.' },
    { no: 4, correct: false, why: 'continue를 무시하고 1부터 10까지 모두 더한 값(55)이라 틀렸습니다.' },
  ],
}

export const TEXT_QUESTION = {
  item: {
    id: '2024-2-064',
    examId: '2024-2',
    number: 64,
    subjectCode: 4,
    subjectName: '프로그래밍 언어 활용',
    stem: '다음 내용이 설명하는 결합도는?',
    passage: '한 모듈이 다른 모듈의 상세한 처리 절차를 알고 있어 이를 통제하는 경우나 처리 기능이 두 모듈에 분리되어 설계된 경우에 발생하며, 권리 전도 현상이 발생할 수 있다.',
    passageKind: 'text',
    difficulty: 2,
    choices: [
      { no: 1, text: '제어 결합도' },
      { no: 2, text: '스탬프 결합도' },
      { no: 3, text: '외부 결합도' },
      { no: 4, text: '내용 결합도' },
    ],
    figure: { needed: false, kind: null, imageUrl: null, alt: null },
    tags: ['결합도', '제어 결합도', '모듈화'],
    state: null,
  },
  answer: 1,
  explanation: '제어 결합도는 한 모듈이 다른 모듈의 내부 논리 흐름을 통제하려고 제어 신호(플래그)를 전달할 때 발생합니다. 처리 기능이 두 모듈로 나뉘어 설계되면 상대 모듈의 판단을 좌우하게 되어 권리 전도 현상이 나타나므로 이 설명에 해당합니다. 스탬프 결합도는 자료 구조 전체를 전달할 때, 외부 결합도는 외부에 선언된 데이터를 공유할 때, 내용 결합도는 다른 모듈의 내부 자료를 직접 참조할 때 발생합니다.',
  keyPoint: '제어 결합도와 권리 전도 현상',
  choicesAnalysis: [
    { no: 1, correct: true, why: '다른 모듈의 처리 절차를 통제하는 제어 신호를 전달하고 권리 전도 현상이 나타나는 결합도이므로 정답입니다.' },
    { no: 2, correct: false, why: '스탬프 결합도는 두 모듈이 배열이나 레코드 같은 자료 구조 전체를 주고받을 때 발생합니다.' },
    { no: 3, correct: false, why: '외부 결합도는 여러 모듈이 외부에 선언된 전역 데이터를 함께 사용할 때 발생합니다.' },
    { no: 4, correct: false, why: '내용 결합도는 한 모듈이 다른 모듈의 내부 데이터나 코드를 직접 참조하는 가장 강한 결합도입니다.' },
  ],
}

export const TABLE_QUESTION = {
  item: {
    id: '2025-1-076',
    examId: '2025-1',
    number: 76,
    subjectCode: 4,
    subjectName: '프로그래밍 언어 활용',
    stem: '다음과 같은 세그먼트 테이블을 가지는 시스템에서 논리 주소(2, 176)에 대한 물리 주소는?',
    passage: '세그먼트번호 | 시작주소 | 길이(바이트)\n0 | 670 | 248\n1 | 1752 | 422\n2 | 222 | 198\n3 | 996 | 604',
    passageKind: 'table',
    difficulty: 2,
    choices: [
      { no: 1, text: '398' },
      { no: 2, text: '400' },
      { no: 3, text: '1928' },
      { no: 4, text: '1930' },
    ],
    figure: { needed: false, kind: null, imageUrl: null, alt: null },
    tags: ['세그먼테이션', '물리 주소'],
    state: null,
  },
  answer: 1,
  explanation: '논리 주소 (2, 176)은 세그먼트 번호가 2이고 변위가 176이라는 뜻이므로, 세그먼트 2의 시작 주소 222에 변위 176을 더한 398이 물리 주소가 됩니다. 이때 세그먼트 2의 길이는 198바이트이므로 변위 176은 세그먼트 범위 안에 있어 정상적으로 접근할 수 있습니다.',
  keyPoint: '세그먼테이션에서 물리 주소 = 세그먼트 시작 주소 + 변위',
  choicesAnalysis: [
    { no: 1, correct: true, why: '222+176=398이므로 정답입니다.' },
    { no: 2, correct: false, why: '400은 시작 주소에 변위를 잘못 더한 값입니다.' },
    { no: 3, correct: false, why: '1928은 세그먼트 1의 시작 주소 1752에 176을 더한 값으로 세그먼트 번호가 다릅니다.' },
    { no: 4, correct: false, why: '1930은 세그먼트 1에 변위를 잘못 적용한 값입니다.' },
  ],
}

export const FIGURE_QUESTION = {
  item: {
    id: '2024-2-074',
    examId: '2024-2',
    number: 74,
    subjectCode: 4,
    subjectName: '프로그래밍 언어 활용',
    stem: '다음은 어떤 프로그램 구조를 나타낸다. 모듈 F에서의 Fan-In과 Fan-Out의 수는 얼마인가?',
    passage: null,
    passageKind: null,
    difficulty: 2,
    choices: [
      { no: 1, text: 'Fan-In : 2, Fan-Out : 3' },
      { no: 2, text: 'Fan-In : 3, Fan-Out : 2' },
      { no: 3, text: 'Fan-In : 1, Fan-Out : 2' },
      { no: 4, text: 'Fan-In : 2, Fan-Out : 1' },
    ],
    figure: {
      needed: true,
      kind: 'diagram',
      imageUrl: '/figures/2024-2/074.png',
      alt: '맨 위 A 모듈에서 B, C, D로 화살표가 갈라지고 B는 E와 F를, C와 D도 모두 F를 호출하며 F 아래에 G와 H가 연결된 모듈 구조도',
    },
    tags: ['Fan-In', 'Fan-Out', '모듈 구조도'],
    state: null,
  },
  answer: 2,
  explanation: 'Fan-In은 특정 모듈을 호출하는 상위 모듈의 수이고, Fan-Out은 특정 모듈이 호출하는 하위 모듈의 수입니다. 구조도에서 F로 들어오는 화살표는 B, C, D에서 온 3개이고, F에서 나가는 화살표는 G, H로 가는 2개입니다. 따라서 F의 Fan-In은 3, Fan-Out은 2입니다.',
  keyPoint: 'Fan-In과 Fan-Out의 정의와 계수',
  choicesAnalysis: [
    { no: 1, correct: false, why: 'F를 호출하는 모듈은 B, C, D 세 개이므로 Fan-In 2는 틀린 값입니다.' },
    { no: 2, correct: true, why: 'F를 호출하는 모듈이 3개, F가 호출하는 모듈이 2개이므로 정답입니다.' },
    { no: 3, correct: false, why: 'F를 호출하는 상위 모듈이 세 개이므로 Fan-In 1은 맞지 않습니다.' },
    { no: 4, correct: false, why: 'F가 호출하는 하위 모듈이 G, H 두 개이므로 Fan-Out 1은 틀린 값입니다.' },
  ],
}

/** 라운드 1 — 네 문항(코드·지문·표·도식) */
export const ROUND1_QUESTIONS = [CODE_QUESTION, TEXT_QUESTION, TABLE_QUESTION, FIGURE_QUESTION]

/** 오답 복습 라운드 — 라운드 1 에서 틀린 표 문항 하나만 남는다 */
export const ROUND2_QUESTIONS = [TABLE_QUESTION]

export const STUB_AT = '2026-09-12T01:00:00Z'
