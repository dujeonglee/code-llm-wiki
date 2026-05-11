---
title: Linux Kernel LLM Wiki
last_synced: null
covers: []
---

# Linux Kernel LLM Wiki

Karpathy의 LLM Wiki 패턴을 리눅스 커널 소스 트리에 적용한 자동 생성 위키.

- 원본(불변): `raw/linux/` (사용자가 동기화)
- 위키 페이지(LLM 소유): `wiki/`
- 운영 규칙: [`CLAUDE.md`](../CLAUDE.md)

## 섹션

- `subsystems/` — 서브시스템 단위 페이지 (mm, net, sched, ...)
- `concepts/` — 횡단 개념 (RCU, slab, scheduler class, ...)
- `entities/` — 핵심 자료구조 · 함수 · 매크로
- `queries/` — 재사용 가능한 LLM 분석 산출물 (code review, porting, feature impl)
- `_meta/` — 커버리지 인덱스, annealing 백로그

> 이 페이지는 LLM이 갱신합니다. 사람이 직접 편집하지 마세요.
