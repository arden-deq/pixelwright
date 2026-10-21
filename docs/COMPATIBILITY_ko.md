# Pixelwright 플랫폼 호환성

대상 버전: **0.6.1** · 공식 문서 확인일: **2026-10-14**

Pixelwright는 동일한 `SKILL.md`와 Python 검사기를 OpenAI 계열과 Claude 계열에서 사용한다. 지원 여부는 모델 이름보다 **파일 접근과 Python 실행이 가능한 호스트**에 달려 있다. 생성 프롬프트는 제작 방향을 안내하고, 최종 PNG의 격자 규격은 검사기의 실제 실행 결과로 판정한다.

## 지원 범위

| 사용 환경 | 패키지 사용 방식 | 품질 판정 조건 |
| --- | --- | --- |
| Codex 로컬 환경 | `pixelwright/` 폴더를 로컬 스킬 경로에 배치 | Python 3.12 이상, Pillow, NumPy, PNG·출력 폴더 접근 |
| ChatGPT의 스킬 지원 환경 | 호스트가 제공하는 스킬 기능으로 로드 | 같은 파일과 Python 실행 조건을 확인한 뒤 검사 |
| Claude Code 로컬 환경 | `pixelwright/` 폴더를 개인 또는 프로젝트 스킬 경로에 배치 | 같은 로컬 실행 조건 |
| Claude의 사용자 스킬 기능 | `pixelwright-v0.6.1.zip` 업로드 후 활성화 | Code execution and file creation 활성화, 실행 환경의 의존성 확인 |
| OpenAI·Claude API 기반 에이전트 | 애플리케이션에서 스킬과 실행 도구를 별도로 연결 | 호출자가 컨테이너·파일·Python 환경을 구성하고 실제 검사 실행 |
| 일반 모델 호출, 참고 문서 첨부만 한 대화 | 제작 가이드로 참고 | 검사기를 실행하지 않은 파일에는 `PASS` 판정 금지 |

