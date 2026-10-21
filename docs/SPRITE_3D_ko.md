# 3D 골격에서 2D 도트 스프라이트 생성하기

이 경로는 실제 Blender 골격과 갑옷·장비 메시를 먼저 만들고, 고정 직교 카메라로 렌더한 구도를 이미지 생성의 입력으로 사용합니다. 기준 캐릭터 한 장을 공유하고, 걷기·공격·막기를 각각 6프레임 시트 한 장으로 생성합니다. [실제 결과와 검증 기록](examples/knight-3d/)을 포함했습니다.

현재는 소스 체크아웃의 개발 도구입니다. 설치용 v0.6.1 ZIP에는 이 선택적 Blender 도구가 들어 있지 않습니다. Blender는 가이드 제작에만 필요하며, 나머지는 저장된 JSON/PNG와 기존 Pillow·NumPy 의존성으로 실행합니다.

## 생성 순서

먼저 저장소의 Python 의존성을 설치하고 Blender를 준비합니다. 아래 `blender`는 실행 파일의 경로로 바꿀 수 있습니다. 새 실행마다 빈 출력 폴더를 사용합니다.

```sh
python -m pip install -r pixelwright/requirements.txt
blender --background --factory-startup --python tools/knight_render_3d.py -- --out-dir runs/knight-3d/rig
python tools/knight_sheet_3d.py prepare --rig-dir runs/knight-3d/rig --out-dir runs/knight-3d/generation
```

렌더러는 18개 뼈, 38개 메시 부품과 시간 키프레임이 있는 `knight-rig.blend`를 저장합니다. 각 포즈에 대해 볼륨 렌더, 실제 메시 ID, 고정 범위의 깊이·카메라 법선 이미지를 내보냅니다. 메시 ID는 평가된 Blender 삼각형의 Z-buffer에서 얻습니다. 준비 단계는 카메라·월드 좌표·프레임 크기·통과 기준을 복사하고 가이드 해시를 고정합니다.

`prompts.json`의 `anchor`를 먼저 생성합니다. 기준 이미지를 승인하기 전에는 상태 시트를 생성하지 않습니다. HTTP 경로에서는 `OPENAI_API_KEY`를 환경 변수에 설정합니다.

```sh
python tools/knight_generate_frames.py --poses runs/knight-3d/generation --animation anchor
python tools/knight_sheet_3d.py anchor --run-dir runs/knight-3d/generation
```

기준 이미지도 도트와 구도를 눈으로 확인합니다. `anchor` 명령은 원본을 보존하고 128×128 격자로 투영한 뒤 **기준 캐릭터 한 장만** 균일 배율로 등록합니다. `anchor-calibration.json`에 배율·이동·원본 해시와 투영 검사 결과를 기록합니다. 구도가 실패하면 종료 코드 `2`를 반환합니다. 기술적 통과가 작화 승인을 대신하지는 않습니다.

v0.6.1에서는 이미 고정된 투영 검사를 통과하는 기준 이미지를 배율 1과 원래 위치로 보존합니다. 미정렬 후보에 균일 배율 보정을 적용하며, 보정 후에도 같은 투영 기준으로 검사합니다. 3D 기준 뼈 길이는 유한한 양수, 길이 허용치는 유한한 0 이상의 수여야 합니다. NaN·무한대·잘못된 타입은 구체적인 FAIL 보고서로 거부합니다.

```sh
python tools/knight_generate_frames.py --poses runs/knight-3d/generation --animation walk --animation attack --animation block
python tools/knight_sheet_3d.py check --run-dir runs/knight-3d/generation --palette docs/examples/knight-3d/palette.json --out-dir runs/knight-3d/audit
```

생성 서비스는 고정된 3×2 배치의 볼륨·골격 가이드와 기준 캐릭터를 함께 받습니다. 각 셀은 512×512이며 논리 프레임은 128×128입니다. 상태 시트의 전체 캔버스만 같은 격자에 투영합니다. **프레임마다 크기·중심·발 위치를 맞추는 보정은 수행하지 않습니다.** 잘못 그린 부위는 수정 생성하고, 원본과 실패 보고서를 남깁니다.

`--palette`를 생략하면 모든 동작의 색상을 모아 공통 팔레트를 만듭니다. 지정하면 같은 불투명 RGB 팔레트를 모든 동작에 적용하며, 준비 시 지정한 색상 예산을 초과할 수 없습니다. 이번 결과는 가까운 검정·회색을 합치고 강철·적색·가죽·황동 명암 램프를 공유하는 19색을 사용했습니다. 색상 변환에도 디더링을 사용하지 않습니다.

## 서로 다른 검증을 구분하기

