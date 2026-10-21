# 2D 시안에 3D 골격 동작 적용하기

**참고 이미지 또는 프롬프트 → 2D 도트 시안 → 시안 비율의 3D 맨 골격 → 같은 캐릭터의 새로운 2D 애니메이션** 순서입니다. 외형은 2D 시안에서 결정합니다. 3D는 카메라, 관절 위치, 깊이와 가림 관계를 전달합니다. 갑옷 메시나 3D 실루엣을 만들고 이를 도트로 전사하는 경로가 아닙니다.

[실제 생성 초안과 실패 보고서](examples/knight-design-first/)를 함께 제공합니다. 픽셀 규격과 골격 기하 검사는 통과했지만, 일부 그림의 포즈와 장비 크기는 기준을 벗어났습니다. 완성 에셋으로 승인하지 않았습니다.

[요구사항과 진행 상황](SPRITE_REQUIREMENTS_AND_STATUS_ko.md)에 현재의 걷기 품질 문제와 후속 작업을 기록했습니다. 발 접지·체중 이동·시간 연속성 검사는 아직 구현하지 않았습니다. 다음 걷기 생성은 새 실행에서 골격의 보행 자체를 먼저 수정·검토한 뒤 진행합니다.

현재 소스 체크아웃에서 사용하는 개발 도구이며 설치용 v0.6.2 ZIP에는 들어 있지 않습니다. Pillow·NumPy는 기존 의존성입니다. Blender는 골격 파일 제작과 독립 검증에 사용합니다.

## 1. 골격 없이 2D 시안 만들기

```sh
python -m pip install -r pixelwright/requirements.txt
python tools/knight_design_first.py init --out-dir runs/design-first --prompt "강철 갑옷과 붉은 타바드, 사자 문장 방패와 메이스를 든 기사"
```

사용자 참고 이미지가 있으면 `init`에 `--reference path/to/reference.png`를 추가합니다. 초기 `prompts.json`에는 `design` 작업 하나만 있습니다. 3D 자료나 포즈 입력은 없습니다. 참고 이미지를 그대로 시안으로 채택해도 됩니다.

