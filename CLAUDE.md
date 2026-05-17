# LLM 운영 규칙 (Karpathy LLM Wiki 패턴)

이 파일은 위키를 유지·보수하는 LLM 에이전트의 동작 SOP입니다.
사람이 읽고 검증할 수 있도록 의도적으로 짧게 유지합니다.

## 1. 레이어

| 디렉토리 / 파일 | 소유 | 규칙 |
|---|---|---|
| `raw/<top>/` | 사용자 | 각 sub-tree는 별도 local git clone. `raw/*`는 wiki repo에서 gitignore. **불변** — LLM은 읽기만 한다. |
| `wiki/raw/<top>/*.md` | LLM | 소스 유도 페이지 (`kind: entity`/`subsystem`/`concept`). LLM이 생성·갱신. 사람은 직접 편집 금지. |
| `wiki/queries/*.md` | LLM | 쿼리 산출물. `update_wiki query`가 생성. 사람은 직접 편집 금지. |
| `wiki/index.md`, `wiki/raw/<top>/_index.md` | 도구 / 사람 | 구조·인덱스 페이지. `_index.md`는 `seed_pages.sh`가 자동 생성, `index.md`는 사람이 PR로. `covers:`가 비어 있어 LLM이 유도할 근거가 없음. |
| `wiki/_meta/` | LLM | `coverage.json`, `todo.md` — 도구가 갱신. |
| `CLAUDE.md`, `scripts/`, `config/` | 사람 + LLM | 사람이 리뷰. PR로 변경. |

`KERNEL_ROOT`는 `raw/` (sub-tree의 부모). `covers:` 글로브와 페이지 sha 해석 모두 이 기준.

## 2. 페이지 구조

각 위키 페이지는 다음 front-matter로 시작한다.

```yaml
---
title: <사람이 읽는 이름>
kind: subsystem | concept | entity | query
covers:              # KERNEL_ROOT (= raw/) 기준 상대 경로 (glob 허용)
  - pcie_scsc/mlme.c
  - pcie_scsc/mlme.h
last_synced_sha: <sub-tree git sha — covers 첫 세그먼트의 raw/<top>/ HEAD>
last_synced: <ISO date>
sources:             # 페이지 작성 시 LLM이 실제로 읽은 파일들 + 참고 문서
  - pcie_scsc/mlme.c#L100-L320
  - pcie_scsc/dev.h#L472-L500
---
```

상호 링크는 Obsidian 스타일 `[[raw/<top>/<basename>|표시명]]`. 페이지는 `wiki/raw/<top>/`에 mirror되어 있으므로 target은 `wiki/` 기준 상대 경로 — 예: `[[raw/pcie_scsc/_concept_fapi|FAPI signaling]]`. 끊긴 링크는 annealing 잡이 감지한다.

## 3. 워크플로

### 3.1 초기 시드 (seed)

새 sub-tree(`raw/<top>/`)를 wiki에 처음 들일 때:

1. **로컬 git 만들기**: `cd raw/<top> && git init && git add . && git commit -m "initial import"`.
   - sub-tree의 HEAD sha가 페이지의 `last_synced_sha`로 기록됨. 외부 upstream에서 clone한 경우 자동.
2. **stub 페이지 일괄 생성**: `bash scripts/seed_pages.sh` — `.c`/`.h` 짝마다 빈 front-matter + 스텁 본문을 만들고 `coverage.json`에 등록.
3. **본문 채우기 (per page)**:
   ```bash
   python -m scripts.update_wiki seed-agent \
     --page raw/<top>/<file>.md --model <model>
   ```
   Claude Agent SDK가 `Read`/`Grep`으로 sub-tree를 탐색하고 SOP 형식의 페이지를 한 번에 작성한다. 백엔드(클라우드 / ollama / 기타 Anthropic-compat 프록시)는 `config/llm.local.json`의 `default_profile` 또는 `--profile` 플래그로 선택 — SDK 환경변수는 `scripts/llm_client.sdk_env_for_profile()`이 자동 set한다.
   - **Anthropic 클라우드**: `claude` 프로필. `--model claude-sonnet-4-5` 등. `ANTHROPIC_API_KEY` 셸에 있어야 함 (profile.auth_env로 지정).
   - **ollama 로컬**: `ollama` 프로필. `--model qwen3.6:27b-q4_K_M` 같은 ollama 모델명. 키 불필요.
4. 이미 채워진 페이지(`last_synced` 존재) 재시도는 `--overwrite` 명시.

### 3.2 패치 트리거 업데이트

