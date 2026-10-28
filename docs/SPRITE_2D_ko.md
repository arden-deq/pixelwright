# 골격 없이 일관적인 2D 스프라이트 만들고 검사하기

기본 생성 경로는 **선택한 2D 시안 → 공통 규격·동작 설명 고정 → 상태별 이미지 생성 → 실제 그림 관찰 → 일관성·움직임 검사**입니다. 사람·동물의 해부 구조나 3D 스켈레톤을 설명할 필요가 없습니다. 존재하지 않는 물체도 `core`, `vane`, `tail` 같은 임의 부위와 보이는 특징점으로 다룹니다.

실행 도구는 [`pixel_sequence.py`](../pixelwright/scripts/pixel_sequence.py)이며 설치용 ZIP에도 포함합니다. Python 3.12+, Pillow, NumPy를 사용하며 Blender는 필요하지 않습니다. 전체 명세와 관찰 형식은 [런타임 참조 문서](../pixelwright/references/sequences.md)에 있습니다.

## 1. 시안과 규격을 먼저 선택

사용자 참고 이미지나 이미지 생성 도구로 외형 시안을 먼저 만듭니다. 선택한 시안은 모든 상태의 공통 입력입니다. 시안의 부위 이름, 고유 색·무늬·치수, 프레임 크기·배율·팔레트, 상태별 동작과 시간을 명세에 적습니다. 해부 구조 대신 ‘눈 중심’, ‘날개 끝’, ‘회전판의 연결점’처럼 실제 그림에서 찾을 수 있는 특징점을 씁니다.

```sh
python pixelwright/scripts/pixel_sequence.py prepare --spec creature.json --reference selected-design.png --out-dir runs/creature-v1
```

`contract.json`, 원본 시안, 정규 시안, 원본 명세, 팔레트와 상태별 프롬프트의 해시가 고정됩니다. 생성 후 기준을 바꿔 통과시키지 않습니다. 명세를 바꾸려면 새 실행을 만듭니다.

`strict`는 원본의 정수 배율·정확한 RGBA 셀을 요구합니다. `project`는 생성 전에 선언한 손실 파생 경로로, 정확한 전체 시트 종횡비를 요구하고 캔버스 전체를 한 번에 최근접 샘플링합니다. 같은 알파 임계값과 선택 시안의 공통 팔레트를 적용합니다. 프레임별 확대·축소·크롭·중심 맞추기는 하지 않습니다. 변환 전 샘플 색상 차이도 검사하므로 다른 색의 원본을 팔레트 변환만으로 합격시키지 않습니다.

## 2. 선택한 시안으로 상태 시트 생성

호스트 이미지 생성 도구에 `run/reference-native.png`와 `run/prompts/상태.txt`를 제공합니다. 모든 상태에서 같은 시안, 카메라, 슬롯 크기와 도트 배율을 유지합니다. 생성 원본은 그대로 가져옵니다.

```sh
python pixelwright/scripts/pixel_sequence.py import --run runs/creature-v1 --state hover --image generated-hover.png --producer "사용한 호스트 이미지 생성 도구"
```

HTTP API를 사용할 때는 환경의 `OPENAI_API_KEY`와 명시적인 모델이 필요합니다.

```sh
python pixelwright/scripts/pixel_sequence.py generate --run runs/creature-v1 --state hover --model YOUR_SUPPORTED_IMAGE_MODEL --quality high
```

HTTP 래퍼는 선택한 시안 한 장과 고정 프롬프트를 `/images/edits`로 보냅니다. 모델·서비스의 지원 크기와 옵션은 사용 전에 확인합니다. `--background`는 기본적으로 전송하지 않으며 지원 모델에서만 명시합니다. 생성 모델이나 자동 배경 제거를 내장한 도구가 아닙니다. 이번 실제 예제는 호스트 image_gen을 사용했고, HTTP 래퍼의 전송 검증은 모의 응답입니다.

재생성에 `--replace`를 쓰면 이전 PNG와 생성 기록을 `history/`에 보관합니다. 기존 관찰 파일은 새 원본 해시와 달라져 거부됩니다. 서비스 오류는 현재 원본과 매니페스트를 보존합니다.

## 3. 실제 그림을 관찰

```sh
python pixelwright/scripts/pixel_sequence.py observations --run runs/creature-v1 --out observed.json
python pixelwright/scripts/pixel_sequence.py check --run runs/creature-v1 --out-dir runs/creature-unobserved
```

