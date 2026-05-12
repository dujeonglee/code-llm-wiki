# LLM 운영 규칙 (Karpathy LLM Wiki 패턴 / 커널 적용)

이 파일은 위키를 유지·보수하는 LLM 에이전트의 동작 SOP입니다.
사람이 읽고 검증할 수 있도록 의도적으로 짧게 유지합니다.

## 1. 레이어

| 디렉토리 | 소유 | 규칙 |
|---|---|---|
| `raw/linux/` | 사용자 | **불변**. LLM은 읽기만 한다. |
| `wiki/` | LLM | LLM이 모든 페이지를 생성·갱신한다. 사람은 직접 편집 금지. |
| `wiki/_meta/` | LLM | `coverage.json`, `todo.md` — 도구가 갱신한다. |
| `CLAUDE.md`, `scripts/`, `config/` | 사람 + LLM | 사람이 리뷰. PR로 변경. |

## 2. 페이지 구조

각 위키 페이지는 다음 front-matter로 시작한다.

```yaml
---
title: <사람이 읽는 이름>
kind: subsystem | concept | entity | query
covers:              # 이 페이지가 책임지는 raw/ 경로 (glob 허용)
  - mm/slab.c
  - mm/slub.c
last_synced_sha: <커널 commit sha, 이 페이지가 마지막으로 반영한 시점>
last_synced: <ISO date>
sources:             # 페이지 작성 시 LLM이 실제로 읽은 파일들 + 참고 문서
  - mm/slab.c#L100-L320
  - Documentation/core-api/memory-allocation.rst
---
```

상호 링크는 `[[concepts/rcu|RCU]]` 같은 위키 링크 표기를 쓴다.
끊긴 링크는 annealing 잡이 감지한다.

## 3. 워크플로

### 3.1 패치 트리거 업데이트 (요구사항 2)

1. `scripts/sync_kernel.sh`가 `raw/linux/`를 fetch.
2. `scripts/patch_router.py`가 `git diff` → 변경된 파일 → `coverage.json`을 통해 **영향받는 위키 페이지 목록**을 만든다.
3. `scripts/update_wiki.py`가 각 영향 페이지마다:
   - 페이지 현재 본문 + diff hunk + 인접 소스 파일 일부를 컨텍스트로 LLM 호출
   - LLM은 페이지를 **부분 갱신**한다 (전면 재작성이 아니라 변경된 부분만)
   - front-matter의 `last_synced_sha`, `last_synced`를 업데이트
4. 커버되지 않은 새 파일은 `wiki/_meta/todo.md`에 추가한다.

### 3.2 Annealing (요구사항 1)

`scripts/anneal.py`가 주기적으로 (cron) 다음 중 하나를 골라 patch-up 한다.

- `last_synced`가 N일 이상 오래된 페이지
- 끊긴 `[[wiki-link]]`
- `coverage.json`에서 어떤 페이지도 커버하지 않는 raw 파일
- 페이지 간 모순 가능성 (LLM 자체 평가)

한 회 실행에서 최대 K개 항목만 처리한다 (토큰/비용 상한).

### 3.3 사람의 질의 (요구사항 4)

LLM이 코드 리뷰 / 포팅 / 기능 추가에 위키를 활용할 때:

1. 먼저 `wiki/index.md` → 관련 `subsystems/*` / `concepts/*` 페이지를 읽는다.
2. 부족하면 `covers:`에 적힌 raw 파일을 직접 본다.
3. 산출물은 `wiki/queries/<slug>.md`에 저장하고, **provenance**(템플릿 ID, 참조한
   페이지들과 각자의 `last_synced_sha`, 커널 HEAD sha, 모델, 시각)를 같이 적는다.
   이건 `python -m scripts.update_wiki query`가 자동으로 함.

**템플릿 (system prompt + 입력 스캐폴드)**: `wiki/queries/_templates/code-review.md`,
`porting-guide.md`, `feature-impl.md`.

#### 재사용 규칙 (중요)

저장된 쿼리는 **감사용 흔적**이지 **재사용 가능한 캐시가 아니다**. 카테고리별 정책:

| 템플릿 | 재사용 정책 |
|---|---|
| `code-review` | **일회용**. 다른 패치/PR에 절대 재활용하지 말 것. 같은 패치도 코드가 움직였으면 재실행. |
| `porting-guide` | **연구 출발점**으로만. 실제 포팅 작업 시점에 양쪽 트리가 움직였을 가능성 높으므로 재실행 필수. |
| `feature-impl` | **머지 전까지만 유효**. 기능이 들어간 뒤엔 `wiki/queries/archive/`로 이동 또는 폐기. |

> 🚨 freshness 배지 같은 자동 신선도 표시는 의도적으로 만들지 않았다. "출처가 안 움직였다"는
> 신호가 "결론이 여전히 맞다"는 보장으로 오해되어 더 위험한 거짓 자신감을 만들 수 있기 때문.
> 의심되면 무조건 재실행하라.

## 4. LLM 호출

모든 호출은 `scripts/llm_client.py`를 거친다.
프로필은 `config/llm.json` (없으면 `config/llm.local.json`, 없으면 `config/llm.example.json`).

## 5. 금지 사항

- `raw/` 아래 파일을 절대 수정하지 않는다.
- `wiki/` 페이지를 사람의 검토 없이 main 브랜치에 직접 푸시하지 않는다 (자동화는 PR로).
- 페이지를 전면 재작성하지 않는다 — diff 기반 patch-up이 기본.
