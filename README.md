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
CLAUDE.md           # 에이전트 SOP
```

## 빠른 시작

1. **설정 파일 준비**
   ```bash
   cp config/llm.example.json config/llm.local.json
   # llm.local.json 에서 default_profile / model 등 조정
   ```
2. **API 키 환경변수**
   ```bash
   export ANTHROPIC_API_KEY=...   # claude 프로필
   export OPENAI_API_KEY=...      # openai 프로필
   ```
3. **연결 확인**
   ```bash
   python -m scripts.llm_client --probe --all
   ```
   양쪽 프로필이 `OK`면 D1 완료.

4. **커널 소스 배치**
   - `raw/linux/`에 타겟 서브시스템(예: `mm/`, `net/core/`)을 포함한 git 트리를 둔다.
   - 전체 mainline일 필요는 없다. 부분 트리도 OK.

## 진행 상태

- [x] D1: 스캐폴드 + LLM provider 추상화
- [x] D2: 패치 라우터 + 커버리지 인덱스
- [x] D3: 위키 생성/업데이트 코어
- [x] D4: Annealing 잡
- [ ] D5: MkDocs 빌드 + Pages 배포
- [ ] D6: GH Actions cron 통합
- [ ] D7: LLM 소비 패턴 + E2E

## 데모: mock LLM E2E (API 키 없이)

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
```

자세한 운영 규칙은 [`CLAUDE.md`](./CLAUDE.md) 참조.
