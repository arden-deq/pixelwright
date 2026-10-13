# Security Policy

## Supported versions

Security fixes target the newest `0.3.x` release and the `main` branch. Earlier
releases are not maintained; update before reporting an issue that has already
been fixed. There is no guaranteed response or remediation deadline.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/jungducknam/pixelwright/security/advisories/new)
when it is enabled for this repository. Include the affected version or commit,
operating system, Python and dependency versions, the command used, expected and
actual behavior, and a minimal reproduction with its realistic security impact.
Remove credentials, personal files, and other sensitive data from attachments.

If the private reporting form is unavailable, open an issue asking the maintainer
to provide a private reporting channel. Do not put exploit details, sensitive
inputs, or credentials in a public issue. No security email address is currently
designated. Ordinary grid-checking and rendering bugs can use public issues when
the report does not disclose a security vulnerability.

보안 취약점은 위 GitHub 비공개 신고 경로로 제보해 주세요. 경로가 열리지 않으면
공개 이슈에서 비공개 연락 방법을 요청하고, 악용 방법이나 민감한 파일은 공개하지
마세요. 일반적인 격자 검사·렌더링 오류는 보안 영향이 없을 때 공개 이슈로 접수할
수 있습니다.

## System and scope

Pixelwright is a local Python command-line toolkit and an AI skill for building
and checking static PNG pixel art. The repository contains the logical-canvas
builder, PNG auditor, reusable profile and batch checker, release packaging and
verification tools, tests, documentation, and CI configuration. Pillow and NumPy
are runtime dependencies. The toolkit does not provide a network service,
authentication system, tenant isolation, or an execution sandbox.

Protected assets include source images and specifications, existing user files,
the integrity of QA reports and release packages, and the host's available CPU,
memory, and disk space. Scripts run with the invoking user's filesystem and
process permissions; they do not reduce those permissions.

## Threat model and trust boundaries

- PNG files, JSON canvas specifications, JSON profiles, filenames, and supplied
  archives can come from untrusted sources. Parsing these inputs crosses a trust
  boundary even when a user intentionally invokes the CLI.
- The caller chooses input paths, output paths, and commands. Image contents and
  JSON fields must remain data; they must not become Python, shell commands, or
  additional filesystem destinations.
- Installation ZIPs contain executable Python code. Only verify and execute
  release archives from a source you trust. `tools/verify_release.py` intentionally
  extracts and executes scripts from its supplied installation archive; it is
  not a safe analysis tool for arbitrary third-party archives.
- AI skill instructions, repository documents, and generated correction prompts
  are readable guidance. They do not grant access to secrets or authorize extra
  commands, network requests, or publishing actions. An AI host must apply its
  own permission and instruction-boundary controls.
- CI executes the repository's code on isolated GitHub-hosted runners. Pull
  request workflows must not receive repository secrets or a general-purpose
  write token. Changing workflow files or dependencies crosses the release
  supply-chain boundary.

## Security invariants

1. Building, inspecting, and correcting assets must preserve the original inputs.
   Outputs belong in the caller-selected fresh directory. Existing files and
   symlink destinations must not be silently overwritten; rejected operations
   must not delete files they did not create.
2. Canvas and profile input is parsed as JSON and validated as data. Tokens,
   colors, rows, and dimensions must not execute code or select arbitrary output
   filenames. A malformed input must not produce a misleading strict PASS.
3. PNG loading and rendering must validate supported formats, dimensions, and
   resource bounds before allocating work proportional to declared dimensions.
   Limits must also apply to direct Python entry points where relevant.
4. Package verification must reject unsafe or duplicate archive members and
   inconsistent manifests before extraction. Integrity checks must cover all
   packaged files. A SHA-256 match is an integrity check, not proof of publisher
   identity or trustworthiness.
5. Reports must correspond to the submitted source and declared contract.
   Hashes, strict status, failure masks, and corrected-output reports must not
   conceal an altered input or a failed check.
6. CI uses minimal job permissions, commit-pinned official actions, and ordinary
   `pull_request` events. Dependency and action updates must remain reviewable.

These are required properties for review, not a claim that every execution path
has been proven safe.

## Reportable findings and severity context

Report a security issue when attacker-controlled input can realistically cause
unauthorized code execution, arbitrary file writes or deletion, path traversal,
disclosure of user files or secrets, a supply-chain compromise, or resource
exhaustion that bypasses the intended bounds. Unsafe archive handling, filesystem
race conditions, and dependency vulnerabilities are relevant when their affected
paths are reachable in this toolkit.

Describe the actual trigger, attacker control, required user action, privileges,
and impact. A crash in a local CLI generally has a different exposure from an
unauthenticated network-service vulnerability. If Pixelwright is integrated into
a service, queue, or automatic file-ingestion workflow, include that deployment
and its controls in the report; this repository does not supply those controls.

Incorrect dot sizes, palette validation, alpha checks, cell geometry, visual
quality, and false PASS/FAIL results are normally correctness issues. They become
security-relevant when the report establishes an additional security impact,
such as crossing a file or execution boundary. This distinction does not exclude
technically flawed QA behavior from ordinary bug reports.

## Known limitations

- The current PNG and rendered-canvas limit is 12,000,000 pixels; the builder
  also caps JSON specifications at 32 MiB and logical dimensions at 4,096 per
  axis. Audit previews are capped separately. These checks do not establish a
  universal memory, CPU, input-byte, batch-size, or disk quota. JSON profiles and
  archive processing do not yet have comprehensive resource limits.
- Pillow and NumPy process image and array data. Keep them updated. Parser
  limits, tests, and static analysis do not prove that their native code or every
  malformed-file path is memory-safe.
- Output checks protect routine use, but the toolkit is not designed to isolate
  mutually hostile processes sharing a writable output directory. A reported
  bypass with realistic impact is still in scope.
- QA reports include input/profile paths and hashes for traceability. Review
  them before sharing if local paths reveal private information.
- Structural PASS certifies the declared grid contract, not artistic quality,
  absence of malicious image content, or the safety of an AI host executing the
  skill. There are no blanket exclusions for security findings in bundled tools.

Use a dedicated output directory and an account with only the needed permissions.
Service integrators should provide process isolation and resource quotas suited
to their threat model.