1. `scripts/sync_subtree.py --tree raw/<top> --record`가 sub-tree의 git fetch + 변경 파일 매니페스트 emit + `coverage.subtree_shas[<top>]`에 새 HEAD 기록.
2. `scripts/patch_router.py`가 매니페스트 → 변경된 파일 → `coverage.json`을 통해 **영향받는 위키 페이지 목록**을 만든다.
3. `python -m scripts.update_wiki update --routing r.json`이 각 영향 페이지마다:
   - 페이지 현재 본문 + diff hunk + 인접 소스 파일 일부를 컨텍스트로 LLM 호출
   - LLM은 페이지를 **부분 갱신**한다 (전면 재작성이 아니라 변경된 부분만)
   - front-matter의 `last_synced_sha`, `last_synced`를 업데이트
4. 커버되지 않은 새 파일은 `wiki/_meta/todo.md`에 추가한다.

### 3.3 Annealing

`scripts/anneal.py`가 주기적으로 (cron) 다음 중 하나를 골라 patch-up 한다.

- `last_synced`가 N일 이상 오래된 페이지
- 끊긴 `[[wiki-link]]`
- `coverage.json`에서 어떤 페이지도 커버하지 않는 raw 파일
- 페이지 간 모순 가능성 (LLM 자체 평가)

한 회 실행에서 최대 K개 항목만 처리한다 (토큰/비용 상한).

### 3.4 사람의 질의

LLM이 코드 리뷰 / 포팅 / 기능 추가에 위키를 활용할 때:

1. 먼저 `wiki/index.md` → 관련 sub-tree(`wiki/raw/<top>/`)의 페이지를 읽는다. 아키텍처 페이지(`_*.md`, `kind: subsystem`/`concept`)를 먼저 보면 큰 그림을 빨리 잡는다.
2. 부족하면 `covers:`에 적힌 raw 파일을 직접 본다.
3. 산출물은 `wiki/queries/<slug>.md`에 저장하고, **provenance**(템플릿 ID, 참조한
   페이지들과 각자의 `last_synced_sha`, 커널 HEAD sha, 모델, 시각)를 같이 적는다.
   이건 `python -m scripts.update_wiki query`가 자동으로 함.

**템플릿**: `wiki/queries/_templates/code-review.md`, `porting-guide.md`, `feature-impl.md`.

#### 재사용 규칙 (중요)

저장된 쿼리는 **감사용 흔적**이지 **재사용 가능한 캐시가 아니다**.

| 템플릿 | 재사용 정책 |
|---|---|
| `code-review` | **일회용**. 다른 패치/PR에 절대 재활용하지 말 것. 같은 패치도 코드가 움직였으면 재실행. |
| `porting-guide` | **연구 출발점**으로만. 실제 포팅 작업 시점에 양쪽 트리가 움직였을 가능성 높으므로 재실행 필수. |
| `feature-impl` | **머지 전까지만 유효**. 기능이 들어간 뒤엔 `wiki/queries/archive/`로 이동 또는 폐기. |

> 🚨 freshness 배지 같은 자동 신선도 표시는 의도적으로 만들지 않았다. "출처가 안 움직였다"는
> 신호가 "결론이 여전히 맞다"는 보장으로 오해되어 더 위험한 거짓 자신감을 만들 수 있기 때문.
> 의심되면 무조건 재실행하라.

## 4. LLM 호출

- `update` / `query` 서브커맨드는 `scripts/llm_client.py` (one-shot HTTP) 사용.
- `seed-agent` 서브커맨드는 `claude-agent-sdk` (별도 `pip install`)를 사용해 agentic loop을 돈다.
- 두 경로 모두 `config/llm.local.json`의 프로필을 동일하게 읽음 (`default_profile` 또는 `--profile`). `seed-agent`는 활성 프로필에서 SDK가 필요로 하는 env vars (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`)를 `sdk_env_for_profile()`로 자동 set — 셸 env에 별도 export 불필요. wiki repo 설정이 단일 진실의 출처.

## 5. 금지 사항

- `raw/` 아래 파일을 절대 수정하지 않는다.
- `wiki/` 페이지를 사람의 검토 없이 main 브랜치에 직접 푸시하지 않는다 (자동화는 PR로).
- 페이지를 전면 재작성하지 않는다 — diff 기반 patch-up이 기본 (3.2). 초기 시드(3.1)는 예외.

## 6. 코드 위생 (기술 부채 방지)

기능을 빼거나 인터페이스를 바꿀 때는 **같은 PR에서** 다음을 함께 정리한다.

- **죽은 코드 / 사용하지 않는 import** 즉시 삭제. "나중에 정리"는 안 한다.
- 무의미해진 **테스트 케이스** 삭제 또는 대체.
- 호출 측 / docstring / README / CLI 도움말 동일 커밋에서 갱신.
- 머지 전 `grep`으로 삭제 대상 심볼 잔여 참조 0개 확인.

부채를 미루지 않는다 — 다음 사람(다른 LLM 세션 포함)이 stale한 신호로 잘못된 결정을 내릴 위험이 크다.