OpenAI는 `SKILL.md` 폴더 형식, Codex 로컬 스킬 검색 경로, ChatGPT의 스킬 기능을 문서화한다. ChatGPT에서 배포용 플러그인으로 제공하는 경로도 별도로 존재한다. 이 ZIP은 단일 스킬 패키지이며 플러그인 등록까지 포함하지 않는다. [OpenAI 공식 Build skills](https://learn.chatgpt.com/docs/build-skills)

Claude의 사용자 스킬은 코드 실행 기능을 필요로 하며, 현재 업로드 화면은 `Customize > Skills`이다. 계정·조직의 기능 허용 여부는 해당 환경에서 확인한다. [Claude 공식 Use skills](https://support.claude.com/en/articles/12512180-use-skills-in-claude)

## 로컬 설치 위치

압축을 풀어 얻은 `pixelwright/` 폴더 전체를 아래 위치 중 하나에 둔다. `SKILL.md`만 복사하면 검사기와 참조 파일이 빠진다.

| 호스트 | 개인용 | 프로젝트용 |
| --- | --- | --- |
| Codex | `~/.agents/skills/pixelwright/` | `<repo>/.agents/skills/pixelwright/` |
| Claude Code | `~/.claude/skills/pixelwright/` | `<repo>/.claude/skills/pixelwright/` |

Windows에서 `~`는 사용자 홈 폴더를 뜻한다. 예를 들어 Codex 개인 경로는 `C:\Users\<사용자명>\.agents\skills\pixelwright\`이다. Codex는 현재 작업 폴더부터 저장소 루트까지의 `.agents/skills`를 검색한다. [OpenAI 공식 로컬 스킬 경로](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)

Codex CLI·IDE에서는 `$pixelwright`, Claude Code에서는 `/pixelwright`로 명시적으로 호출할 수 있다. Claude Code의 개인 경로는 로컬 세션용이므로 Cowork·클라우드 세션에 같은 경로가 읽힌다고 가정하지 않는다. [Claude Code 공식 Skills](https://code.claude.com/docs/en/skills)

호스트가 스킬의 위치를 알려주면 그 위치의 `SKILL.md`를 기준으로 `scripts/`, `references/`, `examples/`를 찾는다. 사용자의 작업 폴더와 설치 폴더는 다를 수 있다. 공통 스킬에는 특정 호스트만 지원하는 변수 치환이나 도구 이름을 필수 조건으로 넣지 않는다.

## Claude 업로드 ZIP 구조

`pixelwright-v0.6.1.zip` 안에는 **하나의 최상위 `pixelwright/` 폴더**가 있어야 한다. 그 안에 `SKILL.md`와 실행 파일이 함께 들어간다.

```text
pixelwright-v0.6.1.zip
└── pixelwright/
    ├── SKILL.md
    ├── requirements.txt
    ├── scripts/
    │   ├── pixel_build.py
    │   ├── pixel_palette.py
    │   ├── pixel_qa.py
    │   ├── pixelwright.py
    │   ├── pixel_layers.py
    │   └── pixel_sprite.py
    ├── references/
    ├── examples/
    └── agents/
```

ZIP의 최상위에 `SKILL.md`를 바로 넣거나, `release/pixelwright/`처럼 포장 폴더를 하나 더 넣지 않는다. 스킬 이름과 폴더 이름은 `pixelwright`로 맞춘다. [Claude 공식 패키징 안내](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills#package-your-skill)

## 실행 확인과 판정 경계

호스트의 실제 실행 환경에서 Python 버전과 의존성을 확인한다. 개인 PC에 설치된 패키지가 원격 컨테이너에도 있다고 가정하면 안 된다.

```text
python --version
python -c "import PIL, numpy; print(PIL.__version__, numpy.__version__)"
```

의존성은 `pixelwright/requirements.txt`에 명시한다. 로컬 설치가 필요한 경우 프로젝트 전용 환경을 사용한다. Claude API의 스킬 실행 환경에서는 실행 중 네트워크 접근과 추가 패키지 설치가 제한되므로, 의존성 사용 가능 여부를 먼저 확인해야 한다. [Claude Platform 공식 실행 제약](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview#runtime-environment-constraints)

Pixelwright의 실행 계약은 다음과 같다.

1. 입력 PNG와 규격을 실제 파일로 읽는다.
2. 동일한 Python 검사기를 실행한다.
3. 검사기가 만든 리포트를 확인하고 그 파일에 대한 판정을 전달한다.
4. 수정본을 만들었다면 수정본을 다시 검사한다.

실행 도구가 없거나 의존성을 불러오지 못하면 **미검증**으로 표시하고 실행 가능한 명령을 제공한다. 화면 미리보기나 모델의 육안 평가만으로 격자 적합성을 보장하지 않는다. 품질 보장은 검사한 파일의 규격 준수에 한정되며 캐릭터의 매력, 구도, 스타일 같은 미술적 품질은 별도로 평가한다.

0.6.1의 대상은 캐릭터·아이템·UI 등 **정적 PNG**, 재사용 JSON 팔레트, 선택적 레이어 합성, 그리고 하나의 정적 PNG 시트에 담은 스프라이트 프레임과 선언형 부위 리그다. 팔레트 추출·램프 생성·색상 변환은 같은 Python 의존성으로 실행하며 추가 생성 API나 계정을 요구하지 않는다. 라이브러리 참조는 작화 JSON 폴더 안의 상대 경로로 해석하므로 작화와 라이브러리를 함께 옮긴다. 색상 변환은 원래 격자와 알파를 유지하고 결과를 원래 프로필로 검사한다. 애니메이션은 프레임을 시트 PNG에 배치하고 `pixel_sprite.py`로 검사하며, 검사 결과의 GIF는 진단용 미리보기다. APNG 같은 애니메이션 컨테이너 입력은 지원 대상에서 제외한다. 이미지 생성 모델이나 외부 편집 도구는 호스트가 이미 제공하는 기능을 필요에 따라 사용하며, Pixelwright가 별도의 생성 API 어댑터나 자동 외부 호출을 제공하지는 않는다.

## 이 버전에서 확인한 것

공식 문서와 공통 패키지 구조에 맞춰 호환성을 설계했다. 실제 계정에 설치하거나 Claude 업로드를 수행한 상태를 뜻하지 않는다. 각 호스트에서 처음 사용할 때는 스킬 로드, 의존성 확인, 정상·불량 샘플 판정, 출력 파일 접근까지 확인한다. 공급자별 실행 환경이 달라도 같은 파일과 규격에는 같은 검사 결과를 사용한다.
