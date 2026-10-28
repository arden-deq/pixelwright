# 말 탄 기사 돌격: sprite-gen 시트 형식 예시

사용자가 시트를 직접 보고 판단하기 위한 생성 예시다. 기준 시안 1회, 돌격 행 1회를 호스트 내장 image_gen으로 생성했다. sprite-gen의 이미지 생성 CLI는 호출하지 않았으며, prepare → extract → compose-atlas → preview → inspect → compose-gif는 실제 sprite-gen 2.45.3 도구로 수행했다. 사용한 커밋은 `59b2738a2e76ed7043d9691a230396ed6374a336`이다.

## 규격

sprite-gen 전체에 고정된 해상도는 없다. 작업별 요청이 프레임 크기·개수·FPS·반복 여부를 정하고, 완성 시트의 manifest가 실제 프레임 사각형을 기록한다. 생성된 원본 행은 추출 전 이미지이므로 완성 시트와 해상도가 다를 수 있다.

- 생성 원본: `run/raw/charge.png`, 2172×724, 초록 크로마 배경, 돌격 8자세.
- 완성 시트: `run/sprite-sheet-alpha.png`, 2048×192, 투명 배경, 가로 8칸.
- 프레임: 256×192, 10FPS, 100ms씩 8개, 반복.
- 정확한 좌표와 재생 정보: `run/manifest.json`.
- 프레임별 PNG: frames-manifest의 파일 경로를 따른다.
- 보기용 GIF: `run/exports/charge.gif`; 확대된 검사 미리보기: `pixel-audit/animations/charge.gif`.

## 검증 결과

최종 상태는 **FAIL**이다. sprite-gen 자체 추출·합성·inspect는 ok이며 경고를 남겼다. 독립 Pixelwright 검사는 2×2 셀 균일성 100%, 부분 투명도 0을 확인했으나, 요청한 32색보다 많은 실제 62색과 7프레임의 안전 여백 위반을 검출했다. 허용 규격은 생성 전 `attempt-contract.json`에 고정했고, 검사 프로파일이 같은 값을 쓰는지 확인했다.

원본 양끝의 꼬리·창 잘림, 네 번째 자세의 상대적인 크기 변화도 남아 있다. 사용자가 실제 결과를 판단하도록 원본과 sprite-gen 합성 결과를 그대로 보존했다. 보정하거나 다시 생성하지 않았다. 자연스러운 말의 접지·무게 이동·반복 연결은 별도 검증되지 않았다.

자세한 수치와 입력 해시는 `validation.json`, 실제 프롬프트는 `base-prompt.txt`와 `generation-prompt.txt`에 있다. sprite-gen 추출이 정규화 요청에 chroma 기본값 등을 추가할 수 있으므로 생성 전 입력 해시는 `generation-request.json`에 별도로 남겼다.

## manifest 직접 검사

새 `sprite-gen` 검사 명령은 별도 Pixelwright spec 없이 완성 시트와 runtime manifest를 받는다. 팔레트 상한은 manifest에 없으므로 원래 요청의 `fit.palette_size`에서 읽었다. 저장소 루트에서 실행한 명령은 다음과 같다.

```sh
python pixelwright/scripts/pixelwright.py sprite-gen \
  --sheet docs/examples/mounted-knight-charge-v1/run/sprite-sheet-alpha.png \
  --manifest docs/examples/mounted-knight-charge-v1/run/manifest.json \
  --request docs/examples/mounted-knight-charge-v1/run/sprite-request.json \
  --size-tolerance 0.10 --area-tolerance 0.25 \
  --out-dir docs/examples/mounted-knight-charge-v1/manifest-audit-v2
```

| 검사 | 결과 | 측정 |
| --- | --- | --- |
| 팔레트 | FAIL | 공통 제한 32색, 실제 보이는 RGB 62색 |
| 안전 여백 | FAIL | 각 축 12px 기준, 8프레임 중 7개 위반 |
| 크기 일관성 | REVIEW | 4번째 높이 −11.1%, 8번째 폭 −12.0% |
| 프레임 배치 | PASS | manifest 좌표·크기 일치, 겹침·프레임 밖 픽셀 없음 |

크기는 같은 동작의 보이는 외곽 폭·높이와 픽셀 면적 중앙값으로 비교한다. 기본 허용폭은 치수 10%, 면적 25%다. 자세·창·가려짐·잘림도 수치를 바꾸므로 크기 결과는 검토 후보이며 신체 부위 크기 오류를 확정하지 않는다. 도트 격자와 움직임의 자연스러움은 이 명령의 검사 대상이 아니다.

입력 PNG와 JSON은 변경하지 않았다. [전체 보고서](manifest-audit-v2/report.json), [프레임 비교 이미지](manifest-audit-v2/frames.png), [시트 검사 이미지](manifest-audit-v2/layout_overlay.png)에 측정값과 입력 해시가 남아 있다. 재실행 시 새 출력 폴더를 지정한다.

`manifest-audit-v2`는 패키지의 upstream 선언을 `report.upstream`에 포함한다. sprite-gen 원본 저장소·Apache-2.0·확인한 2.45.3 버전/커밋과 `data_format` 관계를 기록하며, 검증할 때 설치가 필요하지 않음을 표시한다. 호환성 확인 버전은 입력 생성기의 검증된 버전이 아니다. [초기 보고서](manifest-audit-v1/report.json)를 보존했으며 두 실행의 측정값·판정·입력 해시는 같다.

규격 근거: https://github.com/aldegad/sprite-gen/blob/59b2738a2e76ed7043d9691a230396ed6374a336/docs/run-contract.md