`prompts.json`을 실제 이미지 생성 서비스에 전달해 `raw/design.png`로 보존합니다. HTTP 도구는 참고 이미지가 없으면 `/images/generations`, 있으면 `/images/edits`를 사용합니다. `OPENAI_API_KEY`는 환경 변수로 설정합니다. [공식 생성 API 형식](https://developers.openai.com/api/reference/resources/images/methods/generate)을 따르며, 첫 시안 요청에는 `input_fidelity`를 보내지 않습니다.

```sh
python tools/knight_generate_frames.py --poses runs/design-first --animation design
python tools/knight_design_first.py select --run-dir runs/design-first --source runs/design-first/raw/design.png
```

`select`는 원본을 보존하고 128×128 논리 격자와 공통 24색으로 투영합니다. 시안 한 장만 전체 높이 88셀·발밑 y=112에 균일 배율로 배치하고, 변환 내역과 해시를 `identity.json`에 기록합니다. 이때 골격은 아직 없습니다. 이 손실 변환을 거친 **선택된 2D 시안**이 이후 외형의 기준이며, 원본 API 이미지가 정확한 픽셀 격자를 가졌다고 주장하지 않습니다. `select`가 사람의 작화 승인을 의미하지는 않습니다.

## 2. 시안에 골격 맞추기

선택한 `references/design-native.png`에서 관절과 안정적으로 측정할 부위를 직접 확인합니다. [실제 관찰 파일](examples/knight-design-first/generation/design-landmarks.json)은 `design_sha256`, 각 관절의 `xy`, `depth_offset_m`, `part_dimensions`를 기록합니다. 관절 이름은 예제와 동일합니다. 2D 한 장에서 알 수 없는 깊이는 작성한 가정이며, 자동 3D 복원을 했다는 의미가 아닙니다.

3D 기준 뼈 길이는 유한한 양수, 길이 허용치는 유한한 0 이상의 수여야 합니다. NaN·무한대·잘못된 타입은 구체적인 FAIL 보고서로 거부합니다.

```sh
python tools/knight_design_first.py poses --run-dir runs/design-first --landmarks path/to/design-landmarks.json
blender --background --factory-startup --python tools/knight_render_3d.py -- --skeleton-contract runs/design-first/contract.json --out-dir runs/design-first-armature
```

뼈 길이는 선택한 시안의 관절과 깊이에서 계산합니다. 기존 모션의 방향과 도달 비율을 전달하고, 다른 신체 비율에서도 길이가 유지되도록 3D IK를 풉니다. 카메라, 모든 포즈와 허용치를 `contract.json`에 고정합니다. Blender 파일에는 18개 뼈, 카메라와 동작 키프레임이 있으며 **외형 메시 수는 0개**입니다. Blender 투영과 독립 계산도 비교합니다.

각 상태의 생성 입력은 같은 슬롯 크기로 반복한 **2D 시안 시트가 첫 번째**, 색 선과 관절만 있는 **골격 시트가 두 번째**입니다. 볼륨 렌더, 갑옷 메시, 재질, 실루엣 마스크는 생성 입력이나 작화 합격 기준에 사용하지 않습니다. 천과 장식, 윤곽과 명암은 2D 애니메이션으로 새로 그립니다.

상태 프롬프트는 선택한 시안과 원래 요청을 따릅니다. 특정 체형이나 붉은 의상·장식 등을 일괄 강제하지 않습니다. JSON은 한글 프롬프트와 관찰 메모를 포함할 수 있는 UTF-8 파일입니다.

## 3. 상태 시트 생성과 독립 검사

```sh
python tools/knight_generate_frames.py --poses runs/design-first --animation walk --animation attack --animation block
python tools/knight_design_first.py check --run-dir runs/design-first --out-dir runs/design-first-audit
```

걷기·공격·막기를 각각 3×2 슬롯의 6프레임 시트로 생성합니다. 슬롯당 128×128 논리 셀, 4배 PNG입니다. 상태 시트 전체를 같은 격자와 시안 팔레트에 투영합니다. **생성된 동작 프레임을 개별 확대·축소·재배치하지 않습니다.** 잘못 그린 부위는 수정 생성하고 실패 원본을 보존합니다.

생성 요청을 보내기 전에 선택한 시안, 계약, 골격 PNG와 반복 시안 시트의 해시를 검사하고 입력 순서를 확인합니다. 변경된 입력은 종료 코드 `1`로 거부합니다. `select` 이후에는 `--force`도 시안을 덮어쓰지 않습니다. 전체 재생성은 동작 시트만 대상으로 삼으며, `--animation design --force`로 선택한 시안을 바꾸려 하면 새 실행 폴더를 사용하도록 안내합니다.

특정 상태를 수정하려면 프롬프트의 수정 지시를 보완한 뒤 다음처럼 재생성합니다. 교체되는 PNG는 `generated/history/`에 정확한 바이트와 이전 생성 기록을 보관하고, `generated/manifest.json`의 `history`에서 찾을 수 있습니다. 서비스 오류가 나면 현재 PNG와 생성 기록을 그대로 유지합니다. 시안이나 포즈 자체를 바꾸려면 새 실행 폴더를 만듭니다.

```sh
python tools/knight_generate_frames.py --poses runs/design-first --animation attack --force
```

관찰 파일 없이 실행하면 픽셀이 정상이고 골격이 정상이더라도 그림의 포즈는 `REVIEW`입니다. 골격 좌표를 그대로 그림의 관찰 좌표로 복사해 합격시키지 않습니다. 실제 그림에서 관절과 부위 크기를 따로 측정한 [관찰 파일](examples/knight-design-first/generation/artwork-annotations.json)을 전달합니다. 관찰 방법·검토자·정확한 원본 이미지와 계약 해시가 필요합니다. 가려져 판단할 수 없는 값은 `null` 또는 생략하며 검토 상태를 유지합니다.

관절은 유한한 숫자 두 개, 치수는 시안과 같은 개수의 유한한 양수 배열로 기록합니다. 숫자처럼 보이는 문자열, 불리언, NaN·무한대와 잘못된 컨테이너는 입력 오류로 거부합니다. 상태 시트를 재생성하면 이전 관찰 파일의 원본 해시가 일치하지 않으므로 새 그림을 다시 측정해야 합니다.

```sh
python tools/knight_design_first.py check --run-dir runs/design-first --annotations path/to/artwork-annotations.json --out-dir runs/design-first-observed
```

| 검사 | 확인하는 것과 한계 |
| --- | --- |
| 3D 골격 | 포즈마다 월드 공간 뼈 길이, 독립 계산과 Blender 카메라 투영의 일치 |
| 그림 포즈 | 실제 그림에서 관찰한 관절과 투영 목표의 거리. 이번 계약은 최대 5셀 |
| 부위 크기 | 시안에서 측정한 투구·메이스 머리·방패와 그림 관찰값 비교. 이번 계약은 최대 15% 차이 |
| 도트 규격 | 정확한 4×4 RGBA 셀, 공통 팔레트, 정수 배율, 이진 알파 |
| 시각 검토 | 캐릭터 동일성, 자연스러운 가림, 윤곽 계단, 명암 뭉침, 접합, 움직임과 접지 |

수동 좌표와 치수는 자동 의미론적 부위 분할이 아닙니다. 원근 단축과 가림을 구분하고, 측정할 수 없는 부위는 `REVIEW`로 남깁니다. 골격 길이가 일정하다는 사실은 생성된 팔·다리의 길이가 일정하다는 증명이 아닙니다. 실패 이후 허용치나 깊이를 바꿔 통과시키지 않습니다. 종료 코드는 `0` 통과, `2` 실패 또는 검토 필요, `1` 입력·실행 오류입니다. 작화 판단은 `art-review.json`에 별도로 남깁니다.

출력에는 네이티브 시트, 4배 PNG, 검사기의 실제 격자, 골격 오버레이, GIF와 실행 명세가 포함됩니다. GIF는 반복 미리보기이며 공격·막기의 실행 명세는 일회 동작입니다.

## 실제 실행 기록

2026-10-21 / macOS / Python 3.12 / Blender 5.2.2 LTS에서 실제 호스트 `imagegen` 서비스로 생성했습니다. 선택된 시안·세 상태는 4회 호출이며, 폐기한 시도를 포함하면 11회입니다. 모델 이름은 호스트에서 공개하지 않았습니다. HTTP 래퍼는 모의 전송으로 검증했으며 유료 HTTP 실호출로 검증했다고 주장하지 않습니다.

- 18포즈의 3D 뼈 길이와 카메라 투영 PASS. 외형 메시 0개. Blender와 독립 투영 차이는 최대 `1.310e-5` 논리 셀입니다.
- 파생 시트 768×384 → 3072×1536, 공통 가시 24색, 정확한 4×4 셀 PASS. 반투명·잘못된 투명 RGBA는 0개입니다.
- 독립 수동 관찰: 4프레임 PASS, 13프레임 FAIL, 1프레임 REVIEW. 좌표는 약 1셀의 관찰 오차가 있으므로 경계에 걸린 수치는 정밀 검토가 필요합니다. 명확한 결함은 공격 3번의 메이스 머리 확대, 공격 4번의 과한 웅크림, 막기 1·3·5번의 방패 높이입니다. 프레임 번호는 0부터 셉니다.
- 모든 관찰이 있더라도 피부·의복의 의미론적 크기를 자동 보장하지 않습니다. 현재 샘플의 작화 검토는 `changes_needed`이며 완성 에셋으로 승인하지 않았습니다.

[생성 출처](examples/knight-design-first/generation.json), [실패 포함 검사](examples/knight-design-first/audit/report.json), [별도 시각 검토](examples/knight-design-first/art-review.json)를 확인할 수 있습니다. 이전 [3D 메시 외형 전사 예제](examples/knight-3d/)는 과거 방식의 기록으로 유지합니다.

## sprite-gen에서 참고한 점

[aldegad/sprite-gen](https://github.com/aldegad/sprite-gen/tree/59b2738a2e76ed7043d9691a230396ed6374a336)의 기준 캐릭터 공유, 상태별 시트, 고정 프레임 배치와 공통 픽셀 격자·팔레트 접근을 참고했습니다. [pixel-unfake](https://github.com/aldegad/sprite-gen/blob/59b2738a2e76ed7043d9691a230396ed6374a336/docs/pixel-unfake.md)와 [run-contract](https://github.com/aldegad/sprite-gen/blob/59b2738a2e76ed7043d9691a230396ed6374a336/docs/run-contract.md)가 해당 자료입니다. 이 저장소의 3D 골격과 검증 도구는 별도로 작성했습니다.
