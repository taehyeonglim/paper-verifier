# paper-verifier

[![CI](https://github.com/taehyeonglim/paper-verifier/actions/workflows/ci.yml/badge.svg)](https://github.com/taehyeonglim/paper-verifier/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/paper-verifier)](https://pypi.org/project/paper-verifier/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) | **한국어**

**결정론적 원고 감사 도구**: 원고에 적힌 모든 통계 수치를 *본인의* 분석
산출물과 대조하고, 인용 정합성(참고문헌 목록 ↔ 본문 인용 ↔ 원문 소스)을
끝까지 검증합니다 — 심사위원(또는 독자)이 발견하기 전에.

분석 파이프라인과 투고 PDF 사이에는 긴 수작업 전사(轉寫) 사슬이 있습니다:
숫자를 본문에 옮겨 적고, 반올림하고, 고치고, 여러 버전을 오가며 뒤섞죠.
`paper-verifier`는 원고를 **파이프라인이 실제로 산출한 숫자**와 diff하고,
참고문헌 목록·본문 인용·인용 원문이 여전히 서로 일치하는지 검증합니다.
모든 판정은 Python이 합니다. LLM은 (선택적으로) 단 한 가지 —
패러프레이즈 의미 일치 — 에만 쓰이고, **숫자에는 절대 관여하지 않습니다**.

## 무엇을 검사하나

**통계 수치** (Phase 1, 결정론)
- 본문에서 15종의 claim을 추출 — `*F*(1, 28) = 5.21`, `*p* = .030`, `β`,
  `95% CI [...]`, `d_z`, `η²`, `α`, `N`, `*V*`, `*M*`/`*SD*`, `%`, `*r*` —
  APA 7판 이탤릭, 타이포그래픽 마이너스, 유니코드 글리프까지 인식합니다.
- 각 claim을 ground truth 표와 1:1 대조하되 **반올림 정밀도를 존중**합니다:
  원고에 인쇄된 소수 자리수 기준으로 유효한 반올림일 때만 PASS.
- 오탐 방지 가드: 다중 DV 모호성, 상호작용/상관 맥락, 효과크기 CI vs β CI,
  조건 오귀속 — 결정론적으로 판정할 수 없는 것은 가짜 PASS/FAIL이 아니라
  MANUAL로 분류됩니다.
- **Ground-truth 게이트**: claim은 있는데 쓸 수 있는 ground truth가 없으면
  조용히 통과시키는 대신 run 전체를 hard FAIL시킵니다.

**인용 정합성** (Phase 1, 결정론)
- APA 7판 참고문헌 목록 파싱; 본문 인용(괄호형·서술형·세미콜론 접두형,
  유니코드 성씨 포함) 추출.
- 인용 그래프 교차 대조: **orphan**(목록엔 있는데 인용 안 됨)과
  **dangling**(인용됐는데 목록에 없음)을 검출.
- 로컬 소스 PDF/전문을 저자+연도로 매달기 (±1년 퍼지 매칭은 확정이 아니라
  WARN 처리).

**패러프레이즈 의미** (Phase 2, 옵트인)
- 실질 인용에 대해, 매달린 원문에서 해당 구절을 추출한 뒤 로컬 LLM CLI에
  "당신의 패러프레이즈가 여전히 원문이 말한 것을 말하는가"를 묻습니다
  (인용 목적별 임계값; 단순 배경 인용은 스킵). LLM이 없으면 크래시가 아니라
  MANUAL로 강등됩니다.

## Quickstart (3분)

```bash
pip install paper-verifier
git clone https://github.com/taehyeonglim/paper-verifier
cd paper-verifier/examples/quickstart

paper-verify --config paper-verifier.toml --phase 1 --output-summary
```

동봉된 합성 연구("AI 튜터 vs 정적 텍스트" — 모든 수치가 설계상 정합)에서
기대되는 출력:

```
verification status:
  PASS       27
  WARN        8      # PDF 미구성 5 + orphan 참고문헌 2 + TBD-DOI 1 — 전부 의도된 데모
# exit code 0
```

이제 일부러 깨뜨려 봅시다 — 인용 저자명 오타 + p값 조작:

```bash
sed -i '' 's/(Novak, 2024)/(Nowak, 2024)/' manuscript.md   # macOS 기준; Linux는 '' 제거
sed -i '' 's/\*p\* = .030/\*p\* = .041/' manuscript.md
paper-verify --config paper-verifier.toml --phase 1 ; echo "exit=$?"
```

```
FAIL  p_value claim=0.041 vs gt=0.030214 (digits=3, delta=0.0108)
FAIL  Dangling citation: (Nowak, 2024) — no matching ref entry
exit=1
```

이 exit code가 곧 CI 게이트입니다: 원고 저장소에 `paper-verify`를 걸어두면
분석과 모순되는 수정이 빌드를 깨뜨립니다.

본인 논문에 적용하려면 `examples/quickstart/paper-verifier.toml`을 복사해
파일 경로와 DV 어휘를 선언하세요 —
[docs/configuration.md](docs/configuration.md)와
[docs/input-formats.md](docs/input-formats.md) 참조.

## 실전 사용 기록

이 도구는 연구 자동화 시스템에서 추출됐고, 실제 학회 원고와 그 저널 확장판을
감사했습니다:

- 단일 run에서 **348개 검증 target** — 15종 298개 통계 claim, 참고문헌 23건,
  본문 인용 56건 — 을 R lme4 ↔ scipy 교차검증(8/8 패리티) ground truth와
  대조해 **통계 오류 0건**을 확인했고, 수정 과정에서 **dangling 인용 1건을
  검출**했습니다.
- 같은 감사 설정이 **저널 확장판에 그대로 재사용**됐습니다(참고문헌 41건,
  본문 인용 64건).

## statcheck와의 관계

[statcheck](https://github.com/MicheleNuijten/statcheck)은 보고된 검정통계량과
자유도로부터 p값을 재계산해 *내적* 비일관성을 잡습니다. `paper-verifier`는
다른 질문에 답합니다: **보고된 숫자가 당신의 분석이 실제로 산출한 값과
일치하는가?** 내적으로 일관된 전사 오류는 statcheck을 통과하지만 여기서
걸리고, 전사는 정확한데 보고가 비일관적인 경우는 그 반대입니다. 둘은
상호보완이니 함께 쓰세요. `paper-verifier`는 statcheck이 다루지 않는
인용 그래프와 소스 매달기까지 감사합니다.

## Claude Code 에이전트

[`agents/`](agents/) 디렉토리에 이 CLI를 구동하고 리포트를 해석하는
[Claude Code](https://claude.com/claude-code) 서브에이전트 정의 2종 —
`paper-data-verifier`(통계) · `paper-citation-auditor`(인용) — 이 들어
있습니다. 프로젝트의 `.claude/agents/`에 복사해 쓰세요.

## 설정 한눈에 보기

```toml
[project]
manuscripts = ["sections/*.md"]
references  = "references.md"
stats       = "statistics_verification.md"   # 본인의 교차검증된 분석 산출물

[stats]
condition_labels = ["AI", "TEXT"]

[stats.dv_keywords]
engagement = ["engagement"]

[stats.dv_aliases]
"Engagement" = "engagement"     # 표 행 라벨 → DV 키
"참여도" = "engagement"          # 비영어 산출물도 라벨만 선언하면 동작

[llm]
provider = "none"               # Phase 2 끔; "codex"/"claude"/커스텀 argv로 켜기
```

도메인 특화 정보는 전부 이 파일에 삽니다. 라이브러리 기본값은 비어 있고
fail-safe입니다. 전체 레퍼런스: [docs/configuration.md](docs/configuration.md).

## 한계 (솔직 버전)

- 이 도구는 **재계산기가 아니라 대조기**입니다: ground truth는 고정된
  3-표 마크다운 스키마([docs/input-formats.md](docs/input-formats.md))로
  제공되는 *당신의* 분석 산출물이고, 모델을 다시 돌리지 않으며, 표가 틀리면
  그대로 물려받습니다. 감사를 믿으려면 표부터 교차검증(두 구현)하세요.
- Claim 추출은 라인 단위 regex라 특이한 서식은 claim을 놓칠 수 있습니다
  (조용한 미검출) — `claims.jsonl`을 한 번 훑어 무엇이 잡혔는지 확인하세요.
- DOI 검사는 **문자열 존재 확인뿐**입니다 (레지스트리 조회 안 함).
- Phase 2는 로컬 LLM CLI가 필요하고 그 비결정성을 물려받습니다. 점수가
  FAIL/PASS를 가르지만 모든 판정 원문이 리뷰용으로 보관됩니다.
- Windows는 미검증입니다 (전체가 pathlib 기반이라 동작*할* 것으로 예상 —
  리포트 환영). Python ≥ 3.11.

## 인용

연구 워크플로우에 유용했다면 [CITATION.cff](CITATION.cff)를 참조하세요
(GitHub의 "Cite this repository" 버튼이 작동합니다). JOSS 투고를 준비
중입니다 — [docs/statement-of-need.md](docs/statement-of-need.md).

## 라이선스

[MIT](LICENSE) © 2026 Taehyeong Lim