관찰하지 않은 첫 검사는 REVIEW입니다. 좌표 미리보기와 네이티브 프레임을 보고 시안과 프레임별 부위 마스크, 보이는 치수 양 끝점, 특징점을 기록합니다. 생성 프롬프트의 예상 좌표를 답으로 복사하지 않습니다. 자동 관찰기를 연결할 수도 있지만 실제 픽셀과 관찰 방법·오차를 검토해야 합니다.

관찰은 계약·시안·상태 원본 해시와 묶입니다. 마스크는 투명 셀을 포함하거나 서로 겹칠 수 없고, 전 부위를 관찰했다면 모든 가시 셀을 설명해야 합니다. 측정 끝점은 해당 부위에 있어야 하며, 부위에 속한다고 선언한 특징점도 같은 부위에 있어야 합니다. 가려졌거나 관찰하지 못한 항목은 REVIEW로 남습니다.

## 4. 일관성과 움직임 검사

```sh
python pixelwright/scripts/pixel_sequence.py check --run runs/creature-v1 --observations observed.json --out-dir runs/creature-audit
```

| 검사 | 확인하는 내용 |
| --- | --- |
| 픽셀 | 공통 프레임 크기·슬롯, 정확한 RGBA 격자, 팔레트·알파, 빈 슬롯·여백 |
| 부위 일관성 | 시안 대비 가시 면적, 색 분포, 회전·이동만 허용한 형상/색 무늬 비교, 관찰 치수와 부위 간 비율 |
| 움직임 | 필요한 이동량, 프레임 시간에 따른 속도와 선택적 가속도, 반복 경계 |
| 부위 연결 | 특징점 사이 거리, 연결부 이탈, 선언한 길이·가동 범위 |
| 상대 움직임 | `relative_to` 특징점을 뺀 변위; 물체 전체 이동과 부위 자체 움직임을 구분 |
| 접지 | 선언한 루트 이동을 복원한 접점 미끄럼과 선택적 지면 높이 |
| 작화 검토 | 윤곽·도트 뭉침·명암·실루엣·의도·무게감·반복 연결을 검토자가 별도 기록 |

거리 단위는 논리 셀, 속도는 셀/초, 가속도는 셀/초²입니다. 루트 이동은 각 프레임까지의 누적 이동량입니다. 제자리 걷기의 화면 좌표에 단순 고정발 검사를 적용하지 않습니다.

보고서는 전체 상태, 기술 상태, 픽셀 상태, 프레임별 수치와 작화 검토를 구분합니다. 픽셀만 PASS여도 관찰·검토가 없으면 전체 REVIEW입니다. 부위의 의미를 자동 인식하거나 자연스러움을 보증하지 않습니다. 가림·원근 단축·유연한 부위·명암 변화는 관찰 오차와 함께 판단해야 합니다. 수치상 기준 이탈을 완성 작화의 확정 결함 개수로 해석하지 않습니다.

산출물은 `report.json`, 재생성 지시 `redraw-requests.json`, 상태별 네이티브/확대 PNG, 실제 격자, GIF와 시간 읽기 검증, 부위·특징점 오버레이, 관찰용 좌표 프레임입니다. 종료 코드 `0`은 성공/PASS, `2`는 FAIL·REVIEW, `1`은 입력·실행 오류입니다.

## 5. 예제와 현재 결과

[설치형 튜토리얼](../pixelwright/examples/sequence-orbit/)은 직접 작성한 24×24 셀의 가상 자기 부유 장치입니다. 실제 생성 작화로 소개하지 않습니다. 원본이 정확히 같은 경우에만 알려진 관찰을 적용하며, 6프레임·공통 3색·4배 확대·프레임당 100ms를 검사합니다.

[Aetherseed 실제 생성 예제](examples/aetherseed-2d/)는 2D 시안 한 장과 부유 상태 시트 한 장을 호스트 image_gen으로 생성했습니다. 3D 입력은 없습니다. 64×64 프레임·공통 24색·6프레임·120ms 계약을 생성 전에 고정했습니다. 파생 PNG의 픽셀 검사는 PASS지만 독립적인 보조 관찰 후 전체 FAIL이며, 작화는 `changes_needed`입니다. 색·무늬·크기 변화와 시간에 따른 이동이 기준을 벗어납니다. 허용치를 사후 완화하지 않았습니다.

![검증용 Aetherseed 부유 GIF — 전체 FAIL](examples/aetherseed-2d/audit/hover/pixel-audit/animations/hover.gif)

[현재 요구사항](SPRITE_REQUIREMENTS_AND_STATUS_ko.md)과 [검증 기록](VALIDATION_sequences_ko.md)을 함께 확인합니다. 기존 [3D 기사 경로](SPRITE_3D_ko.md)는 선택적 실험으로 남기며, 부자연스러운 보행과 작화 실패는 해결된 것으로 처리하지 않습니다.
