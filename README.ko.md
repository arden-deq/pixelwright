# Pixelwright

![기사·물약·방패 아이콘으로 소개하는 Pixelwright 배너](docs/images/pixelwright-header.png)

헤더: 2048×1024 · 4×4 px 셀 · 32색 · 131,072셀 PASS · [검사 보고서](docs/examples/header/report.json) · [격자 미리보기](docs/examples/header/grid_overlay.png) · [제작 기록](docs/examples/header/)

[English](README.md) · [한국어](README.ko.md) · 버전 0.3.0 · [Apache License 2.0](LICENSE)

**선언한 격자 위에서 정적 PNG 픽셀아트를 만들고, 모든 셀을 검사합니다.**

Pixelwright는 GPT 계열 호스트와 Claude에서 함께 쓰는 AI 스킬입니다. 캐릭터·아이템·UI 아이콘의 일정한 도트 크기, 격자 안에 온전히 들어가는 정사각형 셀, 셀 내부의 정확한 단일 RGBA 색상을 생성하고 검사합니다. 두 생태계에서 동일한 `SKILL.md`와 Python 도구를 사용하며, 실행 호스트에는 파일 접근과 Python 실행 기능이 필요합니다.

팔레트와 논리 픽셀 행렬을 먼저 만든 뒤 정수 배율로 확대하고, 내보낸 PNG를 검사합니다. 기존 이미지에는 검사 전에 의도한 격자 규격을 선언합니다. 기본 결과에는 원본 이미지와 실제 격자 QA 미리보기를 함께 보여 주어 사용자도 셀을 눈으로 확인할 수 있습니다.

## 같은 기사, 두 가지 격자 규격

![방패와 둔기를 든 풀 플레이트 기사의 4×4·8×8 도트 비교: 원본 이미지, 격자 확대, 공통 32색 팔레트, 실제 QA 결과](docs/images/knight-conditions.ko.png)

Pixelwright 개발 과정에서 실제로 만들고 눈으로 확인한 결과입니다. 풀 플레이트 아머를 착용하고 방패와 플랜지 메이스를 든 전신 기사를 두 규격으로 제작했습니다. 두 PNG 모두 **1024×1536**이며, 동일한 **32색 RGBA 팔레트**(가시 색상 31개 + 투명색 1개)를 사용하고 같은 엄격한 품질 기준을 통과했습니다. 도트 크기를 바꾸면 논리 캔버스와 표현할 수 있는 디테일이 달라지지만, 온전한 정사각형 셀과 정확한 단색 채움은 유지됩니다.

| 버전 | 작화 원본 → 출력 PNG | 도트 1칸 | 단색 셀 | 투명색 포함 색상 수 | 검사 |
| --- | --- | --- | ---: | ---: | --- |
| 세밀한 도트 | [256×384](docs/examples/knight/4px/native.png) → [1024×1536](docs/examples/knight/4px/rendered.png) | 4×4 px | 98,304 / 98,304 | 32 | [PASS 보고서](docs/examples/knight/4px/report.json) |
| 큰 도트 | [128×192](docs/examples/knight/8px/native.png) → [1024×1536](docs/examples/knight/8px/rendered.png) | 8×8 px | 24,576 / 24,576 | 32 | [PASS 보고서](docs/examples/knight/8px/report.json) |

두 검사 모두 **불균일 셀 0개, 반투명 픽셀 0개, 지정 팔레트 밖의 색상 0개**입니다. 투명 셀을 포함해 각 셀 안의 모든 RGBA 값이 정확히 같습니다. 독립적인 픽셀 비교로 출력이 작화 원본을 최근접 이웃 방식으로 정확히 확대한 결과인지도 확인했습니다. [4 px 검증 기록](docs/examples/knight/4px/verification.json) · [8 px 검증 기록](docs/examples/knight/8px/verification.json).

자료 화면에는 원본 이미지와 격자 부분 확대를 함께 배치해 도트 하나하나를 확인할 수 있게 했습니다. 실제 PNG의 도트 크기와 화면 표시용 확대 배율을 각각 표기했습니다. 격자선과 바둑판 배경은 별도 진단 미리보기에만 적용하며, 원본 PNG는 투명 배경과 32색 팔레트를 유지합니다. 이미지 전체를 확인하려면 [4 px 전체 격자](docs/examples/knight/4px/grid_overlay.png) 또는 [8 px 전체 격자](docs/examples/knight/8px/grid_overlay.png)를 열어 봅니다.

생성형 모델의 초기 이미지는 미검증 원본으로 보존하고, Pixelwright의 격자 투영·팔레트 제한 논리 행렬·정수 배율 렌더링으로 검사 대상 결과를 만들었습니다. 이 두 규격의 실제 통과 결과는 도트 크기와 논리 해상도가 달라져도 기술적 품질 기준을 일관되게 충족한다는 근거입니다. 미적 품질은 별도로 눈으로 검수합니다.

