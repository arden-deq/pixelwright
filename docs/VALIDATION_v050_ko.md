# Pixelwright v0.5.0 팔레트 검증 기록

검증일: **2026-10-15**. Windows에서 Python **3.12.10**과 **3.14.7**의 기존 격리 환경으로 실행했습니다. 두 환경 모두 Pillow **12.3.0**, NumPy **2.5.4**를 사용했습니다. 실제 Claude 계정 설치·업로드는 포함하지 않았습니다.

## 테스트와 형식

두 Python 버전에서 각각 전체 **138개 테스트**가 `OK (skipped=2)`로 완료됐습니다. 팔레트 기능 테스트 35개와 설치 패키지 리소스 검사 1개를 추가했습니다. 건너뛴 두 테스트는 Windows의 심볼릭 링크 생성 권한이 필요한 사례입니다.

새 테스트는 관측 RGBA 빈도와 동률 정렬, 추출 잘림, 숨은 RGB의 exact/visible 정책, 동일 알파 목표 선택, 거리 동률, 램프 끝점·반올림·중복 거부, named ramp 선택, 투명 셀 유지, 기존 프로필 재감사, 색상 예산 실패를 검증합니다. 잘못된 원본 격자를 색상 변환으로 감출 수 없는지와 승인 PNG가 실패 시 남지 않는지도 확인했습니다.

라이브러리 참조 빌드는 추출·램프 JSON을 실제 작화에 재사용하고 픽셀·원본 해시를 비교합니다. 경로 이탈, 인라인/파일 팔레트 동시 지정, 비어 있지 않은 출력, 파일 일부 쓰기 실패와 경합, 감사·승격 이후 입력 변경을 검사합니다. 기존 레이어·프로필·PNG QA 회귀 테스트도 함께 통과했습니다.

Skill 형식 검증과 `git diff --check`를 통과했습니다. CLI와 예제 사용법은 [팔레트 안내](../pixelwright/references/palettes.md)에 있습니다.

## 동봉 예제

[palette-demo](../pixelwright/examples/palette-demo/)는 투명색과 5단계 metal 램프를 같은 JSON에 저장하고, `artwork.json`에서 `palette_file`로 참조합니다. 기존 인라인 명세도 계속 지원합니다.

동봉 작화는 **16×16 논리 셀, 8배, 128×128 PNG**로 빌드한 후 원래 예제 프로필로 검사했습니다. **256셀 모두 PASS**입니다. 팔레트는 생성·재사용 방식의 예시이며 자동 미적 승인 근거가 아닙니다.

```sh
python -m unittest discover -s pixelwright/tests
python pixelwright/scripts/pixel_build.py --spec pixelwright/examples/palette-demo/artwork.json --out-dir runs/palette-build-v1
python pixelwright/scripts/pixelwright.py inspect runs/palette-build-v1/rendered.png --profile pixelwright/examples/palette-demo/profile.json --out-dir runs/palette-audit-v1
```

출력 폴더는 실행마다 새 이름을 사용합니다. 기술 PASS와 별도로 네이티브 크기의 실루엣·외곽선·중요한 색상 구분을 검토합니다.

## 설치 ZIP 실행

소스 트리에 의존하지 않고 v0.5.0 설치 ZIP을 새 디렉터리에 풀어 실행했습니다. ZIP 내부 SHA-256 목록과 파일 경계를 검사한 뒤 아래 항목을 확인했습니다.

- 기존 랜턴 256셀과 네 레이어 합성의 최종 71,680셀 PASS.
- 숨긴 불량 레이어와 한 샘플이 손상된 PNG를 거부하고 승인 PNG를 내보내지 않음.
- 패키지의 실제 palette-demo를 빌드·감사하여 256셀 PASS, 참조 팔레트 해시 일치.
- 투명색이 있는 라이브러리에 5단계 램프를 추가하고 `--ramp metal`로 랜턴을 변환.
- 변환 PNG의 크기·알파 평면·선택 램프 소속을 독립 비교하고 동일 프로필로 재검사하여 PASS.
- 변환 PNG에서 팔레트를 정확히 다시 추출하고 저장한 라이브러리를 새 논리 행렬에 재사용.
- PNG·프로필·팔레트·명세·동봉 예제 원본의 해시 유지.

```sh
python tools/package_skill.py --out-dir dist
python tools/package_skill.py --verify dist/pixelwright-v0.5.0.zip
python tools/verify_release.py --archive dist/pixelwright-v0.5.0.zip --out-dir runs/release-v050-check-v1
```

설치 ZIP과 개발 키트 ZIP 모두 내부 무결성 검사를 통과했습니다. 설치 실행 요약은 로컬 `.work/palette-v050-final-release/release-check.json`에 남겼습니다. `verify_release.py`는 신뢰할 수 있는 Pixelwright 소스에서 만든 ZIP에만 실행합니다.

## 독립적인 Skill 사용

구현·테스트·의도한 답을 제공하지 않은 별도 에이전트가 Skill과 실제 요청만 읽고 격리 폴더에서 작업했습니다. 동봉 랜턴에서 최대 8색을 추출하고, 기존 팔레트를 보존하며 5단계 metal 램프를 추가한 뒤 해당 램프와 투명색으로 랜턴을 변환했습니다. 같은 라이브러리를 `palette_file`로 참조하는 새 16×16 방패도 제작했습니다.

추출은 RGBA 7개를 잘림 없이 보존했고, 라이브러리 확장은 기존 7개에 램프 5개를 추가했습니다. 두 출력 모두 원래 16×16·8배·이진 알파 프로필의 독립 검사에서 **256셀 PASS, 불균일 셀 0개**입니다. 랜턴의 알파 평면과 원본·프로필·라이브러리 해시도 유지됐습니다.

실제 원본 이미지와 격자 미리보기를 검수했습니다. 랜턴의 손잡이·계단식 받침과 방패의 넓은 윗부분·뾰족한 끝이 읽혔습니다. metal 변환은 랜턴의 따뜻한 빛을 없애고 노랑·금색의 구분을 합쳤으며, 이 손실을 기술 PASS와 별도로 기록했습니다. 방패의 고립된 한 셀 하이라이트는 의도한 디테일로 검토했습니다.

첫 방패 명세의 누락 토큰은 출력 전에 안전하게 거부됐고, 수정한 명세는 새 출력 폴더에서 성공했습니다. 네이티브 Python 프로세스의 해당 검증 실패 종료 코드는 문서대로 `2`입니다. PowerShell 도구 래퍼가 표시한 종료 코드와 구분하여 확인했습니다. 실행 자료는 로컬 `.work/palette-forward-20261015-01/verification.json`에 보관하고 배포에서 제외했습니다.
