# 3D 골격 → 실제 이미지 생성 → 2D 도트 기사

> 이전 메시 외형 전사 실험입니다. 3D 갑옷 외형을 따라 만드는 방식은 현재 요구사항과 다릅니다. 권장 경로는 [2D 시안을 먼저 만든 뒤 맨 골격으로 동작을 지정하는 예제](../knight-design-first/)입니다. 아래 PASS는 당시 메시 기준 검사에만 해당하며, 새 제작 방식의 승인 근거로 사용하지 않습니다.

실제 Blender 골격·장비를 고정 직교 카메라로 렌더하고, 공통 기준 캐릭터를 사용해 동작별 시트를 생성한 결과입니다. 각 동작은 128×128 논리 프레임 6개이며, 전체 시트는 768×384 → 3072×1536(4×4 셀), 공통 가시 색상은 19개입니다.

| 걷기 | 공격 | 막기 |
| --- | --- | --- |
| ![걷기](walk.gif) | ![공격](attack.gif) | ![막기](block.gif) |

![3D 골격과 볼륨으로 만든 걷기 가이드](walk-3d.gif)

![최종 투명 스프라이트 시트](sprite-sheet.png)

| 실제 도트 확대 | 검사기가 만든 격자 확대 |
| --- | --- |
| ![도트 상세](pixel-detail.png) | ![격자 상세](grid-detail.png) |

[전체 격자](grid-overlay.png)의 청록색 선은 실제 4×4 셀 경계입니다. [골격·투영 오버레이](rig-overlay.png)는 별도 진단 이미지입니다.

- [골격 파일](knight-rig.blend), [카메라·월드 좌표·포즈 계약](rig.json), [Blender 메시 검증](rig-check.json)
- [자동 검사](report.json), [픽셀 규격 검사](pixel-report.json), [별도 시각 검토](art-review.json)
- [실제 생성 도구·입력·프롬프트 해시](generation.json), [픽셀 배율·GIF 시간 검증](verification.json)
- [네이티브 PNG](sprite-sheet-native.png), [실행용 프레임과 애니메이션 명세](manifest.json), [공통 색상 램프](palette.json)

자동 검사는 18프레임 모두 PASS입니다. 검사기의 `artistic_status`는 자동으로 승인하지 않도록 `not_reviewed`로 유지하며, Codex의 시각 검토 결과는 `art-review.json`에 별도로 기록했습니다. 사람의 승인을 받은 것으로 표시하지 않습니다. 투영 영역 비교만으로 생성된 그림의 의미론적 팔다리 길이를 증명하지 않습니다.

원본 생성 파일과 실패 버전은 개발 실행 폴더 `runs/knight-3d-20261021-v2/`에 보존했습니다. 이 예제 폴더에는 최종 산출물·검증 기록과 생성 출처를 담았으며, 전체 원본 API 파일을 중복 배포하지 않습니다. 이미지 생성은 비결정적입니다. 아래 명령은 저장된 최종 PNG의 정확한 픽셀 규격을 재검사합니다.

```sh
python pixelwright/scripts/pixel_sprite.py check --spec docs/examples/knight-3d/spec.json --sheet docs/examples/knight-3d/sprite-sheet.png --profile docs/examples/knight-3d/profile.json --out-dir runs/knight-3d-example-check
```

[3D 제작·생성·검증 절차](../../SPRITE_3D_ko.md)를 참고합니다. GIF의 공격·막기는 반복 미리보기이며, 실행 명세에서는 일회 동작입니다.