[기사 예제 폴더](docs/examples/knight/)에는 편집 가능한 `artwork.json` 행렬, 작화 원본·출력 PNG, 선언한 프로필, 실제 검사 보고서, 독립 검증 기록이 있습니다. 아래 안내에 따라 의존성을 설치한 뒤 동봉한 도구로 두 버전을 재현할 수 있습니다.

```sh
python pixelwright/scripts/pixel_build.py --spec docs/examples/knight/4px/artwork.json --out-dir runs/knight-4px-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/knight-4px-build-v1/rendered.png --profile docs/examples/knight/4px/profile.json --out-dir runs/knight-4px-audit-v1
python pixelwright/scripts/pixel_build.py --spec docs/examples/knight/8px/artwork.json --out-dir runs/knight-8px-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/knight-8px-build-v1/rendered.png --profile docs/examples/knight/8px/profile.json --out-dir runs/knight-8px-audit-v1
```

## 바로 시작하기

**Python 3.12 이상**, Pillow, NumPy가 필요합니다. 저장소 루트에서 실행합니다.

```sh
git clone https://github.com/jungducknam/pixelwright.git
cd pixelwright
python -m venv .venv
```

가상 환경을 활성화합니다.

```sh
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

동봉한 랜턴을 만들고 저장된 PNG를 검사합니다.

```sh
python -m pip install -r pixelwright/requirements.txt
python pixelwright/scripts/pixel_build.py --spec pixelwright/examples/lantern.json --out-dir runs/lantern-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/lantern-build-v1/rendered.png --profile pixelwright/examples/item-profile.json --out-dir runs/lantern-audit-v1
```

예제는 16×16 논리 캔버스를 8배 확대해 128×128 PNG를 만듭니다. `rendered.png`, `report.json`, `grid_overlay.png`를 함께 확인합니다. 출력 폴더는 비어 있거나 존재하지 않아야 합니다. 명령을 반복할 때는 새로운 실행 폴더 이름을 사용합니다.

## AI 스킬로 사용하기

스크립트·참조 문서·예제를 포함한 **`pixelwright/` 폴더 전체**를 스킬 경로에 넣습니다.

| 호스트 | 개인 설치 | 프로젝트 설치 | 명시적 호출 |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/pixelwright/` | `<repo>/.agents/skills/pixelwright/` | `$pixelwright` |
| Claude Code | `~/.claude/skills/pixelwright/` | `<repo>/.claude/skills/pixelwright/` | `/pixelwright` |

