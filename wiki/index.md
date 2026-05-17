---
title: code-llm-wiki
last_synced: null
covers: []
---

# code-llm-wiki

Karpathy의 LLM Wiki 패턴을 임의의 소스 sub-tree에 적용한 자동 생성 위키.

- 원본(불변): `raw/<top>/` — 사용자가 sub-tree마다 별도 git으로 동기화 (예: `raw/pcie_scsc/`, `raw/linux/`)
- 위키 페이지(LLM 소유): `wiki/raw/<top>/` — raw 트리를 1:1 미러
- 운영 규칙: [`../CLAUDE.md`](../CLAUDE.md)

## 구조

```
wiki/
  raw/<top>/                ← sub-tree마다 디렉토리, raw/ 미러
    <basename>.md           ← entity (.c+.h 짝, kind: entity)
    _<basename>.md          ← subsystem 또는 concept (kind: subsystem|concept)
    _index.md               ← 디렉토리별 페이지 인덱스 (seed_pages.sh 생성)
  queries/                  ← LLM 분석 산출물 (code review, porting, feature impl)
    _templates/             ← 쿼리 템플릿
  _meta/
    coverage.json           ← 페이지↔raw 파일 매핑 + last_synced ledger
    todo.md                 ← 커버되지 않은 raw 파일 백로그
    layout-proposals/       ← propose_layout 산출 YAML (검토 후 apply_layout)
```

페이지 종류는 **path가 아니라 front-matter `kind`** 로 구분:

| kind | 위치 | 무엇 |
|---|---|---|
| `entity` | `wiki/raw/<top>/<basename>.md` | translation unit (`.c`+`.h` 짝). `seed_pages.sh`가 자동 생성 |
| `subsystem` | `wiki/raw/<top>/_<basename>.md` | 여러 파일에 걸친 강결합 단위. `propose_layout` → `apply_layout` |
| `concept` | `wiki/raw/<top>/_<basename>.md` | cross-cutting 추상화/프로토콜. 동일 경로 |
| `query` | `wiki/queries/<slug>.md` | 사람의 질의 산출물 |

`_` prefix는 entity와 architectural 페이지를 디렉토리 정렬 시 구분하기 위함.

상호 링크는 Obsidian 스타일 `[[raw/<top>/<basename>|표시명]]` — `wiki/` 기준 상대 경로.

## 현재 sub-tree

`wiki/raw/`의 각 하위 디렉토리가 한 sub-tree.

---

> **이 페이지는 구조 설명용이라 사람이 PR로 갱신합니다.** `covers:`가 비어 있고 LLM이 유도할 근거가 없음. 반면 `wiki/raw/<top>/*.md`는 LLM이 소스에서 유도해 갱신 — CLAUDE.md §1 참조.
