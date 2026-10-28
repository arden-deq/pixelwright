# 2D 시안 우선 생성 흐름의 통합 검증

2026-10-22, main `1899f66`의 v0.6.2 수정과 2D 시안 우선 개발 도구를 통합해 검증했습니다. macOS, Python 3.12, Pillow 13.0.0, NumPy 2.5.4, Blender 5.2.2 LTS 환경입니다. 이 기록은 새 이미지 생성이나 작화 승인 기록이 아닙니다.

## 생성과 재생성

상태 생성은 선택한 2D 시안과 고정 골격의 해시가 일치할 때만 요청합니다. 입력은 반복한 2D 시안 시트, 해당 상태의 맨 골격 시트 순서입니다. 상태 프롬프트는 원래 요청과 선택한 시안을 사용하며 특정 의상이나 체형을 강제하지 않습니다.

선택한 시안은 `--force`로 덮어쓸 수 없습니다. 전체 재생성은 상태 시트만 대상으로 삼습니다. 교체하는 원본 PNG와 이전 생성 기록은 `generated/history/`에 보관하고 현재 manifest에서 연결합니다. 서비스 실패 시 기존 PNG와 manifest가 유지되는 것도 검증했습니다. 이 전송 경로는 모의 응답으로 검사했으며 이번 통합 과정에서는 유료 이미지 API를 호출하지 않았습니다.

## 코드 검증

- 전체 단위 테스트 **266개 PASS**. 이 중 시안 우선 흐름은 26개입니다.
- 고정 시안 덮어쓰기, 변경된 골격·계약, 뒤바뀐 입력 순서를 생성 요청 전에 거부했습니다.
- 두 번 교체한 이미지의 정확한 바이트와 이전 provenance를 모두 보존했습니다.
- 관찰 좌표·치수의 문자열, 불리언, NaN·무한대, 잘못된 컨테이너를 입력 오류로 거부했습니다. 미관찰·가림은 계속 REVIEW입니다.
- 시스템 기본 인코딩을 cp1252로 모의한 상태에서도 한글 요청이 선택·포즈·생성 프롬프트까지 UTF-8로 유지됐습니다.
- Python 엔트리 포인트 컴파일과 v0.6.2 ZIP 제작·독립 설치 검증을 수행했습니다.

## 실제 저장 예제 재검사

[예제 원본](examples/knight-design-first/generation/)을 변경하지 않고 다시 검사했습니다. 네이티브 시트는 저장된 예제와 픽셀 단위로 같았고, 출력 PNG는 정확한 최근접 4배 확대였습니다. 픽셀 규격은 PASS이며, 독립 수동 관찰은 **4프레임 PASS / 13프레임 FAIL / 1프레임 REVIEW**로 유지됐습니다. 검사 명령의 종료 코드 `2`는 이 작화 실패·검토 상태를 의미합니다.

Blender에서 18포즈를 다시 만들고 검사했습니다. 외형 메시 수는 **0개**, 최대 월드 뼈 길이 오차는 `6.107e-16 m`, Blender 카메라와 독립 투영 차이는 `1.310e-5` 논리 셀 이내였습니다. 골격 PASS가 생성 그림의 포즈·장비 크기 PASS를 대신하지 않습니다. [작화 결함과 관찰 기록](examples/knight-design-first/)은 그대로 유지합니다.

```sh
python -m pip install -r pixelwright/requirements.txt
python -m unittest discover -s pixelwright/tests -v
python tools/package_skill.py --out-dir runs/design-first-dist
python tools/verify_release.py --archive runs/design-first-dist/pixelwright-v0.6.2.zip --out-dir runs/design-first-installed
python tools/knight_generate_frames.py --poses docs/examples/knight-design-first/generation --dry-run --force
python tools/knight_design_first.py check --run-dir docs/examples/knight-design-first/generation --annotations docs/examples/knight-design-first/generation/artwork-annotations.json --out-dir runs/design-first-observed
```

출력 폴더는 새 경로를 사용합니다. 마지막 명령은 작화 실패를 보존하므로 종료 코드 `2`가 예상값입니다. 설치 ZIP에는 선택적 소스 개발 도구와 Blender가 포함되지 않습니다.