로컬 설치 경로와 호출 방식은 [OpenAI 공식 스킬 문서](https://learn.chatgpt.com/docs/build-skills), [Claude Code 공식 스킬 문서](https://code.claude.com/docs/en/skills)를 따릅니다. Windows를 포함해 `~`는 사용자 홈 폴더를 뜻합니다.

사용자 스킬 업로드를 지원하는 Claude 환경에서는 아래 명령으로 설치 ZIP을 만든 뒤 호스트의 스킬 화면에서 업로드합니다. 코드 실행과 파일 생성을 활성화하고 Python 의존성이 사용 가능한지 확인합니다. 다른 ChatGPT 환경이나 API 기반 호스트에는 해당 환경의 스킬 로더와 실행 도구가 필요합니다. Pixelwright에는 공급자별 생성 API 어댑터가 포함되지 않습니다. [플랫폼 호환성 안내](docs/COMPATIBILITY_ko.md)와 [Claude 공식 사용자 스킬 문서](https://support.claude.com/en/articles/12512180-use-skills-in-claude)를 참고합니다.

스킬을 호출한 뒤 다음과 같이 요청할 수 있습니다.

> 24×24 물약 아이템을 8배 확대해서 만들어 줘. 가시 색상은 최대 10개, 투명도는 이진 값으로 해 줘. 내보낸 PNG를 Pixelwright로 검사하고, 원본과 격자 미리보기를 함께 보여 줘. 실제 PASS/FAIL 보고서도 포함해 줘.

PNG 접근과 검사기의 성공적인 실행이 없으면 결과는 **미검증**입니다. 스킬을 로드하거나 모델에 “픽셀아트”를 요청하는 것만으로 규격 준수를 확인할 수 없습니다. 이 저장소의 검증에서는 실제 Claude 계정 설치·업로드까지 수행하지 않았습니다.

## 품질 규격 선언하기

재사용 가능한 JSON 프로필로 여러 에셋에 동일한 기술 규칙을 적용합니다.

```json
{
  "schema_version": 1,
  "name": "24px game items",
  "logical_size": "24x24",
  "scale": 8,
  "max_colors": 10,
  "alpha": "binary",
  "transparent_rgb": "exact"
}
```

이를 `profile.json`으로 저장합니다. 이 규격은 원점 `(0, 0)`, 8×8 셀, 192×192 PNG를 요구합니다. 가로·세로에 동일한 양의 정수 배율을 적용하며 엄격한 프로필은 배율 2 이상을 요구합니다. 생성·검사 전에 규격을 확정합니다. 검사기는 이미지를 통과시키기 위해 다른 격자를 추정하거나 크기를 바꾸지 않습니다.

`transparent_rgb: "exact"`는 알파가 0인 부분의 숨은 RGB 값도 비교합니다. 숨은 차이를 정규화할 때만 `"visible"`을 명시적으로 선택합니다. 선택 필드 `allowed_palette`로 전체 RGBA 값을 제한할 수 있습니다. `alpha: "any"`는 셀 내부가 균일한 반투명을 허용합니다. 같은 색의 인접 도트가 큰 비정형 모양을 이루어도 됩니다. 정사각형 규칙은 개별 격자 셀에 적용합니다.

모든 필드, 허용 PNG 형식, 산출물, 종료 코드는 [품질 규격 문서](pixelwright/references/quality-contract.md)에 있습니다. 논리 행렬 형식은 [생성 안내](pixelwright/references/creation.md)를 참고합니다.

## 검사·일괄 검사·보정

이미지 하나를 검사하거나 여러 이미지에 같은 프로필을 적용합니다.

```sh
python pixelwright/scripts/pixelwright.py inspect input.png --profile profile.json --out-dir runs/audit-v1
python pixelwright/scripts/pixelwright.py batch item-a.png item-b.png --profile profile.json --out-dir runs/batch-v1
```

프로필 명령은 모두 PASS이면 `0`, FAIL/REVIEW이면 `2`, 입력·실행 오류이면 `1`로 종료합니다. CI의 적합성 판정에도 이 인터페이스를 사용합니다. 미리보기와 함께 JSON 상태, 정확한 위반 개수를 확인합니다.

명시적인 보정은 원본에서 관측한 색상을 선언한 격자에 투영해 새로운 후보를 만듭니다. 이 과정에는 정보 손실이 있을 수 있습니다.

```sh
python pixelwright/scripts/pixel_qa.py fix input.png --logical-size 24x24 --render-size 192x192 --out-dir runs/repair-v1
python pixelwright/scripts/pixelwright.py inspect runs/repair-v1/fixed_upscaled.png --profile profile.json --out-dir runs/repair-audit-v1
```

보정본을 채택하기 전에 `comparison.png`, `fix_review.json`, 원본·보정본 보고서를 확인합니다. 원본 기하는 선언한 격자에 이미 맞아야 합니다. 보정은 원본 파일을 보존하지만 디테일을 제거할 수 있습니다. 보정 파일은 원래 프로필로 다시 검사합니다.

## 검증과 패키징

```sh
python -m unittest discover -s pixelwright/tests -v
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.3.0.zip
python tools/verify_release.py --archive dist/pixelwright-v0.3.0.zip --out-dir runs/release-check-v1
```

패키징은 최상위 `pixelwright/` 폴더 하나를 포함하는 설치 ZIP과 테스트·문서를 포함하는 개발 키트 ZIP을 만듭니다. 패키지 검증기는 ZIP 구조와 SHA-256 목록을 검사하고, 릴리스 검증기는 설치 패키지를 풀어 실제로 실행합니다. 빌드 결과는 로컬 `dist/`에 생성합니다.

`verify_release.py`는 패키지 안의 Python 코드를 실행하므로 검토한 Pixelwright 소스에서 만든 신뢰할 수 있는 ZIP에만 사용합니다. 해시 목록이 일치한다는 것은 내부 무결성을 확인할 뿐 배포자의 신원을 증명하지 않습니다.

## 지원 범위·라이선스·보안

버전 0.3.0은 **정적 PNG 캐릭터·아이템·UI 아이콘**을 지원합니다. 기술적 PASS는 검사한 파일의 격자, 셀 내부의 정확한 단색, 선언한 프로필 제약을 확인합니다. 미적 품질이나 다른 앱의 확대 표시 방식까지 보장하지는 않습니다. 실루엣·가독성·팔레트·재질 디테일은 별도로 검수합니다. 애니메이션과 아틀라스 검증은 이 버전의 지원 범위에서 제외합니다.

Pixelwright에는 **Apache License 2.0**을 적용합니다. [LICENSE](LICENSE)와 [NOTICE](NOTICE)를 확인합니다.

지원 버전과 취약점 신고 방법은 [SECURITY.md](SECURITY.md)에 있습니다. 저장소에는 [CI](.github/workflows/ci.yml), [CodeQL](.github/workflows/codeql.yml), [의존성 업데이트 설정](.github/dependabot.yml)이 포함됩니다. 이 설정들은 유지 관리를 돕는 장치이며 독립 보안 감사가 완료되었다는 뜻은 아닙니다.

AI 작업 절차는 [`pixelwright/SKILL.md`](pixelwright/SKILL.md), 플랫폼 실행 조건은 [호환성 안내](docs/COMPATIBILITY_ko.md), 구현 판단 근거는 [설계 문서](docs/DESIGN_ko.md)에서 확인할 수 있습니다.