| 검사 | 확인하는 것 |
| --- | --- |
| 3D 골격 | 모든 포즈의 월드 공간 뼈 길이, 독립 계산과 Blender 카메라 투영의 일치 |
| Blender 메시 | 포즈마다 평가된 메시 모서리의 실제 길이가 유지되는지 |
| 2D 구도 | 같은 슬롯에서 실제 렌더 실루엣·보이는 부위 영역·머리 영역과 겹치는지 |
| 도트 규격 | 4×4 셀의 정확한 RGBA 균일성, 정수 배율, 공통 팔레트, 이진 알파 |
| 시각 검토 | 실루엣, 윤곽 계단, 명암 뭉침, 부위 접합, 앞뒤 가림, 타이밍·크기 흔들림 |

3D 부위가 회전하면 2D 길이는 원근 단축으로 달라질 수 있습니다. 따라서 2D 뼈 길이를 일정하게 강제하지 않습니다. 기존 `pixel_sprite.py`의 2D 부위 맵 검사와 이 실험의 3D 투영 검사는 서로 다른 검사입니다.

생성된 그림에는 정답 의미론적 부위 라벨이 없습니다. 투영 영역의 채움 정도만으로 생성된 팔·다리의 고유 길이가 일정하다고 증명할 수 없습니다. 리포트는 이를 명시하며, 최종 시트와 모든 포즈의 시각 검토를 별도로 기록합니다. 깊이·숨김 상태·허용치를 바꾸어 실패를 통과시키지 않습니다.

원본 API 이미지 자체의 정확한 격자를 보증하지 않습니다. 고정 논리 격자 투영과 팔레트 변환을 거친 **파생 PNG**를 다시 검사합니다. 출력은 네이티브 시트, 4배 PNG, 검사기의 실제 격자 미리보기, 3D 투영 오버레이, GIF와 실행용 `manifest.json`입니다. GIF는 보기 편하도록 반복되며, 실행 명세의 공격·막기는 일회 동작입니다.

## 실제 실행 결과

2026-10-21 macOS / Python 3.12 / Blender 5.2.2 LTS에서 확인했습니다.

- 이미지 생성은 Codex의 실제 `imagegen` 서비스로 8회 실행했습니다. 첫 기준 이미지와 상태 시트의 머리 크기 실패를 남기고, 기준 이미지 수정과 투구 수정 생성을 거쳤습니다. 모델 이름은 호스트에서 공개하지 않아 기록하지 않았습니다.
- 최종 18프레임의 픽셀 검사와 등록된 3D 투영 검사 모두 PASS입니다. 실루엣 IoU는 0.790–0.903이며, 머리 영역 중심 차이는 최대 1.690 논리 셀입니다.
- 메시 모서리 길이 차이는 최대 `3.714e-7 m`, Blender와 독립 카메라 투영 차이는 최대 `1.283e-5` 논리 셀입니다.
- 네이티브 시트는 768×384, 확대 PNG는 3072×1536이며 294,912개 논리 셀 모두 정확합니다. 실제 가시 색상은 19개, 반투명 픽셀·팔레트 밖 픽셀·불균일 셀은 모두 0개입니다.
- 골격 손상·누락 무기·잘못된 위치·변경된 계약/가이드·잘못된 알파/팔레트 및 HTTP 요청 형식을 포함한 전체 209개 테스트가 통과했습니다. 설치 ZIP 제작·독립 설치 검증도 통과했습니다.

HTTP 생성 도구는 요청 형식을 모의 전송으로 테스트했습니다. 이 환경의 실제 생성은 호스트 `imagegen` 경로였으며, HTTP 래퍼 자체의 유료 실호출을 검증했다고 주장하지 않습니다. [생성 출처](examples/knight-3d/generation.json), [자동 검사](examples/knight-3d/report.json), [별도 시각 검토](examples/knight-3d/art-review.json)를 참고합니다.

## sprite-gen에서 참고한 점

[aldegad/sprite-gen](https://github.com/aldegad/sprite-gen/tree/59b2738a2e76ed7043d9691a230396ed6374a336)의 기준 캐릭터 공유, 상태별 시트 생성, 픽셀 격자 복원, 고정된 프레임 배치와 공통 팔레트 접근을 참고했습니다. 특히 [pixel-unfake](https://github.com/aldegad/sprite-gen/blob/59b2738a2e76ed7043d9691a230396ed6374a336/docs/pixel-unfake.md)와 [run-contract](https://github.com/aldegad/sprite-gen/blob/59b2738a2e76ed7043d9691a230396ed6374a336/docs/run-contract.md)를 읽었습니다. 해당 프로젝트가 3D 골격을 제공하는 것은 아니며, 이 저장소의 3D 골격·렌더러·투영 검사는 별도로 작성했습니다.
