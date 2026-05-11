# code-llm-wiki

리눅스 커널 소스를 동기화하면서 LLM이 자동으로 유지·보수하는 코드 위키.
Karpathy의 [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
패턴을 코드 도메인에 적용했다.

## 무엇을 하나

- **패치 중심 업데이트**: 커널에 새 커밋이 들어오면 영향받는 위키 페이지만 LLM이 부분 갱신.
- **Annealing**: 코드 변경이 없어도 cron이 오래된 페이지·끊긴 링크·미커버 파일을 골라 보정.
- **MD → HTML**: MkDocs로 정적 사이트 빌드, GitHub Pages 배포.
- **LLM 지식 기반**: 생성된 위키를 코드 리뷰·포팅·기능 추가 시 LLM이 직접 활용 (`wiki/queries/` 템플릿).

## 레이아웃

```
raw/linux/          # 커널 소스 (불변, 사용자가 동기화)
wiki/               # LLM이 소유하는 markdown 페이지들
  index.md
  subsystems/       # 서브시스템 단위
  concepts/         # 횡단 개념
  entities/         # 자료구조/함수/매크로
  queries/          # 재사용 가능한 LLM 산출물
  _meta/            # coverage.json, todo.md
scripts/            # 동기화·업데이트·annealing·빌드 도구
config/             # LLM 프로필 (OpenAI / Anthropic / OpenAI-호환)
CLAUDE.md           # 에이전트 SOP (LLM 운영 규칙)
```

## 진행 상태

- [x] D1: 스캐폴드 + LLM provider 추상화
- [x] D2: 패치 라우터 + 커버리지 인덱스
- [x] D3: 위키 생성/업데이트 코어
- [x] D4: Annealing 잡
- [ ] D5: MkDocs 빌드 + Pages 배포
- [ ] D6: GH Actions cron 통합
- [ ] D7: LLM 소비 패턴 + E2E

---

## 위키 처음 만들기 (콜드 스타트)

빈 저장소에서 의미 있는 위키까지 가는 절차. **첫 페이지를 시드하기 전까지는 한 번만** 거치면 됩니다.

### 0. 사전 준비

#### (0-1) LLM 설정

```bash
# 설정 파일을 복사하고 편집 (default_profile, model 등 조정)
cp config/llm.example.json config/llm.local.json
${EDITOR:-vi} config/llm.local.json

# API 키 — 사용하는 프로필에 맞게
export ANTHROPIC_API_KEY=sk-ant-...        # claude 프로필
export OPENAI_API_KEY=sk-...               # openai 프로필 (또는 OpenAI-호환 엔드포인트)

# 연결 검증
python -m scripts.llm_client --probe                 # 기본 프로필
python -m scripts.llm_client --probe --all           # 설정된 모든 프로필
python -m scripts.llm_client --selftest              # 오프라인 검증(키 불요)
```

`config/llm.local.json`은 `.gitignore`에 포함돼 있어 커밋되지 않습니다.

#### (0-2) 커널 소스 배치

`raw/linux/`에 git 트리를 두기. 전체 mainline일 필요 없음. **타겟 서브시스템만 좁게 클론하는 게 가장 빠르고 토큰도 덜 듭니다.**

```bash
# 옵션 A: 한두 서브시스템만 (mm + net/core 추천 시작점)
git clone --filter=blob:none --no-checkout \
    https://github.com/torvalds/linux raw/linux
cd raw/linux
git sparse-checkout init --cone
git sparse-checkout set mm net/core
git checkout master
cd -

# 옵션 B: 안정 LTS 브랜치 전체 (변동 적어서 cron에 적합)
git clone -b linux-6.6.y --single-branch \
    https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git raw/linux

# 옵션 C: 다른 위치에 이미 체크아웃 있으면 심볼릭 링크
ln -s /work/linux raw/linux
# 또는 환경변수로
export KERNEL_DIR=/work/linux
```

`sync_kernel.py`의 경로 우선순위: `--kernel-dir` CLI 플래그 > `$KERNEL_DIR` > `raw/linux/`.

---

### 1. 첫 페이지 **시드** — 사람이 구조를 결정, LLM이 내용을 채움

이 단계는 **자동화되지 않습니다**. 어떤 페이지로 위키를 시작할지는 도메인 판단이라 사람이 결정. 큰 단위(subsystem) 한두 개 → 그 안의 핵심 개념·구조체 순서가 일반적입니다.

```bash
# (a) 서브시스템 페이지 (큰 그림)
python -m scripts.update_wiki seed \
    --page subsystems/mm.md --kind subsystem \
    --covers 'mm/*.c' 'mm/*.h'

# (b) 그 안의 핵심 개념 (대상이 좁아질수록 LLM 응답이 정확해짐)
python -m scripts.update_wiki seed \
    --page concepts/slab.md --kind concept \
    --covers 'mm/slab*.c' 'mm/slub.c'

python -m scripts.update_wiki seed \
    --page concepts/page-allocator.md --kind concept \
    --covers 'mm/page_alloc.c' 'mm/page-flags.c'

# (c) 핵심 자료구조 (선택)
python -m scripts.update_wiki seed \
    --page entities/struct-page.md --kind entity \
    --covers 'include/linux/mm_types.h'
```

각 호출이 내부적으로 하는 일:

1. `--covers` 글롭에 매칭되는 커널 파일 목록을 enumerate (최대 `--max-files`, 기본 120)
2. 그중 일부 파일의 처음 N줄을 발췌 (`--max-excerpts`개, `--excerpt-lines`줄, 기본 8 × 80)
3. 컨텍스트(파일 목록 + 발췌 + 현재 HEAD sha)와 함께 LLM 호출
4. LLM이 위키 페이지 작성 — `# title` + Key data structures + Key entry points + Related + Recent changes
5. `wiki/_meta/coverage.json`에 페이지 등록, 처음이면 `last_kernel_sha`도 초기화

#### dry-run으로 미리보기

```bash
python -m scripts.update_wiki seed --dry-run \
    --page concepts/slab.md --kind concept \
    --covers 'mm/slab*.c'
```

품질이 마음에 안 들면 `--page` 경로/`--covers` 글롭/`--kind`를 조정 후 다시. 위키 트리에는 아무것도 쓰이지 않습니다.

#### 키 없이 파이프라인만 시험

```bash
python -m scripts.update_wiki seed \
    --page subsystems/mm.md --kind subsystem \
    --covers 'mm/*.c' --mock-llm
```

`--mock-llm`은 결정적 템플릿 응답을 사용 — 실제 LLM 호출 없이 시드/업데이트/anneal 흐름을 끝까지 검증할 수 있습니다.

#### 비용 가늠

Claude Opus 기준 시드 1페이지 ≈ 입력 8~20k 토큰, 출력 1~3k 토큰. mm 서브시스템 전부 시드해도 보통 페이지 5~10개면 충분.

---

### 2. 이후 자동 사이클 — 사람이 손댈 일 없음

시드 한두 개 끝나면 나머지는 자동:

```
시드된 페이지
     │
     ▼
sync_kernel.py ─▶ patch_router.py ─▶ update_wiki update
 (커널 fetch)       (영향 페이지)         (LLM 부분 갱신)
                                              │
                                              ▼
                              coverage.json + last_synced_sha 갱신
                                              │
                                              ▼
                                  anneal.py 주기 실행
                          (오래된 페이지 / 끊긴 링크 / drift 수리)
```

수동 실행 예 (D6의 GitHub Actions가 이걸 대신 돌립니다):

```bash
# 패치 사이클 1회 (보통 매시간 cron)
python -m scripts.sync_kernel --record \
    | python -m scripts.patch_router --apply --out /tmp/r.json
python -m scripts.update_wiki update --routing /tmp/r.json

# Annealing 1회 (보통 매일 cron, budget으로 비용 상한)
python -m scripts.anneal scan                                # 후보 점검(읽기만)
python -m scripts.anneal run --budget 3                      # 상위 3개 수리
python -m scripts.anneal run --budget 3 --dry-run --mock-llm # 안전 시연
```

---

### 3. 위키 확장 — 새 영역 발견 시

`patch_router --apply`가 처음 보는 커밋의 미커버 파일을 `wiki/_meta/todo.md`에 모으고, `anneal scan`도 그걸 리포트합니다. 새 서브시스템·개념이 자주 보이면 **수동으로** seed 한 번 더:

```bash
# anneal scan 결과나 todo.md를 보고
python -m scripts.update_wiki seed \
    --page subsystems/net-core.md --kind subsystem \
    --covers 'net/core/*.c'
```

이게 의도된 설계입니다 — **위키의 "구조"(어떤 페이지가 존재할지)는 사람이 정하고, "내용"은 LLM이 채우고 유지**.

---

## 명령어 참조 (cheat sheet)

| 목적 | 명령 |
|---|---|
| LLM 연결 검증 | `python -m scripts.llm_client --probe --all` |
| LLM 오프라인 검증 | `python -m scripts.llm_client --selftest` |
| 커널 diff 매니페스트 | `python -m scripts.sync_kernel [--no-fetch] [--record]` |
| 영향 페이지 라우팅 | `python -m scripts.patch_router --manifest m.json [--apply]` |
| 새 페이지 시드 | `python -m scripts.update_wiki seed --page P --kind K --covers G...` |
| 패치 → 페이지 갱신 | `python -m scripts.update_wiki update --routing r.json` |
| Annealing 점검 | `python -m scripts.anneal scan` |
| Annealing 수리 | `python -m scripts.anneal run --budget N` |
| 단위 테스트 | `python -m unittest discover -s tests` |

공통 플래그: `--mock-llm`(키 불요 모의 응답), `--dry-run`(파일 쓰지 않음), `--profile NAME`(LLM 프로필 선택), `--kernel-dir PATH`(커널 트리 위치 override).

---

## D1-D4 빠른 데모 (mock LLM, 키 없이)

```bash
# 1) 페이지 시드
python -m scripts.update_wiki seed \
    --page subsystems/mm.md --kind subsystem \
    --covers 'mm/*.c' 'mm/*.h' --mock-llm

# 2) 가짜 패치로 업데이트
cat > /tmp/routing.json <<'EOF'
{ "from": null, "to": "abc1234",
  "affected_pages": ["subsystems/mm.md"], "uncovered": [], "commits": [] }
EOF
python -m scripts.update_wiki update --routing /tmp/routing.json \
    --mock-llm --kernel-dir /none

# 3) Annealing 점검 + 수리
python -m scripts.anneal scan --kernel-dir /none
python -m scripts.anneal run --budget 3 --mock-llm --kernel-dir /none
```

생성된 `wiki/subsystems/mm.md`와 `wiki/_meta/coverage.json` 변화를 확인.

---

자세한 운영 규칙은 [`CLAUDE.md`](./CLAUDE.md) 참조.
